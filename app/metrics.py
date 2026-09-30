"""Keystroke-timing analysis.

Everything here is a pure function of the recorded input events, so a stored
session can be re-analyzed later with a different pause threshold.

Definitions (a "word" is the standard 5 characters):

* Overall WPM   - final text length over the time from first to last keystroke.
* Burst WPM     - characters typed while actively typing, over active time only.
                  A gap shorter than the pause threshold counts as active time.
* Pause         - any gap between edits at or above the threshold.
* Backspace     - any deletion edit (Backspace, Delete, word-delete).
"""

from collections.abc import Iterable
from itertools import pairwise
from math import ceil

from app import spelling
from app.models import (
    Accuracy,
    Analysis,
    Burst,
    EventKind,
    InputEvent,
    Pause,
    PauseBucket,
    Summary,
    Timeline,
    TimelineBucket,
)

CHARS_PER_WORD = 5
# A burst needs this much material before its speed is worth reporting.
MIN_BURST_CHARS = 15
MIN_BURST_SECONDS = 2.0
# Timeline bucket widths, picked so a session renders as <= MAX_BUCKETS columns.
BUCKET_STEPS = (1, 2, 3, 5, 10, 15, 30, 60)
MAX_BUCKETS = 90
# Upper edges (seconds) of the pause-length bands; the first band starts at the threshold.
PAUSE_BAND_EDGES = (5.0, 15.0)


def wpm(chars: int, seconds: float) -> float | None:
    if seconds < 1 or chars <= 0:
        return None
    return round(chars / CHARS_PER_WORD / (seconds / 60), 1)


def analyze(
    events: list[InputEvent],
    text: str,
    pause_threshold_ms: int = 2000,
    user_words: Iterable[str] = (),
) -> Analysis:
    events = sorted(events, key=lambda e: e.t)
    threshold = pause_threshold_ms
    first_t = events[0].t
    last_t = events[-1].t
    writing_s = (last_t - first_t) / 1000

    typed = [e for e in events if e.kind is EventKind.TYPE]
    deletes = [e for e in events if e.kind is EventKind.DELETE]
    pastes = [e for e in events if e.kind is EventKind.PASTE]
    chars_typed = sum(e.added for e in typed)
    chars_deleted = sum(e.removed for e in events)

    # Walk consecutive gaps once, splitting the session into bursts and pauses.
    active_ms = 0.0
    burst_chars = 0
    pauses: list[Pause] = []
    bursts: list[Burst] = []
    run_start, run_chars = first_t, 0
    for prev, cur in pairwise(events):
        gap = cur.t - prev.t
        if gap >= threshold:
            pauses.append(_pause(prev.t - first_t, cur.t - first_t))
            bursts.append(_burst(run_start - first_t, prev.t - first_t, run_chars))
            run_start, run_chars = cur.t, 0
            continue
        active_ms += gap
        if cur.kind is EventKind.TYPE:
            burst_chars += cur.added
            run_chars += cur.added
    bursts.append(_burst(run_start - first_t, last_t - first_t, run_chars))

    pause_s = sum(p.seconds for p in pauses)
    peak = max((b.wpm for b in bursts if b.wpm is not None), default=None)
    keystrokes = len(typed) + len(deletes)
    final_chars = len(text)

    summary = Summary(
        overall_wpm=wpm(final_chars, writing_s),
        burst_wpm=wpm(burst_chars, active_ms / 1000),
        peak_burst_wpm=peak,
        pause_seconds=round(pause_s, 1),
        pause_share=round(pause_s / writing_s, 3) if writing_s > 0 else 0.0,
        pause_count=len(pauses),
        longest_pause_seconds=max((p.seconds for p in pauses), default=0.0),
        backspace_count=len(deletes),
        backspaces_per_100_keys=round(100 * len(deletes) / keystrokes, 1) if keystrokes else 0.0,
        chars_deleted=chars_deleted,
        deleted_share=round(chars_deleted / chars_typed, 3) if chars_typed else 0.0,
        time_to_first_key_seconds=round(first_t / 1000, 1),
        writing_seconds=round(writing_s, 1),
        active_seconds=round(active_ms / 1000, 1),
        chars_typed=chars_typed,
        final_chars=final_chars,
        final_words=len(text.split()),
        paste_count=len(pastes),
        chars_pasted=sum(e.added for e in pastes),
    )
    accuracy = spelling.check(text, user_words, writing_s)
    return Analysis(
        pause_threshold_ms=threshold,
        summary=summary,
        accuracy=accuracy,
        pause_buckets=_pause_buckets(pauses, threshold),
        bursts=bursts,
        pauses=pauses,
        timeline=_timeline(events, first_t, writing_s),
        insights=_insights(summary, accuracy),
    )


def _pause(start_ms: float, end_ms: float) -> Pause:
    return Pause(
        start_s=round(start_ms / 1000, 2),
        end_s=round(end_ms / 1000, 2),
        seconds=round((end_ms - start_ms) / 1000, 1),
    )


def _burst(start_ms: float, end_ms: float, chars: int) -> Burst:
    # The first edit of a run has no measured lead-in time, so it is excluded
    # from `chars`; speed is only reported for runs long enough to be stable.
    seconds = (end_ms - start_ms) / 1000
    long_enough = chars >= MIN_BURST_CHARS and seconds >= MIN_BURST_SECONDS
    return Burst(
        start_s=round(start_ms / 1000, 2),
        end_s=round(end_ms / 1000, 2),
        chars=chars,
        wpm=wpm(chars, seconds) if long_enough else None,
    )


def _pause_buckets(pauses: list[Pause], threshold_ms: int) -> list[PauseBucket]:
    lows = [threshold_ms / 1000, *(e for e in PAUSE_BAND_EDGES if e > threshold_ms / 1000)]
    highs = [*lows[1:], float("inf")]
    buckets = []
    for lo, hi in zip(lows, highs, strict=True):
        members = [p for p in pauses if lo <= p.seconds < hi]
        buckets.append(
            PauseBucket(
                label=f"{lo:g}–{hi:g} s" if hi != float("inf") else f"{lo:g} s +",
                count=len(members),
                seconds=round(sum(p.seconds for p in members), 1),
            )
        )
    return buckets


def _timeline(events: list[InputEvent], first_t: float, writing_s: float) -> Timeline:
    step = next((s for s in BUCKET_STEPS if writing_s / s <= MAX_BUCKETS), BUCKET_STEPS[-1])
    count = max(1, ceil(writing_s / step) or 1)
    typed = [0] * count
    deleted = [0] * count
    for e in events:
        i = min(int((e.t - first_t) / 1000 // step), count - 1)
        if e.kind is EventKind.TYPE:
            typed[i] += e.added
        deleted[i] += e.removed
    return Timeline(
        bucket_seconds=step,
        buckets=[
            TimelineBucket(
                start_s=i * step,
                wpm=round(typed[i] / CHARS_PER_WORD / (step / 60), 1),
                typed=typed[i],
                deleted=deleted[i],
            )
            for i in range(count)
        ],
    )


def _insights(s: Summary, acc: Accuracy) -> list[str]:
    notes: list[str] = []
    if s.writing_seconds < 10 or s.chars_typed < 40:
        return ["Write a little more (a few sentences) for the numbers to mean much."]

    pause_pct = round(s.pause_share * 100)
    if s.pause_share >= 0.5:
        notes.append(
            f"You spent {pause_pct}% of your writing time paused. Thinking, not typing, "
            "sets your pace, so typing faster would barely change your total time."
        )
    elif s.pause_share >= 0.25:
        notes.append(
            f"About {pause_pct}% of your time went to pauses. That's a healthy mix of "
            "thinking and typing."
        )
    else:
        notes.append(
            f"Only {pause_pct}% of your time was spent paused. You mostly typed straight "
            "through, so typing speed has a real effect on how long prompts take you."
        )

    if s.burst_wpm and s.active_seconds > 0:
        # Time saved if every active stretch ran 20 WPM faster.
        faster = s.active_seconds * s.burst_wpm / (s.burst_wpm + 20)
        saved = s.active_seconds - faster
        share = round(100 * saved / s.writing_seconds)
        notes.append(
            f"If you typed 20 WPM faster during bursts, this prompt would have taken "
            f"{saved:.0f} s less ({share}% of your writing time)."
        )

    if acc.words_checked >= 15:
        pct = round((acc.spelling_accuracy or 0) * 100)
        if acc.misspelled == 0:
            notes.append("No spelling mistakes were left in your final text.")
        elif pct >= 97:
            notes.append(
                f"{acc.misspelled} misspelled word{'s' if acc.misspelled > 1 else ''} made it "
                f"into your final text ({pct}% accuracy). AI models usually read past small "
                "typos, though they can blur names, numbers, and technical terms."
            )
        else:
            notes.append(
                f"{acc.misspelled} words were misspelled in your final text ({pct}% accuracy). "
                "A quick proofread before you send a prompt is cheaper than a misunderstood "
                "answer."
            )

    if s.backspaces_per_100_keys >= 15:
        notes.append(
            f"You pressed a delete key {s.backspaces_per_100_keys:g} times per 100 keys, so you "
            "revise heavily as you go. You could try getting the whole idea down first, "
            "then editing."
        )
    elif s.backspaces_per_100_keys < 5:
        notes.append("You made very few corrections, so your drafts come out close to final.")

    if s.time_to_first_key_seconds >= 30:
        notes.append(
            f"You thought for {s.time_to_first_key_seconds:.0f} s before your first keystroke. "
            "That time isn't counted in any speed above."
        )
    if s.paste_count:
        notes.append(
            f"{s.chars_pasted} pasted characters were left out of the typing-speed numbers."
        )
    return notes
