import type { VoiceModel } from '../types';

export const USD_PER_M_SPEECH_IN = 3;
export const USD_PER_M_SPEECH_OUT = 12;
export const USD_PER_M_TEXT_IN = 0.33;
export const USD_PER_M_TEXT_OUT = 2.75;
export const SPEECH_TOKENS_PER_SEC = 10;
export const GEMINI_AUDIO_TOKENS_PER_SEC = 32;

export function bytesToSeconds(bytes: number, sampleRateBytesPerSec: number): number {
  return bytes / sampleRateBytesPerSec;
}

export interface CostEstimateParams {
  inputAudioBytes: number;
  outputAudioBytes: number;
  inputText: string;
  outputText: string;
  model?: VoiceModel;
}

export function estimateSessionCost({
  inputAudioBytes,
  outputAudioBytes,
  inputText,
  outputText,
  model = 'nova-sonic',
}: CostEstimateParams): number {
  const inputSeconds = bytesToSeconds(inputAudioBytes, 32000);
  const outputSeconds = bytesToSeconds(outputAudioBytes, 48000);

  const speechTokensIn = inputSeconds * (model === 'gemini-live' ? GEMINI_AUDIO_TOKENS_PER_SEC : SPEECH_TOKENS_PER_SEC);
  const speechTokensOut = outputSeconds * (model === 'gemini-live' ? GEMINI_AUDIO_TOKENS_PER_SEC : SPEECH_TOKENS_PER_SEC);

  const textTokensIn = Math.ceil(inputText.length / 4);
  const textTokensOut = Math.ceil(outputText.length / 4);

  const speechInRate = model === 'gemini-live' ? 3.0 : USD_PER_M_SPEECH_IN;
  const speechOutRate = model === 'gemini-live' ? 12.0 : USD_PER_M_SPEECH_OUT;
  const textInRate = model === 'gemini-live' ? 0.5 : USD_PER_M_TEXT_IN;
  const textOutRate = model === 'gemini-live' ? 2.0 : USD_PER_M_TEXT_OUT;

  const cost =
    (speechTokensIn * speechInRate) / 1e6 +
    (speechTokensOut * speechOutRate) / 1e6 +
    (textTokensIn * textInRate) / 1e6 +
    (textTokensOut * textOutRate) / 1e6;

  return cost;
}

export function formatUsd(value: number): string {
  if (value === 0) return 'US$ 0,0000';
  
  // Use Intl.NumberFormat for pt-BR
  const formatter = new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: value < 0.01 ? 4 : 2,
    maximumFractionDigits: value < 0.01 ? 4 : 2,
  });
  
  return formatter.format(value);
}
