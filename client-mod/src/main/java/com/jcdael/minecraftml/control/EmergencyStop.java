package com.jcdael.minecraftml.control;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import org.lwjgl.glfw.GLFW;

/**
 * Emergency stop system with F9 latch functionality.
 * When latched, all AI controls are disabled until manually reset.
 * This implements fail-closed safety: latched state persists until explicit reset.
 */
public class EmergencyStop {
    private static final int EMERGENCY_KEY = GLFW.GLFW_KEY_F9;
    private boolean latched = false;
    private boolean keyWasPressed = false;
    private final MinecraftClient client;
    
    public EmergencyStop(MinecraftClient client) {
        this.client = client;
    }
    
    /**
     * Update the emergency stop state based on F9 key input.
     * Should be called every tick.
     */
    public void update() {
        boolean keyIsPressed = InputUtil.isKeyPressed(client.getWindow().getHandle(), EMERGENCY_KEY);
        
        // Detect rising edge (key pressed when it wasn't before)
        if (keyIsPressed && !keyWasPressed) {
            // Toggle latch state on F9 press
            latched = !latched;
            
            // Log state change
            if (latched) {
                System.out.println("[MinecraftML] EMERGENCY STOP LATCHED - AI controls disabled");
            } else {
                System.out.println("[MinecraftML] Emergency stop reset - AI controls enabled");
            }
        }
        
        keyWasPressed = keyIsPressed;
    }
    
    /**
     * Check if emergency stop is currently latched.
     * @return true if AI controls should be disabled
     */
    public boolean isLatched() {
        return latched;
    }
    
    /**
     * Force latch the emergency stop (e.g., from fault detection).
     */
    public void latch() {
        if (!latched) {
            latched = true;
            System.out.println("[MinecraftML] Emergency stop latched by system");
        }
    }
    
    /**
     * Reset the emergency stop latch.
     * Only call this when safe to resume AI control.
     */
    public void reset() {
        if (latched) {
            latched = false;
            System.out.println("[MinecraftML] Emergency stop manually reset");
        }
    }
    
    /**
     * Get the current latch state as a string for logging/debugging.
     */
    public String getStateString() {
        return latched ? "LATCHED" : "READY";
    }
    
    /**
     * Check if emergency stop would be triggered by current input.
     * This is a safety check before applying any AI control.
     */
    public boolean wouldTrigger() {
        return InputUtil.isKeyPressed(client.getWindow().getHandle(), EMERGENCY_KEY);
    }
}