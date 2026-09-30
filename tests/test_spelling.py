import pytest

from app.models import IssueKind
from app.spelling import check

CLEAN_PROMPTS = [
    "Please review this pull request for security problems like SQL injection, XSS, and "
    "hardcoded secrets.",
    "I'm planning a kitchen remodel with a budget of about twenty thousand dollars. We'd like "
    "new cabinets, quartz countertops, and a backsplash.",
    "Can you help me debug a Python script that runs fine locally but fails on the server with "
    "a timeout? It uses async requests and a Postgres database.",
    "Create a beginner running plan for a 5K. I can jog for ten minutes without stopping.",
    "Plan a week of dinners for someone who's newly vegetarian, with a shopping list grouped by "
    "aisle. Don't include mushrooms, and I won't eat tofu.",
    "Help me compare two health-insurance plans: deductibles, copays, out-of-pocket maximums, "
    "and in-network providers.",
    "Summarize the notes into action items with owners and due dates, then flag anything "
    "that's blocked or unassigned, e.g. items waiting on Priya or the vendor.",
    "Here's the error from app.py: `TypeError: 'NoneType' object is not subscriptable`. "
    "See https://example.com/docs/errors or email me at sam.lee@example.com.",
    "Write a function called dedupeContacts that takes a list of rows from contacts_2024.csv "
    "and keeps the newest entry per phone number.",
    "Explain how vaccines work to a curious ten-year-old, using an analogy. Avoid jargon, "
    "i.e. words like antibodies, unless you define them.",
]


@pytest.mark.parametrize("text", CLEAN_PROMPTS)
def test_clean_prompts_have_no_issues(text):
    acc = check(text)
    assert acc.issues == [], [(i.kind, i.text) for i in acc.issues]
    assert acc.spelling_accuracy == 1.0


@pytest.mark.parametrize(
    ("typo", "fix"),
    [
        ("itmes", "items"),
        ("recieve", "receive"),
        ("seperate", "separate"),
        ("definately", "definitely"),
        ("teh", "the"),
        ("remodle", "remodel"),
        ("vegitarian", "vegetarian"),
        ("tommorow", "tomorrow"),
    ],
)
def test_typos_are_flagged_with_the_right_suggestion(typo, fix):
    acc = check(f"Please make a list of {typo} for the project.")
    assert acc.misspelled == 1
    (issue,) = acc.issues
    assert issue.kind is IssueKind.SPELLING
    assert issue.text == typo
    assert issue.suggestions[0] == fix


def test_offsets_point_at_the_word():
    text = "Turn these notes into action itmes please."
    (issue,) = check(text).issues
    assert text[issue.start : issue.end] == "itmes"


def test_offsets_are_utf16_after_emoji():
    text = "Great job 🎉 on the recieve step."
    (issue,) = check(text).issues
    # 🎉 is one code point but two UTF-16 code units, so JS offsets shift by one.
    assert issue.start == text.index("recieve") + 1


def test_sentence_start_capitalized_typo_is_checked_and_keeps_case():
    (issue,) = check("Definately include a budget.").issues
    assert issue.suggestions[0] == "Definitely"


def test_unknown_words_without_suggestions_are_not_counted():
    acc = check("Set up the zxqvbnmw pipeline for me.")
    assert acc.misspelled == 0
    assert acc.unknown == 1
    assert acc.issues[0].kind is IssueKind.UNKNOWN


def test_user_dictionary_words_are_accepted():
    text = "Ask the grpcurl tool about the dispatchr queue."
    acc = check(text)
    assert (acc.misspelled, acc.unknown) == (1, 1)  # dispatchr has a close match; grpcurl doesn't
    assert check(text, user_words=["Dispatchr", "grpcurl"]).issues == []


def test_repeated_word():
    acc = check("Please make the the list shorter.")
    (issue,) = acc.issues
    assert issue.kind is IssueKind.REPEAT
    assert issue.text == "the the"
    assert acc.misspelled == 0  # mechanics issues don't count against spelling


def test_lowercase_i_and_sentence_start():
    kinds = [(i.kind, i.text) for i in check("i think so. then i'm done.").issues]
    assert kinds == [
        (IssueKind.CAPITALIZATION, "i"),
        (IssueKind.CAPITALIZATION, "then"),
        (IssueKind.CAPITALIZATION, "i'm"),
    ]


def test_new_lines_and_abbreviations_do_not_need_capitals():
    text = "Things to pack:\nsocks, e.g. wool ones, etc. and snacks vs. meals."
    assert check(text).issues == []


def test_missing_space_after_punctuation():
    acc = check("Make it short,then send it.Thanks!")
    assert [(i.kind, i.suggestions[0]) for i in acc.issues] == [
        (IssueKind.SPACING, "short, then"),
        (IssueKind.SPACING, "it. Thanks"),
    ]


def test_net_wpm_subtracts_misspellings():
    text = "x" * 250  # 50 "words" typed over one minute
    assert check(text, writing_seconds=60).net_wpm == 50.0
    typo_text = "The recieve and seperate steps. " + "x" * 218
    assert check(typo_text, writing_seconds=60).net_wpm == 48.0


def test_empty_text():
    acc = check("")
    assert acc.words_checked == 0
    assert acc.spelling_accuracy is None
    assert acc.net_wpm is None
