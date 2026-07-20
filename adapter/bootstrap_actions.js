function createSmeltItem({
  bot,
  gotoNear,
  findPlacedBlock,
  itemCount,
  compactPosition,
  withContainerOperation,
  containerActive,
  delay
}) {
  return async function smeltItem(action, signal) {
    const inputName = String(action.input || '')
    const fuelName = String(action.fuel || '')
    const outputName = String(action.output || '')
    if (inputName !== 'raw_iron' || fuelName !== 'coal' || outputName !== 'iron_ingot') {
      throw Object.assign(new Error('Unsupported smelt recipe'), { code: 'missing_recipe' })
    }
    const furnaceBlock = findPlacedBlock('furnace', 16)
    if (!furnaceBlock) throw Object.assign(new Error('No placed furnace nearby'), { code: 'missing_furnace' })
    await gotoNear(furnaceBlock.position.x, furnaceBlock.position.y, furnaceBlock.position.z, 2, signal)
    const beforeOutput = itemCount(outputName)
    const inputItem = bot.inventory.items().find(candidate => candidate.name === inputName)
    const fuelItem = bot.inventory.items().find(candidate => candidate.name === fuelName)
    if (!inputItem) throw Object.assign(new Error(`Missing ${inputName}`), { code: 'missing_ingredients' })
    if (!fuelItem) throw Object.assign(new Error(`Missing ${fuelName}`), { code: 'missing_fuel' })
    const beforeInput = itemCount(inputName)
    const beforeFuel = itemCount(fuelName)
    const itemSummary = item => item ? { name: item.name, count: item.count } : null
    const furnace = await withContainerOperation(() => bot.openFurnace(furnaceBlock))
    let observedOutputSlot = itemSummary(furnace.outputItem())
    const observeOutputSlot = (slot, _oldItem, newItem) => {
      if (slot === 2 && newItem && newItem.name === outputName) {
        observedOutputSlot = { name: newItem.name, count: newItem.count, slot: newItem.slot === undefined ? 2 : newItem.slot }
      }
    }
    if (typeof furnace.on === 'function') furnace.on('updateSlot', observeOutputSlot)
    let furnaceClosed = false
    const closeFurnace = () => {
      if (furnaceClosed) return
      furnaceClosed = true
      try {
        furnace.close()
      } catch (_) {}
    }
    try {
      await withContainerOperation(() => furnace.putInput(inputItem.type, null, 1))
      const afterInput = itemCount(inputName)
      const inputSlotAfterPut = itemSummary(furnace.inputItem())
      await withContainerOperation(() => furnace.putFuel(fuelItem.type, null, 1))
      const afterFuel = itemCount(fuelName)
      const fuelSlotAfterPut = itemSummary(furnace.fuelItem())
      const furnaceSlotSnapshot = outputFallback => ({
        input_slot: inputSlotAfterPut,
        fuel_slot: fuelSlotAfterPut,
        output_slot_before_take: itemSummary(furnace.outputItem()) || observedOutputSlot || itemSummary(outputFallback)
      })
      const actionBudget = Math.min(Number(action.timeout_ms || 120000), 180000)
      const deadline = Date.now() + Math.max(1000, actionBudget - 5000)
      const buildSuccess = async (furnaceEvidence, transferSource) => {
        closeFurnace()
        await delay(500, signal)
        const afterOutput = itemCount(outputName)
        if (afterOutput > beforeOutput) {
          return {
            kind: 'smelt',
            input: inputName,
            fuel: fuelName,
            output: outputName,
            furnace_position: compactPosition(furnaceBlock.position),
            output_before: beforeOutput,
            output_after: afterOutput,
            input_before: beforeInput,
            input_after_put: afterInput,
            fuel_before: beforeFuel,
            fuel_after_put: afterFuel,
            furnace: furnaceEvidence,
            output_transfer_source: transferSource,
            container_pending: 0,
            container_active: containerActive()
          }
        }
        return null
      }
      while (Date.now() < deadline) {
        if (signal.aborted) throw Object.assign(new Error('interrupted'), { code: 'interrupted' })
        const output = furnace.outputItem()
        const observedOutput = observedOutputSlot && observedOutputSlot.name === outputName && observedOutputSlot.count >= 1 ? observedOutputSlot : null
        if ((output && output.name === outputName && output.count >= 1) || observedOutput) {
          const transferResult = await withContainerOperation(() => {
            if (output) return furnace.takeOutput()
            if (typeof bot.putAway === 'function' && Number.isInteger(observedOutput.slot)) return Promise.resolve(bot.putAway(observedOutput.slot)).then(() => observedOutput)
            return furnace.takeOutput()
          })
          const furnaceEvidence = furnaceSlotSnapshot(output || observedOutput || transferResult)
          const success = await buildSuccess(furnaceEvidence, output ? 'take_output' : 'observed_output_slot')
          if (success) return success
        }
        await delay(500, signal)
      }
      throw Object.assign(new Error('Timed out waiting for smelt output'), { code: 'timeout' })
    } finally {
      if (typeof furnace.off === 'function') furnace.off('updateSlot', observeOutputSlot)
      else if (typeof furnace.removeListener === 'function') furnace.removeListener('updateSlot', observeOutputSlot)
      closeFurnace()
    }
  }
}

module.exports = { createSmeltItem }
