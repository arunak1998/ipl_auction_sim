"""
The auctioneer's voice: real neural speech (Piper), not the browser's
robotic speechSynthesis.

WHY IT IS BUILT THIS WAY. Piper sounds good but is not fast: a 65-character
phrase measured at ~2.9 seconds on this machine. A bidding war fires a
raise every few hundred milliseconds, so synthesising on demand would fall
hopelessly behind the auction it is narrating.

Auction speech, though, is formulaic -- "<amount> crore, <team>", "going
once", "sold" -- so the VOCABULARY is tiny even though the number of
sentences is not. Every fragment is synthesised once into a cache, and a
line is then assembled by concatenating raw PCM, which costs microseconds.
That is the whole trick: pre-generate ~70 fragments, never synthesise
again.

Falls back silently to no audio if Piper or the voice model is missing, so
the game still runs on a machine that never downloaded them.
"""

from __future__ import annotations

import io
import re
import wave
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
VOICES_DIR = BACKEND_DIR / "voices"
CACHE_DIR = VOICES_DIR / "cache"
MODEL = VOICES_DIR / "en_GB-alan-medium.onnx"

_voice = None
_loaded = False
_fragments: dict[str, bytes] = {}   # phrase -> raw PCM frames
_params: tuple[int, int, int] | None = None  # channels, sampwidth, framerate


def available() -> bool:
    return MODEL.exists()


def _load():
    """Load Piper once, lazily -- importing it costs a second and the game
    should still start on a machine without the model."""
    global _voice, _loaded
    if _loaded:
        return _voice
    _loaded = True
    if not available():
        return None
    try:
        from piper import PiperVoice
        _voice = PiperVoice.load(str(MODEL), config_path=str(MODEL) + ".json")
    except Exception:
        _voice = None
    return _voice


def _cache_path(phrase: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_")[:60]
    return CACHE_DIR / f"{slug}.wav"


def _synthesise_to_cache(phrase: str) -> Path | None:
    path = _cache_path(phrase)
    if path.exists():
        return path
    voice = _load()
    if voice is None:
        return None
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    with wave.open(str(tmp), "wb") as w:
        voice.synthesize_wav(phrase, w)
    tmp.replace(path)
    return path


def _frames(phrase: str) -> bytes:
    """Raw PCM for one fragment, read from cache (synthesising if needed)."""
    global _params
    if phrase in _fragments:
        return _fragments[phrase]
    path = _synthesise_to_cache(phrase)
    if path is None or not path.exists():
        return b""
    with wave.open(str(path), "rb") as r:
        _params = (r.getnchannels(), r.getsampwidth(), r.getframerate())
        data = r.readframes(r.getnframes())
    _fragments[phrase] = data
    return data


def _silence(ms: int) -> bytes:
    if _params is None:
        return b""
    channels, width, rate = _params
    return b"\x00" * int(rate * ms / 1000) * channels * width


def speak_wav(fragments: list[str], gap_ms: int = 60) -> bytes | None:
    """Assemble a line from cached fragments and return a complete WAV.

    Concatenating PCM is what makes this fast enough to narrate a live
    auction -- no model is run here at all once the cache is warm.
    """
    chunks = []
    for i, fragment in enumerate(fragments):
        data = _frames(fragment)
        if not data:
            continue
        if i:
            chunks.append(_silence(gap_ms))
        chunks.append(data)
    if not chunks or _params is None:
        return None

    channels, width, rate = _params
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(b"".join(chunks))
    return buf.getvalue()


# --- the auction's entire vocabulary ------------------------------------

FIXED_PHRASES = [
    "crore", "going once", "going twice", "going thrice", "sold", "unsold",
    "base price", "lot", "and", "to",
    # Display role names (App.tsx's mapRole output). The pool's own roles
    # are cached via lot_vocabulary(); these are the spoken labels, which
    # split Bowler into Fast/Spin.
    "Batsman", "All-Rounder", "Wicketkeeper", "Fast Bowler", "Spin Bowler",
]


def money_fragments(amount: float) -> list[str]:
    """Bid amounts only ever land on the auction's own increments (0.20
    below 2 Cr, 0.50 below 5, 1.00 above), so the set of spoken numbers is
    small enough to pre-generate in full."""
    whole = int(amount)
    frac = int(round((amount - whole) * 100))
    if frac == 0:
        return [str(whole), "crore"]
    return [f"{whole} point {frac // 10 if frac % 10 == 0 else frac}", "crore"]


def bid_vocabulary() -> list[str]:
    """Every number the auction can possibly say."""
    values: set[float] = set()
    v = 0.20
    while v < 2.0:
        values.add(round(v, 2)); v += 0.20
    v = 2.0
    while v < 5.0:
        values.add(round(v, 2)); v += 0.50
    v = 5.0
    while v <= 45.0:
        values.add(round(v, 2)); v += 1.0
    phrases: set[str] = set()
    for value in values:
        for fragment in money_fragments(value):
            phrases.add(fragment)
    return sorted(phrases)


def lot_vocabulary() -> list[str]:
    """Everything needed to announce a LOT in the neural voice: every
    player's name, every role, every country, and every base price.

    620 names is a big cache (~25MB) but it is generated once and it is the
    difference between the auctioneer saying the player's name properly and
    the browser's robotic voice cutting in mid-announcement.
    """
    from rl.data_loader import load_player_pool
    phrases: set[str] = set()
    for player in load_player_pool():
        phrases.add(player.name)
        phrases.add(player.role)
        phrases.add(player.country or "India")
        for fragment in money_fragments(player.base_price_cr):
            phrases.add(fragment)
    return sorted(phrases)


def warm_cache(team_names: list[str], include_lots: bool = True) -> int:
    """Pre-generate every fragment the auctioneer can utter. Run once; after
    that the cache is on disk and startup is instant."""
    phrases = FIXED_PHRASES + bid_vocabulary() + list(team_names)
    if include_lots:
        phrases += lot_vocabulary()
    made = 0
    for phrase in phrases:
        if not _cache_path(phrase).exists():
            if _synthesise_to_cache(phrase):
                made += 1
    return made
