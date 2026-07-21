package com.jcdael.minecraftml.protocol;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.util.HashSet;
import java.util.Set;

/**
 * Protocol V2 for MinecraftML communication.
 * Defines message formats, validation, and capabilities for 'fabric_local_player' role.
 */
public class ProtocolV2 {
    public static final String VERSION = "2.0";
    public static final String ROLE_FABRIC_LOCAL_PLAYER = "fabric_local_player";
    
    private static final Gson GSON = new GsonBuilder()
        .setPrettyPrinting()
        .create();
    
    /**
     * Base message interface for all protocol messages.
     */
    public interface Message {
        String getType();
        String toJson();
    }
    
    /**
     * Handshake message sent by client to establish connection.
     */
    public static class Handshake implements Message {
        private final String version;
        private final String role;
        private final Set<String> capabilities;
        
        public Handshake(String role, Set<String> capabilities) {
            this.version = VERSION;
            this.role = role;
            this.capabilities = capabilities;
        }
        
        public Handshake() {
            this(ROLE_FABRIC_LOCAL_PLAYER, getDefaultCapabilities());
        }
        
        public String getVersion() { return version; }
        public String getRole() { return role; }
        public Set<String> getCapabilities() { return capabilities; }
        
        @Override
        public String getType() { return "handshake"; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
        
        private static Set<String> getDefaultCapabilities() {
            Set<String> caps = new HashSet<>();
            caps.add("control");
            caps.add("look_delta");
            caps.add("sequence");
            caps.add("stop");
            caps.add("noop");
            caps.add("observation");
            caps.add("tick_based");
            return caps;
        }
    }
    
    /**
     * Observation message sent from client to brain.
     */
    public static class Observation implements Message {
        private final String type = "observation";
        private final long tick;
        private final JsonObject data;
        
        public Observation(long tick, JsonObject data) {
            this.tick = tick;
            this.data = data;
        }
        
        public long getTick() { return tick; }
        public JsonObject getData() { return data; }
        
        @Override
        public String getType() { return type; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Action message sent from brain to client.
     */
    public static class Action implements Message {
        private final String type;
        private final JsonObject data;
        
        public Action(String type, JsonObject data) {
            this.type = type;
            this.data = data;
        }
        
        public String getActionType() { return type; }
        public JsonObject getData() { return data; }
        
        @Override
        public String getType() { return type; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Control action for direct key control.
     */
    public static class ControlAction {
        private final String key;
        private final boolean pressed;
        private final int duration; // in ticks
        
        public ControlAction(String key, boolean pressed, int duration) {
            this.key = key;
            this.pressed = pressed;
            this.duration = duration;
        }
        
        public String getKey() { return key; }
        public boolean isPressed() { return pressed; }
        public int getDuration() { return duration; }
    }
    
    /**
     * Look delta action for mouse movement.
     */
    public static class LookDeltaAction {
        private final float yawDelta;
        private final float pitchDelta;
        
        public LookDeltaAction(float yawDelta, float pitchDelta) {
            this.yawDelta = yawDelta;
            this.pitchDelta = pitchDelta;
        }
        
        public float getYawDelta() { return yawDelta; }
        public float getPitchDelta() { return pitchDelta; }
    }
    
    /**
     * Sequence action for multiple actions in sequence.
     */
    public static class SequenceAction {
        private final Action[] actions;
        private final int[] delays; // delays between actions in ticks
        
        public SequenceAction(Action[] actions, int[] delays) {
            this.actions = actions;
            this.delays = delays;
        }
        
        public Action[] getActions() { return actions; }
        public int[] getDelays() { return delays; }
    }
    
    /**
     * Stop action to stop all current actions.
     */
    public static class StopAction {
        private final boolean immediate;
        
        public StopAction(boolean immediate) {
            this.immediate = immediate;
        }
        
        public boolean isImmediate() { return immediate; }
    }
    
    /**
     * No-op action (do nothing).
     */
    public static class NoopAction {
        // Empty action
    }
    
    /**
     * Parse a JSON string into a Message object.
     */
    public static Message parseMessage(String json) {
        try {
            JsonObject obj = JsonParser.parseString(json).getAsJsonObject();
            
            if (obj.has("type")) {
                String type = obj.get("type").getAsString();
                
                switch (type) {
                    case "handshake":
                        return GSON.fromJson(obj, Handshake.class);
                    case "observation":
                        return GSON.fromJson(obj, Observation.class);
                    default:
                        // Assume it's an action
                        return GSON.fromJson(obj, Action.class);
                }
            }
            
            throw new ProtocolException("Message missing 'type' field");
        } catch (Exception e) {
            throw new ProtocolException("Failed to parse message: " + e.getMessage(), e);
        }
    }
    
    /**
     * Validate a handshake message.
     */
    public static void validateHandshake(Handshake handshake) {
        if (!VERSION.equals(handshake.getVersion())) {
            throw new ProtocolException("Unsupported protocol version: " + handshake.getVersion());
        }
        
        if (!ROLE_FABRIC_LOCAL_PLAYER.equals(handshake.getRole())) {
            throw new ProtocolException("Unsupported role: " + handshake.getRole() + 
                ". Expected: " + ROLE_FABRIC_LOCAL_PLAYER);
        }
        
        if (handshake.getCapabilities() == null || handshake.getCapabilities().isEmpty()) {
            throw new ProtocolException("No capabilities specified");
        }
        
        // Check for required capabilities
        Set<String> required = new HashSet<>();
        required.add("observation");
        required.add("tick_based");
        
        for (String req : required) {
            if (!handshake.getCapabilities().contains(req)) {
                throw new ProtocolException("Missing required capability: " + req);
            }
        }
    }
    
    /**
     * Validate an action message.
     */
    public static void validateAction(Action action) {
        String actionType = action.getActionType();
        
        switch (actionType) {
            case "control":
                validateControlAction(action.getData());
                break;
            case "look_delta":
                validateLookDeltaAction(action.getData());
                break;
            case "sequence":
                validateSequenceAction(action.getData());
                break;
            case "stop":
                validateStopAction(action.getData());
                break;
            case "noop":
                // No validation needed for noop
                break;
            default:
                throw new ProtocolException("Unknown action type: " + actionType);
        }
    }
    
    private static void validateControlAction(JsonObject data) {
        if (!data.has("key")) {
            throw new ProtocolException("Control action missing 'key' field");
        }
        if (!data.has("pressed")) {
            throw new ProtocolException("Control action missing 'pressed' field");
        }
        
        String key = data.get("key").getAsString();
        Set<String> validKeys = new HashSet<>();
        validKeys.add("forward");
        validKeys.add("back");
        validKeys.add("left");
        validKeys.add("right");
        validKeys.add("jump");
        validKeys.add("sneak");
        validKeys.add("sprint");
        validKeys.add("attack");
        validKeys.add("use");
        
        if (!validKeys.contains(key)) {
            throw new ProtocolException("Invalid key for control action: " + key);
        }
    }
    
    private static void validateLookDeltaAction(JsonObject data) {
        if (!data.has("yaw_delta")) {
            throw new ProtocolException("Look delta action missing 'yaw_delta' field");
        }
        if (!data.has("pitch_delta")) {
            throw new ProtocolException("Look delta action missing 'pitch_delta' field");
        }
        
        float yawDelta = data.get("yaw_delta").getAsFloat();
        float pitchDelta = data.get("pitch_delta").getAsFloat();
        
        // Validate reasonable ranges
        if (Math.abs(yawDelta) > 180.0f) {
            throw new ProtocolException("Yaw delta too large: " + yawDelta);
        }
        if (Math.abs(pitchDelta) > 90.0f) {
            throw new ProtocolException("Pitch delta too large: " + pitchDelta);
        }
    }
    
    private static void validateSequenceAction(JsonObject data) {
        if (!data.has("actions")) {
            throw new ProtocolException("Sequence action missing 'actions' field");
        }
        if (!data.has("delays")) {
            throw new ProtocolException("Sequence action missing 'delays' field");
        }
        
        // Additional validation would parse and validate each action in the sequence
    }
    
    private static void validateStopAction(JsonObject data) {
        if (!data.has("immediate")) {
            throw new ProtocolException("Stop action missing 'immediate' field");
        }
    }
    
    /**
     * Protocol exception for validation errors.
     */
    public static class ProtocolException extends RuntimeException {
        public ProtocolException(String message) {
            super(message);
        }
        
        public ProtocolException(String message, Throwable cause) {
            super(message, cause);
        }
    }
}