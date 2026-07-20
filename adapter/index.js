'use strict'

const fs = require('fs')
const path = require('path')
const crypto = require('crypto')
const { spawn } = require('child_process')
const readline = require('readline')
const mineflayer = require('mineflayer')
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder')
const { Vec3 } = require('vec3')
const WebSocket = require('ws')
const { PROTOCOL_VERSION, ActionRunner, buildStandaloneLifecycle, delay, validateBrainMessage } = require('./safety')
const { createSmeltItem } = require('./bootstrap_actions')

const root = path.resolve(__dirname, '..')
const configPath = path.join(root, 'config.json')
const examplePath = path.join(root, 'config.example.json')
const config = JSON.parse(fs.readFileSync(fs.existsSync(configPath) ? configPath : examplePath, 'utf8'))
if (process.env.BRAIN_URL) config.brain.url = process.env.BRAIN_URL
if (process.env.MINECRAFT_HOST) config.minecraft.host = process.env.MINECRAFT_HOST
if (process.env.MINECRAFT_PORT) config.minecraft.port = Number(process.env.MINECRAFT_PORT)
const lifecycleLogPath = process.env.ADAPTER_LIFECYCLE_LOG || path.join(root, 'data', 'adapter-lifecycle.jsonl')
const adapterId = String(config.adapter_id || process.env.MINECRAFT_AI_ADAPTER_ID || 'local-mineflayer-adapter')
const directGoal = process.env.DIRECT_GOAL || ''
const directMode = directGoal.trim().length > 0
const pythonExe = process.env.PYTHON_EXE || path.join(root, 'brain', '.venv', 'Scripts', 'python.exe')

function requireLocalhost(value, field) {
  if (value !== '127.0.0.1' && value !== 'localhost') {
    throw new Error(`${field} must be localhost-only; got ${value}`)
  }
}

requireLocalhost(config.minecraft.host, 'minecraft.host')
const brainUrl = new URL(config.brain.url)
requireLocalhost(brainUrl.hostname, 'brain.url')

const botOptions = {
  host: config.minecraft.host,
  port: config.minecraft.port,
  username: config.minecraft.username,
  auth: config.minecraft.auth || 'offline'
}
if (config.minecraft.version) botOptions.version = config.minecraft.version

const bot = mineflayer.createBot(botOptions)
bot.loadPlugin(pathfinder)

let socket = null
let socketReady = false
let directWorker = null
let spawned = false
let observationSeq = 0
let observationTimer = null
let runner = null
let faulted = false
let pendingContainerOperations = 0
let smeltItemImpl = null

function logLifecycle(entry) {
  try {
    fs.mkdirSync(path.dirname(lifecycleLogPath), { recursive: true })
    fs.appendFileSync(lifecycleLogPath, JSON.stringify({ adapter_pid: process.pid, ...entry }) + '\n', 'utf8')
  } catch (error) {
    console.error('[adapter-lifecycle-log]', error.message)
  }
}

function stopEverything() {
  bot.clearControlStates()
  if (bot.pathfinder) bot.pathfinder.setGoal(null)
  try {
    bot.stopDigging()
  } catch (_) {
    // Mineflayer exposes stopDigging only while digging on some versions.
  }
  try {
    if (bot.currentWindow) bot.closeWindow(bot.currentWindow)
  } catch (_) {
    // Closing an already-closing window is harmless; pending click operations stay fenced by ActionRunner.
  }
}

function quarantineAndDisconnect(reason) {
  faulted = true
  logLifecycle({ event: 'adapter_quarantine_disconnect', reason, at: Date.now() })
  stopEverything()
  if (observationTimer) clearInterval(observationTimer)
  try {
    if (socket) socket.close()
  } catch (_) {}
  try {
    bot.end(`adapter faulted: ${reason}`)
  } catch (_) {}
}

function send(payload) {
  if (directMode) {
    if (!directWorker || !directWorker.stdin.writable) return
    directWorker.stdin.write(JSON.stringify({ kind: 'adapter_message', payload: { protocol_version: PROTOCOL_VERSION, ...payload } }) + '\n')
    return
  }
  if (!socketReady || !socket) return
  socket.send(JSON.stringify({ protocol_version: PROTOCOL_VERSION, ...payload }))
}

function unavailableState() {
  return {
    position: { x: 0, y: 0, z: 0 },
    velocity: { x: 0, y: 0, z: 0 },
    health: 0,
    food: 0,
    inventory: [],
    nearby_blocks: { counts: {}, samples: [] },
    nearby_entities: [],
    action_running: false,
    movement_active: false,
    pathfinder_active: false,
    digging_active: false,
    danger: null
  }
}

function sendUnavailableResult(actionId, code, error) {
  const state = spawned && runner ? makeObservation() : unavailableState()
  const now = Date.now()
  const lifecycle = buildStandaloneLifecycle(actionId, code, state, error, now)
  const payload = {
    type: 'result',
    action_id: actionId,
    ok: false,
    elapsed_ms: 0,
    before_state: state,
    after_state: state,
    code,
    error,
    lifecycle
  }
  logLifecycle({ event: 'action_started', action_id: actionId, seq: 0, at: now })
  send(payload)
  logLifecycle({
    event: 'terminal_message',
    message_type: 'result',
    action_id: actionId,
    code,
    ok: false,
    lifecycle,
    at: Date.now()
  })
}

async function handleBrainMessage(message) {
  const valid = validateBrainMessage(message)
  if (!valid.ok) {
    send({ type: 'error', code: valid.code, message: valid.message })
    return
  }

  if (message.type === 'cancel') {
    if (runner) await runner.cancel(message.action_id)
    return
  }

  if (faulted) {
    sendUnavailableResult(message.action_id, 'adapter_faulted', 'adapter is quarantined')
    return
  }

  if (!spawned) {
    sendUnavailableResult(message.action_id, 'unavailable', 'bot has not spawned')
    return
  }

  await runner.run(message.action_id, message.action, message.action.timeout_ms || config.safety.max_action_duration_ms || 20000)
}

function connectBrain() {
  socket = new WebSocket(config.brain.url)
  const sessionId = crypto.randomUUID()

  socket.on('open', () => {
    socketReady = true
    console.log(`[brain] connected to ${config.brain.url}`)
    send({
      type: 'hello',
      client: 'mineflayer-adapter',
      role: 'mineflayer_adapter',
      adapter_id: adapterId,
      session_id: sessionId,
      adapter_version: 'phase1-safe-adapter'
    })
  })

  socket.on('message', async raw => {
    let message
    try {
      message = JSON.parse(raw.toString())
    } catch (error) {
      send({ type: 'error', code: 'invalid_json', message: error.message })
      return
    }

    await handleBrainMessage(message)
  })

  socket.on('close', () => {
    socketReady = false
    console.log('[brain] disconnected; retrying')
    stopEverything()
    if (!faulted) setTimeout(connectBrain, 2000)
  })

  socket.on('error', error => {
    console.error('[brain]', error.message)
  })
}

function startDirectBrain() {
  const pythonPath = path.join(root, 'brain', '.venv', 'Lib', 'site-packages')
  directWorker = spawn(pythonExe, ['-u', 'stdio_worker.py'], {
    cwd: path.join(root, 'brain'),
    env: {
      ...process.env,
      PYTHONPATH: `${pythonPath};${process.env.PYTHONPATH || ''}`
    },
    stdio: ['pipe', 'pipe', 'pipe']
  })
  socketReady = true
  console.log('[brain] direct stdio worker started')

  readline.createInterface({ input: directWorker.stdout }).on('line', async line => {
    if (!line.trim()) return
    let message
    try {
      message = JSON.parse(line)
    } catch (error) {
      console.error('[brain-direct] invalid json:', line)
      return
    }
    if (message.type === 'control_response') {
      console.log(`[brain-direct] ${message.message}`)
      return
    }
    if (message.type === 'worker_error') {
      console.error('[brain-direct]', message.message)
      return
    }
    await handleBrainMessage({ protocol_version: PROTOCOL_VERSION, ...message })
  })

  directWorker.stderr.on('data', chunk => process.stderr.write(`[brain-direct] ${chunk}`))
  directWorker.on('exit', (code, signal) => {
    socketReady = false
    console.error(`[brain-direct] exited code=${code} signal=${signal}`)
    if (!faulted) quarantineAndDisconnect('brain_direct_worker_exited')
  })
}

function submitDirectGoalWhenReady() {
  if (!directMode || !socketReady || !directWorker || !directWorker.stdin.writable) return
  directWorker.stdin.write(JSON.stringify({
    kind: 'goal',
    payload: {
      protocol_version: PROTOCOL_VERSION,
      type: 'goal',
      text: directGoal,
      requested_by: 'direct-evaluator'
    }
  }) + '\n')
}

function compactPosition(position) {
  return {
    x: Number(position.x.toFixed(2)),
    y: Number(position.y.toFixed(2)),
    z: Number(position.z.toFixed(2))
  }
}

function collectNearbyBlocks() {
  const hr = Math.max(1, Math.min(16, Number(config.observation.horizontal_radius || 12)))
  const vr = Math.max(1, Math.min(8, Number(config.observation.vertical_radius || 6)))
  const base = bot.entity.position.floored()
  const counts = {}
  const samples = []

  for (let dx = -hr; dx <= hr; dx += 1) {
    for (let dy = -vr; dy <= vr; dy += 1) {
      for (let dz = -hr; dz <= hr; dz += 1) {
        const block = bot.blockAt(new Vec3(base.x + dx, base.y + dy, base.z + dz))
        if (!block || block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air') continue
        counts[block.name] = (counts[block.name] || 0) + 1
        if (samples.length < 256) samples.push({ name: block.name, dx, dy, dz })
      }
    }
  }

  const oak = bot.registry.blocksByName.oak_log
  if (oak) {
    const knownOak = bot.findBlocks({ matching: oak.id, maxDistance: 64, count: 64 })
    for (const position of knownOak) {
      const dx = position.x - base.x
      const dy = position.y - base.y
      const dz = position.z - base.z
      if (Math.abs(dx) <= hr && Math.abs(dy) <= vr && Math.abs(dz) <= hr) continue
      counts.oak_log = (counts.oak_log || 0) + 1
      if (samples.length < 256) samples.push({ name: 'oak_log', dx, dy, dz })
    }
  }

  return { counts, samples }
}

function collectEntities() {
  const radius = Number(config.observation.entity_radius || 16)
  return Object.values(bot.entities)
    .filter(entity => entity !== bot.entity && entity.position && bot.entity.position.distanceTo(entity.position) <= radius)
    .slice(0, 64)
    .map(entity => ({
      id: entity.id,
      name: entity.name || entity.username || entity.displayName || 'unknown',
      kind: entity.type || 'unknown',
      position: compactPosition(entity.position),
      distance: Number(bot.entity.position.distanceTo(entity.position).toFixed(2)),
      is_valid: entity.isValid !== false
    }))
}

function inventoryCounts() {
  const counts = {}
  for (const item of bot.inventory.items()) counts[item.name] = (counts[item.name] || 0) + item.count
  return counts
}

function movementActive() {
  return Object.values(bot.controlState || {}).some(Boolean)
}

function pathfinderActive() {
  try {
    return Boolean(bot.pathfinder && bot.pathfinder.isMoving && bot.pathfinder.isMoving())
  } catch (_) {
    return false
  }
}

function containerActive() {
  return pendingContainerOperations > 0 || Boolean(bot.currentWindow)
}

async function withContainerOperation(operation) {
  pendingContainerOperations += 1
  try {
    return await operation()
  } finally {
    pendingContainerOperations -= 1
  }
}

function makeObservation() {
  const inventory = bot.inventory.items().map(item => ({ name: item.name, count: item.count, slot: item.slot }))
  const nearby = collectNearbyBlocks()
  const inWater = Boolean(bot.entity.isInWater)
  const oxygen = Number.isFinite(bot.oxygenLevel) ? bot.oxygenLevel : 20
  const onFire = Boolean(bot.entity.onFire)
  const danger = inWater && oxygen < 10 ? 'drowning' : onFire ? 'fire' : null

  return {
    position: compactPosition(bot.entity.position),
    yaw: Number(bot.entity.yaw.toFixed(4)),
    pitch: Number(bot.entity.pitch.toFixed(4)),
    velocity: compactPosition(bot.entity.velocity),
    on_ground: Boolean(bot.entity.onGround),
    health: bot.health,
    food: bot.food,
    saturation: bot.foodSaturation,
    oxygen,
    dimension: bot.game ? bot.game.dimension : null,
    game_mode: bot.game ? bot.game.gameMode : null,
    time_of_day: bot.time ? bot.time.timeOfDay : null,
    is_raining: Boolean(bot.isRaining),
    danger,
    held_item: bot.heldItem ? { name: bot.heldItem.name, count: bot.heldItem.count } : null,
    inventory,
    inventory_counts: inventoryCounts(),
    nearby_blocks: nearby,
    nearby_entities: collectEntities(),
    action_running: Boolean(runner && runner.activeActionId()),
    movement_active: movementActive(),
    pathfinder_active: pathfinderActive(),
    digging_active: Boolean(bot.targetDigBlock),
    container_active: containerActive()
  }
}

async function executeAction(action, signal) {
  const kind = action.kind
  if (signal.aborted) throw Object.assign(new Error('interrupted'), { code: 'interrupted' })

  if (kind === 'noop') return { kind }
  if (kind === 'stop') {
    stopEverything()
    return { kind, reason: action.reason || null }
  }
  if (kind === 'control') {
    const duration = Math.max(50, Math.min(Number(config.safety.max_control_duration_ms || 2000), Number(action.duration_ms || 250)))
    stopEverything()
    for (const [state, value] of Object.entries(action.states || {})) bot.setControlState(state, Boolean(value))
    await delay(duration, signal)
    stopEverything()
    return { kind, duration_ms: duration }
  }
  if (kind === 'look_delta') {
    const yawDelta = Number(action.yaw_delta || 0)
    const pitchDelta = Number(action.pitch_delta || 0)
    const nextPitch = Math.max(-Math.PI / 2, Math.min(Math.PI / 2, bot.entity.pitch + pitchDelta))
    await bot.look(bot.entity.yaw + yawDelta, nextPitch, true)
    return { kind, yaw_delta: yawDelta, pitch_delta: pitchDelta }
  }
  if (kind === 'goto') {
    await gotoNear(Number(action.x), Number(action.y), Number(action.z), Math.max(1, Number(action.radius || 1)), signal)
    return { kind, position: compactPosition(bot.entity.position) }
  }
  if (kind === 'goto_relative') {
    const p = bot.entity.position
    await gotoNear(p.x + Number(action.dx || 0), p.y + Number(action.dy || 0), p.z + Number(action.dz || 0), Math.max(1, Number(action.radius || 1)), signal)
    return { kind, position: compactPosition(bot.entity.position) }
  }
  if (kind === 'mine_nearest') return await mineNearest(action, signal)
  if (kind === 'equip') {
    const itemName = String(action.item || '')
    const item = bot.inventory.items().find(candidate => candidate.name === itemName)
    if (!item) throw Object.assign(new Error(`Item not in inventory: ${itemName}`), { code: 'unavailable' })
    await bot.equip(item, action.destination || 'hand')
    return { kind, item: itemName }
  }
  if (kind === 'eat') {
    const candidates = action.item ? [String(action.item)] : ['cooked_beef', 'cooked_porkchop', 'cooked_chicken', 'bread', 'baked_potato', 'apple', 'carrot']
    const item = bot.inventory.items().find(candidate => candidates.includes(candidate.name))
    if (!item) throw Object.assign(new Error('No configured food found in inventory'), { code: 'unavailable' })
    await bot.equip(item, 'hand')
    await bot.consume()
    return { kind, item: item.name }
  }
  if (kind === 'craft') return await craftItem(action, signal)
  if (kind === 'place_block') return await placeInventoryBlock(action, signal)
  if (kind === 'smelt') return await smeltItem(action, signal)
  throw Object.assign(new Error(`Unsupported action kind: ${kind}`), { code: 'unsupported_action' })
}

async function gotoNear(x, y, z, radius, signal) {
  const promise = bot.pathfinder.goto(new goals.GoalNear(x, y, z, radius))
  signal.addEventListener('abort', () => stopEverything(), { once: true })
  await promise
}

async function gotoBlock(x, y, z, signal) {
  const goal = goals.GoalBlock ? new goals.GoalBlock(x, y, z) : new goals.GoalNear(x, y, z, 0.8)
  const promise = bot.pathfinder.goto(goal)
  signal.addEventListener('abort', () => stopEverything(), { once: true })
  await promise
}

function isEmptyForStanding(block) {
  return !block || block.name === 'air' || block.name === 'cave_air' || block.name === 'void_air' || block.boundingBox === 'empty'
}

function isSolidFloor(block) {
  return Boolean(block && block.boundingBox === 'block')
}

function adjacentStandPositions(target) {
  const candidates = []
  for (let dx = -3; dx <= 3; dx += 1) {
    for (let dz = -3; dz <= 3; dz += 1) {
      if (dx === 0 && dz === 0) continue
      for (let dy = -1; dy <= 1; dy += 1) {
        const x = target.x + dx
        const y = target.y + dy
        const z = target.z + dz
        const feet = bot.blockAt(new Vec3(x, y, z))
        const head = bot.blockAt(new Vec3(x, y + 1, z))
        const floor = bot.blockAt(new Vec3(x, y - 1, z))
        if (!isEmptyForStanding(feet) || !isEmptyForStanding(head) || !isSolidFloor(floor)) continue
        const targetCenter = new Vec3(target.x + 0.5, target.y + 0.5, target.z + 0.5)
        const standCenter = new Vec3(x + 0.5, y + 1.5, z + 0.5)
        if (standCenter.distanceTo(targetCenter) > 4.4) continue
        candidates.push({ x, y, z, distance: bot.entity.position.distanceTo(new Vec3(x + 0.5, y, z + 0.5)) })
      }
    }
  }
  return candidates.sort((a, b) => a.distance - b.distance).slice(0, 8)
}

async function gotoAdjacentForDig(target, signal) {
  for (const stand of adjacentStandPositions(target)) {
    if (signal.aborted) throw Object.assign(new Error('interrupted'), { code: 'interrupted' })
    try {
      await Promise.race([
        gotoBlock(stand.x, stand.y, stand.z, signal),
        delay(3500, signal).then(() => {
          stopEverything()
          throw Object.assign(new Error('candidate approach timed out'), { code: 'unreachable' })
        })
      ])
      return stand
    } catch (error) {
      if (error && (error.code === 'interrupted' || error.code === 'timeout')) throw error
    }
  }
  throw Object.assign(new Error('No adjacent standing position for target block'), { code: 'unreachable' })
}

async function mineNearest(action, signal) {
  const blockName = String(action.block || '')
  const blockType = bot.registry.blocksByName[blockName]
  if (!blockType) throw Object.assign(new Error(`Unknown block: ${blockName}`), { code: 'invalid_block' })

  const beforeCount = inventoryCounts()[blockName] || 0
  const maxDistance = Math.max(2, Number(action.max_distance || 32))
  const botY = bot.entity.position.y
  const foundPositions = bot.findBlocks({ matching: blockType.id, maxDistance, count: 32 })
    .sort((a, b) => {
      const yDelta = Math.abs(a.y - botY) - Math.abs(b.y - botY)
      if (yDelta !== 0) return yDelta
      return bot.entity.position.distanceTo(a) - bot.entity.position.distanceTo(b)
    })
  const reachableLooking = foundPositions.filter(position => position.y >= botY - 2 && position.y <= botY + 3)
  const positions = (reachableLooking.length > 0 ? reachableLooking : foundPositions).slice(0, 12)
  if (positions.length === 0) throw Object.assign(new Error(`No ${blockName} found in range`), { code: 'unavailable' })

  let lastError = null
  for (const target of positions) {
    if (signal.aborted) throw Object.assign(new Error('interrupted'), { code: 'interrupted' })
    try {
      const currentBlock = bot.blockAt(target)
      if (!currentBlock || currentBlock.name === 'air' || currentBlock.name === 'cave_air' || currentBlock.name === 'void_air') {
        const afterCount = inventoryCounts()[blockName] || 0
        if (afterCount > beforeCount) {
          return { kind: 'mine_nearest', block: blockName, position: compactPosition(target), before_count: beforeCount, after_count: afterCount, note: 'target_changed_after_inventory_gain' }
        }
        lastError = Object.assign(new Error('Target block disappeared'), { code: 'unavailable' })
        continue
      }
      if (!bot.canDigBlock(currentBlock)) {
        await gotoAdjacentForDig(target, signal)
      }
      if (!bot.canDigBlock(currentBlock)) {
        const afterCount = inventoryCounts()[blockName] || 0
        if (afterCount > beforeCount) {
          return { kind: 'mine_nearest', block: blockName, position: compactPosition(currentBlock.position), before_count: beforeCount, after_count: afterCount, note: 'inventory_gain_despite_cannot_dig' }
        }
        lastError = Object.assign(new Error(`Cannot dig ${currentBlock.name}`), { code: 'unreachable' })
        continue
      }
      await bot.lookAt(currentBlock.position.offset(0.5, 0.5, 0.5), true)
      await bot.dig(currentBlock, true)
      await delay(900, signal)
      const afterCount = inventoryCounts()[blockName] || 0
      return { kind: 'mine_nearest', block: blockName, position: compactPosition(currentBlock.position), before_count: beforeCount, after_count: afterCount }
    } catch (error) {
      const code = error && error.code ? error.code : 'unreachable'
      if (code === 'interrupted' || code === 'timeout') throw error
      const afterCount = inventoryCounts()[blockName] || 0
      if (afterCount > beforeCount) {
        return { kind: 'mine_nearest', block: blockName, position: compactPosition(target), before_count: beforeCount, after_count: afterCount, note: 'inventory_gain_after_error', error: error.message }
      }
      lastError = Object.assign(new Error(error.message || `Could not dig ${blockName}`), { code })
    }
  }
  throw (lastError || Object.assign(new Error(`No reachable ${blockName} found in range`), { code: 'unreachable' }))
}

function itemCount(name) {
  return inventoryCounts()[name] || 0
}

function findPlacedBlock(name, maxDistance = 8) {
  const blockType = bot.registry.blocksByName[name]
  if (!blockType) return null
  const positions = bot.findBlocks({ matching: blockType.id, maxDistance, count: 16 })
    .sort((a, b) => bot.entity.position.distanceTo(a) - bot.entity.position.distanceTo(b))
  for (const position of positions) {
    const block = bot.blockAt(position)
    if (block && block.name === name) return block
  }
  return null
}

async function craftItem(action, signal) {
  const itemName = String(action.item || '')
  const desiredIncrease = Math.max(1, Math.min(64, Number(action.count || 1)))
  const item = bot.registry.itemsByName[itemName]
  if (!item) throw Object.assign(new Error(`Missing recipe item: ${itemName}`), { code: 'missing_recipe' })
  const before = itemCount(itemName)
  const table = action.use_crafting_table ? findPlacedBlock('crafting_table', 16) : null
  if (action.use_crafting_table && !table) {
    throw Object.assign(new Error('No placed crafting table nearby'), { code: 'missing_crafting_table' })
  }
  if (table) await gotoNear(table.position.x, table.position.y, table.position.z, 2, signal)
  const recipes = bot.recipesFor(item.id, null, 1, table)
  if (!recipes || recipes.length === 0) throw Object.assign(new Error(`No recipe for ${itemName}`), { code: 'missing_recipe' })
  const recipe = recipes[0]
  const outputCount = recipe.result && recipe.result.count ? Number(recipe.result.count) : 1
  const times = Math.max(1, Math.ceil(desiredIncrease / outputCount))
  try {
    await bot.craft(recipe, times, table)
  } catch (error) {
    throw Object.assign(new Error(error && error.message ? error.message : `Could not craft ${itemName}`), { code: 'missing_ingredients' })
  }
  await delay(250, signal)
  const after = itemCount(itemName)
  if (after <= before) {
    throw Object.assign(new Error(`Craft verification failed for ${itemName}`), { code: 'failed_verification' })
  }
  return { kind: 'craft', item: itemName, before_count: before, after_count: after, recipe_applications: times, used_crafting_table: Boolean(table) }
}

function placementCandidates() {
  const base = bot.entity.position.floored()
  const occupied = new Set([
    `${base.x},${base.y},${base.z}`,
    `${base.x},${base.y + 1},${base.z}`
  ])
  const faces = [
    new Vec3(0, 1, 0),
    new Vec3(1, 0, 0),
    new Vec3(-1, 0, 0),
    new Vec3(0, 0, 1),
    new Vec3(0, 0, -1)
  ]
  const candidates = []
  for (let dx = -3; dx <= 3; dx += 1) {
    for (let dy = -2; dy <= 1; dy += 1) {
      for (let dz = -3; dz <= 3; dz += 1) {
        const referencePosition = new Vec3(base.x + dx, base.y + dy, base.z + dz)
        if (bot.entity.position.distanceTo(referencePosition) > 4.5) continue
        for (const face of faces) {
          const target = referencePosition.plus(face)
          if (occupied.has(`${target.x},${target.y},${target.z}`)) continue
          candidates.push({ referencePosition, face, target })
        }
      }
    }
  }
  return candidates.sort((a, b) => {
    const topFaceDelta = (b.face.y === 1 ? 1 : 0) - (a.face.y === 1 ? 1 : 0)
    if (topFaceDelta !== 0) return topFaceDelta
    return bot.entity.position.distanceTo(a.target) - bot.entity.position.distanceTo(b.target)
  })
}

async function placeInventoryBlock(action, signal) {
  const itemName = String(action.item || '')
  const item = bot.inventory.items().find(candidate => candidate.name === itemName)
  if (!item) throw Object.assign(new Error(`Item not in inventory: ${itemName}`), { code: 'missing_ingredients' })
  await bot.equip(item, 'hand')
  let lastError = null
  for (const candidate of placementCandidates()) {
    if (signal.aborted) throw Object.assign(new Error('interrupted'), { code: 'interrupted' })
    const reference = bot.blockAt(candidate.referencePosition)
    if (!reference || reference.boundingBox !== 'block') continue
    const targetBlock = bot.blockAt(candidate.target)
    if (!targetBlock || !['air', 'cave_air', 'void_air'].includes(targetBlock.name)) continue
    try {
      const faceCenter = reference.position.offset(
        0.5 + candidate.face.x * 0.5,
        0.5 + candidate.face.y * 0.5,
        0.5 + candidate.face.z * 0.5
      )
      await bot.lookAt(faceCenter, true)
      await bot.placeBlock(reference, candidate.face)
      await delay(300, signal)
      const placed = bot.blockAt(candidate.target)
      if (placed && placed.name === itemName) {
        return { kind: 'place_block', item: itemName, position: compactPosition(candidate.target) }
      }
      lastError = Object.assign(new Error(`Placed block verification failed for ${itemName}`), { code: 'failed_verification' })
    } catch (error) {
      if (error && error.code === 'interrupted') throw error
      lastError = error
      continue
    }
  }
  const suffix = lastError && lastError.message ? `: ${lastError.message}` : ''
  throw Object.assign(new Error(`No placement location for ${itemName}${suffix}`), { code: 'no_placement_location' })
}

async function smeltItem(action, signal) {
  if (!smeltItemImpl) {
    smeltItemImpl = createSmeltItem({
      bot,
      gotoNear,
      findPlacedBlock,
      itemCount,
      compactPosition,
      withContainerOperation,
      containerActive,
      delay
    })
  }
  return await smeltItemImpl(action, signal)
}

bot.once('spawn', () => {
  spawned = true
  const movements = new Movements(bot)
  movements.canDig = true
  movements.allow1by1towers = false
  movements.allowParkour = false
  movements.allowSprinting = false
  movements.maxDropDown = 2
  movements.infiniteLiquidDropdownDistance = false
  movements.liquidCost = 100
  bot.pathfinder.setMovements(movements)
  console.log(`[minecraft] spawned as ${bot.username}`)
  runner = new ActionRunner({
    execute: executeAction,
    cleanup: async () => stopEverything(),
    observe: makeObservation,
    send,
    logLifecycle,
    onFault: async reason => quarantineAndDisconnect(reason)
  })

  observationTimer = setInterval(() => {
    if (!socketReady || (runner && runner.activeActionId()) || !spawned) return
    send({ type: 'observation', request_id: `obs-${++observationSeq}`, timestamp_ms: Date.now(), state: makeObservation() })
  }, Math.max(100, Number(config.brain.observation_interval_ms || 500)))

  submitDirectGoalWhenReady()
})

bot.on('chat', (username, message) => {
  if (username === bot.username) return
  if (message.startsWith('!goal ')) {
    send({ type: 'goal', text: message.slice(6).trim(), requested_by: username })
  } else if (message === '!pause') {
    send({ type: 'command', command: 'pause', requested_by: username })
  } else if (message === '!resume') {
    send({ type: 'command', command: 'resume', requested_by: username })
  } else if (message === '!status') {
    send({ type: 'command', command: 'status', requested_by: username })
  }
})

bot.on('death', () => {
  stopEverything()
  const actionId = runner && runner.activeActionId() ? runner.activeActionId() : 'no-active-action'
  send({ type: 'event', event: 'death', timestamp_ms: Date.now(), action_id: actionId })
})
bot.on('kicked', reason => console.error('[minecraft] kicked:', reason))
bot.on('error', error => console.error('[minecraft]', error))
bot.on('end', () => {
  spawned = false
  stopEverything()
  if (observationTimer) clearInterval(observationTimer)
  console.log('[minecraft] disconnected')
})

if (directMode) startDirectBrain()
else connectBrain()
