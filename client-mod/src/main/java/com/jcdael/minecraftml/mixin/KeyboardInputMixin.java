package com.jcdael.minecraftml.mixin;

import com.jcdael.minecraftml.MinecraftMLMod;
import net.minecraft.client.Keyboard;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

@Mixin(Keyboard.class)
public class KeyboardInputMixin {
    @Inject(method = "onKey", at = @At("HEAD"))
    private void onKey(long window, int key, int scancode, int action, int modifiers, CallbackInfo ci) {
        if (MinecraftMLMod.getInstance() != null && MinecraftMLMod.getInstance().getManualInputMonitor() != null) {
            MinecraftMLMod.getInstance().getManualInputMonitor().onKeyInput(key, scancode, action, modifiers);
        }
    }
}