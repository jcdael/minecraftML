package com.jcdael.minecraftml.input;

import com.jcdael.minecraftml.control.AIControlManager;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;
import net.minecraft.text.Text;
import org.lwjgl.glfw.GLFW;

/**
 * Handles key mappings for the MinecraftML mod.
 * Provides F8, F9, and G key bindings with proper translation support.
 */
public class KeyInputHandler {
    private final MinecraftClient client;
    private final AIControlManager controlManager;
    
    // Key bindings
    private KeyBinding toggleAiControlKey;
    private KeyBinding activateAiControlKey;
    private KeyBinding toggleDebugKey;
    
    // State tracking
    private boolean debugMode = false;
    
    public KeyInputHandler(MinecraftClient client, AIControlManager controlManager) {
        this.client = client;
        this.controlManager = controlManager;
        initializeKeyBindings();
        registerCallbacks();
    }
    
    /**
     * Initialize and register all key bindings.
     */
    private void initializeKeyBindings() {
        // F8: Toggle AI control system on/off
        toggleAiControlKey = KeyBindingHelper.registerKeyBinding(new KeyBinding(
            "key.minecraftml.toggle_ai_control",
            InputUtil.Type.KEYSYM,
            GLFW.GLFW_KEY_F8,
            "category.minecraftml.control"
        ));
        
        // F9: Activate/deactivate AI control
        activateAiControlKey = KeyBindingHelper.registerKeyBinding(new KeyBinding(
            "key.minecraftml.activate_ai_control",
            InputUtil.Type.KEYSYM,
            GLFW.GLFW_KEY_F9,
            "category.minecraftml.control"
        ));
        
        // G: Toggle debug mode
        toggleDebugKey = KeyBindingHelper.registerKeyBinding(new KeyBinding(
            "key.minecraftml.toggle_debug",
            InputUtil.Type.KEYSYM,
            GLFW.GLFW_KEY_G,
            "category.minecraftml.debug"
        ));
    }
    
    /**
     * Register tick event callbacks.
     */
    private void registerCallbacks() {
        ClientTickEvents.END_CLIENT_TICK.register(client -> {
            handleKeyInputs();
        });
    }
    
    /**
     * Handle key input checks each tick.
     */
    private void handleKeyInputs() {
        // Handle F8: Toggle AI control system
        while (toggleAiControlKey.wasPressed()) {
            handleToggleAiControl();
        }
        
        // Handle F9: Activate/deactivate AI control
        while (activateAiControlKey.wasPressed()) {
            handleActivateAiControl();
        }
        
        // Handle G: Toggle debug mode
        while (toggleDebugKey.wasPressed()) {
            handleToggleDebug();
        }
    }
    
    /**
     * Handle F8 key press: toggle AI control system.
     */
    private void handleToggleAiControl() {
        AIControlManager.ControlState currentState = controlManager.getCurrentState();
        
        if (currentState == AIControlManager.ControlState.OFF) {
            // Turn on AI control system
            controlManager.prepareControl();
            sendMessageToChat("AI control system enabled. Press F9 to activate control.");
        } else {
            // Turn off AI control system
            controlManager.disableControl();
            sendMessageToChat("AI control system disabled.");
        }
    }
    
    /**
     * Handle F9 key press: activate/deactivate AI control.
     */
    private void handleActivateAiControl() {
        AIControlManager.ControlState currentState = controlManager.getCurrentState();
        
        if (currentState == AIControlManager.ControlState.READY) {
            // Activate AI control
            if (controlManager.requestControl()) {
                sendMessageToChat("AI control activated. AI now has control.");
            }
        } else if (currentState == AIControlManager.ControlState.ACTIVE) {
            // Deactivate AI control
            controlManager.releaseAllAiControls();
            sendMessageToChat("AI control deactivated. Player has control.");
        } else if (currentState == AIControlManager.ControlState.OFF) {
            // System is off, need to enable first
            sendMessageToChat("AI control system is off. Press F8 to enable it first.");
        }
    }
    
    /**
     * Handle G key press: toggle debug mode.
     */
    private void handleToggleDebug() {
        debugMode = !debugMode;
        
        if (debugMode) {
            sendMessageToChat("Debug mode enabled.");
            // Here you would enable debug logging, visualizations, etc.
        } else {
            sendMessageToChat("Debug mode disabled.");
            // Here you would disable debug logging, visualizations, etc.
        }
    }
    
    /**
     * Check if debug mode is enabled.
     */
    public boolean isDebugModeEnabled() {
        return debugMode;
    }
    
    /**
     * Send a message to the player's chat.
     */
    private void sendMessageToChat(String message) {
        if (client.player != null) {
            client.player.sendMessage(Text.literal("[MinecraftML] " + message), false);
        }
    }
    
    /**
     * Get the toggle AI control key binding.
     */
    public KeyBinding getToggleAiControlKey() {
        return toggleAiControlKey;
    }
    
    /**
     * Get the activate AI control key binding.
     */
    public KeyBinding getActivateAiControlKey() {
        return activateAiControlKey;
    }
    
    /**
     * Get the toggle debug key binding.
     */
    public KeyBinding getToggleDebugKey() {
        return toggleDebugKey;
    }
}