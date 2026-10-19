/**
 * A crowd bed synthesised in the browser: filtered noise with a slow swell, and a roar
 * on goals. No recorded or copyrighted audio is used.
 */
export class Crowd {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private bed: GainNode | null = null;
  private roarGain: GainNode | null = null;
  private muted = false;

  /** Must be called from a user gesture (browsers block audio before one). */
  start() {
    if (this.ctx) {
      void this.ctx.resume();
      return;
    }
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    this.ctx = ctx;
    const len = ctx.sampleRate * 4;
    const buf = ctx.createBuffer(2, len, ctx.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = buf.getChannelData(ch);
      // Brown-ish noise: a murmur rather than a hiss.
      let last = 0;
      for (let i = 0; i < len; i++) {
        last = (last + 0.02 * (Math.random() * 2 - 1)) / 1.02;
        d[i] = last * 3.5;
      }
    }
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.loop = true;
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = 520;
    band.Q.value = 0.6;
    this.master = ctx.createGain();
    this.master.gain.value = this.muted ? 0 : 0.9;
    this.bed = ctx.createGain();
    this.bed.gain.value = 0.35;
    this.roarGain = ctx.createGain();
    this.roarGain.gain.value = 0;
    // A slow LFO so the murmur breathes.
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 0.13;
    const lfoGain = ctx.createGain();
    lfoGain.gain.value = 0.08;
    lfo.connect(lfoGain).connect(this.bed.gain);
    lfo.start();
    src.connect(band);
    band.connect(this.bed).connect(this.master);
    const roarBand = ctx.createBiquadFilter();
    roarBand.type = "bandpass";
    roarBand.frequency.value = 900;
    roarBand.Q.value = 0.5;
    src.connect(roarBand).connect(this.roarGain).connect(this.master);
    this.master.connect(ctx.destination);
    src.start();
  }

  setMuted(m: boolean) {
    this.muted = m;
    if (this.master && this.ctx) this.master.gain.setTargetAtTime(m ? 0 : 0.9, this.ctx.currentTime, 0.08);
  }

  /** Pause the bed while playback is paused. */
  setActive(on: boolean) {
    if (!this.ctx) return;
    if (on) void this.ctx.resume();
    else void this.ctx.suspend();
  }

  roar(strength = 1) {
    if (!this.ctx || !this.roarGain) return;
    const g = this.roarGain.gain;
    const now = this.ctx.currentTime;
    g.cancelScheduledValues(now);
    g.setValueAtTime(g.value, now);
    g.linearRampToValueAtTime(1.6 * strength, now + 0.35);
    g.setTargetAtTime(0.25, now + 2.5, 1.8);
    g.setTargetAtTime(0, now + 8, 1.5);
  }
}
