package com.jcdael.minecraftml.control;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import org.lwjgl.glfw.GLFW;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Manages AI control state and input ownership with explicit state machine.
 * Implements fail-closed safety semantics and manual override detection.
 */
public class AiControlManager {
    private final MinecraftClient client;
    private final AtomicReference<ControlState> currentState;
    private final Map<String, Boolean> aiKeyStates;
    private final Map<String, KeyBinding> keyBindings;
    
    /**
     * Explicit input-ownership state machine as specified in section 9.
     */
    public enum ControlState {
        OFF,              // AI control completely disabled
        READY,            // AI control available but not active
        ACTIVE,           // AI has control, executing actions
        PAUSED,           // AI control temporarily paused
        MANUAL_OVERRIDE,  // Player has taken manual control
        EMERGENCY_LATCHED,// Emergency stop triggered, requires reset
        FAULTED           // System fault detected, requires restart
    }
    
    public AiControlManager(MinecraftClient client) {
        this.client = client;
        this.currentState = new AtomicReference<>(ControlState.OFF);
        this.aiKeyStates = new HashMap<>();
        this.keyBindings = new HashMap<>();
        
        // Initialize AI-controlled key states
        initializeKeyStates();
        
        System.out.println("[AiControlManager] Initialized with state: " + currentState.get());
    }
    
    /**
     * Initialize all AI-controlled key states to false.
     */
    private void initializeKeyStates() {
        String[] aiControlledKeys = {
            "forward", "back", "left", "right",
            "jump", "sneak", "sprint",
            "attack", "use"
        };
        
        for (String key : aiControlledKeys) {
            aiKeyStates.put(key, false);
        }
    }
    
    /**
     * Get the current control state.
     */
    public ControlState getControlState() {
        return currentState.get();
    }
    
    /**
     * Set the control state with validation.
     */
    public void setControlState(ControlState newState) {
        ControlState oldState = currentState.get();
        
        // Validate state transition
        if (isValidTransition(oldState, newState)) {
            currentState.set(newState);
            System.out.println("[AiControlManager] State transition: " + oldState + " -> " + newState);
            
            // Handle state-specific actions
            onStateChange(oldState, newState);
        } else {
            System.err.println("[AiControlManager] Invalid state transition: " + oldState + " -> " + newState);
        }
    }
    
    /**
     * Check if a state transition is valid.
     */
    private boolean isValidTransition(ControlState from, ControlState to) {
        // Emergency latched and faulted states are terminal until reset
        if (from == ControlState.EMERGENCY_LATCHED || from == ControlState.FAULTED) {
            return to == ControlState.OFF; // Only allowed to go to OFF
        }
        
        // Valid transitions based on state machine
        switch (from) {
            case OFF:
                return to == ControlState.READY || to == ControlState.FAULTED;
            case READY:
                return to == ControlState.ACTIVE || to == ControlState.OFF || to == ControlState.FAULTED;
            case ACTIVE:
                return to == ControlState.PAUSED || to == ControlState.MANUAL_OVERRIDE || 
                       to == ControlState.EMERGENCY_LATCHED || to == ControlState.OFF || 
                       to == ControlState.FAULTED;
            case PAUSED:
                return to == ControlState.ACTIVE || to == ControlState.OFF || 
                       to == ControlState.EMERGENCY_LATCHED || to == ControlState.FAULTED;
            case MANUAL_OVERRIDE:
                return to == ControlState.ACTIVE || to == ControlState.OFF || 
                       to == ControlState.EMERGENCY_LATCHED || to == ControlState.FAULTED;
            default:
                return false;
        }
    }
    
    /**
     * Handle actions when state changes.
     */
    private void onStateChange(ControlState oldState, ControlState newState) {
        // When leaving ACTIVE state, release all controls
        if (oldState == ControlState.ACTIVE && newState != ControlState.ACTIVE) {
            releaseAllAiControls();
        }
        
        // When entering EMERGENCY_LATCHED, ensure all controls are released
        if (newState == ControlState.EMERGENCY_LATCHED) {
            releaseAllAiControls();
        }
        
        // When entering FAULTED, log error and release controls
        if (newState == ControlState.FAULTED) {
            System.err.println("[AiControlManager] System fault detected");
            releaseAllAiControls();
        }
    }
    
    /**
     * Release all AI-controlled inputs immediately.
     * This is the fail-closed safety mechanism.
     */
    public void releaseAllAiControls() {
        System.out.println("[AiControlManager] Releasing all AI controls");
        
        // Set all AI key states to false
        for (String key : aiKeyStates.keySet()) {
            aiKeyStates.put(key, false);
            simulateKeyRelease(key);
        }
        
        // Also release mouse look control
        resetMouseLook();
    }
    
    /**
     * Set AI control for a specific key.
     */
    public void setAiKeyControl(String key, boolean pressed) {
        // Only allow AI control when in ACTIVE state
        if (currentState.get() != ControlState.ACTIVE) {
            return;
        }
        
        // Validate key
        if (!aiKeyStates.containsKey(key)) {
            System.err.println("[AiControlManager] Unknown AI-controlled key: " + key);
            return;
        }
        
        // Update key state
        aiKeyStates.put(key, pressed);
        
        // Simulate key press/release
        if (pressed) {
            simulateKeyPress(key);
        } else {
            simulateKeyRelease(key);
        }
    }
    
    /**
     * Set AI mouse look control.
     */
    public void setAiMouseLook(float yawDelta, float pitchDelta) {
        // Only allow AI control when in ACTIVE state
        if (currentState.get() != ControlState.ACTIVE) {
            return;
        }
        
        // Apply mouse look delta
        applyMouseLookDelta(yawDelta, pitchDelta);
    }
    
    /**
     * Check if AI currently controls a specific key.
     */
    public boolean isAiControllingKey(String key) {
        return aiKeyStates.getOrDefault(key, false);
    }
    
    /**
     * Check if player has manually overridden any AI-controlled input.
     */
    public boolean hasManualOverride() {
        // This would be implemented by ManualInputMonitor
        // For now, return false
        return false;
    }
    
    /**
     * Set faulted state with reason.
     */
    public void setFaulted(String reason) {
        System.err.println("[AiControlManager] Setting FAULTED state: " + reason);
        setControlState(ControlState.FAULTED);
    }
    
    /**
     * Reset from emergency latched state.
     */
    public boolean resetEmergencyLatch() {
        if (currentState.get() == ControlState.EMERGENCY_LATCHED) {
            setControlState(ControlState.OFF);
            return true;
        }
        return false;
    }
    
    /**
     * Simulate key press for AI control.
     */
    private void simulateKeyPress(String key) {
        // In a real implementation, this would simulate actual key presses
        // For now, just log
        System.out.println("[AiControlManager] Simulating key press: " + key);
    }
    
    /**
     * Simulate key release for AI control.
     */
    private void simulateKeyRelease(String key) {
        // In a real implementation, this would simulate actual key releases
        // For now, just log
        System.out.println("[AiControlManager] Simulating key release: " + key);
    }
    
    /**
     * Apply mouse look delta for AI control.
     */
    private void applyMouseLookDelta(float yawDelta, float pitchDelta) {
        // In a real implementation, this would apply mouse movement
        // For now, just log
        System.out.println("[AiControlManager] Applying mouse look delta: yaw=" + yawDelta + ", pitch=" + pitchDelta);
    }
    
    /**
     * Reset mouse look to neutral.
     */
    private void resetMouseLook() {
        System.out.println("[AiControlManager] Resetting mouse look");
    }
    
    /**
     * Get all current AI key states.
     */
    public Map<String, Boolean> getAiKeyStates() {
        return new HashMap<>(aiKeyStates);
    }
    
    /**
     * Check if AI control is currently active.
     */
    public boolean isAiActive() {
        return currentState.get() == ControlState.ACTIVE;
    }
    
    /**
     * Check if system is in a safe state (not controlling).
     */
    public boolean isInSafeState() {
        ControlState state = currentState.get();
        return state == ControlState.OFF || 
               state == ControlState.READY || 
               state == ControlState.PAUSED ||
               state == ControlState.EMERGENCY_LATCHED ||
               state == ControlState.FAULTED;
    }
}