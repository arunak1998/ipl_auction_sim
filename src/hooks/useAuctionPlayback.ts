import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Turns the backend's batched auction events into a paced performance.
 *
 * WHY THIS EXISTS: the backend resolves an entire bidding war in one go and
 * sends the whole batch plus the final state. The UI used to apply all of
 * it instantly, so a seven-round war between two franchises -- the most
 * exciting thing that happens in an auction -- appeared as three lines of
 * text and a number that had already changed. The drama was in the data and
 * the interface was throwing it away.
 *
 * So events are queued and replayed one at a time on a timer. No backend
 * change is needed; the events were always there, they just arrive faster
 * than a human can experience them.
 *
 * The state snapshot is authoritative and is applied only when a batch
 * finishes playing, so the UI can linger on the player still under the
 * hammer while the backend has already moved on.
 */

export interface AuctionEvent {
  type: string;
  team_id?: string;
  player_name?: string;
  amount?: number;
  price_cr?: number;
  /** Synthetic, added by this hook -- not sent by the backend. */
  synthetic?: boolean;
}

export type PlaybackSpeed = 'LIVE' | 'FAST' | 'INSTANT';

/** Milliseconds each event is allowed to breathe, per speed setting. */
const BEAT: Record<PlaybackSpeed, Record<string, number>> = {
  LIVE: { BID: 520, GOING_ONCE: 620, GOING_TWICE: 620, SOLD: 1500, UNSOLD: 950, DEFAULT: 260 },
  FAST: { BID: 240, GOING_ONCE: 260, GOING_TWICE: 260, SOLD: 760, UNSOLD: 460, DEFAULT: 120 },
  INSTANT: { BID: 0, GOING_ONCE: 0, GOING_TWICE: 0, SOLD: 0, UNSOLD: 0, DEFAULT: 0 },
};

interface Batch<S> {
  events: AuctionEvent[];
  state: S;
}

interface Options<S> {
  /** Render one event. Called once per event, in order. */
  onEvent: (event: AuctionEvent) => void;
  /** Apply the authoritative snapshot once a batch has finished playing. */
  onBatchComplete: (state: S) => void;
  speed: PlaybackSpeed;
}

/**
 * The auctioneer's count is REAL now, so nothing is synthesised here.
 *
 * This used to splice a fake GOING_ONCE/GOING_TWICE in front of every SOLD,
 * because the backend settled a lot the instant nobody answered and the
 * hammer would otherwise land with no warning. The auction now runs on a
 * clock (see App.tsx's CLOCK_MS): the count is what actually decides the
 * lot, and a rival can still steal it mid-count -- so faking the beats here
 * would announce a countdown that had already happened.
 */
function withAuctioneerBeats(events: AuctionEvent[]): AuctionEvent[] {
  return events;
}

export function useAuctionPlayback<S>({ onEvent, onBatchComplete, speed }: Options<S>) {
  const queue = useRef<Batch<S>[]>([]);
  const current = useRef<{ events: AuctionEvent[]; state: S } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);

  // Kept in refs so the playback loop always calls the latest closures
  // without needing to restart itself mid-batch.
  const onEventRef = useRef(onEvent);
  const onCompleteRef = useRef(onBatchComplete);
  const speedRef = useRef(speed);
  onEventRef.current = onEvent;
  onCompleteRef.current = onBatchComplete;
  speedRef.current = speed;

  const step = useCallback(() => {
    // Finished the batch in hand? Commit its state, then take the next one.
    if (current.current && current.current.events.length === 0) {
      onCompleteRef.current(current.current.state);
      current.current = null;
    }
    if (!current.current) {
      const next = queue.current.shift();
      if (!next) {
        // Clear the handle BEFORE flipping the flag: enqueue() uses
        // timer.current to decide whether a chain is already running, and
        // the last fired timeout's id is still sitting in it. Leaving it
        // set means the next batch silently never starts playing.
        timer.current = null;
        setIsPlaying(false);
        return;
      }
      current.current = { events: withAuctioneerBeats(next.events), state: next.state };
      // A batch with no events at all is just a state update -- no theatre.
      if (current.current.events.length === 0) {
        onCompleteRef.current(current.current.state);
        current.current = null;
        step();
        return;
      }
    }

    const event = current.current.events.shift()!;
    onEventRef.current(event);

    const beats = BEAT[speedRef.current];
    const delay = beats[event.type] ?? beats.DEFAULT;
    timer.current = setTimeout(step, delay);
  }, []);

  const enqueue = useCallback(
    (batch: Batch<S>) => {
      queue.current.push(batch);
      if (!timer.current) {
        setIsPlaying(true);
        step();
      }
    },
    [step],
  );

  /** Drop the theatre and jump to the end -- applies every pending state. */
  const skip = useCallback(() => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (current.current) {
      for (const event of current.current.events) onEventRef.current(event);
      onCompleteRef.current(current.current.state);
      current.current = null;
    }
    let batch = queue.current.shift();
    while (batch) {
      for (const event of batch.events) onEventRef.current(event);
      onCompleteRef.current(batch.state);
      batch = queue.current.shift();
    }
    setIsPlaying(false);
  }, []);

  // The loop reschedules itself, so isPlaying has to be cleared when the
  // timer chain ends. step() does that; this just guards unmount.
  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
      timer.current = null;
    };
  }, []);

  // step() sets timer.current on every beat; clear it when the chain stops
  // so a later enqueue can start a fresh chain.
  useEffect(() => {
    if (!isPlaying && timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
  }, [isPlaying]);

  return { enqueue, skip, isPlaying, pending: queue.current.length };
}
