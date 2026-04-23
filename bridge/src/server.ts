/**
 * Python 与 Node 桥接层之间的本地 WebSocket 服务。
 *
 * 安全约束：
 * - 只监听 `127.0.0.1`
 * - 首条消息必须完成 `BRIDGE_TOKEN` 鉴权
 * - 带浏览器 `Origin` 头的连接直接拒绝
 */

import { WebSocketServer, WebSocket } from 'ws';
import { WhatsAppClient, InboundMessage } from './whatsapp.js';

interface SendCommand {
  type: 'send';
  to: string;
  text: string;
}

interface SendMediaCommand {
  type: 'send_media';
  to: string;
  filePath: string;
  mimetype: string;
  caption?: string;
  fileName?: string;
}

type BridgeCommand = SendCommand | SendMediaCommand;

interface BridgeMessage {
  type: 'message' | 'status' | 'qr' | 'error';
  [key: string]: unknown;
}

export class BridgeServer {
  private wss: WebSocketServer | null = null;
  private wa: WhatsAppClient | null = null;
  private clients: Set<WebSocket> = new Set();

  constructor(private port: number, private authDir: string, private token: string) {}

  async start(): Promise<void> {
    if (!this.token.trim()) {
      throw new Error('BRIDGE_TOKEN is required');
    }

    // 这里只允许本机连接，避免桥接口被当成公开服务暴露出去。
    this.wss = new WebSocketServer({
      host: '127.0.0.1',
      port: this.port,
      verifyClient: (info, done) => {
        const origin = info.origin || info.req.headers.origin;
        if (origin) {
          console.warn(`Rejected WebSocket connection with Origin header: ${origin}`);
          done(false, 403, 'Browser-originated WebSocket connections are not allowed');
          return;
        }
        done(true);
      },
    });
    console.log(`🌉 Bridge server listening on ws://127.0.0.1:${this.port}`);
    console.log('🔒 Token authentication enabled');

    // 先把 WhatsApp 客户端绑上广播回调，再统一由 BridgeServer 向 Python 侧扇出。
    this.wa = new WhatsAppClient({
      authDir: this.authDir,
      onMessage: (msg) => this.broadcast({ type: 'message', ...msg }),
      onQR: (qr) => this.broadcast({ type: 'qr', qr }),
      onStatus: (status) => this.broadcast({ type: 'status', status }),
    });

    // 每条 Python 连接都必须先完成鉴权，避免本地其他进程直接接管桥接服务。
    this.wss.on('connection', (ws) => {
      // 把鉴权限制在第一帧完成，避免未认证连接长期占住资源。
      const timeout = setTimeout(() => ws.close(4001, 'Auth timeout'), 5000);
      ws.once('message', (data) => {
        clearTimeout(timeout);
        try {
          const msg = JSON.parse(data.toString());
          if (msg.type === 'auth' && msg.token === this.token) {
            console.log('🔗 Python client authenticated');
            this.setupClient(ws);
          } else {
            ws.close(4003, 'Invalid token');
          }
        } catch {
          ws.close(4003, 'Invalid auth message');
        }
      });
    });

    // 桥接服务起来后再连 WhatsApp，保证状态事件有出口可发。
    await this.wa.connect();
  }

  private setupClient(ws: WebSocket): void {
    this.clients.add(ws);

    ws.on('message', async (data) => {
      try {
        const cmd = JSON.parse(data.toString()) as BridgeCommand;
        await this.handleCommand(cmd);
        ws.send(JSON.stringify({ type: 'sent', to: cmd.to }));
      } catch (error) {
        console.error('Error handling command:', error);
        ws.send(JSON.stringify({ type: 'error', error: String(error) }));
      }
    });

    ws.on('close', () => {
      console.log('🔌 Python client disconnected');
      this.clients.delete(ws);
    });

    ws.on('error', (error) => {
      console.error('WebSocket error:', error);
      this.clients.delete(ws);
    });
  }

  private async handleCommand(cmd: BridgeCommand): Promise<void> {
    if (!this.wa) return;

    if (cmd.type === 'send') {
      await this.wa.sendMessage(cmd.to, cmd.text);
    } else if (cmd.type === 'send_media') {
      await this.wa.sendMedia(cmd.to, cmd.filePath, cmd.mimetype, cmd.caption, cmd.fileName);
    }
  }

  private broadcast(msg: BridgeMessage): void {
    const data = JSON.stringify(msg);
    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(data);
      }
    }
  }

  async stop(): Promise<void> {
    // 先关掉 Python 侧连接，避免它们在后端停止过程中继续发命令。
    for (const client of this.clients) {
      client.close();
    }
    this.clients.clear();

    // 再关闭本地 WebSocket 服务，阻止新连接进入。
    if (this.wss) {
      this.wss.close();
      this.wss = null;
    }

    // 最后断开 WhatsApp，完成整个桥接层的有序收尾。
    if (this.wa) {
      await this.wa.disconnect();
      this.wa = null;
    }
  }
}
