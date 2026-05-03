"""Lightweight heuristic to decide whether a query question carries enough
personal reflection that we should offer the user the option to also save
it as an entry. Pure regex — no LLM call, zero latency cost.

Returns:
    {
        "score":         float in [0.0, 1.0],
        "should_offer":  bool (True when score > 0.6),
        "signals":       list of matched signal names (for transparency),
    }
"""

import re

# ── First-person presence ────────────────────────────────────────────────
_FIRST_PERSON_EN = re.compile(
    r"\b(I|I'm|I've|I'd|I'll|my|me|myself|mine)\b",
    re.IGNORECASE,
)
_FIRST_PERSON_ZH = re.compile(r"我|自己")

# ── Reflection / feeling verbs ───────────────────────────────────────────
_REFLECTION_VERBS_EN = re.compile(
    r"\b(feel|feels|feeling|felt|think|thought|believe|fear|afraid|worried|"
    r"worry|wonder|sense|notice|realize|realise|doubt|hope|regret|anxious|"
    r"scared|nervous|panic|catastroph)\w*\b",
    re.IGNORECASE,
)
_REFLECTION_VERBS_ZH = re.compile(
    r"觉得|感觉|害怕|担心|恐惧|怀疑|相信|认为|意识到|想到|感到|"
    r"灾难化|焦虑|紧张|惊恐|不安|愧疚|后悔|不甘|纠结|郁闷"
)

# ── Analysis-seeking phrases (turn an utterance from statement → question) ─
_ANALYSIS_PHRASES_EN = re.compile(
    r"(why am i|why do i|how should i|how can i|help me (analyze|analyse|understand)|"
    r"what'?s wrong with me|what should i do)",
    re.IGNORECASE,
)
_ANALYSIS_PHRASES_ZH = re.compile(
    r"怎么办|怎样才能|为什么我|帮我分析|帮我看看|咨询|分析下|"
    r"怎么(才能|改善|破|走出)|如何(才能|改变|改善)"
)


def score_capture_intent(question: str) -> dict:
    """Score how reflective the question is. See module docstring."""
    text = (question or "").strip()
    if not text:
        return {"score": 0.0, "should_offer": False, "signals": []}

    score = 0.0
    signals: list[str] = []

    if _FIRST_PERSON_EN.search(text) or _FIRST_PERSON_ZH.search(text):
        score += 0.30
        signals.append("first_person")

    if _REFLECTION_VERBS_EN.search(text) or _REFLECTION_VERBS_ZH.search(text):
        score += 0.30
        signals.append("reflection_verb")

    if _ANALYSIS_PHRASES_EN.search(text) or _ANALYSIS_PHRASES_ZH.search(text):
        score += 0.20
        signals.append("analysis_seeking")

    if len(text) > 30:
        score += 0.20
        signals.append("substantive_length")

    score = min(score, 1.0)
    return {
        "score":        round(score, 2),
        "should_offer": score > 0.6,
        "signals":      signals,
    }
