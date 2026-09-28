import { useRef, useCallback, useEffect } from 'react';
import { StreamingPcm16Resampler } from '../audio/streamingPcm16Resampler';
import type { AudioWorkletMessage } from '../types';

interface UseAudioPlaybackOptions {
  inputSampleRate?: number;
  bufferSeconds?: number;
}

export function useAudioPlayback({ inputSampleRate = 24000, bufferSeconds = 10 }: UseAudioPlaybackOptions) {
  const audioContextRef = useRef<AudioContext | null>(null);
  const playbackNodeRef = useRef<AudioWorkletNode | null>(null);
  const resamplerRef = useRef<StreamingPcm16Resampler | null>(null);
  const outputSampleRateRef = useRef<number | null>(null);
  const initializePromiseRef = useRef<Promise<void> | null>(null);
  const isPlayingRef = useRef(false);

  const close = useCallback(async () => {
    let initializationError: unknown = null;
    const initializePromise = initializePromiseRef.current;
    if (initializePromise) {
      try {
        await initializePromise;
      } catch (error) {
        initializationError = error;
      }
    }

    resamplerRef.current?.reset();
    resamplerRef.current = null;

    const playbackNode = playbackNodeRef.current;
    playbackNodeRef.current = null;

    if (playbackNode) {
      playbackNode.port.close();
      playbackNode.disconnect();
    }

    const audioContext = audioContextRef.current;
    audioContextRef.current = null;
    outputSampleRateRef.current = null;
    isPlayingRef.current = false;

    if (audioContext) {
      await audioContext.close();
    }

    if (initializationError !== null) {
      throw initializationError;
    }
  }, []);

  const initialize = useCallback(async () => {
    if (audioContextRef.current && playbackNodeRef.current && resamplerRef.current && outputSampleRateRef.current !== null) {
      return;
    }

    if (initializePromiseRef.current) {
      return initializePromiseRef.current;
    }

    const initializePromise = (async () => {
      let audioContext: AudioContext | null = null;
      let playbackNode: AudioWorkletNode | null = null;

      try {
        audioContext = new AudioContext();
        const outputSampleRate = audioContext.sampleRate;
        const resampler = new StreamingPcm16Resampler({
          inputSampleRate,
          outputSampleRate,
        });

        if (audioContext.state === 'suspended') {
          await audioContext.resume();
        }

        await audioContext.audioWorklet.addModule('/playback-worklet.js');

        playbackNode = new AudioWorkletNode(audioContext, 'playback-processor', {
          processorOptions: { bufferSeconds },
        });

        playbackNode.port.onmessage = (event: MessageEvent<AudioWorkletMessage>) => {
          if (event.data.type === 'playbackStart') {
            isPlayingRef.current = true;
            console.info('[voice] playback started');
          } else if (event.data.type === 'playbackStop') {
            isPlayingRef.current = false;
          }
        };

        playbackNode.connect(audioContext.destination);

        audioContextRef.current = audioContext;
        playbackNodeRef.current = playbackNode;
        resamplerRef.current = resampler;
        outputSampleRateRef.current = outputSampleRate;

        console.info('[voice] playback initialized', {
          inputSampleRate,
          outputSampleRate,
          contextState: audioContext.state,
        });
      } catch (error) {
        isPlayingRef.current = false;

        if (playbackNode) {
          playbackNode.port.close();
          playbackNode.disconnect();
        }

        if (audioContext) {
          try {
            await audioContext.close();
          } catch (closeError) {
            console.error('[voice] playback initialization cleanup failed', closeError);
          }
        }

        throw error;
      } finally {
        initializePromiseRef.current = null;
      }
    })();

    initializePromiseRef.current = initializePromise;
    return initializePromise;
  }, [inputSampleRate, bufferSeconds]);

  const play = useCallback((pcm16: ArrayBuffer) => {
    if (!playbackNodeRef.current || !resamplerRef.current) return;

    const resampledPcm16 = resamplerRef.current.pushChunk(pcm16);
    if (!resampledPcm16) return;

    playbackNodeRef.current.port.postMessage({ type: 'audio', pcm: resampledPcm16 }, [resampledPcm16]);
  }, []);

  const clear = useCallback(() => {
    resamplerRef.current?.reset();
    if (playbackNodeRef.current) {
      playbackNodeRef.current.port.postMessage({ type: 'clear' });
    }
    isPlayingRef.current = false;
  }, []);

  const flush = useCallback(() => {
    resamplerRef.current?.reset();
    if (playbackNodeRef.current) {
      playbackNodeRef.current.port.postMessage({ type: 'flush' });
    }
    isPlayingRef.current = false;
  }, []);

  const handoff = useCallback((crossfadeMs: number) => {
    if (!playbackNodeRef.current) return;
    const outputSampleRate = outputSampleRateRef.current;
    if (!outputSampleRate) return;

    const crossfadeSamples = Math.round((outputSampleRate * crossfadeMs) / 1000);
    playbackNodeRef.current.port.postMessage({ type: 'handoff', crossfadeSamples });
  }, []);

  const suspend = useCallback(async () => {
    await audioContextRef.current?.suspend();
  }, []);

  const resume = useCallback(async () => {
    await audioContextRef.current?.resume();
  }, []);

  useEffect(() => {
    return () => {
      void close().catch((error) => {
        console.error('[voice] playback cleanup failed', error);
      });
    };
  }, [close]);

  return {
    initialize,
    play,
    clear,
    flush,
    handoff,
    suspend,
    resume,
    close,
    isPlaying: isPlayingRef.current,
  };
}
