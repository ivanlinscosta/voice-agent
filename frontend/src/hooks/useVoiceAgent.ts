import { useState, useCallback, useRef, useEffect } from 'react';
import { VoiceSocket, createVoiceSocket } from '../services/voiceSocket';
import { useAudioCapture } from './useAudioCapture';
import { useAudioPlayback } from './useAudioPlayback';
import { estimateSessionCost } from '../utils/costEstimate';
import type { ConnectionStatus, TranscriptEntry, VoiceModel, WebSocketMessage } from '../types';

interface UseVoiceAgentOptions {
  wsUrl: string;
  token?: string;
  defaultModel?: VoiceModel;
  onError?: (message: string) => void;
}

function joinTranscriptChunks(existing: string, chunk: string): string {
  if (!existing) return chunk;
  if (!chunk) return existing;
  if (/\s$/.test(existing) || /^[.,;:!?)\]]/.test(chunk)) {
    return existing + chunk;
  }
  return `${existing} ${chunk}`;
}

export function useVoiceAgent({ wsUrl, token, defaultModel = 'nova-sonic', onError }: UseVoiceAgentOptions) {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const [selectedModel, setSelectedModel] = useState<VoiceModel>(defaultModel);
  const [transcripts, setTranscripts] = useState<TranscriptEntry[]>([]);
  const [volume, setVolume] = useState(0);
  const [sessionDuration, setSessionDuration] = useState(0);
  const [estimatedCost, setEstimatedCost] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isMuted, setIsMuted] = useState(false);

  const socketRef = useRef<VoiceSocket | null>(null);
  const sessionStartRef = useRef<number | null>(null);
  const durationIntervalRef = useRef<number | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const inputAudioBytesRef = useRef<number>(0);
  const outputAudioBytesRef = useRef<number>(0);
  const inputTextRef = useRef<string>('');
  const outputTextRef = useRef<string>('');
  const assistantBubbleOpenRef = useRef<boolean>(false);

  const isMutedRef = useRef<boolean>(false);
  isMutedRef.current = isMuted;

  const { start: startCapture, stop: stopCapture } = useAudioCapture({
    onAudioData: (pcm16) => {
      if (!isMutedRef.current) {
        inputAudioBytesRef.current += pcm16.byteLength;
        socketRef.current?.sendAudio(pcm16);
      }
    },
    sampleRate: 16000,
    frameDurationMs: 30,
  });

  const { initialize: initPlayback, play, clear, flush } = useAudioPlayback({
    inputSampleRate: 24000,
    bufferSeconds: 10,
  });

  const updateCost = useCallback(() => {
    setEstimatedCost(estimateSessionCost({
      inputAudioBytes: inputAudioBytesRef.current,
      outputAudioBytes: outputAudioBytesRef.current,
      inputText: inputTextRef.current,
      outputText: outputTextRef.current,
      model: selectedModel,
    }));
  }, [selectedModel]);

  const handleMessage = useCallback((message: WebSocketMessage) => {
    switch (message.type) {
      case 'session_started':
        sessionIdRef.current = message.session_id ?? null;
        sessionStartRef.current = Date.now();
        if (durationIntervalRef.current) {
          clearInterval(durationIntervalRef.current);
        }
        durationIntervalRef.current = window.setInterval(() => {
          if (sessionStartRef.current) {
            setSessionDuration(Math.floor((Date.now() - sessionStartRef.current) / 1000));
            updateCost();
          }
        }, 1000);
        break;

      case 'session_renewed':
        sessionIdRef.current = message.session_id ?? null;
        break;

      case 'user_transcript':
        if (message.text) {
          assistantBubbleOpenRef.current = false;
          inputTextRef.current += message.text + ' ';
          setTranscripts(prev => [...prev, {
            id: crypto.randomUUID(),
            role: 'user',
            text: message.text!,
            timestamp: Date.now(),
          }]);
          updateCost();
        }
        break;

      case 'assistant_transcript':
        if (message.text) {
          outputTextRef.current += message.text + ' ';
          const chunk = message.text;
          const appendToOpen = assistantBubbleOpenRef.current;
          assistantBubbleOpenRef.current = true;
          setTranscripts(prev => {
            const last = prev[prev.length - 1];
            if (appendToOpen && last?.role === 'assistant') {
              const merged = [...prev];
              merged[merged.length - 1] = {
                ...last,
                text: joinTranscriptChunks(last.text, chunk),
              };
              return merged;
            }
            return [...prev, {
              id: crypto.randomUUID(),
              role: 'assistant' as const,
              text: chunk,
              timestamp: Date.now(),
            }];
          });
          updateCost();
        }
        break;

      case 'assistant_turn_end':
        assistantBubbleOpenRef.current = false;
        setStatus('listening');
        break;

      case 'interrupted':
        assistantBubbleOpenRef.current = false;
        setStatus('listening');
        flush();
        break;

      case 'error':
        setError(message.message ?? 'Unknown error');
        onError?.(message.message ?? 'Unknown error');
        break;
    }
  }, [flush, onError, updateCost]);

  const handleAudio = useCallback((audioData: ArrayBuffer) => {
    outputAudioBytesRef.current += audioData.byteLength;
    if (status === 'listening' || status === 'thinking') {
      setStatus('speaking');
    }
    play(audioData);
  }, [play, status]);

  const handleStatusChange = useCallback((newStatus: string) => {
    setStatus(newStatus as ConnectionStatus);
  }, []);

  const handleVolumeChange = useCallback((vol: number) => {
    setVolume(vol);
  }, []);

  const connect = useCallback(async (overrideModel?: VoiceModel) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) return;

    const activeModel = overrideModel || selectedModel;
    if (overrideModel && overrideModel !== selectedModel) {
      setSelectedModel(overrideModel);
    }

    setError(null);
    setStatus('connecting');
    
    inputAudioBytesRef.current = 0;
    outputAudioBytesRef.current = 0;
    inputTextRef.current = '';
    outputTextRef.current = '';
    assistantBubbleOpenRef.current = false;
    setEstimatedCost(0);

    try {
      console.info('[voice] connecting', wsUrl, 'model:', activeModel);
      await initPlayback();

      const socket = createVoiceSocket(wsUrl, token, activeModel);
      socket.setStatusHandler(handleStatusChange);
      socket.addMessageHandler(handleMessage);
      socket.addBinaryHandler(handleAudio);
      socketRef.current = socket;

      await socket.connect();
      await startCapture(handleVolumeChange);
      console.info('[voice] connect + capture complete');
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to connect';
      console.error('[voice] connect failed:', message, err);
      setError(message);
      setStatus('error');
      onError?.(message);
    }
  }, [wsUrl, token, selectedModel, initPlayback, handleStatusChange, handleMessage, handleAudio, startCapture, onError, handleVolumeChange]);

  const disconnect = useCallback(async () => {
    if (durationIntervalRef.current) {
      clearInterval(durationIntervalRef.current);
      durationIntervalRef.current = null;
    }
    sessionStartRef.current = null;

    stopCapture();
    socketRef.current?.disconnect();
    socketRef.current = null;
    clear();
    setStatus('disconnected');
    setVolume(0);
    setIsMuted(false);
  }, [stopCapture, clear]);

  const clearTranscripts = useCallback(() => {
    assistantBubbleOpenRef.current = false;
    setTranscripts([]);
  }, []);

  const sendStopSession = useCallback(() => {
    socketRef.current?.stopSession();
  }, []);

  const toggleMute = useCallback(() => {
    setIsMuted(prev => !prev);
  }, []);

  const sendText = useCallback((text: string) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send({ type: 'message', text });
      
      assistantBubbleOpenRef.current = false;
      inputTextRef.current += text + ' ';
      setTranscripts(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'user',
        text: text,
        timestamp: Date.now(),
      }]);
      updateCost();
      return true;
    }
    return false;
  }, [updateCost]);

  useEffect(() => {
    return () => {
      if (durationIntervalRef.current) {
        clearInterval(durationIntervalRef.current);
      }
      socketRef.current?.disconnect();
    };
  }, []);

  const formatDuration = (seconds: number) => {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}:${secs.toString().padStart(2, '0')}`;
  };

  return {
    status,
    selectedModel,
    setSelectedModel,
    transcripts,
    volume,
    sessionDuration,
    estimatedCost,
    error,
    connect,
    disconnect,
    clearTranscripts,
    sendStopSession,
    sessionId: sessionIdRef.current,
    formatDuration,
    isMuted,
    toggleMute,
    sendText,
  };
}
