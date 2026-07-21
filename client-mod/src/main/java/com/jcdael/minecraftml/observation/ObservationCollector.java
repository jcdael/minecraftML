package com.jcdael.minecraftml.observation;

import net.minecraft.client.MinecraftClient;
import net.minecraft.client.network.ClientPlayerEntity;
import net.minecraft.entity.Entity;
import net.minecraft.entity.player.PlayerInventory;
import net.minecraft.item.ItemStack;
import net.minecraft.util.math.BlockPos;
import net.minecraft.util.math.Box;
import net.minecraft.util.math.Vec3d;
import net.minecraft.world.World;
import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonArray;

import java.util.HashMap;
import java.util.Map;

/**
 * Collects observations from the Minecraft client for training.
 * Reads player state, inventory, and world information.
 * Uses namespace-stripped identifier conventions (e.g., "oak_log" instead of "minecraft:oak_log").
 */
public class ObservationCollector {
    private static final Gson GSON = new GsonBuilder().setPrettyPrinting().create();
    private final MinecraftClient client;
    
    // Configuration for observation collection
    private static final int NEARBY_BLOCKS_RADIUS = 5; // blocks
    private static final int NEARBY_BLOCKS_SAMPLE_COUNT = 20; // max blocks to sample
    private static final double NEARBY_ENTITIES_RADIUS = 10.0; // blocks
    private static final int NEARBY_ENTITIES_SAMPLE_COUNT = 10; // max entities to sample
    
    public ObservationCollector(MinecraftClient client) {
        this.client = client;
    }
    
    /**
     * Collect all observations from the current game state.
     * @return JsonObject containing all observations
     */
    public JsonObject collectAll() {
        JsonObject observations = new JsonObject();
        
        // Collect player observations
        observations.add("player", collectPlayerObservations());
        
        // Collect inventory observations
        observations.add("inventory", collectInventoryObservations());
        
        // Collect world observations
        observations.add("world", collectWorldObservations());
        
        // Collect nearby blocks
        observations.add("nearby_blocks", collectNearbyBlocks());
        
        // Collect nearby entities
        observations.add("nearby_entities", collectNearbyEntities());
        
        // Add metadata
        observations.addProperty("timestamp", System.currentTimeMillis());
        observations.addProperty("protocol_version", "v2");
        observations.addProperty("role", "fabric_local_player");
        
        return observations;
    }
    
    /**
     * Collect player-specific observations.
     */
    private JsonObject collectPlayerObservations() {
        JsonObject player = new JsonObject();
        
        ClientPlayerEntity playerEntity = client.player;
        if (playerEntity == null) {
            return player; // Return empty object if no player
        }
        
        // Position and rotation
        Vec3d pos = playerEntity.getPos();
        player.addProperty("x", pos.x);
        player.addProperty("y", pos.y);
        player.addProperty("z", pos.z);
        
        player.addProperty("yaw", playerEntity.getYaw());
        player.addProperty("pitch", playerEntity.getPitch());
        
        // Movement and state
        player.addProperty("on_ground", playerEntity.isOnGround());
        player.addProperty("sprinting", playerEntity.isSprinting());
        player.addProperty("sneaking", playerEntity.isSneaking());
        player.addProperty("swimming", playerEntity.isSwimming());
        player.addProperty("flying", playerEntity.getAbilities().flying);
        player.addProperty("creative_mode", playerEntity.isCreative());
        
        // Health and food
        player.addProperty("health", playerEntity.getHealth());
        player.addProperty("max_health", playerEntity.getMaxHealth());
        player.addProperty("food_level", playerEntity.getHungerManager().getFoodLevel());
        player.addProperty("saturation_level", playerEntity.getHungerManager().getSaturationLevel());
        player.addProperty("exhaustion", playerEntity.getHungerManager().getExhaustion());
        
        // Experience
        player.addProperty("experience_level", playerEntity.experienceLevel);
        player.addProperty("experience_progress", playerEntity.experienceProgress);
        player.addProperty("total_experience", playerEntity.totalExperience);
        
        // Velocity
        Vec3d velocity = playerEntity.getVelocity();
        player.addProperty("velocity_x", velocity.x);
        player.addProperty("velocity_y", velocity.y);
        player.addProperty("velocity_z", velocity.z);
        
        // Game mode
        String gameMode = "survival";
        if (playerEntity.isCreative()) {
            gameMode = "creative";
        } else if (playerEntity.isSpectator()) {
            gameMode = "spectator";
        } else if (playerEntity.getAbilities().invulnerable) {
            gameMode = "adventure";
        }
        player.addProperty("game_mode", gameMode);
        
        return player;
    }
    
    /**
     * Collect inventory observations with namespace-stripped identifiers.
     */
    private JsonObject collectInventoryObservations() {
        JsonObject inventory = new JsonObject();
        
        ClientPlayerEntity playerEntity = client.player;
        if (playerEntity == null) {
            return inventory;
        }
        
        PlayerInventory playerInventory = playerEntity.getInventory();
        
        // Main inventory (0-35)
        JsonArray mainInventory = new JsonArray();
        for (int i = 0; i < 36; i++) {
            ItemStack stack = playerInventory.getStack(i);
            if (!stack.isEmpty()) {
                JsonObject item = new JsonObject();
                item.addProperty("slot", i);
                item.addProperty("item", stripNamespace(stack.getItem().toString()));
                item.addProperty("count", stack.getCount());
                item.addProperty("max_stack_size", stack.getMaxCount());
                if (stack.isDamageable()) {
                    item.addProperty("damage", stack.getDamage());
                    item.addProperty("max_damage", stack.getMaxDamage());
                }
                mainInventory.add(item);
            }
        }
        inventory.add("main", mainInventory);
        
        // Hotbar (0-8)
        JsonArray hotbar = new JsonArray();
        for (int i = 0; i < 9; i++) {
            ItemStack stack = playerInventory.getStack(i);
            if (!stack.isEmpty()) {
                JsonObject item = new JsonObject();
                item.addProperty("slot", i);
                item.addProperty("item", stripNamespace(stack.getItem().toString()));
                item.addProperty("count", stack.getCount());
                hotbar.add(item);
            }
        }
        inventory.add("hotbar", hotbar);
        
        // Armor (36-39)
        JsonArray armor = new JsonArray();
        for (int i = 36; i < 40; i++) {
            ItemStack stack = playerInventory.getStack(i);
            if (!stack.isEmpty()) {
                JsonObject item = new JsonObject();
                item.addProperty("slot", i - 36); // 0-3 for armor slots
                item.addProperty("item", stripNamespace(stack.getItem().toString()));
                item.addProperty("count", stack.getCount());
                armor.add(item);
            }
        }
        inventory.add("armor", armor);
        
        // Offhand (40)
        ItemStack offhand = playerInventory.offHand.get(0);
        if (!offhand.isEmpty()) {
            JsonObject offhandObj = new JsonObject();
            offhandObj.addProperty("item", stripNamespace(offhand.getItem().toString()));
            offhandObj.addProperty("count", offhand.getCount());
            inventory.add("offhand", offhandObj);
        }
        
        // Selected hotbar slot
        inventory.addProperty("selected_slot", playerInventory.selectedSlot);
        
        return inventory;
    }
    
    /**
     * Collect world observations.
     */
    private JsonObject collectWorldObservations() {
        JsonObject world = new JsonObject();
        
        World minecraftWorld = client.world;
        if (minecraftWorld == null) {
            return world;
        }
        
        // World info
        world.addProperty("dimension", stripNamespace(minecraftWorld.getRegistryKey().getValue().toString()));
        world.addProperty("time_of_day", minecraftWorld.getTimeOfDay());
        world.addProperty("is_raining", minecraftWorld.isRaining());
        world.addProperty("is_thundering", minecraftWorld.isThundering());
        world.addProperty("rain_gradient", minecraftWorld.getRainGradient(1.0f));
        world.addProperty("thunder_gradient", minecraftWorld.getThunderGradient(1.0f));
        
        // Player position for chunk/block info
        ClientPlayerEntity player = client.player;
        if (player != null) {
            BlockPos playerPos = player.getBlockPos();
            world.addProperty("player_chunk_x", playerPos.getX() >> 4);
            world.addProperty("player_chunk_z", playerPos.getZ() >> 4);
            world.addProperty("player_block_x", playerPos.getX());
            world.addProperty("player_block_y", playerPos.getY());
            world.addProperty("player_block_z", playerPos.getZ());
            
            // Light level at player position
            world.addProperty("light_level", minecraftWorld.getLightLevel(playerPos));
            
            // Biome at player position
            world.addProperty("biome", stripNamespace(minecraftWorld.getBiome(playerPos).getKey().orElseThrow().getValue().toString()));
        }
        
        return world;
    }
    
    /**
     * Collect nearby blocks within configured radius.
     */
    private JsonArray collectNearbyBlocks() {
        JsonArray nearbyBlocks = new JsonArray();
        
        ClientPlayerEntity player = client.player;
        World world = client.world;
        
        if (player == null || world == null) {
            return nearbyBlocks;
        }
        
        BlockPos playerPos = player.getBlockPos();
        int radius = NEARBY_BLOCKS_RADIUS;
        int sampleCount = 0;
        
        // Sample blocks in a sphere around the player
        for (int dx = -radius; dx <= radius && sampleCount < NEARBY_BLOCKS_SAMPLE_COUNT; dx++) {
            for (int dy = -radius; dy <= radius && sampleCount < NEARBY_BLOCKS_SAMPLE_COUNT; dy++) {
                for (int dz = -radius; dz <= radius && sampleCount < NEARBY_BLOCKS_SAMPLE_COUNT; dz++) {
                    BlockPos blockPos = playerPos.add(dx, dy, dz);
                    
                    // Skip if too far (sphere check)
                    double distance = Math.sqrt(dx*dx + dy*dy + dz*dz);
                    if (distance > radius) {
                        continue;
                    }
                    
                    // Sample every other block to reduce count
                    if ((dx + dy + dz) % 2 != 0) {
                        continue;
                    }
                    
                    // Get block state and add to observations
                    net.minecraft.block.BlockState blockState = world.getBlockState(blockPos);
                    if (!blockState.isAir()) {
                        JsonObject block = new JsonObject();
                        block.addProperty("x", blockPos.getX());
                        block.addProperty("y", blockPos.getY());
                        block.addProperty("z", blockPos.getZ());
                        block.addProperty("block", stripNamespace(blockState.getBlock().toString()));
                        block.addProperty("distance", (float)distance);
                        
                        nearbyBlocks.add(block);
                        sampleCount++;
                    }
                }
            }
        }
        
        return nearbyBlocks;
    }
    
    /**
     * Collect nearby entities within configured radius.
     */
    private JsonArray collectNearbyEntities() {
        JsonArray nearbyEntities = new JsonArray();
        
        ClientPlayerEntity player = client.player;
        World world = client.world;
        
        if (player == null || world == null) {
            return nearbyEntities;
        }
        
        Vec3d playerPos = player.getPos();
        double radius = NEARBY_ENTITIES_RADIUS;
        
        // Create bounding box for entity search
        Box searchBox = new Box(
            playerPos.x - radius, playerPos.y - radius, playerPos.z - radius,
            playerPos.x + radius, playerPos.y + radius, playerPos.z + radius
        );
        
        // Get entities in the area
        int sampleCount = 0;
        for (Entity entity : world.getEntities()) {
            if (sampleCount >= NEARBY_ENTITIES_SAMPLE_COUNT) {
                break;
            }
            
            // Skip the player themselves
            if (entity == player) {
                continue;
            }
            
            Vec3d entityPos = entity.getPos();
            double distance = playerPos.distanceTo(entityPos);
            
            if (distance <= radius) {
                JsonObject entityObj = new JsonObject();
                entityObj.addProperty("type", stripNamespace(entity.getType().toString()));
                entityObj.addProperty("x", entityPos.x);
                entityObj.addProperty("y", entityPos.y);
                entityObj.addProperty("z", entityPos.z);
                entityObj.addProperty("distance", (float)distance);
                entityObj.addProperty("has_custom_name", entity.hasCustomName());
                
                if (entity.hasCustomName()) {
                    entityObj.addProperty("custom_name", entity.getCustomName().getString());
                }
                
                // Add entity-specific properties
                if (entity instanceof net.minecraft.entity.LivingEntity) {
                    net.minecraft.entity.LivingEntity livingEntity = (net.minecraft.entity.LivingEntity) entity;
                    entityObj.addProperty("health", livingEntity.getHealth());
                    entityObj.addProperty("max_health", livingEntity.getMaxHealth());
                    entityObj.addProperty("is_sneaking", livingEntity.isSneaking());
                    entityObj.addProperty("is_sprinting", livingEntity.isSprinting());
                }
                
                nearbyEntities.add(entityObj);
                sampleCount++;
            }
        }
        
        return nearbyEntities;
    }
    
    /**
     * Strip namespace from identifier (e.g., "minecraft:oak_log" -> "oak_log").
     */
    private String stripNamespace(String identifier) {
        if (identifier == null) {
            return "";
        }
        
        int colonIndex = identifier.indexOf(':');
        if (colonIndex != -1 && colonIndex + 1 < identifier.length()) {
            return identifier.substring(colonIndex + 1);
        }
        
        return identifier;
    }
    
    /**
     * Collect a minimal observation set for high-frequency updates.
     */
    public JsonObject collectMinimal() {
        JsonObject minimal = new JsonObject();
        
        ClientPlayerEntity player = client.player;
        if (player != null) {
            Vec3d pos = player.getPos();
            minimal.addProperty("x", pos.x);
            minimal.addProperty("y", pos.y);
            minimal.addProperty("z", pos.z);
            minimal.addProperty("yaw", player.getYaw());
            minimal.addProperty("pitch", player.getPitch());
            minimal.addProperty("on_ground", player.isOnGround());
            minimal.addProperty("health", player.getHealth());
            minimal.addProperty("food_level", player.getHungerManager().getFoodLevel());
        }
        
        return minimal;
    }
    
    /**
     * Get the configuration for observation collection.
     */
    public JsonObject getConfiguration() {
        JsonObject config = new JsonObject();
        config.addProperty("nearby_blocks_radius", NEARBY_BLOCKS_RADIUS);
        config.addProperty("nearby_blocks_sample_count", NEARBY_BLOCKS_SAMPLE_COUNT);
        config.addProperty("nearby_entities_radius", NEARBY_ENTITIES_RADIUS);
        config.addProperty("nearby_entities_sample_count", NEARBY_ENTITIES_SAMPLE_COUNT);
        return config;
    }
}