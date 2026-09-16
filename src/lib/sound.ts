/**
 * Auction room sound, synthesised in the browser.
 *
 * Deliberately NO audio files: every sound here is generated with the Web
 * Audio API. That keeps the repo asset-free and licence-free, makes the
 * sounds tunable in code, and means nothing to load before the first gavel.
 *
 * Browsers refuse to start audio until the user has interacted with the
 * page, so the context is created lazily on the first play() and resumed if
 * suspended -- calling any of these before a click is a harmless no-op
 * rather than a crash.
 */

let ctx: AudioContext | null = null;
let muted = false;

function audio(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (!ctx) {
    const Ctor = window.AudioContext ?? (window as any).webkitAudioContext;
    if (!Ctor) return null;
    ctx = new Ctor();
  }
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

export function setMuted(value: boolean) {
  muted = value;
}

export function isMuted() {
  return muted;
}

/** One shaped oscillator note. */
function tone(
  freq: number,
  duration: number,
  {
    type = 'sine',
    gain = 0.15,
    sweepTo,
    delay = 0,
  }: { type?: OscillatorType; gain?: number; sweepTo?: number; delay?: number } = {},
) {
  const ac = audio();
  if (!ac || muted) return;
  const t0 = ac.currentTime + delay;
  const osc = ac.createOscillator();
  const amp = ac.createGain();

  osc.type = type;
  osc.frequency.setValueAtTime(freq, t0);
  if (sweepTo) osc.frequency.exponentialRampToValueAtTime(sweepTo, t0 + duration);

  // Quick attack, exponential decay -- percussive rather than organ-like.
  amp.gain.setValueAtTime(0.0001, t0);
  amp.gain.exponentialRampToValueAtTime(gain, t0 + 0.012);
  amp.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);

  osc.connect(amp).connect(ac.destination);
  osc.start(t0);
  osc.stop(t0 + duration + 0.05);
}

/** Filtered noise burst -- the "crack" in a gavel, the rustle in a crowd. */
function noise(
  duration: number,
  { gain = 0.2, filterHz = 1800, delay = 0 }: { gain?: number; filterHz?: number; delay?: number } = {},
) {
  const ac = audio();
  if (!ac || muted) return;
  const t0 = ac.currentTime + delay;
  const frames = Math.floor(ac.sampleRate * duration);
  const buffer = ac.createBuffer(1, frames, ac.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < frames; i++) {
    // Fade the noise out across the buffer so it reads as a hit, not a hiss.
    data[i] = (Math.random() * 2 - 1) * (1 - i / frames);
  }
  const src = ac.createBufferSource();
  src.buffer = buffer;

  const filter = ac.createBiquadFilter();
  filter.type = 'lowpass';
  filter.frequency.setValueAtTime(filterHz, t0);

  const amp = ac.createGain();
  amp.gain.setValueAtTime(gain, t0);
  amp.gain.exponentialRampToValueAtTime(0.0001, t0 + duration);

  src.connect(filter).connect(amp).connect(ac.destination);
  src.start(t0);
}

/** A rival (or you) raises the paddle. Rises in pitch as bidding escalates. */
export function playBid(escalation = 0) {
  const base = 420 + Math.min(escalation, 10) * 28;
  tone(base, 0.1, { type: 'triangle', gain: 0.1, sweepTo: base * 1.5 });
}

/** Your own paddle -- brighter and a touch louder, so you can hear it's you. */
export function playMyBid() {
  tone(680, 0.13, { type: 'square', gain: 0.09, sweepTo: 980 });
}

/** Auctioneer's "going once" / "going twice" -- a wooden tick with tension. */
export function playGoing(second = false) {
  noise(0.06, { gain: 0.14, filterHz: 2600 });
  tone(second ? 300 : 260, 0.09, { type: 'triangle', gain: 0.07 });
}

/** Gavel down. Crack, thump, then a short bright confirmation. */
export function playSold() {
  noise(0.09, { gain: 0.45, filterHz: 3200 });
  tone(140, 0.22, { type: 'sine', gain: 0.32, sweepTo: 70 });
  tone(523.25, 0.16, { type: 'triangle', gain: 0.1, delay: 0.1 });
  tone(659.25, 0.16, { type: 'triangle', gain: 0.1, delay: 0.16 });
  tone(783.99, 0.26, { type: 'triangle', gain: 0.11, delay: 0.22 });
}

/** Nobody bid. Flat, dead thud -- deliberately unsatisfying. */
export function playUnsold() {
  noise(0.07, { gain: 0.18, filterHz: 700 });
  tone(150, 0.3, { type: 'sine', gain: 0.16, sweepTo: 96 });
}

/** Crowd reaction for a record-breaking or otherwise notable price. */
export function playGasp() {
  noise(0.55, { gain: 0.1, filterHz: 1100 });
  tone(300, 0.5, { type: 'sine', gain: 0.05, sweepTo: 520 });
}

/** A new player comes under the hammer. */
export function playNextLot() {
  tone(392, 0.1, { type: 'triangle', gain: 0.07 });
  tone(587.33, 0.14, { type: 'triangle', gain: 0.07, delay: 0.07 });
}
