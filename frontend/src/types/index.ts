export type ConnectionStatus = 'disconnected' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'error';

export type VoiceModel = 'nova-sonic' | 'gemini-live';

export interface WebSocketMessage {
  type: string;
  session_id?: string;
  model?: string;
  text?: string;
  content_id?: string;
  message?: string;
}

export interface TranscriptEntry {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: number;
}

export interface AudioWorkletMessage {
  type: 'audio' | 'clear' | 'flush' | 'handoff' | 'playbackStart' | 'playbackStop';
  pcm?: ArrayBuffer;
  crossfadeSamples?: number;
  sequence?: number;
}