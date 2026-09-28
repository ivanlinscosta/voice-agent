import type { WebSocketMessage } from '../types';

type MessageHandler = (message: WebSocketMessage) => void;
type BinaryHandler = (data: ArrayBuffer) => void;

export class VoiceSocket {
  private ws: WebSocket | null = null;
  private url: string;
  private token: string | null;
  private model: string;
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 5;
  private reconnectDelay = 1000;
  private isIntentionalClose = false;
  private messageHandlers: Set<MessageHandler> = new Set();
  private binaryHandlers: Set<BinaryHandler> = new Set();
  private onStatusChange: ((status: string) => void) | null = null;
  private binaryFrames = 0;
  private binaryLogged = false;
  private sentAudioFrames = 0;
  private pingTimer: ReturnType<typeof setInterval> | null = null;

  constructor(url: string, token: string | null = null, model: string = 'nova-sonic') {
    this.url = url;
    this.token = token;
    this.model = model;
  }

  setStatusHandler(handler: (status: string) => void) {
    this.onStatusChange = handler;
  }

  addMessageHandler(handler: MessageHandler) {
    this.messageHandlers.add(handler);
    return () => this.messageHandlers.delete(handler);
  }

  addBinaryHandler(handler: BinaryHandler) {
    this.binaryHandlers.add(handler);
    return () => this.binaryHandlers.delete(handler);
  }

  private updateStatus(status: string) {
    if (this.onStatusChange) {
      this.onStatusChange(status);
    }
  }

  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      if (this.ws?.readyState === WebSocket.OPEN) {
        resolve();
        return;
      }

      this.isIntentionalClose = false;
      this.updateStatus('connecting');

      const urlObj = new URL(this.url, window.location.href);
      if (this.token) {
        urlObj.searchParams.set('token', this.token);
      }
      if (this.model) {
        urlObj.searchParams.set('model', this.model);
      }
      const wsUrl = urlObj.toString();
      this.ws = new WebSocket(wsUrl);

      this.ws.binaryType = 'arraybuffer';

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.updateStatus('listening');
        console.info('[voice] websocket open', this.url);
        this.stopPing();
        this.pingTimer = setInterval(() => {
          this.send({ type: 'ping' });
        }, 25000);
        // Session is started by the server on accept; do not send start_session.
        resolve();
      };

      this.ws.onmessage = (event) => {
        if (typeof event.data === 'string') {
          try {
            const message = JSON.parse(event.data) as WebSocketMessage;
            console.info('[voice] message', message.type, message);
            this.handleMessage(message);
          } catch (e) {
            console.error('[voice] failed to parse message:', e);
          }
        } else if (event.data instanceof ArrayBuffer) {
          const size = event.data.byteLength;
          if (!this.binaryLogged) {
            console.info('[voice] first binary audio frame', size);
            this.binaryLogged = true;
          }
          this.binaryFrames += 1;
          if (this.binaryFrames % 50 === 0) {
            console.info(`[voice] audio frames=${this.binaryFrames} lastBytes=${size}`);
          }
          this.binaryHandlers.forEach(handler => handler(event.data));
        }
      };

      this.ws.onclose = (event) => {
        console.info('[voice] websocket close', event.code, event.reason);
        this.stopPing();
        this.updateStatus('disconnected');
        if (!this.isIntentionalClose && this.reconnectAttempts < this.maxReconnectAttempts) {
          const attempt = this.reconnectAttempts;
          this.reconnectAttempts++;
          setTimeout(() => {
            void this.connect().catch(() => {
              this.updateStatus('error');
            });
          }, this.reconnectDelay * Math.pow(2, attempt));
        }
      };

      this.ws.onerror = (error) => {
        console.error('[voice] websocket error', error);
        this.updateStatus('error');
        reject(error);
      };
    });
  }

  private handleMessage(message: WebSocketMessage) {
    this.messageHandlers.forEach(handler => handler(message));
  }

  send(message: object) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    }
  }

  sendAudio(audioData: ArrayBuffer) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(audioData);
      if (this.sentAudioFrames === 0 || this.sentAudioFrames % 100 === 0) {
        console.info(`[voice] sent audio frames=${this.sentAudioFrames + 1} bytes=${audioData.byteLength}`);
      }
      this.sentAudioFrames += 1;
    } else if (this.sentAudioFrames === 0) {
      console.warn('[voice] sendAudio skipped: websocket not open');
      this.sentAudioFrames = 1;
    }
  }

  stopSession() {
    this.send({ type: 'stop_session' });
  }

  private stopPing() {
    if (this.pingTimer) {
      clearInterval(this.pingTimer);
      this.pingTimer = null;
    }
  }

  disconnect() {
    this.isIntentionalClose = true;
    this.stopPing();
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  get readyState() {
    return this.ws?.readyState ?? WebSocket.CLOSED;
  }
}

export function createVoiceSocket(url: string, token?: string, model?: string): VoiceSocket {
  return new VoiceSocket(url, token ?? null, model ?? 'nova-sonic');
}