class PlaybackProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const bufferSeconds = options.processorOptions?.bufferSeconds || 10;
    this.ringBuffer = new Float32Array(sampleRate * bufferSeconds);
    this.writeIndex = 0;
    this.readIndex = 0;
    this.isPlaying = false;
    this.crossfadeRemaining = 0;
    this.crossfadeGain = 0;
    this.handoffBuffer = new Float32Array(0);
    this.prebufferSamples = Math.round(sampleRate * 0.15);
    this.underrunQuanta = 0;
    this.maxUnderrunQuanta = Math.max(1, Math.round((sampleRate * 0.08) / 128));

    this.port.onmessage = (e) => {
      if (e.data.type === 'audio') {
        const pcm16 = new Int16Array(e.data.pcm);
        const free = this.ringBuffer.length - (this.writeIndex - this.readIndex);
        const toWrite = Math.max(0, Math.min(pcm16.length, free));
        for (let i = 0; i < toWrite; i++) {
          this.ringBuffer[this.writeIndex % this.ringBuffer.length] = pcm16[i] / 32768;
          this.writeIndex++;
        }
        this.underrunQuanta = 0;
        const available = this.writeIndex - this.readIndex;
        if (!this.isPlaying && available >= this.prebufferSamples) {
          this.isPlaying = true;
          this.port.postMessage({ type: 'playbackStart' });
        }
      } else if (e.data.type === 'clear' || e.data.type === 'flush') {
        this.writeIndex = 0;
        this.readIndex = 0;
        this.isPlaying = false;
        this.crossfadeRemaining = 0;
        this.handoffBuffer = new Float32Array(0);
        this.underrunQuanta = 0;
        if (e.data.type === 'clear') {
          this.port.postMessage({ type: 'playbackStop' });
        }
      } else if (e.data.type === 'handoff') {
        const crossfadeSamples = e.data.crossfadeSamples || 0;
        if (crossfadeSamples > 0) {
          const available = this.writeIndex - this.readIndex;
          const handoffSize = Math.min(available, crossfadeSamples);
          this.handoffBuffer = new Float32Array(handoffSize);
          for (let i = 0; i < handoffSize; i++) {
            this.handoffBuffer[i] = this.ringBuffer[(this.readIndex + i) % this.ringBuffer.length];
          }
          this.crossfadeRemaining = handoffSize;
          this.crossfadeGain = 1;
        }
      }
    };
  }

  process(inputs, outputs) {
    const output = outputs[0]?.[0];
    if (!output) return true;

    const available = this.writeIndex - this.readIndex;
    const samplesToRead = Math.min(available, output.length);

    if (samplesToRead > 0) {
      this.underrunQuanta = 0;
      for (let i = 0; i < samplesToRead; i++) {
        let sample = this.ringBuffer[this.readIndex % this.ringBuffer.length];

        if (this.crossfadeRemaining > 0 && i < this.handoffBuffer.length) {
          const handoffSample = this.handoffBuffer[i];
          sample = sample * this.crossfadeGain + handoffSample * (1 - this.crossfadeGain);
          this.crossfadeGain = Math.max(0, this.crossfadeGain - 1 / this.crossfadeRemaining);
          this.crossfadeRemaining--;
        }

        output[i] = sample;
        this.readIndex++;
      }
      for (let i = samplesToRead; i < output.length; i++) {
        output[i] = 0;
      }
    } else if (this.isPlaying) {
      this.underrunQuanta += 1;
      if (this.underrunQuanta > this.maxUnderrunQuanta) {
        this.isPlaying = false;
        this.underrunQuanta = 0;
        this.port.postMessage({ type: 'playbackStop' });
      }
    }

    return true;
  }
}

registerProcessor('playback-processor', PlaybackProcessor);
