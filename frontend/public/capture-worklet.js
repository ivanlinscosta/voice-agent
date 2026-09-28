class CaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const { targetSampleRate = 16000, frameDurationMs = 30 } = options.processorOptions || {};
    this.targetSampleRate = targetSampleRate;
    this.ratio = sampleRate / targetSampleRate;
    this.frameSamplesTarget = Math.round((targetSampleRate * frameDurationMs) / 1000);
    this.inAcc = new Float32Array(0);
    this.pos = 0;
    this.outBuf = [];
  }

  _appendInput(chunk) {
    const merged = new Float32Array(this.inAcc.length + chunk.length);
    merged.set(this.inAcc, 0);
    merged.set(chunk, this.inAcc.length);
    this.inAcc = merged;
  }

  _flush() {
    const int16 = new Int16Array(this.outBuf.length);
    for (let i = 0; i < this.outBuf.length; i++) {
      const s = Math.max(-1, Math.min(1, this.outBuf[i]));
      int16[i] = s < 0 ? s * 32768 : s * 32767;
    }
    this.outBuf = [];
    this.port.postMessage({ type: 'audio', pcm: int16.buffer }, [int16.buffer]);
  }

  process(inputs) {
    const input = inputs[0][0];
    if (input && input.length) {
      this._appendInput(input);
      while (this.pos + 1 < this.inAcc.length) {
        const i0 = Math.floor(this.pos);
        const frac = this.pos - i0;
        const s0 = this.inAcc[i0];
        const s1 = this.inAcc[i0 + 1];
        this.outBuf.push(s0 + (s1 - s0) * frac);
        this.pos += this.ratio;
        if (this.outBuf.length >= this.frameSamplesTarget) {
          this._flush();
        }
      }
      const consumed = Math.floor(this.pos);
      if (consumed > 0) {
        this.inAcc = this.inAcc.slice(consumed);
        this.pos -= consumed;
      }
    }
    return true;
  }
}

registerProcessor('capture-processor', CaptureProcessor);