package com.jcdael.minecraftml.network;

import com.jcdael.minecraftml.control.AiControlManager;
import com.jcdael.minecraftml.control.ActionExecutor;
import com.jcdael.minecraftml.observation.ObservationCollector;
import com.jcdael.minecraftml.protocol.ProtocolV2;
import com.jcdael.minecraftml.protocol.ProtocolV2.Action;
import com.jcdael.minecraftml.protocol.ProtocolV2.Handshake;
import com.jcdael.minecraftml.protocol.ProtocolV2.Observation;
import com.jcdael.minecraftml.protocol.ProtocolV2.ProtocolException;
import com.google.gson.JsonObject;
import net.minecraft.client.MinecraftClient;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.WebSocket;
import java.nio.ByteBuffer;
import java.time.Duration;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

/**
 * WebSocket client for connecting to the Python brain using JDK 21's java.net.http.WebSocket.
 * Handles protocol V2 communication and message processing.
 * Localhost-only connections with bounded queues and fail-closed safety.
 */
public class BrainWebSocketClient implements WebSocket.Listener {
    private static final Logger LOGGER = LoggerFactory.getLogger(BrainWebSocketClient.class);
    
    private final MinecraftClient client;
    private final AiControlManager controlManager;
    private final ActionExecutor actionExecutor;
    private final ObservationCollector observationCollector;
    private final BlockingQueue<String> messageQueue;
    private final AtomicBoolean handshakeComplete;
    private final AtomicReference<WebSocket> webSocketRef;
    private final HttpClient httpClient;
    
    private long lastObservationTick = 0;
    private static final int OBSERVATION_INTERVAL_TICKS = 5; // Send observations every 5 ticks
    private static final int MAX_QUEUE_SIZE = 1000; // Maximum messages in queue
    private static final Duration CONNECT_TIMEOUT = Duration.ofSeconds(10);
    private static final Duration PING_INTERVAL = Duration.ofSeconds(30);
    
    // Thread pool for WebSocket operations
    private final ExecutorService executorService;
    
    public BrainWebSocketClient(
            String serverUri,
            MinecraftClient client,
            AiControlManager controlManager,
            ActionExecutor actionExecutor,
            ObservationCollector observationCollector
    ) {
        this.client = client;
        this.controlManager = controlManager;
        this.actionExecutor = actionExecutor;
        this.observationCollector = observationCollector;
        this.messageQueue = new LinkedBlockingQueue<>(MAX_QUEUE_SIZE);
        this.handshakeComplete = new AtomicBoolean(false);
        this.webSocketRef = new AtomicReference<>();
        
        // Create HTTP client with timeout
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(CONNECT_TIMEOUT)
                .executor(Executors.newVirtualThreadPerTaskExecutor())
                .build();
        
        // Create executor for background tasks
        this.executorService = Executors.newSingleThreadExecutor(r -> {
            Thread thread = new Thread(r, "BrainWebSocket-Processor");
            thread.setDaemon(true);
            return thread;
        });
        
        // Start connection
        connect(serverUri);
    }
    
    /**
     * Connect to the WebSocket server.
     */
    private void connect(String serverUri) {
        try {
            URI uri = new URI(serverUri);
            
            // Validate localhost-only constraint
            if (!"localhost".equals(uri.getHost()) && !"127.0.0.1".equals(uri.getHost())) {
                LOGGER.error("WebSocket connections are only allowed to localhost, got: {}", uri.getHost());
                controlManager.setFaulted("Non-localhost connection attempt");
                return;
            }
            
            LOGGER.info("Connecting to brain server at {}", uri);
            
            // Build WebSocket with this class as listener
            WebSocket.Builder builder = httpClient.newWebSocketBuilder();
            
            // Set ping interval
            builder.connectTimeout(CONNECT_TIMEOUT);
            
            // Connect asynchronously
            CompletableFuture<WebSocket> webSocketFuture = builder.buildAsync(uri, this);
            
            // Handle connection result
            webSocketFuture.whenComplete((webSocket, throwable) -> {
                if (throwable != null) {
                    LOGGER.error("Failed to connect to brain server: {}", throwable.getMessage());
                    controlManager.setFaulted("Connection failed: " + throwable.getMessage());
                } else {
                    LOGGER.info("WebSocket connection established");
                    webSocketRef.set(webSocket);
                    
                    // Send handshake immediately
                    sendHandshake();
                }
            });
            
        } catch (Exception e) {
            LOGGER.error("Failed to create WebSocket connection: {}", e.getMessage());
            controlManager.setFaulted("Connection setup failed: " + e.getMessage());
        }
    }
    
    @Override
    public void onOpen(WebSocket webSocket) {
        LOGGER.info("WebSocket connection opened");
        WebSocket.Listener.super.onOpen(webSocket);
        
        // Request more messages
        webSocket.request(1);
    }
    
    @Override
    public CompletionStage<?> onText(WebSocket webSocket, CharSequence data, boolean last) {
        LOGGER.debug("Received WebSocket message (last: {}): {}", last, data);
        
        // Process the message
        String message = data.toString();
        processMessage(message);
        
        // Request next message
        webSocket.request(1);
        
        return CompletableFuture.completedFuture(null);
    }
    
    @Override
    public CompletionStage<?> onClose(WebSocket webSocket, int statusCode, String reason) {
        LOGGER.info("WebSocket connection closed: {} (code: {})", reason, statusCode);
        
        // Reset control state
        controlManager.setControlState(AiControlManager.ControlState.OFF);
        handshakeComplete.set(false);
        
        // Clear any pending actions
        actionExecutor.stopAllActions(true);
        
        // Clear WebSocket reference
        webSocketRef.set(null);
        
        return CompletableFuture.completedFuture(null);
    }
    
    @Override
    public void onError(WebSocket webSocket, Throwable error) {
        LOGGER.error("WebSocket error: {}", error.getMessage(), error);
        
        // Set faulted state on serious errors
        if (error instanceof java.net.ConnectException) {
            controlManager.setFaulted("Connection error: " + error.getMessage());
        }
    }
    
    @Override
    public CompletionStage<?> onPing(WebSocket webSocket, ByteBuffer message) {
        LOGGER.debug("Received ping");
        // Echo back the ping as pong
        return webSocket.sendPong(message);
    }
    
    @Override
    public CompletionStage<?> onPong(WebSocket webSocket, ByteBuffer message) {
        LOGGER.debug("Received pong");
        return WebSocket.Listener.super.onPong(webSocket, message);
    }
    
    /**
     * Process a received message.
     */
    private void processMessage(String message) {
        // Add to queue for processing
        boolean added = messageQueue.offer(message);
        if (!added) {
            LOGGER.warn("Message queue full, dropping message");
            return;
        }
        
        // Process in background thread
        executorService.submit(() -> {
            try {
                String msg = messageQueue.poll(1, TimeUnit.SECONDS);
                if (msg != null) {
                    handleMessage(msg);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                LOGGER.warn("Message processing interrupted");
            } catch (Exception e) {
                LOGGER.error("Error processing message: {}", e.getMessage(), e);
            }
        });
    }
    
    /**
     * Handle a single message.
     */
    private void handleMessage(String message) {
        try {
            LOGGER.debug("Processing message: {}", message);
            
            // Parse and handle message
            ProtocolV2.Message parsedMessage = ProtocolV2.parseMessage(message);
            
            if (parsedMessage instanceof ProtocolV2.Handshake) {
                handleHandshakeResponse((Handshake) parsedMessage);
            } else if (parsedMessage instanceof Action) {
                handleAction((Action) parsedMessage);
            } else if (parsedMessage instanceof Observation) {
                // Should not receive observations from brain
                LOGGER.error("Received observation from brain (unexpected)");
            } else {
                LOGGER.error("Unknown message type: {}", parsedMessage.getType());
            }
        } catch (ProtocolException e) {
            LOGGER.error("Protocol error: {}", e.getMessage());
            // In case of protocol error, disconnect
            closeConnection(1002, "Protocol error: " + e.getMessage());
        } catch (Exception e) {
            LOGGER.error("Error processing message: {}", e.getMessage(), e);
        }
    }
    
    /**
     * Send handshake to brain server.
     */
    private void sendHandshake() {
        try {
            Handshake handshake = new Handshake();
            String handshakeJson = handshake.toJson();
            send(handshakeJson);
            LOGGER.info("Sent handshake: {}", handshakeJson);
        } catch (Exception e) {
            LOGGER.error("Failed to send handshake: {}", e.getMessage(), e);
        }
    }
    
    /**
     * Handle handshake response from brain.
     */
    private void handleHandshakeResponse(Handshake response) {
        try {
            // Validate the handshake response
            ProtocolV2.validateHandshake(response);
            
            LOGGER.info("Handshake successful with brain");
            LOGGER.info("  Version: {}", response.getVersion());
            LOGGER.info("  Role: {}", response.getRole());
            LOGGER.info("  Capabilities: {}", response.getCapabilities());
            
            handshakeComplete.set(true);
            controlManager.setControlState(AiControlManager.ControlState.READY);
            
        } catch (ProtocolException e) {
            LOGGER.error("Handshake validation failed: {}", e.getMessage());
            closeConnection(1002, "Handshake validation failed: " + e.getMessage());
        }
    }
    
    /**
     * Handle action from brain.
     */
    private void handleAction(Action action) {
        if (!handshakeComplete.get()) {
            LOGGER.error("Received action before handshake complete");
            return;
        }
        
        try {
            // Validate the action
            ProtocolV2.validateAction(action);
            
            // Execute the action
            String actionType = action.getActionType();
            JsonObject data = action.getData();
            
            switch (actionType) {
                case "control":
                    handleControlAction(data);
                    break;
                case "look_delta":
                    handleLookDeltaAction(data);
                    break;
                case "sequence":
                    handleSequenceAction(data);
                    break;
                case "stop":
                    handleStopAction(data);
                    break;
                case "noop":
                    // Do nothing
                    break;
                default:
                    LOGGER.error("Unknown action type: {}", actionType);
                    sendError("unknown_action_type", "Unknown action type: " + actionType);
            }
        } catch (ProtocolException e) {
            LOGGER.error("Action validation failed: {}", e.getMessage());
            sendError("action_validation_failed", e.getMessage());
        } catch (Exception e) {
            LOGGER.error("Error handling action: {}", e.getMessage(), e);
            sendError("action_execution_error", e.getMessage());
        }
    }
    
    /**
     * Handle control action (movement keys).
     */
    private void handleControlAction(JsonObject data) {
        try {
            // Extract control states
            boolean forward = data.has("forward") && data.get("forward").getAsBoolean();
            boolean back = data.has("back") && data.get("back").getAsBoolean();
            boolean left = data.has("left") && data.get("left").getAsBoolean();
            boolean right = data.has("right") && data.get("right").getAsBoolean();
            boolean jump = data.has("jump") && data.get("jump").getAsBoolean();
            boolean sneak = data.has("sneak") && data.get("sneak").getAsBoolean();
            boolean sprint = data.has("sprint") && data.get("sprint").getAsBoolean();
            boolean attack = data.has("attack") && data.get("attack").getAsBoolean();
            boolean use = data.has("use") && data.get("use").getAsBoolean();
            
            // Apply controls through action executor
            actionExecutor.setMovementControls(forward, back, left, right);
            actionExecutor.setJump(jump);
            actionExecutor.setSneak(sneak);
            actionExecutor.setSprint(sprint);
            actionExecutor.setAttack(attack);
            actionExecutor.setUse(use);
            
            LOGGER.debug("Applied control action");
            
        } catch (Exception e) {
            LOGGER.error("Error parsing control action: {}", e.getMessage());
            throw e;
        }
    }
    
    /**
     * Handle look delta action (mouse movement).
     */
    private void handleLookDeltaAction(JsonObject data) {
        try {
            // Extract look deltas
            float yawDelta = data.has("yaw_delta") ? data.get("yaw_delta").getAsFloat() : 0.0f;
            float pitchDelta = data.has("pitch_delta") ? data.get("pitch_delta").getAsFloat() : 0.0f;
            
            // Apply look delta through action executor
            actionExecutor.setLookDelta(yawDelta, pitchDelta);
            
            LOGGER.debug("Applied look delta: yaw={}, pitch={}", yawDelta, pitchDelta);
            
        } catch (Exception e) {
            LOGGER.error("Error parsing look delta action: {}", e.getMessage());
            throw e;
        }
    }
    
    /**
     * Handle sequence action (multiple actions in sequence).
     */
    private void handleSequenceAction(JsonObject data) {
        try {
            // Extract sequence of actions
            if (data.has("actions") && data.get("actions").isJsonArray()) {
                var actionsArray = data.getAsJsonArray("actions");
                for (var actionElement : actionsArray) {
                    if (actionElement.isJsonObject()) {
                        JsonObject actionObj = actionElement.getAsJsonObject();
                        String actionType = actionObj.get("type").getAsString();
                        JsonObject actionData = actionObj.getAsJsonObject("data");
                        
                        // Execute each action in sequence
                        switch (actionType) {
                            case "control":
                                handleControlAction(actionData);
                                break;
                            case "look_delta":
                                handleLookDeltaAction(actionData);
                                break;
                            default:
                                LOGGER.warn("Unknown action type in sequence: {}", actionType);
                        }
                    }
                }
            }
            
            LOGGER.debug("Applied sequence action");
            
        } catch (Exception e) {
            LOGGER.error("Error parsing sequence action: {}", e.getMessage());
            throw e;
        }
    }
    
    /**
     * Handle stop action (stop all current actions).
     */
    private void handleStopAction(JsonObject data) {
        try {
            // Extract stop parameters
            boolean emergency = data.has("emergency") && data.get("emergency").getAsBoolean();
            String reason = data.has("reason") ? data.get("reason").getAsString() : "stop_action_received";
            
            // Stop all actions
            actionExecutor.stopAllActions(emergency);
            
            if (emergency) {
                controlManager.setControlState(AiControlManager.ControlState.EMERGENCY_LATCHED);
            } else {
                controlManager.setControlState(AiControlManager.ControlState.PAUSED);
            }
            
            LOGGER.info("Stop action executed: emergency={}, reason={}", emergency, reason);
            
        } catch (Exception e) {
            LOGGER.error("Error parsing stop action: {}", e.getMessage());
            throw e;
        }
    }
    
    /**
     * Send observation to brain.
     */
    public void sendObservation(long tick) {
        if (!handshakeComplete.get()) {
            return;
        }
        
        try {
            // Collect observations
            JsonObject observations = observationCollector.collectAll();
            
            // Create observation message
            Observation observation = new Observation(tick, observations);
            String observationJson = observation.toJson();
            
            // Send observation
            send(observationJson);
            
            LOGGER.debug("Sent observation for tick {}", tick);
            
        } catch (Exception e) {
            LOGGER.error("Failed to send observation: {}", e.getMessage(), e);
        }
    }
    
    /**
     * Send error message to brain.
     */
    private void sendError(String code, String message) {
        try {
            JsonObject errorDetails = new JsonObject();
            errorDetails.addProperty("timestamp", System.currentTimeMillis());
            
            ProtocolV2.Error error = new ProtocolV2.Error(code, message, errorDetails);
            String errorJson = error.toJson();
            
            send(errorJson);
            
            LOGGER.error("Sent error to brain: {} - {}", code, message);
            
        } catch (Exception e) {
            LOGGER.error("Failed to send error message: {}", e.getMessage(), e);
        }
    }
    
    /**
     * Send a message through the WebSocket.
     */
    private void send(String message) {
        WebSocket webSocket = webSocketRef.get();
        if (webSocket != null) {
            webSocket.sendText(message, true);
        } else {
            LOGGER.warn("Cannot send message, WebSocket not connected");
        }
    }
    
    /**
     * Close the WebSocket connection.
     */
    public void closeConnection(int statusCode, String reason) {
        WebSocket webSocket = webSocketRef.get();
        if (webSocket != null) {
            webSocket.sendClose(statusCode, reason);
        }
    }
    
    /**
     * Check if handshake is complete.
     */
    public boolean isHandshakeComplete() {
        return handshakeComplete.get();
    }
    
    /**
     * Check if WebSocket is connected.
     */
    public boolean isConnected() {
        WebSocket webSocket = webSocketRef.get();
        return webSocket != null;
    }
    
    /**
     * Check if ready to receive actions.
     */
    public boolean isReady() {
        return isConnected() && isHandshakeComplete();
    }
    
    /**
     * Shutdown the WebSocket client.
     */
    public void shutdown() {
        // Close connection
        closeConnection(1000, "Client shutdown");
        
        // Shutdown executor
        executorService.shutdown();
        try {
            if (!executorService.awaitTermination(5, TimeUnit.SECONDS)) {
                executorService.shutdownNow();
            }
        } catch (InterruptedException e) {
            executorService.shutdownNow();
            Thread.currentThread().interrupt();
        }
        
        LOGGER.info("BrainWebSocketClient shutdown complete");
    }
}