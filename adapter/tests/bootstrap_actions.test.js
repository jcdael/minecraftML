const assert = require('node:assert/strict')
const test = require('node:test')
const { EventEmitter } = require('node:events')
const { ActionRunner } = require('../safety')
const { createSmeltItem } = require('../bootstrap_actions')

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function signalDelay(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, Math.min(ms, 1))
    signal.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(Object.assign(new Error('interrupted'), { code: 'interrupted' }))
    }, { once: true })
  })
}

function makeHarness(options = {}) {
  const state = {
    inventory: { raw_iron: 1, coal: 1, iron_ingot: 0 },
    containerPending: 0,
    currentWindow: false,
    closed: false,
    moving: false,
    digging: false,
    pathing: false
  }
  const furnaceBlock = { position: { x: 1, y: 64, z: 1 } }
  const furnace = Object.assign(new EventEmitter(), {
    input: null,
    fuel: null,
    output: { name: 'iron_ingot', count: 1 },
    async putInput() {
      state.inventory.raw_iron -= 1
      this.input = { name: 'raw_iron', count: 1 }
    },
    async putFuel() {
      state.inventory.coal -= 1
      this.fuel = { name: 'coal', count: 1 }
      if (options.staleOutputItem) this.emit('updateSlot', 2, null, { name: 'iron_ingot', count: 1, slot: 2 })
    },
    inputItem() {
      return this.input
    },
    fuelItem() {
      return this.fuel
    },
    outputItem() {
      if (options.staleOutputItem) return null
      return this.output
    },
    async takeOutput() {
      if (options.takeOutput) return await options.takeOutput(state)
      state.inventory.iron_ingot += 1
      this.output = null
      return { name: 'iron_ingot', count: 1 }
    },
    close() {
      state.closed = true
      state.currentWindow = false
    }
  })
  const bot = {
    inventory: {
      items: () => [
        ...(state.inventory.raw_iron > 0 ? [{ name: 'raw_iron', type: 100, count: state.inventory.raw_iron }] : []),
        ...(state.inventory.coal > 0 ? [{ name: 'coal', type: 101, count: state.inventory.coal }] : []),
        ...(state.inventory.iron_ingot > 0 ? [{ name: 'iron_ingot', type: 102, count: state.inventory.iron_ingot }] : [])
      ]
    },
    async openFurnace() {
      state.currentWindow = true
      return furnace
    },
    async putAway(slot) {
      if (options.putAway) return await options.putAway(state, slot)
      assert.equal(slot, 2)
      state.inventory.iron_ingot += 1
      furnace.output = null
      return { name: 'iron_ingot', count: 1, slot }
    }
  }
  const smelt = createSmeltItem({
    bot,
    gotoNear: async () => {},
    findPlacedBlock: () => furnaceBlock,
    itemCount: name => state.inventory[name] || 0,
    compactPosition: position => position,
    withContainerOperation: async operation => {
      state.containerPending += 1
      try {
        return await operation()
      } finally {
        state.containerPending -= 1
      }
    },
    containerActive: () => state.containerPending > 0 || state.currentWindow,
    delay: signalDelay
  })
  return { state, smelt }
}

function makeRunner(execute, harness, options = {}) {
  const sent = []
  const faults = []
  const runner = new ActionRunner({
    execute,
    cleanup: async () => {
      harness.state.moving = false
      harness.state.pathing = false
      harness.state.digging = false
      if (options.afterCleanup) options.afterCleanup(harness.state)
    },
    observe: () => ({
      position: { x: 0, y: 64, z: 0 },
      velocity: { x: 0, y: 0, z: 0 },
      health: 20,
      food: 20,
      inventory: [],
      nearby_blocks: { counts: {}, samples: [] },
      nearby_entities: [],
      action_running: false,
      movement_active: harness.state.moving,
      pathfinder_active: harness.state.pathing,
      digging_active: harness.state.digging,
      container_active: harness.state.containerPending > 0 || harness.state.currentWindow,
      danger: null
    }),
    send: payload => sent.push(payload),
    onFault: async (reason, context) => faults.push({ reason, action_id: context && context.actionId }),
    maxDurationMs: options.maxDurationMs || 100,
    settlementGraceMs: options.settlementGraceMs || 10,
    postStopGraceMs: options.postStopGraceMs || 5,
    postStopProbeMs: options.postStopProbeMs === undefined ? 5 : options.postStopProbeMs
  })
  return { runner, sent, faults }
}

function onlyResult(sent) {
  const results = sent.filter(payload => payload.type === 'result')
  assert.equal(results.length, 1)
  return results[0]
}

test('smelt waits for output transfer and faults a delayed window operation after timeout fence', async () => {
  const harness = makeHarness({ takeOutput: async () => new Promise(() => {}) })
  const { runner, sent, faults } = makeRunner((action, signal) => harness.smelt(action, signal), harness, { settlementGraceMs: 5 })

  await runner.run('act-smelt-hang', { kind: 'smelt', input: 'raw_iron', fuel: 'coal', output: 'iron_ingot', timeout_ms: 10 }, 10)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'adapter_faulted')
  assert.equal(result.lifecycle.execution_settled.settled, false)
  assert.equal(result.lifecycle.final_activity_state.final.container_active, true)
  await wait(5)
  assert.equal(faults[0].reason, 'execution_unsettled_after_fence')
})

test('smelt output transfer after cancel quarantines instead of returning late success', async () => {
  let resolveClick
  const harness = makeHarness({ takeOutput: async state => new Promise(resolve => { resolveClick = () => { state.inventory.iron_ingot += 1; resolve() } }) })
  const { runner, sent, faults } = makeRunner((action, signal) => harness.smelt(action, signal), harness, { settlementGraceMs: 5 })

  const running = runner.run('act-smelt-cancel', { kind: 'smelt', input: 'raw_iron', fuel: 'coal', output: 'iron_ingot' }, 100)
  await wait(5)
  await runner.cancel('act-smelt-cancel')
  resolveClick()
  await running

  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'adapter_faulted')
  await wait(5)
  assert.equal(faults.length, 1)
})

test('smelt output transfer failure returns failed action with no ingot success detail', async () => {
  const harness = makeHarness({ takeOutput: async () => { throw new Error('click failed') } })
  const { runner, sent, faults } = makeRunner((action, signal) => harness.smelt(action, signal), harness)

  await runner.run('act-smelt-click-fail', { kind: 'smelt', input: 'raw_iron', fuel: 'coal', output: 'iron_ingot' }, 100)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'action_failed')
  assert.equal(Boolean(result.detail), false)
  assert.equal(faults.length, 0)
})

test('smelt accepts observed furnace output slot when helper output view is stale', async () => {
  const harness = makeHarness({ staleOutputItem: true })
  const { runner, sent } = makeRunner((action, signal) => harness.smelt(action, signal), harness, { maxDurationMs: 200 })

  await runner.run('act-smelt-observed-slot', { kind: 'smelt', input: 'raw_iron', fuel: 'coal', output: 'iron_ingot', timeout_ms: 120 }, 200)
  const result = onlyResult(sent)
  assert.equal(result.ok, true)
  assert.equal(result.detail.output_transfer_source, 'observed_output_slot')
  assert.deepEqual(result.detail.furnace.output_slot_before_take, { name: 'iron_ingot', count: 1, slot: 2 })
})

test('craft place and smelt timeout/cancellation are fenced by the runner', async () => {
  for (const action of [
    { kind: 'craft', item: 'furnace', count: 1, use_crafting_table: true },
    { kind: 'place_block', item: 'furnace' },
    { kind: 'smelt', input: 'raw_iron', fuel: 'coal', output: 'iron_ingot' }
  ]) {
    const harness = makeHarness()
    const { runner, sent } = makeRunner(async () => new Promise(() => {}), harness, { settlementGraceMs: 5 })
    await runner.run(`act-${action.kind}`, action, 5)
    const result = onlyResult(sent)
    assert.equal(result.ok, false)
    assert.equal(result.code, 'adapter_faulted')
  }
})

test('post-stop container side effect is unsafe activity evidence', async () => {
  const harness = makeHarness()
  const { runner, sent } = makeRunner(async () => ({ done: true }), harness, {
    afterCleanup: fake => {
      setTimeout(() => {
        fake.currentWindow = true
      }, 1)
    },
    postStopGraceMs: 5,
    postStopProbeMs: 5
  })

  await runner.run('act-post-stop-container', { kind: 'noop' }, 100)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'unsafe_continuation')
  assert.equal(result.lifecycle.unsafe_continuation, true)
  assert.equal(result.lifecycle.final_activity_state.final.container_active, true)
})
