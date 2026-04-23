#!/usr/bin/env node
/**
 * elebot WhatsApp Bridge 入口。
 *
 * 这个进程负责把 WhatsApp Web 侧事件转发给 Python 主进程，
 * 同时接收 Python 发来的发送指令。
 *
 * 使用方式：
 *   npm run build && npm start
 *
 * 自定义端口或认证目录时：
 *   BRIDGE_PORT=3001 AUTH_DIR=~/.elebot/whatsapp npm start
 */

// Baileys 在 ESM 环境里仍依赖全局 crypto，这里统一补齐。
import { webcrypto } from 'crypto';
if (!globalThis.crypto) {
  (globalThis as any).crypto = webcrypto;
}

import { BridgeServer } from './server.js';
import { homedir } from 'os';
import { join } from 'path';

const PORT = parseInt(process.env.BRIDGE_PORT || '3001', 10);
const AUTH_DIR = process.env.AUTH_DIR || join(homedir(), '.elebot', 'whatsapp-auth');
const TOKEN = process.env.BRIDGE_TOKEN?.trim();

if (!TOKEN) {
  console.error('BRIDGE_TOKEN is required. Start the bridge via elebot so it can provision a local secret automatically.');
  process.exit(1);
}

console.log('🐈 elebot WhatsApp Bridge');
console.log('========================\n');

const server = new BridgeServer(PORT, AUTH_DIR, TOKEN);

// 显式兜住退出信号，避免扫码状态和 WebSocket 连接被硬切断。
process.on('SIGINT', async () => {
  console.log('\n\nShutting down...');
  await server.stop();
  process.exit(0);
});

process.on('SIGTERM', async () => {
  await server.stop();
  process.exit(0);
});

// 桥接进程只有一个入口，启动失败时直接退出，避免留下半可用状态。
server.start().catch((error) => {
  console.error('Failed to start bridge:', error);
  process.exit(1);
});
