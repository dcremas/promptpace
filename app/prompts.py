"""The bank of prompt-writing tasks."""

from app.models import Prompt

_TASKS: dict[str, list[str]] = {
    "Home": [
        "Ask an AI to help you plan a kitchen remodel.",
        "Ask an AI to help you organize a cluttered garage over one weekend.",
        "Ask an AI to help you choose between a heat pump and a new furnace.",
        "Ask an AI to design a weekly cleaning schedule for a family of four.",
    ],
    "Work": [
        "Ask an AI to draft an email declining a meeting without sounding rude.",
        "Ask an AI to turn your messy meeting notes into a clear action-item list.",
        "Ask an AI to help you prepare for a salary negotiation.",
        "Ask an AI to write a job description for a junior data analyst.",
        "Ask an AI to help you give constructive feedback to a teammate.",
    ],
    "Travel": [
        "Ask an AI to plan a four-day trip to a city you've never visited.",
        "Ask an AI to build a packing list for a week of camping with kids.",
        "Ask an AI to compare two routes for a cross-country road trip.",
    ],
    "Food": [
        "Ask an AI to plan a week of dinners for someone who is newly vegetarian.",
        "Ask an AI to help you scale a recipe for a party of 25.",
        "Ask an AI to suggest a menu for a dinner party with two picky eaters.",
    ],
    "Money": [
        "Ask an AI to help you build a monthly budget after a job change.",
        "Ask an AI to explain the trade-offs of paying off a car loan early.",
        "Ask an AI to help you compare two health-insurance plans.",
    ],
    "Learning": [
        "Ask an AI to create a 30-day plan for learning basic Spanish.",
        "Ask an AI to explain how vaccines work to a curious ten-year-old.",
        "Ask an AI to quiz you on a topic you're studying, one question at a time.",
    ],
    "Code": [
        "Ask an AI to help you debug a script that runs fine locally but fails on a server.",
        "Ask an AI to review a pull request for security problems.",
        "Ask an AI to write a function that removes duplicate contacts from a spreadsheet.",
        "Ask an AI to explain a confusing error message and suggest fixes.",
    ],
    "Life": [
        "Ask an AI to help you plan a surprise 40th birthday party.",
        "Ask an AI to help you write a heartfelt toast for a friend's wedding.",
        "Ask an AI to create a beginner running plan for a first 5K.",
        "Ask an AI to help you decide whether to adopt a dog or a cat.",
    ],
}


def _slug(text: str) -> str:
    words = "".join(c.lower() if c.isalnum() else " " for c in text).split()
    return "-".join(w for w in words if w not in {"ask", "an", "ai", "to", "a", "the"})[:48]


PROMPTS: dict[str, Prompt] = {
    (p := Prompt(id=_slug(text), category=category, text=text)).id: p
    for category, texts in _TASKS.items()
    for text in texts
}
