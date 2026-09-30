from app.metrics import analyze
from app.models import EventKind, InputEvent


def typing(start_ms: float, chars: int, interval_ms: float) -> list[InputEvent]:
    return [
        InputEvent(t=start_ms + i * interval_ms, kind=EventKind.TYPE, added=1) for i in range(chars)
    ]


def test_steady_typing_has_no_pauses():
    # 300 chars at 200 ms each = 60 WPM (5 keys/s -> 1 word/s).
    events = typing(1000, 300, 200)
    s = analyze(events, "x" * 300).summary
    assert s.pause_count == 0
    assert s.time_to_first_key_seconds == 1.0
    assert s.burst_wpm == 60.0
    # 300 chars over 59.8 s of writing.
    assert s.overall_wpm == 60.2


def test_pause_splits_bursts_and_lowers_overall_only():
    first = typing(0, 100, 200)  # ends at 19.8 s
    second = typing(29_800, 100, 200)  # 10 s gap, then another burst
    a = analyze(first + second, "x" * 200)
    s = a.summary
    assert s.pause_count == 1
    assert s.pause_seconds == 10.0
    assert s.longest_pause_seconds == 10.0
    assert s.burst_wpm == 60.0  # the pause doesn't slow the burst speed
    assert s.overall_wpm == 48.4  # but it does slow overall speed
    assert len(a.bursts) == 2
    assert all(b.wpm == 60.0 for b in a.bursts)
    assert [b.count for b in a.pause_buckets] == [0, 1, 0]


def test_pause_bands_follow_threshold():
    events = typing(0, 50, 200) + typing(9_800 + 6_000, 50, 200)
    bands = analyze(events, "x" * 100, pause_threshold_ms=5000).pause_buckets
    assert [b.label for b in bands] == ["5–15 s", "15 s +"]
    assert [b.count for b in bands] == [1, 0]


def test_threshold_changes_what_counts_as_a_pause():
    events = typing(0, 50, 200) + typing(9_800 + 1_500, 50, 200)  # 1.5 s gap
    assert analyze(events, "x" * 100, pause_threshold_ms=2000).summary.pause_count == 0
    assert analyze(events, "x" * 100, pause_threshold_ms=1000).summary.pause_count == 1


def test_backspaces_are_counted_and_rated():
    events = typing(0, 90, 200)
    events += [InputEvent(t=18_000 + i * 150, kind=EventKind.DELETE, removed=1) for i in range(10)]
    s = analyze(events, "x" * 80).summary
    assert s.backspace_count == 10
    assert s.backspaces_per_100_keys == 10.0
    assert s.chars_deleted == 10
    assert s.deleted_share == round(10 / 90, 3)


def test_paste_is_excluded_from_typing_speed():
    events = typing(0, 50, 200)
    events.append(InputEvent(t=10_000, kind=EventKind.PASTE, added=500))
    s = analyze(events, "x" * 550).summary
    assert s.chars_typed == 50
    assert s.paste_count == 1
    assert s.chars_pasted == 500


def test_single_event_does_not_divide_by_zero():
    a = analyze([InputEvent(t=500, kind=EventKind.TYPE, added=1)], "x")
    assert a.summary.overall_wpm is None
    assert a.summary.burst_wpm is None
    assert len(a.timeline.buckets) == 1


def test_timeline_buckets_cover_session():
    events = typing(0, 600, 200)  # ~2 minutes
    tl = analyze(events, "x" * 600).timeline
    assert len(tl.buckets) <= 90
    assert sum(b.typed for b in tl.buckets) == 600
    assert tl.bucket_seconds == 2


def test_unsorted_events_are_handled():
    events = list(reversed(typing(0, 100, 200)))
    assert analyze(events, "x" * 100).summary.burst_wpm == 60.0
