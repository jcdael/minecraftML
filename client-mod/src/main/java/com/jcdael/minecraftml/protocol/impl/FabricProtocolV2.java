package com.jcdael.minecraftml.protocol.impl;

import com.jcdael.minecraftml.protocol.ProtocolV2;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.HashSet;
import java.util.Set;

/**
 * Fabric-specific implementation of Protocol V2 for local-player training.
 * Provides Fabric-specific message handling and serialization.
 */
public class FabricProtocolV2 {
    private static final Logger LOGGER = LoggerFactory.getLogger(FabricProtocolV2.class);
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    
    /**
     * Create a hello message with Fabric-specific capabilities.
     * This is the initial handshake message sent to the brain server.
     */
    public static String createHelloMessage() {
        JsonObject hello = new JsonObject();
        hello.addProperty("type", "hello");
        hello.addProperty("protocol_version", "2.0");
        
        // Add capabilities
        JsonObject capabilities = new JsonObject();
        
        // Observation fields we support
        JsonObject observationFields = new JsonObject();
        observationFields.addProperty("position", true);
        observationFields.addProperty("velocity", true);
        observationFields.addProperty("health", true);
        observationFields.addProperty("food_level", true);
        observationFields.addProperty("inventory", true);
        observationFields.addProperty("nearby_blocks", true);
        observationFields.addProperty("nearby_entities", true);
        observationFields.addProperty("yaw_pitch", true);
        observationFields.addProperty("on_ground", true);
        observationFields.addProperty("sprinting", true);
        observationFields.addProperty("sneaking", true);
        observationFields.addProperty("swimming", true);
        observationFields.addProperty("experience", true);
        observationFields.addProperty("light_level", true);
        observationFields.addProperty("dimension", true);
        observationFields.addProperty("time_of_day", true);
        observationFields.addProperty("weather", true);
        capabilities.add("observation_fields", observationFields);
        
        // Action types we support
        JsonObject actionTypes = new JsonObject();
        actionTypes.addProperty("control", true);
        actionTypes.addProperty("look_delta", true);
        actionTypes.addProperty("sequence", true);
        actionTypes.addProperty("noop", true);
        actionTypes.addProperty("stop", true);
        capabilities.add("action_types", actionTypes);
        
        // Control states we support
        JsonObject controlStates = new JsonObject();
        controlStates.addProperty("OFF", true);
        controlStates.addProperty("READY", true);
        controlStates.addProperty("ACTIVE", true);
        controlStates.addProperty("PAUSED", true);
        controlStates.addProperty("MANUAL_OVERRIDE", true);
        controlStates.addProperty("EMERGENCY_LATCHED", true);
        controlStates.addProperty("FAULTED", true);
        capabilities.add("control_states", controlStates);
        
        hello.add("capabilities", capabilities);
        
        return GSON.toJson(hello);
    }
    
    /**
     * Parse and validate a hello response from the brain server.
     */
    public static boolean validateHelloResponse(String jsonResponse) {
        try {
            JsonObject response = JsonParser.parseString(jsonResponse).getAsJsonObject();
            
            if (!response.has("type") || !"hello".equals(response.get("type").getAsString())) {
                LOGGER.error("Invalid response type for hello validation");
                return false;
            }
            
            if (!response.has("protocol_version")) {
                LOGGER.error("Missing protocol version in hello response");
                return false;
            }
            
            String version = response.get("protocol_version").getAsString();
            if (!"2.0".equals(version)) {
                LOGGER.error("Unsupported protocol version: {}", version);
                return false;
            }
            
            LOGGER.info("Hello response validated successfully");
            return true;
            
        } catch (Exception e) {
            LOGGER.error("Failed to parse hello response: {}", e.getMessage());
            return false;
        }
    }
    
    /**
     * Create an observation message from collected data.
     */
    public static String createObservationMessage(long timestamp, JsonObject observationData) {
        JsonObject observation = new JsonObject();
        observation.addProperty("type", "observation");
        observation.addProperty("timestamp", timestamp);
        observation.add("data", observationData);
        
        return GSON.toJson(observation);
    }
    
    /**
     * Parse an action message from the brain server.
     */
    public static ProtocolV2.Message parseActionMessage(String jsonMessage) {
        try {
            return ProtocolV2.parseMessage(jsonMessage);
        } catch (ProtocolV2.ProtocolException e) {
            LOGGER.error("Failed to parse action message: {}", e.getMessage());
            throw e;
        }
    }
    
    /**
     * Create an error message to send to the brain server.
     */
    public static String createErrorMessage(String code, String message, JsonObject details) {
        JsonObject error = new JsonObject();
        error.addProperty("type", "error");
        error.addProperty("code", code);
        error.addProperty("message", message);
        
        if (details != null) {
            error.add("details", details);
        }
        
        error.addProperty("timestamp", System.currentTimeMillis());
        
        return GSON.toJson(error);
    }
    
    /**
     * Create a control state update message.
     */
    public static String createControlStateMessage(String state, String reason) {
        JsonObject stateUpdate = new JsonObject();
        stateUpdate.addProperty("type", "control_state");
        stateUpdate.addProperty("state", state);
        
        if (reason != null && !reason.isEmpty()) {
            stateUpdate.addProperty("reason", reason);
        }
        
        stateUpdate.addProperty("timestamp", System.currentTimeMillis());
        
        return GSON.toJson(stateUpdate);
    }
    
    /**
     * Validate that a message is properly formatted JSON.
     */
    public static boolean validateMessageFormat(String jsonMessage) {
        try {
            JsonParser.parseString(jsonMessage);
            return true;
        } catch (Exception e) {
            LOGGER.error("Invalid JSON message: {}", e.getMessage());
            return false;
        }
    }
    
    /**
     * Extract message type from JSON without full parsing.
     */
    public static String extractMessageType(String jsonMessage) {
        try {
            JsonObject message = JsonParser.parseString(jsonMessage).getAsJsonObject();
            if (message.has("type")) {
                return message.get("type").getAsString();
            }
            return null;
        } catch (Exception e) {
            LOGGER.error("Failed to extract message type: {}", e.getMessage());
            return null;
        }
    }
    
    /**
     * Get the default capabilities set for Fabric local player.
     */
    public static Set<String> getDefaultCapabilities() {
        Set<String> capabilities = new HashSet<>();
        capabilities.add("control");
        capabilities.add("look_delta");
        capabilities.add("sequence");
        capabilities.add("stop");
        capabilities.add("noop");
        capabilities.add("observation");
        capabilities.add("tick_based");
        capabilities.add("fabric_local_player");
        capabilities.add("same_player_control");
        capabilities.add("client_only");
        capabilities.add("localhost_only");
        capabilities.add("fail_closed_safety");
        return capabilities;
    }
}