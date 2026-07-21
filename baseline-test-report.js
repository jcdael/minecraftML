#!/usr/bin/env node
/**
 * Baseline Test Report for minecraftML
 * Captured before Fabric migration
 */

const fs = require('fs');
const path = require('path');

console.log('=== MinecraftML Baseline Test Report ===');
console.log('Date:', new Date().toISOString());
console.log('Branch:', 'feature/fabric-local-player-mvp');
console.log('Migration Target: Mineflayer -> Fabric Local Player MVP');
console.log('');

// Check 1: Project Structure
console.log('1. Project Structure Check:');
const requiredDirs = ['adapter', 'brain'];
const requiredFiles = [
  'README.md',
  'config.example.json',
  'adapter/index.js',
  'adapter/package.json',
  'brain/main.py'
];

let structurePass = true;
requiredDirs.forEach(dir => {
  if (fs.existsSync(dir)) {
    console.log(`  ✓ ${dir}/ directory exists`);
  } else {
    console.log(`  ✗ ${dir}/ directory missing`);
    structurePass = false;
  }
});

requiredFiles.forEach(file => {
  if (fs.existsSync(file)) {
    console.log(`  ✓ ${file} exists`);
  } else {
    console.log(`  ✗ ${file} missing`);
    structurePass = false;
  }
});

console.log('');

// Check 2: Adapter Dependencies
console.log('2. Adapter Dependencies Check:');
try {
  const packageJson = JSON.parse(fs.readFileSync('adapter/package.json', 'utf8'));
  const deps = packageJson.dependencies || {};
  const devDeps = packageJson.devDependencies || {};
  
  console.log(`  ✓ package.json readable`);
  console.log(`  - Main dependencies: ${Object.keys(deps).length}`);
  console.log(`  - Dev dependencies: ${Object.keys(devDeps).length}`);
  
  if (deps.mineflayer) {
    console.log(`  ✓ Mineflayer dependency found (version: ${deps.mineflayer})`);
  } else {
    console.log(`  ✗ Mineflayer dependency not found`);
    structurePass = false;
  }
} catch (error) {
  console.log(`  ✗ Cannot read package.json: ${error.message}`);
  structurePass = false;
}

console.log('');

// Check 3: Configuration
console.log('3. Configuration Check:');
try {
  const configExample = fs.readFileSync('config.example.json', 'utf8');
  const config = JSON.parse(configExample);
  
  console.log(`  ✓ config.example.json readable`);
  console.log(`  - Minecraft version: ${config.minecraft?.version || 'not specified'}`);
  console.log(`  - Host: ${config.minecraft?.host || 'not specified'}`);
  console.log(`  - Auth mode: ${config.minecraft?.auth || 'not specified'}`);
  
  if (config.minecraft?.auth === 'offline') {
    console.log(`  ✓ Offline auth mode configured`);
  }
} catch (error) {
  console.log(`  ✗ Cannot read config.example.json: ${error.message}`);
  structurePass = false;
}

console.log('');

// Check 4: Brain Python Environment
console.log('4. Brain Python Environment Check:');
const brainFiles = [
  'brain/main.py',
  'brain/requirements.txt',
  'brain/agent.py'
];

let brainPass = true;
brainFiles.forEach(file => {
  if (fs.existsSync(file)) {
    console.log(`  ✓ ${file} exists`);
  } else {
    console.log(`  ✗ ${file} missing`);
    brainPass = false;
  }
});

console.log('');

// Summary
console.log('=== Summary ===');
console.log(`Project Structure: ${structurePass ? 'PASS' : 'FAIL'}`);
console.log(`Brain Files: ${brainPass ? 'PASS' : 'FAIL'}`);
console.log('');
console.log('Current Architecture:');
console.log('- Mineflayer-based bot client');
console.log('- WebSocket communication between adapter and brain');
console.log('- Python-based learning agent');
console.log('- Goal-oriented task execution');
console.log('');
console.log('Migration Notes:');
console.log('1. Need to replace Mineflayer with Fabric local player');
console.log('2. Maintain WebSocket protocol compatibility');
console.log('3. Preserve goal execution logic');
console.log('4. Add Fabric mod structure and build system');
console.log('5. Implement local player control via Fabric API');