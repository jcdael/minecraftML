package com.jcdael.minecraftml;

import com.jcdael.minecraftml.observation.ObservationCollector;
import com.jcdael.minecraftml.control.AiControlManager;
import com.jcdael.minecraftml.control.ManualInputMonitor;
import com.jcdael.minecraftml.control.ActionExecutor;
import com.jcdael.minecraftml.network.BrainWebSocketClient;
import com.jcdael.minecraftml.protocol.ProtocolV2;
import com.jcdael.minecraftml.protocol.ProtocolV2.Message;
import com.jcdael.minecraftml.protocol.ProtocolV2.Action;
import com.jcdael.minecraftml.protocol.ProtocolV2.Observation;

import net.fabricmc.api.ClientModInitializer;
import net.fabricmc.fabric.api.client.event.lifecycle.v1.ClientTickEvents;
import net.fabricmc.fabric.api.client.keybinding.v1.KeyBindingHelper;
import net.minecraft.client.MinecraftClient;
import net.minecraft.client.option.KeyBinding;
import net.minecraft.client.util.InputUtil;

import org.lwjgl.glfw.GLFW;

import java.net.URI;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/**
 * Main Fabric mod for MinecraftML local-player training.
 */
public class MinecraftMLMod implements ClientModInitializer {
    private static final String MOD_ID = "minecraftml";
    
    // Configuration
    private static final String WEBSOCKET_URL = "ws://localhost:8765";
    private static final int OBSERVATION_INTERVAL_TICKS = 5; // Every 5 ticks (~4 times per second)
    
    // Components
    private ObservationCollector observationCollector;
    private AiControlManager controlManager;
    private ManualInputMonitor manualInputMonitor;
    private ActionExecutor actionExecutor;
    private BrainWebSocketClient webSocketClient;
    
    // State
    private final AtomicBoolean isActive = new AtomicBoolean(false);
    private int tickCounter = 0;
    
    // Key bindings as specified in section 9
    private KeyBinding toggleAiKey;      // F8: toggle AI control
    private KeyBinding emergencyStopKey; // F9: emergency stop
    private KeyBinding goalScreenKey;    // G: goal screen
    
    // Thread management
    private ScheduledExecutorService executorService;
    
    // Singleton instance
    private static MinecraftMLMod instance;
    
    @Override
    public void onInitializeClient() {
        System.out.println("[MinecraftML] Initializing Fabric local-player training mod");
        
        // Set singleton instance
        instance = this;
        
        // Initialize components
        MinecraftClient client = MinecraftClient.getInstance();
        observationCollector = new ObservationCollector(client);
        controlManager = new AiControlManager(client);
        manualInputMonitor = new ManualInputMonitor(client, controlManager);
        actionExecutor = new ActionExecutor(controlManager);
        
        // Register key bindings
        registerKeyBindings();
        
        // Register tick handler
        ClientTickEvents.END_CLIENT_TICK.register(this::onClientTick);
        
        System.out.println("[MinecraftML] Mod initialization complete");
    }
    
    /**
     * Register key bindings for mod controls as specified in section 9.
     */
    private void registerKeyBindings() {
        // F8: toggle AI control
        toggleAiKey = new KeyBinding(
            "key.minecraftml.toggle_ai",
            InputUtil.Type.KEYSYM,
            GLFW.GLFW_KEY_F8,
            "category.minecraftml.control"
        );
        
        // F9: emergency stop
        emergencyStopKey = new KeyBinding(
            "key.minecraftml.emergency_stop",
            InputUtil.Type.KEYSYM,
            GLFW.GLFW_KEY_F9,
            "category.minecraftml.safety"
        );
        
        // G: goal screen
        goalScreenKey = new KeyBinding(
            "key.minecraftml.goal_screen",
            InputUtil.Type.KEYSYM,
            GLFW.GLFW_KEY_G,
            "category.minecraftml.ui"
        );
        
        KeyBindingHelper.registerKeyBinding(toggleAiKey);
        KeyBindingHelper.registerKeyBinding(emergencyStopKey);
        KeyBindingHelper.registerKeyBinding(goalScreenKey);
    }
    
    /**
     * Handle client tick events.
     */
    private void onClientTick(MinecraftClient client) {
        // Handle key presses
        handleKeyInputs(client);
        
        // Update action executor
        actionExecutor.tick();
        
        // Update manual input monitor
        manualInputMonitor.tick();
        
        // Send observations periodically if active
        if (isActive.get() && webSocketClient != null && webSocketClient.isHandshakeComplete()) {
            tickCounter++;
            
            if (tickCounter >= OBSERVATION_INTERVAL_TICKS) {
                tickCounter = 0;
                sendObservation();
            }
        }
    }
    
    /**
     * Handle key input for mod controls.
     */
    private void handleKeyInputs(MinecraftClient client) {
        // F8: toggle AI control
        if (toggleAiKey.wasPressed()) {
            toggleAiActive(client);
        }
        
        // F9: emergency stop
        if (emergencyStopKey.wasPressed()) {
            emergencyStop(client);
        }
        
        // G: goal screen
        if (goalScreenKey.wasPressed()) {
            showGoalScreen(client);
        }
    }
    
    /**
     * Toggle AI active state (F8).
     */
    private void toggleAiActive(MinecraftClient client) {
        boolean newState = !isActive.get();
        isActive.set(newState);
        
        String message = newState ? "AI control activated" : "AI control deactivated";
        System.out.println("[MinecraftML] " + message);
        
        if (newState) {
            // When activating AI, ensure we're connected
            if (webSocketClient == null || !webSocketClient.isConnected()) {
                System.out.println("[MinecraftML] Not connected to brain, attempting to connect...");
                connectToBrain();
            }
            
            // Set control state to ACTIVE if connected and ready
            if (webSocketClient != null && webSocketClient.isReady()) {
                controlManager.setControlState(AiControlManager.ControlState.ACTIVE);
            }
        } else {
            // When deactivating, release all controls
            controlManager.releaseAllAiControls();
            controlManager.setControlState(AiControlManager.ControlState.OFF);
        }
        
        // Show status message to player
        if (client.player != null) {
            String statusText = newState ? "§aAI control activated" : "§cAI control deactivated";
            client.player.sendMessage(net.minecraft.text.Text.literal(statusText), false);
        }
    }
    
    /**
     * Emergency stop (F9).
     */
    private void emergencyStop(MinecraftClient client) {
        System.out.println("[MinecraftML] EMERGENCY STOP triggered");
        
        // Release all AI controls immediately
        controlManager.releaseAllAiControls();
        
        // Set emergency latched state
        controlManager.setControlState(AiControlManager.ControlState.EMERGENCY_LATCHED);
        
        // Disconnect from brain if connected
        if (webSocketClient != null) {
            webSocketClient.closeConnection(1000, "Emergency stop triggered");
            webSocketClient = null;
        }
        
        // Deactivate AI
        isActive.set(false);
        
        // Show emergency stop message
        if (client.player != null) {
            client.player.sendMessage(net.minecraft.text.Text.literal("§c§lEMERGENCY STOP: AI control disabled"), false);
        }
    }
    
    /**
     * Show goal screen (G).
     */
    private void showGoalScreen(MinecraftClient client) {
        System.out.println("[MinecraftML] Goal screen requested");
        
        // In a real implementation, this would open a GUI screen
        // For now, just log and show a status message
        
        if (client.player != null) {
            String status = isActive.get() ? "§aACTIVE" : "§cINACTIVE";
            String connection = (webSocketClient != null && webSocketClient.isConnected()) ? "§aCONNECTED" : "§cDISCONNECTED";
            String controlState = controlManager.getControlState().toString();
            
            client.player.sendMessage(net.minecraft.text.Text.literal("§6§lMinecraftML Status"), false);
            client.player.sendMessage(net.minecraft.text.Text.literal("§7AI Control: " + status), false);
            client.player.sendMessage(net.minecraft.text.Text.literal("§7Brain Connection: " + connection), false);
            client.player.sendMessage(net.minecraft.text.Text.literal("§7Control State: " + controlState), false);
            client.player.sendMessage(net.minecraft.text.Text.literal("§7Use F8 to toggle AI, F9 for emergency stop"), false);
        }
    }
    
    /**
     * Connect to the brain server.
     */
    private void connectToBrain() {
        if (webSocketClient != null && webSocketClient.isConnected()) {
            System.out.println("[MinecraftML] Already connected to brain server");
            return;
        }
        
        try {
            System.out.println("[MinecraftML] Connecting to brain server at " + WEBSOCKET_URL);
            
            webSocketClient = new BrainWebSocketClient(
                WEBSOCKET_URL,
                MinecraftClient.getInstance(),
                controlManager,
                actionExecutor,
                observationCollector
            );
            
            System.out.println("[MinecraftML] Brain connection initiated");
            
        } catch (Exception e) {
            System.err.println("[MinecraftML] Failed to connect to brain server: " + e.getMessage());
            controlManager.setControlState(AiControlManager.ControlState.FAULTED);
        }
    }
    
    /**
     * Send observation to the brain.
     */
    private void sendObservation() {
        if (webSocketClient == null || !webSocketClient.isConnected()) {
            return;
        }
        
        try {
            webSocketClient.sendObservation(tickCounter);
        } catch (Exception e) {
            System.err.println("[MinecraftML] Failed to send observation: " + e.getMessage());
        }
    }
    
    /**
     * Get the current AI active state.
     */
    public boolean isAiActive() {
        return isActive.get();
    }
    
    /**
     * Get the WebSocket client (for testing).
     */
    public BrainWebSocketClient getWebSocketClient() {
        return webSocketClient;
    }
    
    /**
     * Get the manual input monitor.
     */
    public ManualInputMonitor getManualInputMonitor() {
        return manualInputMonitor;
    }
    
    /**
     * Get the singleton instance of the mod.
     */
    public static MinecraftMLMod getInstance() {
        return instance;
    }
    
    /**
     * Get the Minecraft client instance.
     */
    public MinecraftClient getClient() {
        return MinecraftClient.getInstance();
    }
}