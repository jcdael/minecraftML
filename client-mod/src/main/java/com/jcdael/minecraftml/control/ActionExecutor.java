package com.jcdael.minecraftml.control;

import com.jcdael.minecraftml.protocol.ProtocolV2.Action;
import com.jcdael.minecraftml.protocol.ProtocolV2.ControlAction;
import com.jcdael.minecraftml.protocol.ProtocolV2.LookDeltaAction;
import com.jcdael.minecraftml.protocol.ProtocolV2.SequenceAction;
import com.jcdael.minecraftml.protocol.ProtocolV2.NoopAction;
import com.jcdael.minecraftml.protocol.ProtocolV2.StopAction;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.util.math.Vec3d;

import java.util.ArrayDeque;
import java.util.Deque;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Executes protocol v2 actions with tick-driven state machine.
 * 
 * Safety constraints:
 * - One action at a time
 * - Tick-driven updates
 * - Proper lifecycle evidence
 * - Fail-closed: releases all controls on error or stop
 */
public class ActionExecutor {
    private final AiControlManager controlManager;
    private final MinecraftClient client;
    
    // Current action state
    private final AtomicReference<Action> currentAction = new AtomicReference<>(null);
    private final AtomicReference<ActionState> currentState = new AtomicReference<>(ActionState.IDLE);
    
    // Sequence execution state
    private final Deque<Action> sequenceQueue = new ArrayDeque<>();
    private int sequenceStep = 0;
    
    // Look delta execution state
    private float remainingYawDelta = 0.0f;
    private float remainingPitchDelta = 0.0f;
    
    // Control action execution state
    private int controlActionTicksRemaining = 0;
    
    // Lifecycle evidence
    private long actionStartTick = 0;
    private long actionEndTick = 0;
    private String lastActionType = "none";
    private String lastActionOutcome = "none";
    
    /**
     * Action execution states.
     */
    private enum ActionState {
        IDLE,
        EXECUTING_CONTROL,
        EXECUTING_LOOK_DELTA,
        EXECUTING_SEQUENCE,
        COMPLETING,
        ERROR
    }
    
    /**
     * Create a new ActionExecutor.
     */
    public ActionExecutor(AiControlManager controlManager) {
        this.controlManager = controlManager;
        this.client = MinecraftClient.getInstance();
    }
    
    /**
     * Execute an action.
     * 
     * Safety: Only one action at a time. If an action is already executing,
     * this method returns false and logs a warning.
     */
    public synchronized boolean executeAction(Action action) {
        if (currentAction.get() != null) {
            System.err.println("[ActionExecutor] Cannot execute action: another action is already executing");
            return false;
        }
        
        try {
            currentAction.set(action);
            actionStartTick = client.world.getTime();
            lastActionType = getActionType(action);
            
            if (action instanceof ControlAction) {
                return executeControlAction((ControlAction) action);
            } else if (action instanceof LookDeltaAction) {
                return executeLookDeltaAction((LookDeltaAction) action);
            } else if (action instanceof SequenceAction) {
                return executeSequenceAction((SequenceAction) action);
            } else if (action instanceof NoopAction) {
                return executeNoopAction((NoopAction) action);
            } else if (action instanceof StopAction) {
                return executeStopAction((StopAction) action);
            } else {
                System.err.println("[ActionExecutor] Unknown action type: " + action.getClass().getSimpleName());
                setErrorState("unknown_action_type");
                return false;
            }
        } catch (Exception e) {
            System.err.println("[ActionExecutor] Error executing action: " + e.getMessage());
            e.printStackTrace();
            setErrorState("exception: " + e.getMessage());
            return false;
        }
    }
    
    /**
     * Execute a control action (movement keys).
     */
    private boolean executeControlAction(ControlAction action) {
        // Extract control state from the action
        String key = action.getKey();
        boolean pressed = action.isPressed();
        int duration = action.getDuration();
        
        // Validate duration
        if (duration <= 0) {
            System.err.println("[ActionExecutor] Invalid control duration: " + duration);
            setErrorState("invalid_duration");
            return false;
        }
        
        // Apply control
        controlManager.setAiKeyControl(key, pressed);
        
        // Set execution state
        controlActionTicksRemaining = duration;
        currentState.set(ActionState.EXECUTING_CONTROL);
        
        System.out.println("[ActionExecutor] Started control action: " + key + " = " + pressed + " for " + duration + " ticks");
        return true;
    }
    
    /**
     * Execute a look delta action (smooth camera rotation).
     */
    private boolean executeLookDeltaAction(LookDeltaAction action) {
        float yawDelta = action.getYawDelta();
        float pitchDelta = action.getPitchDelta();
        
        // Validate deltas
        if (Math.abs(yawDelta) > 180.0f || Math.abs(pitchDelta) > 90.0f) {
            System.err.println("[ActionExecutor] Look delta out of bounds: yaw=" + yawDelta + ", pitch=" + pitchDelta);
            setErrorState("look_delta_out_of_bounds");
            return false;
        }
        
        // Set execution state
        remainingYawDelta = yawDelta;
        remainingPitchDelta = pitchDelta;
        currentState.set(ActionState.EXECUTING_LOOK_DELTA);
        
        System.out.println("[ActionExecutor] Started look delta action: yaw=" + yawDelta + ", pitch=" + pitchDelta);
        return true;
    }
    
    /**
     * Execute a sequence action (multiple actions in order).
     */
    private boolean executeSequenceAction(SequenceAction action) {
        Action[] actions = action.getActions();
        int[] delays = action.getDelays();
        
        if (actions == null || actions.length == 0) {
            System.err.println("[ActionExecutor] Empty sequence action");
            setErrorState("empty_sequence");
            return false;
        }
        
        // Add all actions to queue
        sequenceQueue.clear();
        for (Action a : actions) {
            sequenceQueue.add(a);
        }
        sequenceStep = 0;
        
        // Start executing first action
        return startNextSequenceAction();
    }
    
    /**
     * Execute a noop action (do nothing).
     */
    private boolean executeNoopAction(NoopAction action) {
        // No operation - just mark as completed
        completeCurrentAction("noop_completed");
        return true;
    }
    
    /**
     * Execute a stop action (emergency stop).
     */
    private boolean executeStopAction(StopAction action) {
        // Emergency stop - release all controls immediately
        controlManager.releaseAllAiControls();
        completeCurrentAction("emergency_stop");
        return true;
    }
    
    /**
     * Start the next action in a sequence.
     */
    private boolean startNextSequenceAction() {
        if (sequenceQueue.isEmpty()) {
            // Sequence complete
            completeCurrentAction("sequence_completed");
            return true;
        }
        
        Action nextAction = sequenceQueue.poll();
        sequenceStep++;
        
        System.out.println("[ActionExecutor] Starting sequence step " + sequenceStep + ": " + getActionType(nextAction));
        
        // Execute the next action
        if (nextAction instanceof ControlAction) {
            return executeControlAction((ControlAction) nextAction);
        } else if (nextAction instanceof LookDeltaAction) {
            return executeLookDeltaAction((LookDeltaAction) nextAction);
        } else if (nextAction instanceof NoopAction) {
            return executeNoopAction((NoopAction) nextAction);
        } else if (nextAction instanceof StopAction) {
            return executeStopAction((StopAction) nextAction);
        } else {
            System.err.println("[ActionExecutor] Unsupported action type in sequence: " + nextAction.getClass().getSimpleName());
            setErrorState("unsupported_sequence_action");
            return false;
        }
    }
    
    /**
     * Tick update - called every client tick.
     */
    public void tick() {
        ActionState state = currentState.get();
        
        switch (state) {
            case EXECUTING_CONTROL:
                tickControlAction();
                break;
                
            case EXECUTING_LOOK_DELTA:
                tickLookDeltaAction();
                break;
                
            case COMPLETING:
                // Action is completing - clean up
                currentAction.set(null);
                currentState.set(ActionState.IDLE);
                break;
                
            case ERROR:
                // Error state - release controls and reset
                controlManager.releaseAllAiControls();
                currentAction.set(null);
                currentState.set(ActionState.IDLE);
                break;
                
            case IDLE:
            default:
                // Nothing to do
                break;
        }
    }
    
    /**
     * Tick update for control action.
     */
    private void tickControlAction() {
        if (controlActionTicksRemaining <= 0) {
            // Control action complete
            if (currentState.get() == ActionState.EXECUTING_SEQUENCE) {
                // Continue with next sequence action
                startNextSequenceAction();
            } else {
                // Single control action complete
                completeCurrentAction("control_completed");
            }
            return;
        }
        
        controlActionTicksRemaining--;
        
        // Every 20 ticks, log progress
        if (controlActionTicksRemaining % 20 == 0) {
            System.out.println("[ActionExecutor] Control action: " + controlActionTicksRemaining + " ticks remaining");
        }
    }
    
    /**
     * Tick update for look delta action.
     */
    private void tickLookDeltaAction() {
        ClientPlayerEntity player = client.player;
        if (player == null) {
            setErrorState("player_null");
            return;
        }
        
        // Apply smooth rotation (max 10 degrees per tick)
        float yawStep = Math.signum(remainingYawDelta) * Math.min(Math.abs(remainingYawDelta), 10.0f);
        float pitchStep = Math.signum(remainingPitchDelta) * Math.min(Math.abs(remainingPitchDelta), 10.0f);
        
        // Update player look angles
        player.setYaw(player.getYaw() + yawStep);
        player.setPitch(player.getPitch() + pitchStep);
        
        // Update remaining deltas
        remainingYawDelta -= yawStep;
        remainingPitchDelta -= pitchStep;
        
        // Check if look delta is complete
        if (Math.abs(remainingYawDelta) < 0.1f && Math.abs(remainingPitchDelta) < 0.1f) {
            if (currentState.get() == ActionState.EXECUTING_SEQUENCE) {
                // Continue with next sequence action
                startNextSequenceAction();
            } else {
                // Single look delta action complete
                completeCurrentAction("look_delta_completed");
            }
        }
    }
    
    /**
     * Complete the current action.
     */
    private void completeCurrentAction(String outcome) {
        actionEndTick = client.world.getTime();
        lastActionOutcome = outcome;
        
        System.out.println("[ActionExecutor] Action completed: " + outcome + 
                          " (duration: " + (actionEndTick - actionStartTick) + " ticks)");
        
        currentState.set(ActionState.COMPLETING);
    }
    
    /**
     * Set error state and log error.
     */
    private void setErrorState(String error) {
        System.err.println("[ActionExecutor] Action error: " + error);
        lastActionOutcome = "error: " + error;
        currentState.set(ActionState.ERROR);
    }
    
    /**
     * Get the type of an action as a string.
     */
    private String getActionType(Action action) {
        if (action instanceof ControlAction) {
            return "control";
        } else if (action instanceof LookDeltaAction) {
            return "look_delta";
        } else if (action instanceof SequenceAction) {
            return "sequence";
        } else if (action instanceof NoopAction) {
            return "noop";
        } else if (action instanceof StopAction) {
            return "stop";
        } else {
            return "unknown";
        }
    }
    
    /**
     * Get the current action being executed.
     */
    public Action getCurrentAction() {
        return currentAction.get();
    }
    
    /**
     * Get the current execution state.
     */
    public ActionState getCurrentState() {
        return currentState.get();
    }
    
    /**
     * Get lifecycle evidence for the last action.
     */
    public String getLifecycleEvidence() {
        return String.format("Action: %s, Start: %d, End: %d, Outcome: %s",
                           lastActionType, actionStartTick, actionEndTick, lastActionOutcome);
    }
    
    /**
     * Check if an action is currently being executed.
     */
    public boolean isExecuting() {
        return currentAction.get() != null;
    }
    
    /**
     * Cancel the current action.
     */
    public void cancelCurrentAction() {
        if (currentAction.get() != null) {
            System.out.println("[ActionExecutor] Cancelling current action");
            controlManager.releaseAllAiControls();
            currentAction.set(null);
            currentState.set(ActionState.IDLE);
        }
    }
}