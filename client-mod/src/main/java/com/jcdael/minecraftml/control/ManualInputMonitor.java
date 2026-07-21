package com.jcdael.minecraftml.control;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import org.lwjgl.glfw.GLFW;

import java.util.HashSet;
import java.util.Set;

/**
 * Monitors manual input from player to detect manual override conditions.
 * Uses Fabric mixins to intercept input events.
 */
public class ManualInputMonitor {
    private final MinecraftClient client;
    private final AiControlManager controlManager;
    private final Set<KeyBinding> monitoredKeys;
    private boolean manualInputDetected = false;
    private long lastManualInputTime = 0;
    private static final long MANUAL_OVERRIDE_THRESHOLD_MS = 100; // 100ms threshold
    
    public ManualInputMonitor(MinecraftClient client, AiControlManager controlManager) {
        this.client = client;
        this.controlManager = controlManager;
        this.monitoredKeys = new HashSet<>();
        initializeMonitoredKeys();
    }
    
    /**
     * Initialize the set of keys to monitor for manual override.
     */
    private void initializeMonitoredKeys() {
        // Monitor all movement and action keys
        if (client.options != null) {
            monitoredKeys.add(client.options.forwardKey);
            monitoredKeys.add(client.options.backKey);
            monitoredKeys.add(client.options.leftKey);
            monitoredKeys.add(client.options.rightKey);
            monitoredKeys.add(client.options.jumpKey);
            monitoredKeys.add(client.options.sneakKey);
            monitoredKeys.add(client.options.sprintKey);
            monitoredKeys.add(client.options.attackKey);
            monitoredKeys.add(client.options.useKey);
        }
    }
    
    /**
     * Called when a key is pressed (via mixin).
     * @param keyCode The GLFW key code
     * @param scanCode The platform-specific scan code
     * @param action The action (PRESS, REPEAT, RELEASE)
     * @param modifiers Key modifiers
     */
    public void onKeyInput(int keyCode, int scanCode, int action, int modifiers) {
        // Only check for manual override if AI is active
        if (controlManager.getControlState() != AiControlManager.ControlState.ACTIVE) {
            return;
        }
        
        // Check if this is a monitored key
        InputUtil.Key key = InputUtil.fromKeyCode(keyCode, scanCode);
        if (isMonitoredKey(key)) {
            handleManualInput();
        }
    }
    
    /**
     * Called when mouse button is pressed (via mixin).
     * @param button The mouse button
     * @param action The action (PRESS, RELEASE)
     * @param modifiers Key modifiers
     */
    public void onMouseButton(int button, int action, int modifiers) {
        // Only check for manual override if AI is active
        if (controlManager.getControlState() != AiControlManager.ControlState.ACTIVE) {
            return;
        }
        
        // Check if this is a monitored mouse button (attack or use)
        if (button == GLFW.GLFW_MOUSE_BUTTON_LEFT || button == GLFW.GLFW_MOUSE_BUTTON_RIGHT) {
            handleManualInput();
        }
    }
    
    /**
     * Called when mouse is moved (via mixin).
     * @param deltaX Mouse movement in X direction
     * @param deltaY Mouse movement in Y direction
     */
    public void onMouseMove(double deltaX, double deltaY) {
        // Only check for manual override if AI is active
        if (controlManager.getControlState() != AiControlManager.ControlState.ACTIVE) {
            return;
        }
        
        // Check if mouse movement exceeds threshold
        double movementMagnitude = Math.sqrt(deltaX * deltaX + deltaY * deltaY);
        if (movementMagnitude > 0.1) { // Small threshold to ignore tiny movements
            handleManualInput();
        }
    }
    
    /**
     * Check if a key is in the monitored set.
     */
    private boolean isMonitoredKey(InputUtil.Key key) {
        if (client.options == null) {
            return false;
        }
        
        for (KeyBinding monitoredKey : monitoredKeys) {
            if (monitoredKey.isUnbound()) {
                continue;
            }
            
            InputUtil.Key monitoredKeyCode = monitoredKey.getDefaultKey();
            if (monitoredKeyCode != null && monitoredKeyCode.equals(key)) {
                return true;
            }
        }
        
        return false;
    }
    
    /**
     * Handle detection of manual input.
     */
    private void handleManualInput() {
        long currentTime = System.currentTimeMillis();
        
        // Check if this is rapid successive input
        if (currentTime - lastManualInputTime < MANUAL_OVERRIDE_THRESHOLD_MS) {
            manualInputDetected = true;
            
            // Trigger manual override if we have consistent manual input
            if (manualInputDetected) {
                // Set control state to manual override
                controlManager.setControlState(AiControlManager.ControlState.MANUAL_OVERRIDE);
                manualInputDetected = false; // Reset after triggering
            }
        }
        
        lastManualInputTime = currentTime;
    }
    
    /**
     * Reset manual input detection.
     */
    public void reset() {
        manualInputDetected = false;
        lastManualInputTime = 0;
    }
    
    /**
     * Check if manual input was recently detected.
     */
    public boolean wasManualInputDetected() {
        long currentTime = System.currentTimeMillis();
        return manualInputDetected || (currentTime - lastManualInputTime < 1000); // 1 second memory
    }
    
    /**
     * Update method called each tick.
     */
    public void tick() {
        // Reset manual input detection if enough time has passed
        long currentTime = System.currentTimeMillis();
        if (currentTime - lastManualInputTime > 5000) { // 5 second timeout
            manualInputDetected = false;
        }
    }
    
    /**
     * Get the set of monitored keys (for testing/debugging).
     */
    public Set<KeyBinding> getMonitoredKeys() {
        return new HashSet<>(monitoredKeys);
    }
}