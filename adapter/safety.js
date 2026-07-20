'use strict'

const PROTOCOL_VERSION = 1
const MAX_DURATION_MS = 180000
const MAX_ABS_COORD = 30000000
const MAX_MESSAGE_BYTES = 1000000
const DEFAULT_SETTLEMENT_GRACE_MS = 250
const DEFAULT_POST_STOP_GRACE_MS = 150
const DEFAULT_POST_STOP_PROBE_MS = 50
const ACTIVITY_KEYS = [
  'action_running',
  'movement_active',
  'pathfinder_active',
  'digging_active',
  'container_active'
]
const SUPPORTED_ACTIONS = new Set([
  'noop',
  'stop',
  'control',
  'look_delta',
  'goto',
  'goto_relative',
  'mine_nearest',
  'equip',
  'eat',
  'craft',
  'place_block',
  'smelt'
])

function validationError(code, message) {
  return { ok: false, code, message }
}

function validationOk() {
  return { ok: true }
}

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function hasUnknownKeys(value, allowed) {
  return Object.keys(value).filter(key => !allowed.has(key))
}

function numberIn(value, field, min, max) {
  if (typeof value !== 'number' || Number.isNaN(value) || !Number.isFinite(value)) {
    return validationError('invalid_number', `${field} must be a finite number`)
  }
  if (value < min || value > max) return validationError('number_out_of_range', `${field} out of range`)
  return validationOk()
}

function nonEmptyString(value, field, maxLength = 128) {
  if (typeof value !== 'string' || value.length < 1 || value.length > maxLength) {
    return validationError('invalid_string', `${field} must be a non-empty string`)
  }
  return validationOk()
}

function validateAction(action) {
  if (!isPlainObject(action)) return validationError('invalid_action', 'action must be an object')
  if (!SUPPORTED_ACTIONS.has(action.kind)) return validationError('unsupported_action', `unsupported action kind: ${action.kind}`)
  if (Array.isArray(action.steps)) return validationError('malformed_sequence', 'nested sequences are not supported')

  if (action.kind === 'noop') {
    const unknown = hasUnknownKeys(action, new Set(['kind']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    return validationOk()
  }
  if (action.kind === 'stop') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'reason']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    if (action.reason !== undefined) return nonEmptyString(action.reason, 'reason', 128)
    return validationOk()
  }
  if (action.kind === 'control') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'states', 'duration_ms', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    if (!isPlainObject(action.states)) return validationError('invalid_states', 'control.states must be an object')
    const allowed = new Set(['forward', 'back', 'left', 'right', 'jump', 'sprint', 'sneak'])
    for (const [key, value] of Object.entries(action.states)) {
      if (!allowed.has(key)) return validationError('unknown_control_state', `unknown control state: ${key}`)
      if (typeof value !== 'boolean') return validationError('invalid_states', 'control states must be booleans')
    }
    if (Object.keys(action.states).length < 1) return validationError('invalid_states', 'control.states must not be empty')
    const duration = numberIn(action.duration_ms === undefined ? 250 : action.duration_ms, 'duration_ms', 1, MAX_DURATION_MS)
    if (!duration.ok) return duration
    if (action.timeout_ms !== undefined) return numberIn(action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
    return validationOk()
  }
  if (action.kind === 'look_delta') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'yaw_delta', 'pitch_delta', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    const yaw = numberIn(action.yaw_delta === undefined ? 0 : action.yaw_delta, 'yaw_delta', -6.2832, 6.2832)
    if (!yaw.ok) return yaw
    const pitch = numberIn(action.pitch_delta === undefined ? 0 : action.pitch_delta, 'pitch_delta', -3.1416, 3.1416)
    if (!pitch.ok) return pitch
    if (action.timeout_ms !== undefined) return numberIn(action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
    return validationOk()
  }
  if (action.kind === 'goto') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'x', 'y', 'z', 'radius', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    for (const field of ['x', 'y', 'z']) {
      const result = numberIn(action[field], field, -MAX_ABS_COORD, MAX_ABS_COORD)
      if (!result.ok) return result
    }
    const radius = numberIn(action.radius === undefined ? 1 : action.radius, 'radius', 0.5, 16)
    if (!radius.ok) return radius
    if (action.timeout_ms !== undefined) return numberIn(action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
    return validationOk()
  }
  if (action.kind === 'goto_relative') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'dx', 'dy', 'dz', 'radius', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    for (const field of ['dx', 'dy', 'dz']) {
      const result = numberIn(action[field] === undefined ? 0 : action[field], field, -64, 64)
      if (!result.ok) return result
    }
    const radius = numberIn(action.radius === undefined ? 1 : action.radius, 'radius', 0.5, 16)
    if (!radius.ok) return radius
    if (action.timeout_ms !== undefined) return numberIn(action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
    return validationOk()
  }
  if (action.kind === 'mine_nearest') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'block', 'max_distance', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    const block = nonEmptyString(action.block, 'block', 128)
    if (!block.ok) return block
    const distance = numberIn(action.max_distance === undefined ? 24 : action.max_distance, 'max_distance', 1, 64)
    if (!distance.ok) return distance
    return numberIn(action.timeout_ms === undefined ? 20000 : action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
  }
  if (action.kind === 'equip') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'item', 'destination', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    const item = nonEmptyString(action.item, 'item', 128)
    if (!item.ok) return item
    if (action.timeout_ms !== undefined) return numberIn(action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
    return validationOk()
  }
  if (action.kind === 'eat') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'item', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    if (action.item !== undefined) {
      const item = nonEmptyString(action.item, 'item', 128)
      if (!item.ok) return item
    }
    return numberIn(action.timeout_ms === undefined ? 8000 : action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
  }
  if (action.kind === 'craft') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'item', 'count', 'use_crafting_table', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    const allowed = new Set(['oak_planks', 'crafting_table', 'stick', 'wooden_pickaxe', 'stone_pickaxe', 'furnace'])
    const item = nonEmptyString(action.item, 'item', 128)
    if (!item.ok) return item
    if (!allowed.has(action.item)) return validationError('unsupported_recipe', 'craft action is limited to bootstrap recipes')
    const count = numberIn(action.count === undefined ? 1 : action.count, 'count', 1, 64)
    if (!count.ok) return count
    if (action.use_crafting_table !== undefined && typeof action.use_crafting_table !== 'boolean') return validationError('invalid_bool', 'use_crafting_table must be boolean')
    return numberIn(action.timeout_ms === undefined ? 10000 : action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
  }
  if (action.kind === 'place_block') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'item', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    const item = nonEmptyString(action.item, 'item', 128)
    if (!item.ok) return item
    if (!new Set(['crafting_table', 'furnace']).has(action.item)) return validationError('unsupported_place_block', 'place_block is limited to crafting_table and furnace')
    return numberIn(action.timeout_ms === undefined ? 8000 : action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
  }
  if (action.kind === 'smelt') {
    const unknown = hasUnknownKeys(action, new Set(['kind', 'input', 'fuel', 'output', 'count', 'timeout_ms']))
    if (unknown.length) return validationError('unknown_field', `unknown action fields: ${unknown.join(',')}`)
    if (action.input !== 'raw_iron') return validationError('unsupported_smelt_input', 'smelt supports only raw_iron')
    if (action.fuel !== 'coal') return validationError('unsupported_smelt_fuel', 'smelt supports only coal')
    if (action.output !== 'iron_ingot') return validationError('unsupported_smelt_output', 'smelt supports only iron_ingot')
    const count = numberIn(action.count === undefined ? 1 : action.count, 'count', 1, 8)
    if (!count.ok) return count
    return numberIn(action.timeout_ms === undefined ? 60000 : action.timeout_ms, 'timeout_ms', 1, MAX_DURATION_MS)
  }
  return validationOk()
}

function validateBrainMessage(message) {
  if (!isPlainObject(message)) return validationError('invalid_message', 'message must be an object')
  let size = 0
  try {
    size = Buffer.byteLength(JSON.stringify(message), 'utf8')
  } catch (_) {
    return validationError('invalid_message', 'message must be JSON serializable')
  }
  if (size > MAX_MESSAGE_BYTES) return validationError('payload_too_large', 'message payload is too large')
  const unknown = hasUnknownKeys(message, new Set(['protocol_version', 'type', 'action_id', 'action']))
  if (unknown.length) return validationError('unknown_field', `unknown message fields: ${unknown.join(',')}`)
  if (message.protocol_version !== PROTOCOL_VERSION) return validationError('unsupported_protocol_version', 'unsupported protocol version')
  if (message.type === 'action') {
    const id = nonEmptyString(message.action_id, 'action_id', 64)
    if (!id.ok) return id
    return validateAction(message.action)
  }
  if (message.type === 'cancel') {
    if (message.action !== undefined) return validationError('unknown_field', 'cancel must not include action')
    return nonEmptyString(message.action_id, 'action_id', 64)
  }
  return validationError('unsupported_message_type', `unsupported message type: ${message.type}`)
}

function delay(ms, signal) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, ms)
    if (signal) {
      signal.addEventListener('abort', () => {
        clearTimeout(timer)
        reject(Object.assign(new Error('interrupted'), { code: 'interrupted' }))
      }, { once: true })
    }
  })
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function activityFromObservation(observation) {
  const activity = {}
  for (const key of ACTIVITY_KEYS) activity[key] = Boolean(observation && observation[key])
  return activity
}

function anyActivity(activity) {
  return ACTIVITY_KEYS.some(key => Boolean(activity[key]))
}

function buildStandaloneLifecycle(actionId, code, afterState = null, faultReason = null, at = Date.now()) {
  const activity = afterState ? activityFromObservation(afterState) : null
  const unsafe = activity ? anyActivity(activity) : false
  const faulted = code === 'adapter_faulted'
  return {
    action_id: actionId,
    started: at,
    abort_requested: null,
    cleanup_started: at,
    cleanup_completed: at,
    execution_settled: { at, settled: true, ok: false, skipped: true },
    terminal_result: { at, ok: false, code },
    final_activity_state: activity ? { first: activity, final: activity, delayed: activity } : null,
    unsafe_continuation: unsafe,
    faulted,
    fault_reason: faulted ? (faultReason || 'adapter_faulted') : null,
    events: [
      { seq: 1, name: 'cleanup_started', at },
      { seq: 2, name: 'cleanup_completed', at },
      { seq: 3, name: 'execution_settled', at },
      { seq: 4, name: 'post_stop_probe_completed', at, unsafe_continuation: unsafe },
      { seq: 5, name: 'terminal_result', at }
    ]
  }
}

class ActionRunner {
  constructor({
    execute,
    cleanup,
    observe,
    send,
    logLifecycle = () => {},
    onFault = () => {},
    maxDurationMs = MAX_DURATION_MS,
    settlementGraceMs = DEFAULT_SETTLEMENT_GRACE_MS,
    postStopGraceMs = DEFAULT_POST_STOP_GRACE_MS,
    postStopProbeMs = DEFAULT_POST_STOP_PROBE_MS
  }) {
    this.execute = execute
    this.cleanup = cleanup
    this.observe = observe
    this.send = send
    this.logLifecycle = logLifecycle
    this.onFault = onFault
    this.maxDurationMs = maxDurationMs
    this.settlementGraceMs = settlementGraceMs
    this.postStopGraceMs = postStopGraceMs
    this.postStopProbeMs = postStopProbeMs
    this.active = null
    this.cleanupPromise = null
    this.faulted = false
    this.faultReason = null
  }

  activeActionId() {
    return this.active ? this.active.actionId : null
  }

  async run(actionId, action, timeoutMs) {
    if (this.faulted) {
      const state = this.observe()
      const lifecycle = this._standaloneLifecycle(actionId, 'adapter_faulted', state)
      this._log({ event: 'action_started', action_id: actionId, seq: 0, at: lifecycle.started })
      this._sendAndLog({
        type: 'result',
        action_id: actionId,
        ok: false,
        elapsed_ms: 0,
        before_state: state,
        after_state: state,
        code: 'adapter_faulted',
        error: this.faultReason || 'adapter is faulted',
        lifecycle
      })
      return
    }
    if (this.active) {
      const state = this.observe()
      const code = this.active.executeSettled ? 'busy' : 'new_action_before_prior_settlement'
      const lifecycle = this._standaloneLifecycle(actionId, code, state)
      this._log({ event: 'action_started', action_id: actionId, seq: 0, at: lifecycle.started })
      this._sendAndLog({
        type: 'result',
        action_id: actionId,
        ok: false,
        elapsed_ms: 0,
        before_state: state,
        after_state: state,
        code,
        error: 'one active action already running',
        lifecycle
      })
      return
    }

    const startedAt = Date.now()
    const before = this.observe()
    const controller = new AbortController()
    const context = {
      actionId,
      action,
      controller,
      startedAt,
      before,
      terminalSent: false,
      abortReason: null,
      executeStarted: false,
      executeSettled: false,
      executeOk: false,
      executeDetail: null,
      executeError: null,
      cleanupStarted: false,
      cleanupCompleted: false,
      cleanupPromise: null,
      terminalPromise: null,
      terminalKind: null,
      finalActivityState: null,
      unsafeContinuation: false,
      lifecycleSeq: 0,
      lifecycle: {
        action_id: actionId,
        started: startedAt,
        abort_requested: null,
        cleanup_started: null,
        cleanup_completed: null,
        execution_settled: null,
        terminal_result: null,
        final_activity_state: null,
        unsafe_continuation: false,
        events: []
      }
    }
    this.active = context
    this._log({ event: 'action_started', action_id: actionId, seq: 0, at: startedAt })

    const boundedTimeout = Math.max(1, Math.min(this.maxDurationMs, timeoutMs || this.maxDurationMs))
    context.timeoutTimer = setTimeout(() => {
      this._requestAbort(context, 'timeout')
    }, boundedTimeout)

    await Promise.resolve()
    if (!context.abortReason) {
      context.executeStarted = true
      context.executePromise = Promise.resolve()
        .then(() => this.execute(action, controller.signal))
        .then(detail => {
          context.executeSettled = true
          context.executeOk = true
          context.executeDetail = detail
        })
        .catch(error => {
          context.executeSettled = true
          context.executeOk = false
          context.executeError = error
        })
    } else {
      context.executeSettled = true
      context.executeOk = false
      context.executeError = Object.assign(new Error('cancelled before execution started'), { code: context.abortReason })
    }

    if (context.executePromise) await this._waitForExecutionOrAbort(context)
    await this._terminalize(context, 'result')
  }

  async cancel(actionId) {
    if (this.faulted) {
      const after = this.observe()
      this._sendAndLog({
        type: 'cancel_ack',
        action_id: actionId,
        ok: false,
        code: 'adapter_faulted',
        after_state: after,
        lifecycle: this._standaloneLifecycle(actionId, 'adapter_faulted', after)
      })
      return
    }
    if (!this.active) {
      await this._runCleanup(null)
      const after = this.observe()
      this._sendAndLog({
        type: 'cancel_ack',
        action_id: actionId,
        ok: true,
        code: 'no_active_action',
        after_state: after,
        lifecycle: this._standaloneLifecycle(actionId, 'no_active_action', after)
      })
      return
    }
    if (this.active.actionId !== actionId) {
      this._sendAndLog({
        type: 'cancel_ack',
        action_id: actionId,
        ok: false,
        code: 'mismatched_action_id',
        lifecycle: this._standaloneLifecycle(actionId, 'mismatched_action_id')
      })
      return
    }

    const context = this.active
    this._requestAbort(context, 'interrupted')
    await this._terminalize(context, 'cancel')
    const after = context.afterState || this.observe()
    this._sendAndLog({
      type: 'cancel_ack',
      action_id: actionId,
      ok: !context.faulted,
      code: context.faulted ? 'adapter_faulted' : undefined,
      after_state: after,
      lifecycle: { ...context.lifecycle }
    })
  }

  _requestAbort(context, reason) {
    if (!context || context.abortReason) return
    context.abortReason = reason
    const event = this._recordLifecycleEvent(context, 'abort_requested', { reason })
    context.lifecycle.abort_requested = event.at
    context.controller.abort()
  }

  async _waitForExecutionOrAbort(context) {
    while (!context.executeSettled && !context.abortReason) {
      await sleep(5)
    }
    if (context.abortReason) await this._waitForExecutionFence(context, false)
  }

  async _waitForExecutionFence(context, recordLifecycle = true) {
    if (!context.executePromise || context.executeSettled) {
      if (recordLifecycle) this._recordExecutionSettled(context, true, Boolean(context.executeOk), false)
      return
    }
    const deadline = Date.now() + this.settlementGraceMs
    while (!context.executeSettled && Date.now() < deadline) {
      await sleep(5)
    }
    if (recordLifecycle) {
      this._recordExecutionSettled(
        context,
        Boolean(context.executeSettled),
        Boolean(context.executeSettled && context.executeOk),
        !context.executeSettled
      )
    }
    if (!context.executeSettled) {
      await this._fault(context, 'execution_unsettled_after_fence')
    }
  }

  async _terminalize(context, kind) {
    if (context.terminalPromise) return context.terminalPromise
    context.terminalKind = kind
    context.terminalPromise = this._finishTerminal(context)
    return context.terminalPromise
  }

  async _finishTerminal(context) {
    if (context.terminalSent) return
    context.terminalSent = true
    if (context.timeoutTimer) clearTimeout(context.timeoutTimer)

    if (context.abortReason || !context.executeSettled || !context.executeOk) {
      this._requestAbort(context, context.abortReason || 'action_failed')
      await this._runCleanup(context)
      await this._waitForExecutionFence(context)
    }

    await this._runCleanup(context)

    if (!context.lifecycle.execution_settled) {
      this._recordExecutionSettled(
        context,
        Boolean(context.executeSettled),
        Boolean(context.executeSettled && context.executeOk),
        false
      )
    }

    if (context.faulted || !context.executeSettled) {
      await this._runCleanup(context)
      const after = await this._verifyQuiescence(context)
      context.afterState = after
      this._recordTerminalResult(context, false, 'adapter_faulted')
      this._sendAndLog({
        type: 'result',
        action_id: context.actionId,
        ok: false,
        elapsed_ms: Date.now() - context.startedAt,
        before_state: context.before,
        after_state: after,
        code: 'adapter_faulted',
        error: this.faultReason || 'execution did not settle before fence',
        lifecycle: { ...context.lifecycle }
      })
      this._scheduleFaultTeardown(context)
      return
    }

    const after = await this._verifyQuiescence(context)
    context.afterState = after
    const wasAborted = Boolean(context.abortReason)
    const ok = !wasAborted && context.executeSettled && context.executeOk && !context.unsafeContinuation
    const code = ok ? undefined : this._failureCode(context)
    const error = ok ? undefined : this._failureMessage(context, code)
    this._recordTerminalResult(context, ok, code || null)

    const result = {
      type: 'result',
      action_id: context.actionId,
      ok,
      elapsed_ms: Date.now() - context.startedAt,
      before_state: context.before,
      after_state: after,
      lifecycle: { ...context.lifecycle }
    }
    if (ok) result.detail = context.executeDetail
    else {
      result.code = code
      result.error = error
    }
    if (this.active === context) this.active = null
    this._sendAndLog(result)
  }

  _failureCode(context) {
    if (context.abortReason === 'timeout') return 'timeout'
    if (context.abortReason === 'interrupted') return 'interrupted'
    if (context.unsafeContinuation) return 'unsafe_continuation'
    if (!context.executeSettled) return context.abortReason || 'execution_unsettled'
    return context.executeError && context.executeError.code ? String(context.executeError.code) : (context.abortReason || 'action_failed')
  }

  _failureMessage(context, code) {
    if (code === 'timeout') return 'action timed out'
    if (context.executeError && context.executeError.message) return String(context.executeError.message)
    return code
  }

  async _runCleanup(context) {
    if (this.cleanupPromise) {
      await this.cleanupPromise
      return
    }
    if (context && !context.cleanupStarted) {
      context.cleanupStarted = true
      const event = this._recordLifecycleEvent(context, 'cleanup_started')
      context.lifecycle.cleanup_started = event.at
    }
    this.cleanupPromise = Promise.resolve()
      .then(() => this.cleanup())
      .finally(() => {
        this.cleanupPromise = null
      })
    await this.cleanupPromise
    if (context && !context.cleanupCompleted) {
      context.cleanupCompleted = true
      const event = this._recordLifecycleEvent(context, 'cleanup_completed')
      context.lifecycle.cleanup_completed = event.at
    }
  }

  async _fault(context, reason) {
    if (this.faulted) return
    this.faulted = true
    this.faultReason = reason
    if (context) {
      context.faulted = true
      context.lifecycle.faulted = true
      context.lifecycle.fault_reason = reason
    }
    this._log({ event: 'adapter_faulted', action_id: context ? context.actionId : null, reason, at: Date.now() })
  }

  _scheduleFaultTeardown(context) {
    if (!this.faulted || this.faultTeardownScheduled) return
    this.faultTeardownScheduled = true
    setTimeout(() => {
      Promise.resolve()
        .then(() => this.onFault(this.faultReason, context))
        .catch(error => this._log({
          event: 'adapter_fault_teardown_error',
          action_id: context ? context.actionId : null,
          message: error && error.message ? String(error.message) : String(error),
          at: Date.now()
        }))
    }, 0)
  }

  _sendAndLog(payload) {
    this.send(payload)
    if (payload.lifecycle) {
      this._log({
        event: 'terminal_message',
        message_type: payload.type,
        action_id: payload.action_id,
        code: payload.code || null,
        ok: payload.ok,
        lifecycle: payload.lifecycle,
        at: Date.now()
      })
    }
  }

  _log(payload) {
    try {
      this.logLifecycle(payload)
    } catch (_) {
      // Logging must not make cleanup or fault handling less safe.
    }
  }

  async _verifyQuiescence(context) {
    await this._runCleanup(context)
    const first = this._reportedObservation(context, this.observe())
    const firstActivity = activityFromObservation(first)
    if (this.postStopGraceMs > 0) await sleep(this.postStopGraceMs)
    const second = this._reportedObservation(context, this.observe())
    const secondActivity = activityFromObservation(second)
    if (this.postStopProbeMs > 0) await sleep(this.postStopProbeMs)
    const third = this._reportedObservation(context, this.observe())
    const thirdActivity = activityFromObservation(third)
    const unsafe = anyActivity(firstActivity) || anyActivity(secondActivity) || anyActivity(thirdActivity)
    const finalState = {
      first: firstActivity,
      final: secondActivity,
      delayed: thirdActivity
    }
    if (context) {
      context.finalActivityState = finalState
      context.unsafeContinuation = unsafe
      context.lifecycle.final_activity_state = finalState
      context.lifecycle.unsafe_continuation = unsafe
      this._recordLifecycleEvent(context, 'post_stop_probe_completed', { unsafe_continuation: unsafe })
    }
    return second
  }

  _recordLifecycleEvent(context, name, extra = {}) {
    const event = {
      seq: ++context.lifecycleSeq,
      name,
      at: Date.now(),
      ...extra
    }
    context.lifecycle.events.push(event)
    return event
  }

  _recordExecutionSettled(context, settled, ok, fenced) {
    if (context.lifecycle.execution_settled) return
    const event = this._recordLifecycleEvent(context, 'execution_settled')
    context.lifecycle.execution_settled = {
      at: event.at,
      settled,
      ok
    }
    if (fenced) context.lifecycle.execution_settled.fenced = true
  }

  _recordTerminalResult(context, ok, code) {
    if (context.lifecycle.terminal_result) return
    const event = this._recordLifecycleEvent(context, 'terminal_result')
    context.lifecycle.terminal_result = {
      at: event.at,
      ok,
      code
    }
  }

  _reportedObservation(context, observation) {
    if (!context || this.active !== context || !context.executeSettled) return observation
    return { ...observation, action_running: false }
  }

  _standaloneLifecycle(actionId, code, afterState = null) {
    return buildStandaloneLifecycle(actionId, code, afterState, this.faultReason)
  }
}

module.exports = {
  PROTOCOL_VERSION,
  MAX_DURATION_MS,
  validateAction,
  validateBrainMessage,
  ActionRunner,
  buildStandaloneLifecycle,
  delay
}
