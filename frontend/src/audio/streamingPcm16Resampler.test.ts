import { describe, expect, it } from 'vitest';

import { StreamingPcm16Resampler } from './streamingPcm16Resampler';

function createPcm16Buffer(samples: number[]): ArrayBuffer {
  const pcm16 = new Int16Array(samples.length);
  for (let index = 0; index < samples.length; index += 1) {
    pcm16[index] = samples[index];
  }
  return pcm16.buffer;
}

function readPcm16Samples(buffer: ArrayBuffer | null): number[] {
  if (buffer === null) {
    return [];
  }

  return Array.from(new Int16Array(buffer));
}

function readBytes(buffer: ArrayBuffer | null): number[] {
  if (buffer === null) {
    return [];
  }

  return Array.from(new Uint8Array(buffer));
}

function concatBuffers(buffers: ArrayBuffer[]): ArrayBuffer {
  const totalByteLength = buffers.reduce((sum, buffer) => sum + buffer.byteLength, 0);
  const combined = new Uint8Array(totalByteLength);
  let offset = 0;

  for (const buffer of buffers) {
    combined.set(new Uint8Array(buffer), offset);
    offset += buffer.byteLength;
  }

  return combined.buffer;
}

function collectOutputs(resampler: StreamingPcm16Resampler, chunks: ArrayBuffer[]): ArrayBuffer {
  const outputs: ArrayBuffer[] = [];

  for (const chunk of chunks) {
    const output = resampler.pushChunk(chunk);
    if (output !== null) {
      outputs.push(output);
    }
  }

  return concatBuffers(outputs);
}

function splitBuffer(buffer: ArrayBuffer, byteLengths: number[]): ArrayBuffer[] {
  const bytes = new Uint8Array(buffer);
  const chunks: ArrayBuffer[] = [];
  let offset = 0;

  for (const byteLength of byteLengths) {
    if (offset >= bytes.byteLength) {
      break;
    }

    const end = Math.min(offset + byteLength, bytes.byteLength);
    chunks.push(bytes.slice(offset, end).buffer);
    offset = end;
  }

  if (offset < bytes.byteLength) {
    chunks.push(bytes.slice(offset).buffer);
  }

  return chunks;
}

describe('StreamingPcm16Resampler', () => {
  it('preserves an odd-byte carry across chunk boundaries', () => {
    const resampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 24000 });
    const source = createPcm16Buffer([1000, -1000, 1234]);
    const sourceBytes = new Uint8Array(source);
    const firstChunk = sourceBytes.slice(0, 3).buffer;
    const secondChunk = sourceBytes.slice(3).buffer;

    expect(readBytes(resampler.pushChunk(firstChunk))).toEqual(Array.from(sourceBytes.slice(0, 2)));
    expect(readBytes(resampler.pushChunk(secondChunk))).toEqual(Array.from(sourceBytes.slice(2)));
  });

  it('passes complete PCM16 bytes through unchanged when sample rates match', () => {
    const resampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 24000 });
    const source = createPcm16Buffer([300, -1200, 32767, -32768]);

    const output = resampler.pushChunk(source);

    expect(output).not.toBeNull();
    expect(readBytes(output)).toEqual(readBytes(source));
  });

  it('upsamples 24kHz PCM16 to 48kHz with streaming linear interpolation', () => {
    const resampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 48000 });
    const source = createPcm16Buffer([0, 1000, 2000, 3000]);

    const output = resampler.pushChunk(source);

    expect(readPcm16Samples(output)).toEqual([0, 500, 1000, 1500, 2000, 2500, 3000]);
  });

  it('resamples 24kHz PCM16 to 44.1kHz with deterministic rounding', () => {
    const resampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 44100 });
    const source = createPcm16Buffer([0, 1000, 2000, 3000]);

    const output = resampler.pushChunk(source);

    expect(readPcm16Samples(output)).toEqual([0, 544, 1088, 1633, 2177, 2721]);
  });

  it('produces identical output for merged and arbitrarily split chunks', () => {
    const source = createPcm16Buffer([0, 600, -1200, 3000, -3000, 1200, 2400]);
    const mergedResampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 44100 });
    const splitResampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 44100 });

    const mergedOutput = collectOutputs(mergedResampler, [source]);
    const splitOutput = collectOutputs(splitResampler, splitBuffer(source, [1, 4, 3, 2]));

    expect(readBytes(splitOutput)).toEqual(readBytes(mergedOutput));
  });

  it('preserves interpolation continuity across chunk boundaries', () => {
    const resampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 44100 });
    const chunks = splitBuffer(createPcm16Buffer([0, 1000, 2000]), [2]);

    const firstOutput = resampler.pushChunk(chunks[0]);
    const secondOutput = resampler.pushChunk(chunks[1]);

    expect(readPcm16Samples(firstOutput)).toEqual([0]);
    expect(readPcm16Samples(secondOutput)).toEqual([544, 1088, 1633]);
  });

  it('reset clears fractional state and dangling-byte state', () => {
    const resampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 44100 });
    const source = createPcm16Buffer([0, 1000, 2000]);
    const partialChunks = splitBuffer(source, [3]);

    expect(readPcm16Samples(resampler.pushChunk(partialChunks[0]))).toEqual([0]);

    resampler.reset();

    const afterResetOutput = resampler.pushChunk(source);

    expect(readPcm16Samples(afterResetOutput)).toEqual([0, 544, 1088, 1633]);
  });

  it('emits incrementally with bounded per-chunk output size', () => {
    const samples = Array.from({ length: 64 }, (_, index) => index * 100);
    const source = createPcm16Buffer(samples);
    const oneShotResampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 48000 });
    const streamingResampler = new StreamingPcm16Resampler({ inputSampleRate: 24000, outputSampleRate: 48000 });
    const singleSampleChunks = splitBuffer(source, new Array(samples.length).fill(2));

    const expected = readBytes(oneShotResampler.pushChunk(source));
    const outputs: ArrayBuffer[] = [];
    let maxReturnedBytes = 0;

    for (const chunk of singleSampleChunks) {
      const output = streamingResampler.pushChunk(chunk);
      if (output !== null) {
        outputs.push(output);
        maxReturnedBytes = Math.max(maxReturnedBytes, output.byteLength);
      }
    }

    expect(maxReturnedBytes).toBeLessThanOrEqual(4);
    expect(readBytes(concatBuffers(outputs))).toEqual(expected);
  });
});
