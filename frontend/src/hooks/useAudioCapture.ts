import { useRef, useCallback, useEffect } from 'react';
import type { AudioWorkletMessage } from '../types';

interface UseAudioCaptureOptions {
  onAudioData: (pcm16: ArrayBuffer) => void;
  sampleRate?: number;
  frameDurationMs?: number;
}

export function useAudioCapture({ onAudioData, sampleRate = 16000, frameDurationMs = 30 }: UseAudioCaptureOptions) {
  const audioContextRef = useRef<AudioContext | null>(null);
  const captureNodeRef = useRef<AudioWorkletNode | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animationFrameRef = useRef<number | null>(null);
  const onVolumeChangeRef = useRef<((volume: number) => void) | null>(null);

  const start = useCallback(async (onVolumeChange?: (volume: number) => void) => {
    if (streamRef.current) return;

    if (onVolumeChange) {
      onVolumeChangeRef.current = onVolumeChange;
    }

    try {
      const audioContext = new AudioContext({ sampleRate });
      audioContextRef.current = audioContext;
      if (audioContext.state === 'suspended') {
        await audioContext.resume();
      }

      await audioContext.audioWorklet.addModule('/capture-worklet.js');

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      const source = audioContext.createMediaStreamSource(stream);

      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      analyserRef.current = analyser;

      const captureNode = new AudioWorkletNode(audioContext, 'capture-processor', {
        processorOptions: { targetSampleRate: sampleRate, frameDurationMs },
      });
      captureNodeRef.current = captureNode;

      let frameCount = 0;
      captureNode.port.onmessage = (event: MessageEvent<AudioWorkletMessage | ArrayBuffer>) => {
        const data = event.data;
        const pcm =
          data instanceof ArrayBuffer
            ? data
            : data && data.type === 'audio'
              ? data.pcm
              : undefined;
        if (pcm) {
          frameCount += 1;
          if (frameCount === 1 || frameCount % 100 === 0) {
            console.info(`[voice] capture frames=${frameCount} bytes=${pcm.byteLength}`);
          }
          onAudioData(pcm);
        }
      };

      source.connect(captureNode);
      // Keep the worklet graph alive without routing the mic to speakers (feedback).
      const mute = audioContext.createGain();
      mute.gain.value = 0;
      captureNode.connect(mute);
      mute.connect(audioContext.destination);

      console.info('[voice] capture started', {
        contextSampleRate: audioContext.sampleRate,
        targetSampleRate: sampleRate,
        contextState: audioContext.state,
      });

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const checkVolume = () => {
        if (!analyserRef.current) return;
        analyserRef.current.getByteFrequencyData(dataArray);
        const average = dataArray.reduce((a, b) => a + b, 0) / dataArray.length;
        const normalized = average / 255;
        onVolumeChangeRef.current?.(normalized);
        animationFrameRef.current = requestAnimationFrame(checkVolume);
      };
      checkVolume();
    } catch (error) {
      console.error('[voice] failed to start audio capture:', error);
      throw error;
    }
  }, [sampleRate, frameDurationMs, onAudioData]);

  const stop = useCallback(() => {
    if (animationFrameRef.current) {
      cancelAnimationFrame(animationFrameRef.current);
      animationFrameRef.current = null;
    }
    streamRef.current?.getTracks().forEach(track => track.stop());
    streamRef.current = null;
    captureNodeRef.current?.port.close();
    captureNodeRef.current?.disconnect();
    captureNodeRef.current = null;
    audioContextRef.current?.close().catch(() => {});
    audioContextRef.current = null;
    analyserRef.current = null;
  }, []);

  useEffect(() => {
    return () => stop();
  }, [stop]);

  return { start, stop, isActive: !!streamRef.current };
}