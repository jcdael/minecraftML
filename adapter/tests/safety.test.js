'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')
const { ActionRunner, validateAction, validateBrainMessage, PROTOCOL_VERSION } = require('../safety')

function wait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms))
}

function observation(state) {
  return {
    position: { x: 0, y: 64, z: 0 },
    velocity: { x: 0, y: 0, z: 0 },
    health: 20,
    food: 20,
    inventory: [],
    nearby_blocks: { counts: {}, samples: [] },
    nearby_entities: [],
    action_running: state.active,
    movement_active: state.moving,
    pathfinder_active: state.pathing,
    digging_active: state.digging,
    danger: null
  }
}

function makeRunner(execute, options = {}) {
  const state = { active: false, moving: false, pathing: false, digging: false }
  const sent = []
  const logs = []
  const faults = []
  const runner = new ActionRunner({
    execute: async (action, signal) => {
      state.active = true
      return execute(action, signal, state)
    },
    cleanup: async () => {
      if (options.cleanupDelayMs) await wait(options.cleanupDelayMs)
      state.active = false
      state.moving = false
      state.pathing = false
      state.digging = false
      if (options.afterCleanup) options.afterCleanup(state)
    },
    observe: () => observation(state),
    send: payload => sent.push(payload),
    logLifecycle: payload => logs.push(payload),
    onFault: async (reason, context) => {
      faults.push({ reason, action_id: context && context.actionId })
      if (options.onFault) await options.onFault(reason, context, state)
    },
    maxDurationMs: options.maxDurationMs || 1000,
    settlementGraceMs: options.settlementGraceMs || 25,
    postStopGraceMs: options.postStopGraceMs || 20,
    postStopProbeMs: options.postStopProbeMs === undefined ? 5 : options.postStopProbeMs
  })
  return { runner, state, sent, logs, faults }
}

function onlyResult(sent) {
  const results = sent.filter(payload => payload.type === 'result')
  assert.equal(results.length, 1)
  return results[0]
}

test('strict validation rejects coerced values and unknown fields', () => {
  assert.equal(validateAction({ kind: 'control', states: { forward: true }, duration_ms: '250' }).code, 'invalid_number')
  assert.equal(validateAction({ kind: 'goto', x: Infinity, y: 64, z: 0 }).code, 'invalid_number')
  assert.equal(validateAction({ kind: 'noop', unexpected: true }).code, 'unknown_field')
  assert.equal(validateBrainMessage({ protocol_version: PROTOCOL_VERSION, type: 'cancel' }).code, 'invalid_string')
  assert.equal(validateBrainMessage({ protocol_version: PROTOCOL_VERSION, type: 'cancel', action_id: 'act-1', action: { kind: 'stop' } }).code, 'unknown_field')
  assert.equal(validateBrainMessage({ protocol_version: PROTOCOL_VERSION, type: 'cancel', action_id: 'x'.repeat(1_000_100) }).code, 'payload_too_large')
})

test('non-settling execution after abort faults and cannot return success', async () => {
  const { runner, sent, faults, logs } = makeRunner(async (_action, _signal, fake) => {
    fake.moving = true
    await new Promise(() => {})
  }, { settlementGraceMs: 5 })

  await runner.run('act-late', { kind: 'control', states: { forward: true }, duration_ms: 100 }, 5)
  await wait(5)
  const result = onlyResult(sent)
  assert.equal(result.action_id, 'act-late')
  assert.equal(result.ok, false)
  assert.equal(result.code, 'adapter_faulted')
  assert.equal(faults.length, 1)
  assert.equal(faults[0].reason, 'execution_unsettled_after_fence')
  assert.equal(result.lifecycle.faulted, true)
  assert.equal(result.lifecycle.execution_settled.settled, false)
  assert.equal(result.lifecycle.execution_settled.fenced, true)
  assert.equal(result.after_state.movement_active, false)

  await runner.run('act-after-fault', { kind: 'noop' }, 100)
  const faultedResult = sent.find(payload => payload.action_id === 'act-after-fault')
  assert.equal(faultedResult.ok, false)
  assert.equal(faultedResult.code, 'adapter_faulted')
  assert.deepEqual(faultedResult.lifecycle.events.map(event => event.seq), [1, 2, 3, 4, 5])
  assert.deepEqual(faultedResult.lifecycle.events.map(event => event.name), [
    'cleanup_started',
    'cleanup_completed',
    'execution_settled',
    'post_stop_probe_completed',
    'terminal_result'
  ])
  assert.equal(faultedResult.lifecycle.final_activity_state.delayed.movement_active, false)
  assert.ok(logs.find(entry => entry.event === 'action_started' && entry.action_id === 'act-after-fault' && entry.seq === 0))
  assert.ok(logs.find(entry => entry.event === 'terminal_message' && entry.action_id === 'act-after-fault'))
})

test('execution resolving during delayed cleanup is fenced as failed', async () => {
  const { runner, sent } = makeRunner(async () => {
    await wait(15)
    return { resolved_during_cleanup: true }
  }, { cleanupDelayMs: 35, settlementGraceMs: 50 })

  await runner.run('act-cleanup-race', { kind: 'control', states: { forward: true }, duration_ms: 100 }, 5)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'timeout')
  assert.equal(result.lifecycle.execution_settled.settled, true)
  assert.equal(result.lifecycle.execution_settled.ok, true)
  assert.equal(result.lifecycle.cleanup_completed >= result.lifecycle.cleanup_started, true)
})

test('attempted side effect after abort is marked unsafe during post-stop grace', async () => {
  const { runner, sent } = makeRunner(async () => {
    await wait(50)
  }, {
    settlementGraceMs: 5,
    postStopGraceMs: 25,
    afterCleanup: fake => {
      setTimeout(() => {
        fake.moving = true
      }, 5)
    }
  })

  await runner.run('act-side-effect', { kind: 'control', states: { forward: true }, duration_ms: 100 }, 5)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.lifecycle.unsafe_continuation, true)
  assert.equal(result.lifecycle.final_activity_state.final.movement_active, true)
})

test('delayed movement after the original grace window is detected by probe', async () => {
  const { runner, sent } = makeRunner(async (_action, signal) => {
    await new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('interrupted'), { code: 'interrupted' })), { once: true })
    })
  }, {
    postStopGraceMs: 10,
    postStopProbeMs: 35,
    afterCleanup: fake => {
      setTimeout(() => {
        fake.digging = true
      }, 20)
    }
  })

  await runner.run('act-delayed-side-effect', { kind: 'mine_nearest', block: 'oak_log' }, 5)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.lifecycle.unsafe_continuation, true)
  assert.equal(result.lifecycle.final_activity_state.final.digging_active, false)
  assert.equal(result.lifecycle.final_activity_state.delayed.digging_active, true)
})

test('cancellation before execution starts acknowledges inactive state', async () => {
  let executed = false
  const { runner, sent } = makeRunner(async () => {
    executed = true
    await wait(20)
  })

  const running = runner.run('act-pre-cancel', { kind: 'control', states: { forward: true }, duration_ms: 100 }, 500)
  await runner.cancel('act-pre-cancel')
  await running

  const ack = sent.find(payload => payload.type === 'cancel_ack')
  assert.equal(ack.ok, true)
  assert.equal(ack.after_state.action_running, false)
  assert.equal(ack.after_state.movement_active, false)
  assert.equal(executed, false)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'interrupted')
})

test('cancellation during navigation clears pathfinding and emits one terminal result', async () => {
  const { runner, state, sent } = makeRunner(async (_action, signal, fake) => {
    fake.moving = true
    fake.pathing = true
    await new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('interrupted'), { code: 'interrupted' })), { once: true })
    })
  })

  const running = runner.run('act-nav', { kind: 'goto', x: 1, y: 64, z: 1 }, 1000)
  await wait(10)
  await runner.cancel('act-nav')
  await running

  assert.equal(state.moving, false)
  assert.equal(state.pathing, false)
  const ack = sent.find(payload => payload.type === 'cancel_ack')
  assert.equal(ack.ok, true)
  assert.equal(ack.after_state.pathfinder_active, false)
  const result = onlyResult(sent)
  assert.equal(result.action_id, 'act-nav')
  assert.equal(result.ok, false)
  assert.equal(result.code, 'interrupted')
})

test('cancellation during digging clears digging and is idempotent', async () => {
  const { runner, state, sent } = makeRunner(async (_action, signal, fake) => {
    fake.digging = true
    await new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('interrupted'), { code: 'interrupted' })), { once: true })
    })
  })

  const running = runner.run('act-dig', { kind: 'mine_nearest', block: 'oak_log' }, 1000)
  await wait(10)
  await runner.cancel('act-dig')
  await runner.cancel('act-dig')
  await running

  assert.equal(state.digging, false)
  const acks = sent.filter(payload => payload.type === 'cancel_ack' && payload.action_id === 'act-dig')
  assert.equal(acks.length >= 2, true)
  assert.equal(acks.every(ack => ack.ok), true)
  const result = onlyResult(sent)
  assert.equal(result.after_state.digging_active, false)
})

test('unsettled timeout faults, waits cleanup, and never reports success', async () => {
  const { runner, sent, faults } = makeRunner(async (_action, _signal, fake) => {
    fake.moving = true
    await wait(100)
    return { would_have_succeeded: true }
  })

  await runner.run('act-timeout', { kind: 'control', states: { forward: true }, duration_ms: 100 }, 10)
  await wait(5)
  const result = onlyResult(sent)
  assert.equal(result.action_id, 'act-timeout')
  assert.equal(result.ok, false)
  assert.equal(result.code, 'adapter_faulted')
  assert.equal(faults.length, 1)
  assert.equal(result.after_state.movement_active, false)
  assert.equal(result.after_state.action_running, false)
  assert.equal(Boolean(result.detail), false)
})

test('settled timeout remains a normal failed timeout without fault', async () => {
  const { runner, sent, faults } = makeRunner(async (_action, signal, fake) => {
    fake.moving = true
    await new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('interrupted'), { code: 'interrupted' })), { once: true })
    })
  })

  await runner.run('act-settled-timeout', { kind: 'control', states: { forward: true }, duration_ms: 100 }, 10)
  const result = onlyResult(sent)
  assert.equal(result.ok, false)
  assert.equal(result.code, 'timeout')
  assert.equal(result.lifecycle.faulted, undefined)
  assert.deepEqual(result.lifecycle.events.map(event => event.name), [
    'abort_requested',
    'cleanup_started',
    'cleanup_completed',
    'execution_settled',
    'post_stop_probe_completed',
    'terminal_result'
  ])
  assert.equal(faults.length, 0)
})

test('non-settling execute after cancellation rejects new action and quarantines adapter', async () => {
  const { runner, sent, faults } = makeRunner(async (_action, _signal, fake) => {
    fake.digging = true
    await new Promise(() => {})
  }, { settlementGraceMs: 10 })

  const running = runner.run('act-hung-cancel', { kind: 'mine_nearest', block: 'oak_log' }, 1000)
  await wait(10)
  await runner.cancel('act-hung-cancel')
  await runner.run('act-after-fault', { kind: 'noop' }, 1000)
  await running
  await wait(5)

  assert.equal(faults.length, 1)
  const rejected = sent.find(payload => payload.action_id === 'act-after-fault')
  assert.equal(rejected.code, 'adapter_faulted')
  const original = sent.find(payload => payload.action_id === 'act-hung-cancel' && payload.type === 'result')
  assert.equal(original.code, 'adapter_faulted')
})

test('new action attempted during cleanup and fence is rejected before prior settlement', async () => {
  const { runner, sent } = makeRunner(async () => {
    await new Promise(() => {})
  }, { cleanupDelayMs: 50, settlementGraceMs: 50 })

  const running = runner.run('act-cleaning', { kind: 'control', states: { forward: true }, duration_ms: 100 }, 5)
  await wait(10)
  await runner.run('act-during-cleanup', { kind: 'noop' }, 1000)
  await running

  const rejected = sent.find(payload => payload.action_id === 'act-during-cleanup')
  assert.equal(rejected.code, 'new_action_before_prior_settlement')
})

test('concurrent cancel calls share one serialized terminal lifecycle', async () => {
  const { runner, sent } = makeRunner(async (_action, signal) => {
    await new Promise((resolve, reject) => {
      signal.addEventListener('abort', () => reject(Object.assign(new Error('interrupted'), { code: 'interrupted' })), { once: true })
    })
  }, { cleanupDelayMs: 20 })

  const running = runner.run('act-concurrent-cancel', { kind: 'goto', x: 1, y: 64, z: 1 }, 1000)
  await wait(10)
  await Promise.all([runner.cancel('act-concurrent-cancel'), runner.cancel('act-concurrent-cancel')])
  await running

  assert.equal(sent.filter(payload => payload.type === 'result' && payload.action_id === 'act-concurrent-cancel').length, 1)
  const acks = sent.filter(payload => payload.type === 'cancel_ack' && payload.action_id === 'act-concurrent-cancel')
  assert.equal(acks.length, 2)
  assert.equal(acks[0].lifecycle.terminal_result.at, acks[1].lifecycle.terminal_result.at)
})

test('successful action has complete lifecycle and no post-stop activity', async () => {
  const { runner, sent, logs } = makeRunner(async () => ({ done: true }))

  await runner.run('act-ok', { kind: 'noop' }, 1000)
  const result = onlyResult(sent)
  assert.equal(result.ok, true)
  assert.equal(result.lifecycle.action_id, 'act-ok')
  assert.equal(typeof result.lifecycle.started, 'number')
  assert.equal(result.lifecycle.cleanup_completed >= result.lifecycle.cleanup_started, true)
  assert.equal(result.lifecycle.execution_settled.settled, true)
  assert.equal(result.lifecycle.terminal_result.ok, true)
  assert.equal(result.lifecycle.unsafe_continuation, false)
  assert.equal(result.lifecycle.final_activity_state.final.action_running, false)
  assert.deepEqual(result.lifecycle.events.map(event => event.name), [
    'cleanup_started',
    'cleanup_completed',
    'execution_settled',
    'post_stop_probe_completed',
    'terminal_result'
  ])
  assert.deepEqual(result.lifecycle.events.map(event => event.seq), [1, 2, 3, 4, 5])
  assert.equal(logs.find(entry => entry.event === 'action_started').seq, 0)
})
