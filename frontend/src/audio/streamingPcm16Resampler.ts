export interface StreamingPcm16ResamplerOptions {
  inputSampleRate: number;
  outputSampleRate: number;
}

const INT16_MIN = -32768;
const INT16_MAX = 32767;

function validateSampleRate(name: string, sampleRate: number): void {
  if (!Number.isFinite(sampleRate) || !Number.isInteger(sampleRate) || sampleRate <= 0) {
    throw new RangeError(`${name} must be a positive integer sample rate`);
  }
}

function decodePcm16Sample(lowByte: number, highByte: number): number {
  const value = (highByte << 8) | lowByte;
  return value >= 0x8000 ? value - 0x10000 : value;
}

function clampPcm16Sample(value: number): number {
  const rounded = Math.round(value);
  if (rounded < INT16_MIN) {
    return INT16_MIN;
  }
  if (rounded > INT16_MAX) {
    return INT16_MAX;
  }
  return rounded;
}

export class StreamingPcm16Resampler {
  private readonly outputSampleRate: number;
  private readonly inputSampleRateBigInt: bigint;
  private readonly outputSampleRateBigInt: bigint;
  private readonly passthrough: boolean;

  private danglingByte: number | null = null;
  private lastSample: number | null = null;
  private inputSamplesSeen = 0n;
  private nextOutputSampleIndex = 0n;

  constructor({ inputSampleRate, outputSampleRate }: StreamingPcm16ResamplerOptions) {
    validateSampleRate('inputSampleRate', inputSampleRate);
    validateSampleRate('outputSampleRate', outputSampleRate);

    this.outputSampleRate = outputSampleRate;
    this.inputSampleRateBigInt = BigInt(inputSampleRate);
    this.outputSampleRateBigInt = BigInt(outputSampleRate);
    this.passthrough = inputSampleRate === outputSampleRate;
  }

  pushChunk(chunk: ArrayBuffer): ArrayBuffer | null {
    if (this.passthrough) {
      return this.pushPassthroughChunk(chunk);
    }

    const bytes = new Uint8Array(chunk);
    const outputSamples: number[] = [];
    let offset = 0;

    if (this.danglingByte !== null) {
      if (bytes.byteLength === 0) {
        return null;
      }

      const sample = decodePcm16Sample(this.danglingByte, bytes[0]);
      this.danglingByte = null;
      this.processSample(sample, outputSamples);
      offset = 1;
    }

    const completeByteLength = bytes.byteLength - offset;
    const completeLimit = bytes.byteLength - (completeByteLength % 2);

    for (let index = offset; index < completeLimit; index += 2) {
      const sample = decodePcm16Sample(bytes[index], bytes[index + 1]);
      this.processSample(sample, outputSamples);
    }

    if (completeLimit < bytes.byteLength) {
      this.danglingByte = bytes[bytes.byteLength - 1];
    }

    if (outputSamples.length === 0) {
      return null;
    }

    const output = new Int16Array(outputSamples.length);
    for (let index = 0; index < outputSamples.length; index += 1) {
      output[index] = outputSamples[index];
    }

    return output.buffer;
  }

  reset(): void {
    this.danglingByte = null;
    this.lastSample = null;
    this.inputSamplesSeen = 0n;
    this.nextOutputSampleIndex = 0n;
  }

  private pushPassthroughChunk(chunk: ArrayBuffer): ArrayBuffer | null {
    const bytes = new Uint8Array(chunk);

    if (this.danglingByte === null) {
      if (bytes.byteLength === 0) {
        return null;
      }

      if (bytes.byteLength % 2 === 0) {
        return chunk;
      }

      this.danglingByte = bytes[bytes.byteLength - 1];
      if (bytes.byteLength === 1) {
        return null;
      }

      return chunk.slice(0, bytes.byteLength - 1);
    }

    if (bytes.byteLength === 0) {
      return null;
    }

    const totalByteLength = bytes.byteLength + 1;
    const completeByteLength = totalByteLength - (totalByteLength % 2);
    const output = new Uint8Array(completeByteLength);
    output[0] = this.danglingByte;

    const bytesToCopy = completeByteLength - 1;
    output.set(bytes.subarray(0, bytesToCopy), 1);

    this.danglingByte = completeByteLength < totalByteLength ? bytes[bytesToCopy] : null;

    return output.buffer;
  }

  private processSample(sample: number, outputSamples: number[]): void {
    const currentSampleIndex = this.inputSamplesSeen;

    if (this.lastSample === null) {
      this.lastSample = sample;
      this.inputSamplesSeen += 1n;
      this.emitAvailableSamples(sample, sample, currentSampleIndex, outputSamples);
      return;
    }

    const previousSample = this.lastSample;
    this.lastSample = sample;
    this.inputSamplesSeen += 1n;
    this.emitAvailableSamples(previousSample, sample, currentSampleIndex, outputSamples);
  }

  private emitAvailableSamples(previousSample: number, currentSample: number, currentSampleIndex: bigint, outputSamples: number[]): void {
    const currentBoundary = currentSampleIndex * this.outputSampleRateBigInt;
    const previousBoundary = currentSampleIndex === 0n
      ? 0n
      : (currentSampleIndex - 1n) * this.outputSampleRateBigInt;

    let sourcePosition = this.nextOutputSampleIndex * this.inputSampleRateBigInt;
    while (sourcePosition <= currentBoundary) {
      
      if (sourcePosition === currentBoundary) {
        outputSamples.push(currentSample);
        this.nextOutputSampleIndex += 1n;
        sourcePosition = this.nextOutputSampleIndex * this.inputSampleRateBigInt;
        continue;
      }

      const numerator = Number(sourcePosition - previousBoundary);
      const fraction = numerator / this.outputSampleRate;
      const interpolated = previousSample + (currentSample - previousSample) * fraction;
      outputSamples.push(clampPcm16Sample(interpolated));
      this.nextOutputSampleIndex += 1n;
      sourcePosition = this.nextOutputSampleIndex * this.inputSampleRateBigInt;
    }
  }
}
