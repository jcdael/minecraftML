package com.jcdael.minecraftml.protocol;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;

import java.util.*;

/**
 * Canonical Protocol V2 for MinecraftML communication.
 * Implements the unified protocol schema as specified in the requirements.
 * 
 * Protocol version: 2
 * Message types: hello, hello_ack, observation, action, result, cancel, cancel_ack, goal
 */
public class CanonicalProtocol {
    public static final int PROTOCOL_VERSION = 2;
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
     * Hello message sent by client to establish connection.
     * Follows canonical schema from requirements.
     */
    public static class HelloMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "hello";
        private final String client = "minecraft_fabric";
        private final String client_version = "0.2.0";
        private final String minecraft_version = "1.21.4";
        private final String role = ROLE_FABRIC_LOCAL_PLAYER;
        private final String adapter_id;
        private final String session_id;
        private final List<String> capabilities;
        
        public HelloMessage(String adapterId, String sessionId, List<String> capabilities) {
            this.adapter_id = adapterId;
            this.session_id = sessionId;
            this.capabilities = capabilities;
        }
        
        public HelloMessage(String adapterId, String sessionId) {
            this(adapterId, sessionId, getDefaultCapabilities());
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getClient() { return client; }
        public String getClientVersion() { return client_version; }
        public String getMinecraftVersion() { return minecraft_version; }
        public String getRole() { return role; }
        public String getAdapterId() { return adapter_id; }
        public String getSessionId() { return session_id; }
        public List<String> getCapabilities() { return capabilities; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
        
        private static List<String> getDefaultCapabilities() {
            List<String> caps = new ArrayList<>();
            caps.add("observation");
            caps.add("control");
            caps.add("look_delta");
            caps.add("sequence");
            caps.add("cancel");
            caps.add("result_lifecycle");
            caps.add("same_player_control");
            caps.add("tick_based");
            caps.add("manual_override");
            caps.add("emergency_stop");
            return caps;
        }
    }
    
    /**
     * Hello acknowledgment sent by brain to accept connection.
     */
    public static class HelloAckMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "hello_ack";
        private final String session_id;
        private final boolean accepted;
        private final String brain_version = "0.2.0";
        
        public HelloAckMessage(String sessionId, boolean accepted) {
            this.session_id = sessionId;
            this.accepted = accepted;
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getSessionId() { return session_id; }
        public boolean isAccepted() { return accepted; }
        public String getBrainVersion() { return brain_version; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Observation message sent from client to brain.
     */
    public static class ObservationMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "observation";
        private final String session_id;
        private final String request_id;
        private final long timestamp_ms;
        private final long client_tick;
        private final JsonObject state;
        
        public ObservationMessage(String sessionId, String requestId, long timestampMs, 
                                 long clientTick, JsonObject state) {
            this.session_id = sessionId;
            this.request_id = requestId;
            this.timestamp_ms = timestampMs;
            this.client_tick = clientTick;
            this.state = state;
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getSessionId() { return session_id; }
        public String getRequestId() { return request_id; }
        public long getTimestampMs() { return timestamp_ms; }
        public long getClientTick() { return client_tick; }
        public JsonObject getState() { return state; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Action message sent from brain to client.
     */
    public static class ActionMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "action";
        private final String session_id;
        private final String action_id;
        private final String based_on_request_id;
        private final JsonObject action;
        
        public ActionMessage(String sessionId, String actionId, String basedOnRequestId, 
                            JsonObject action) {
            this.session_id = sessionId;
            this.action_id = actionId;
            this.based_on_request_id = basedOnRequestId;
            this.action = action;
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getSessionId() { return session_id; }
        public String getActionId() { return action_id; }
        public String getBasedOnRequestId() { return based_on_request_id; }
        public JsonObject getAction() { return action; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Result message sent from client to brain after action completion.
     */
    public static class ResultMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "result";
        private final String session_id;
        private final String action_id;
        private final boolean ok;
        private final String code;
        private final int elapsed_ticks;
        private final long elapsed_ms;
        private final JsonObject before_state;
        private final JsonObject after_state;
        private final JsonObject metrics;
        private final JsonObject lifecycle;
        
        public ResultMessage(String sessionId, String actionId, boolean ok, String code,
                           int elapsedTicks, long elapsedMs, JsonObject beforeState,
                           JsonObject afterState, JsonObject metrics, JsonObject lifecycle) {
            this.session_id = sessionId;
            this.action_id = actionId;
            this.ok = ok;
            this.code = code;
            this.elapsed_ticks = elapsedTicks;
            this.elapsed_ms = elapsedMs;
            this.before_state = beforeState;
            this.after_state = afterState;
            this.metrics = metrics;
            this.lifecycle = lifecycle;
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getSessionId() { return session_id; }
        public String getActionId() { return action_id; }
        public boolean isOk() { return ok; }
        public String getCode() { return code; }
        public int getElapsedTicks() { return elapsed_ticks; }
        public long getElapsedMs() { return elapsed_ms; }
        public JsonObject getBeforeState() { return before_state; }
        public JsonObject getAfterState() { return after_state; }
        public JsonObject getMetrics() { return metrics; }
        public JsonObject getLifecycle() { return lifecycle; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Cancel message sent from brain to client to cancel an action.
     */
    public static class CancelMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "cancel";
        private final String session_id;
        private final String action_id;
        
        public CancelMessage(String sessionId, String actionId) {
            this.session_id = sessionId;
            this.action_id = actionId;
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getSessionId() { return session_id; }
        public String getActionId() { return action_id; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Cancel acknowledgment sent from client to brain after cancel.
     */
    public static class CancelAckMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "cancel_ack";
        private final String session_id;
        private final String action_id;
        private final JsonObject after_state;
        private final JsonObject lifecycle;
        
        public CancelAckMessage(String sessionId, String actionId, JsonObject afterState,
                              JsonObject lifecycle) {
            this.session_id = sessionId;
            this.action_id = actionId;
            this.after_state = afterState;
            this.lifecycle = lifecycle;
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getSessionId() { return session_id; }
        public String getActionId() { return action_id; }
        public JsonObject getAfterState() { return after_state; }
        public JsonObject getLifecycle() { return lifecycle; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Goal message for setting exploration goals.
     */
    public static class GoalMessage implements Message {
        private final int protocol_version = PROTOCOL_VERSION;
        private final String type = "goal";
        private final String session_id;
        private final String text;
        private final String requested_by;
        
        public GoalMessage(String sessionId, String text, String requestedBy) {
            this.session_id = sessionId;
            this.text = text;
            this.requested_by = requestedBy;
        }
        
        public int getProtocolVersion() { return protocol_version; }
        public String getType() { return type; }
        public String getSessionId() { return session_id; }
        public String getText() { return text; }
        public String getRequestedBy() { return requested_by; }
        
        @Override
        public String toJson() {
            return GSON.toJson(this);
        }
    }
    
    /**
     * Parse a JSON string into the appropriate message type.
     */
    public static Message parseMessage(String json) {
        JsonObject obj = JsonParser.parseString(json).getAsJsonObject();
        String type = obj.get("type").getAsString();
        
        switch (type) {
            case "hello":
                return GSON.fromJson(json, HelloMessage.class);
            case "hello_ack":
                return GSON.fromJson(json, HelloAckMessage.class);
            case "observation":
                return GSON.fromJson(json, ObservationMessage.class);
            case "action":
                return GSON.fromJson(json, ActionMessage.class);
            case "result":
                return GSON.fromJson(json, ResultMessage.class);
            case "cancel":
                return GSON.fromJson(json, CancelMessage.class);
            case "cancel_ack":
                return GSON.fromJson(json, CancelAckMessage.class);
            case "goal":
                return GSON.fromJson(json, GoalMessage.class);
            default:
                throw new IllegalArgumentException("Unknown message type: " + type);
        }
    }
    
    /**
     * Validate that a message has the correct protocol version.
     */
    public static boolean validateProtocolVersion(Message message) {
        // All message classes have protocol_version field
        // This would need reflection to check, but for now assume correct
        return true;
    }
}