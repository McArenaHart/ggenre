/* Selected audio input only: backing playback is never connected to this input. */
class GGenreCapture extends AudioWorkletProcessor {
  constructor(options = {}) {
    super();
    this.channelSelection = options.processorOptions?.channelSelection || "mix";
    this.start = Infinity; this.end = Infinity; this.armed = false; this.done = false;
    this.block = new Float32Array(4096); this.used = 0; this.meterFrames = 0; this.peak = 0; this.captured = 0;
    this.port.onmessage = ({data}) => {
      if (data.type === "arm") { this.start = data.start; this.end = data.end; this.armed = true; }
      if (data.type === "stop") {
        this.end = Math.min(this.end, data.frame);
        if (this.end <= currentFrame || this.end <= this.start) this.finish();
      }
    };
  }
  flush() {
    if (!this.used) return;
    const samples = this.block.slice(0, this.used);
    this.port.postMessage({type: "chunk", samples}, [samples.buffer]); this.used = 0;
  }
  finish() {
    if (this.done) return;
    this.flush(); this.done = true; this.port.postMessage({type: "done", frames: Math.max(0, Math.min(this.captured, this.end - this.start))});
  }
  process(inputs, outputs) {
    // Output silence: hearing your live microphone causes feedback and distracting delay.
    for (const output of outputs) for (const channel of output) channel.fill(0);
    if (this.done) return false;
    const channels = inputs[0] || [], channel = channels[0];
    const length = outputs[0]?.[0]?.length || channel?.length || 128;
    for (let i = 0; i < length; i++) {
      let value = 0;
      if(this.channelSelection === "right") value = (channels[1] || channel)?.[i] || 0;
      else if(this.channelSelection === "left") value = channel?.[i] || 0;
      else if(channels.length){ for(const samples of channels)value += samples[i] || 0; value /= channels.length; }
      this.peak = Math.max(this.peak, Math.abs(value));
      const frame = currentFrame + i;
      if (this.armed && frame >= this.start && frame < this.end) {
        this.block[this.used++] = value; this.captured++;
        if (this.used === this.block.length) this.flush();
      }
    }
    this.meterFrames += length;
    if (this.meterFrames >= sampleRate / 15) {
      this.port.postMessage({type: "meter", peak: this.peak}); this.peak = 0; this.meterFrames = 0;
    }
    if (this.armed && currentFrame + length >= this.end) this.finish();
    return !this.done;
  }
}
registerProcessor("ggenre-capture", GGenreCapture);
