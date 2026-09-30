"""Spelling and light mechanics checks for the final text.

The goal is a typing-test style accuracy score for free-form writing, so the
checker is tuned to avoid false positives: it skips anything that looks like
code, a URL, an acronym, an identifier, or a proper noun, and only counts a
word as misspelled when the dictionary has a close suggestion for it. Words
with no close match are reported as "not in dictionary" and not counted.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from itertools import pairwise
from pathlib import Path

from symspellpy import SymSpell, Verbosity

from app.models import Accuracy, IssueKind, TextIssue

EXTRA_WORDS = Path(__file__).parent / "data" / "extra_words.txt"
MAX_EDIT_DISTANCE = 2
MAX_SUGGESTIONS = 3

# Spans that are never spell-checked.
SKIP_SPANS = re.compile(
    r"```.*?(?:```|$)"  # fenced code
    r"|`[^`\n]*`"  # inline code
    r"|\b(?:https?://|www\.)\S+"  # URLs
    r"|\b[\w.+-]+@[\w-]+\.[\w.-]+"  # email addresses
    r"|(?:[\w.-]*[/\\])+[\w.-]+"  # file paths
    r"|\b\w+\.(?:py|js|ts|md|txt|csv|json|ya?ml|html|css|sql|sh|pdf|docx?|xlsx?)\b",  # files
    re.DOTALL | re.IGNORECASE,
)
WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)*")
MISSING_SPACE = re.compile(r"\b([A-Za-z]{2,})([,;!?]|\.(?=[A-Z]))([A-Za-z]+)")
CONTRACTION_SUFFIXES = ("s", "re", "ve", "ll", "d", "m")
NT_STEMS = {"ca", "wo", "sha", "ai"}  # can't, won't, shan't, ain't
ABBREVIATIONS = {"e.g", "i.e", "etc", "vs", "approx", "mr", "mrs", "ms", "dr", "st", "no", "fig"}
COUNTED = (IssueKind.SPELLING,)
NOT_MECHANICS = (IssueKind.SPELLING, IssueKind.UNKNOWN)


@dataclass(slots=True, frozen=True)
class Span:
    start: int
    end: int
    text: str


@cache
def _symspell() -> SymSpell:
    # prefix_length=5 cuts memory ~3x versus the default with no loss in accuracy.
    sym = SymSpell(max_dictionary_edit_distance=MAX_EDIT_DISTANCE, prefix_length=5)
    sym.load_dictionary(str(files("symspellpy") / "frequency_dictionary_en_82_765.txt"), 0, 1)
    return sym


@cache
def _extra_words() -> frozenset[str]:
    lines = (line.strip() for line in EXTRA_WORDS.read_text().splitlines())
    return frozenset(w for w in lines if w and not w.startswith("#"))


def warm() -> None:
    """Load the dictionary up front so the first request isn't slow."""
    _symspell()
    _extra_words()


def check(text: str, user_words: Iterable[str] = (), writing_seconds: float = 0.0) -> Accuracy:
    extra = _extra_words() | {w.lower() for w in user_words}
    skipped = [m.span() for m in SKIP_SPANS.finditer(text)]

    def outside_skipped(start: int) -> bool:
        return not any(s <= start < e for s, e in skipped)

    tokens = [
        Span(m.start(), m.end(), m.group())
        for m in WORD.finditer(text)
        if outside_skipped(m.start())
    ]

    issues: list[TextIssue] = []
    checked = 0
    for tok in tokens:
        if not _should_check(text, tok):
            continue
        checked += 1
        if _is_known(tok.text, extra):
            continue
        if suggestions := _suggest(tok.text):
            issues.append(
                _issue(text, tok, IssueKind.SPELLING, "Possible misspelling", suggestions)
            )
        else:
            issues.append(
                _issue(text, tok, IssueKind.UNKNOWN, "Not in the dictionary, so not counted", [])
            )

    issues += _repeated_words(text, tokens)
    issues += _capitalization(text, tokens)
    issues += [i for i in _missing_spaces(text) if outside_skipped(i.start)]
    issues.sort(key=lambda i: (i.start, i.end))

    misspelled = sum(1 for i in issues if i.kind in COUNTED)
    net_wpm = None
    if writing_seconds >= 1 and text.strip():
        net_wpm = round(max(0.0, (len(text) / 5 - misspelled) / (writing_seconds / 60)), 1)
    return Accuracy(
        words_checked=checked,
        misspelled=misspelled,
        spelling_accuracy=round((checked - misspelled) / checked, 3) if checked else None,
        net_wpm=net_wpm,
        unknown=sum(1 for i in issues if i.kind is IssueKind.UNKNOWN),
        mechanics=sum(1 for i in issues if i.kind not in NOT_MECHANICS),
        issues=issues,
    )


# ---------- spelling ----------


def _should_check(text: str, tok: Span) -> bool:
    word = tok.text
    if len(word) < 2:
        return False
    before = text[tok.start - 1] if tok.start else " "
    after = text[tok.end] if tok.end < len(text) else " "
    after2 = text[tok.end + 1] if tok.end + 1 < len(text) else " "
    # Part of an identifier, number, file name, markup, or function call.
    if before.isdigit() or after.isdigit() or "_" in (before, after) or after == "(":
        return False
    if after == "." and after2.isalpha():
        return False
    if before in "$#@<{[=\\" or after in ">}]=":
        return False
    letters = word.replace("'", "").replace("’", "")
    if letters.isupper():  # acronym: API, SQL, PR
        return False
    if any(c.isupper() for c in letters[1:]):  # camelCase, iPhone, JavaScript
        return False
    # A capitalized word mid-sentence is probably a name, so leave it alone.
    return not (word[0].isupper() and not _starts_sentence(text, tok.start))


def _is_known(word: str, extra: frozenset[str]) -> bool:
    w = word.lower().replace("’", "'")
    if _in_vocab(w, extra):
        return True
    if "'" not in w:
        return False
    base, _, suffix = w.rpartition("'")
    if suffix == "t" and base.endswith("n"):  # don't, can't, won't
        stem = base[:-1]
        return stem in NT_STEMS or _in_vocab(stem, extra)
    return suffix in CONTRACTION_SUFFIXES and _in_vocab(base, extra)


def _in_vocab(w: str, extra: frozenset[str]) -> bool:
    vocab = _symspell().words

    def known(x: str) -> bool:
        return x in vocab or x in extra

    if known(w):
        return True
    # Regular plurals and third-person verbs of any known word.
    if w.endswith("ies") and known(w[:-3] + "y"):
        return True
    if w.endswith("es") and known(w[:-2]):
        return True
    return w.endswith("s") and known(w[:-1])


def _suggest(word: str) -> list[str]:
    lookup = word.lower().replace("’", "'")
    results = _symspell().lookup(lookup, Verbosity.CLOSEST, MAX_EDIT_DISTANCE)
    out = [r.term for r in results[:MAX_SUGGESTIONS]]
    if word[0].isupper():
        out = [s[:1].upper() + s[1:] for s in out]
    return out


# ---------- mechanics ----------


def _repeated_words(text: str, tokens: list[Span]) -> list[TextIssue]:
    issues = []
    for prev, cur in pairwise(tokens):
        if cur.text.lower() == prev.text.lower() and not text[prev.end : cur.start].strip():
            span = Span(prev.start, cur.end, text[prev.start : cur.end])
            issues.append(_issue(text, span, IssueKind.REPEAT, "Repeated word", [prev.text]))
    return issues


def _capitalization(text: str, tokens: list[Span]) -> list[TextIssue]:
    issues = []
    for tok in tokens:
        w = tok.text.replace("’", "'")
        after = text[tok.end : tok.end + 2]
        is_i = w == "i" and not re.match(r"\.[A-Za-z]", after)  # but not "i.e."
        if is_i or re.fullmatch(r"i'(m|ve|d|ll)", w):
            issues.append(
                _issue(text, tok, IssueKind.CAPITALIZATION, "Capitalize “I”", ["I" + tok.text[1:]])
            )
        elif w[0].islower() and _starts_sentence(text, tok.start, strict=True):
            issues.append(
                _issue(
                    text,
                    tok,
                    IssueKind.CAPITALIZATION,
                    "Start the sentence with a capital letter",
                    [tok.text[0].upper() + tok.text[1:]],
                )
            )
    return issues


def _missing_spaces(text: str) -> list[TextIssue]:
    """Catch "done,then" and "done.Then", but not "e.g." or "Node.js"."""
    return [
        _issue(
            text,
            Span(m.start(), m.end(), m.group()),
            IssueKind.SPACING,
            "Add a space after the punctuation",
            [f"{m[1]}{m[2]} {m[3]}"],
        )
        for m in MISSING_SPACE.finditer(text)
    ]


def _starts_sentence(text: str, index: int, *, strict: bool = False) -> bool:
    """True if the word at `index` begins the text, a line, or a sentence.

    With `strict` (used for the capitalization check), a line break doesn't
    count, since lists and notes often start lowercase, and a period after a
    common abbreviation such as "e.g." or "etc." doesn't either.
    """
    j = index - 1
    while j >= 0 and text[j] in " \t\"'“‘(":
        j -= 1
    if j < 0:
        return True
    if text[j] == "\n":
        return not strict
    if text[j] not in ".!?" or j == index - 1:  # "app.py" has no space after the dot
        return False
    if not strict:
        return True
    word_before = re.search(r"([A-Za-z.]+)$", text[:j])
    return not (word_before and word_before.group(1).lower() in ABBREVIATIONS)


def _issue(
    text: str, span: Span, kind: IssueKind, message: str, suggestions: list[str]
) -> TextIssue:
    return TextIssue(
        kind=kind,
        start=_utf16(text, span.start),
        end=_utf16(text, span.end),
        text=span.text,
        message=message,
        suggestions=suggestions,
    )


def _utf16(text: str, index: int) -> int:
    """The browser indexes strings in UTF-16 code units, not code points."""
    return index + sum(1 for c in text[:index] if ord(c) > 0xFFFF)
