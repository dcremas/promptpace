"""Request and response schemas."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

MAX_EVENTS = 50_000
MAX_TEXT = 20_000


class EventKind(StrEnum):
    TYPE = "type"
    DELETE = "delete"
    PASTE = "paste"


class IssueKind(StrEnum):
    SPELLING = "spelling"
    UNKNOWN = "unknown"
    REPEAT = "repeated_word"
    CAPITALIZATION = "capitalization"
    SPACING = "spacing"


class InputEvent(BaseModel):
    """One edit to the text box, as recorded by the browser."""

    t: Annotated[float, Field(ge=0, description="Milliseconds since the task was shown")]
    kind: EventKind
    added: Annotated[int, Field(ge=0, le=MAX_TEXT)] = 0
    removed: Annotated[int, Field(ge=0, le=MAX_TEXT)] = 0


class SessionIn(BaseModel):
    prompt_id: str
    text: Annotated[str, Field(max_length=MAX_TEXT)]
    events: Annotated[list[InputEvent], Field(min_length=1, max_length=MAX_EVENTS)]
    pause_threshold_ms: Annotated[int, Field(ge=500, le=10_000)] = 2000


class Prompt(BaseModel):
    id: str
    category: str
    text: str


class Summary(BaseModel):
    overall_wpm: float | None
    burst_wpm: float | None
    peak_burst_wpm: float | None
    pause_seconds: float
    pause_share: float
    pause_count: int
    longest_pause_seconds: float
    backspace_count: int
    backspaces_per_100_keys: float
    chars_deleted: int
    deleted_share: float
    time_to_first_key_seconds: float
    writing_seconds: float
    active_seconds: float
    chars_typed: int
    final_chars: int
    final_words: int
    paste_count: int
    chars_pasted: int


class PauseBucket(BaseModel):
    label: str
    count: int
    seconds: float


class Span(BaseModel):
    start_s: float
    end_s: float


class Burst(Span):
    chars: int
    wpm: float | None


class Pause(Span):
    seconds: float


class TimelineBucket(BaseModel):
    start_s: float
    wpm: float
    typed: int
    deleted: int


class Timeline(BaseModel):
    bucket_seconds: int
    buckets: list[TimelineBucket]


class TextIssue(BaseModel):
    kind: IssueKind
    start: int = Field(description="UTF-16 offset into the text, as the browser counts")
    end: int
    text: str
    message: str
    suggestions: list[str]


class Accuracy(BaseModel):
    words_checked: int
    misspelled: int
    spelling_accuracy: float | None
    net_wpm: float | None
    unknown: int
    mechanics: int
    issues: list[TextIssue]


class Analysis(BaseModel):
    pause_threshold_ms: int
    summary: Summary
    accuracy: Accuracy
    pause_buckets: list[PauseBucket]
    bursts: list[Burst]
    pauses: list[Pause]
    timeline: Timeline
    insights: list[str]


class SessionOut(BaseModel):
    id: int
    created_at: str
    prompt: Prompt
    text: str
    analysis: Analysis


class SessionListItem(BaseModel):
    id: int
    created_at: str
    prompt_category: str
    prompt_text: str
    overall_wpm: float | None
    burst_wpm: float | None
    pause_share: float
    backspaces_per_100_keys: float
    spelling_accuracy: float | None
