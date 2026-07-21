package com.jcdael.minecraftml.mixin;

import com.jcdael.minecraftml.MinecraftMLMod;
import net.minecraft.client.Mouse;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Mouse.class)
public class MouseInputMixin {
    @Inject(method = "onMouseButton", at = @At("HEAD"))
    private void onMouseButton(long window, int button, int action, int modifiers, CallbackInfo ci) {
        if (MinecraftMLMod.getInstance() != null && MinecraftMLMod.getInstance().getManualInputMonitor() != null) {
            MinecraftMLMod.getInstance().getManualInputMonitor().onMouseButton(button, action, modifiers);
        }
    }
    
    @Inject(method = "onCursorPos", at = @At("HEAD"))
    private void onCursorPos(long window, double x, double y, CallbackInfo ci) {
        if (MinecraftMLMod.getInstance() != null && MinecraftMLMod.getInstance().getManualInputMonitor() != null) {
            // Calculate delta from previous position
            // Note: This is simplified - in a real implementation we'd track previous position
            MinecraftMLMod.getInstance().getManualInputMonitor().onMouseMove(0, 0);
        }
    }
}