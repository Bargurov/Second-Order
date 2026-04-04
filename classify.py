# classify.py
# Keyword-based classification of geopolitical event headlines.
# Extracted from main.py so it can be imported without pulling in
# the full pipeline (analyze_event, market_check, db).

import re


def _matches_any(words: list[str], text: str) -> bool:
    """Return True if any word/phrase matches as a whole word in text.

    Uses word boundaries so 'expected' does not fire inside 'unexpectedly'.
    """
    return any(re.search(r'\b' + re.escape(word) + r'\b', text) for word in words)


def classify_stage(headline: str) -> str:
    """Classify the headline's event stage with simple keyword checks.

    Priority order matters: anticipation is checked first so hedging verbs
    like 'considers' beat out nouns like 'sanction' that appear lower down.
    'sanction' is intentionally NOT in escalation — the word alone is neutral
    (imposing vs. easing are opposites), so it falls through to 'realized'.
    'talks' is in anticipation, not normalization — talks starting means
    nothing is resolved yet. 'resume/reopen' still covers normalization.

    Example classifications:
      "US considers easing sanctions on Venezuelan oil exports"   -> anticipation
      "US may impose new tariffs on Chinese goods next month"     -> anticipation
      "White House proposal would ease chip export restrictions"  -> anticipation
      "US and China hold trade talks in Geneva"                   -> anticipation
      "Fed expected to cut rates in September"                    -> anticipation
      "Russia launches missile strikes on Ukrainian energy grid"  -> escalation
      "Iran retaliates with drone attack on US base in Iraq"      -> escalation
      "Israel and Hamas reach ceasefire agreement"                -> de-escalation
      "US and China resume diplomatic ties after two-year freeze" -> normalization
      "US imposes sweeping new sanctions on Iranian banks"        -> realized
    """
    text = headline.lower()

    # Hedging verbs, uncertainty markers, and unresolved processes —
    # something hasn't happened yet, or is still being negotiated
    anticipation_words = [
        "may", "could", "might", "expected", "possible", "threat",
        "considers", "considering", "mulls", "weighs", "eyes",
        "plans to", "set to", "likely to", "warns", "at risk",
        "proposal", "proposed", "talks", "negotiations",
    ]

    # Unambiguously aggressive actions — something bad is actively happening
    # Full word forms are listed explicitly so _matches_any word boundaries work correctly.
    # (Stems like "retaliat" broke "retaliatory" once word-boundary matching was added.)
    escalation_words = [
        "attack", "strikes", "retaliates", "retaliated", "retaliation", "retaliatory",
        "invades", "invaded", "invasion", "bombs", "missile",
        "shoots down", "seizes", "expels", "escalates", "escalated", "escalation",
    ]

    deescalation_words = ["ceasefire", "truce", "deal", "agreement"]
    # Full forms listed explicitly for the same reason as escalation_words above.
    normalization_words = [
        "resume", "resumes", "resumed",
        "reopen", "reopens", "reopened",
        "restart", "restarts", "restarted",
        "normalize", "normalized",
        "restored",
    ]

    # Compound pre-check: "resume/reopen/... + talks/negotiations" → normalization wins.
    # Without this, 'talks' (anticipation) would fire before 'resume' (normalization)
    # because anticipation is checked first in the priority chain below.
    talks_words = ["talks", "negotiations"]
    if _matches_any(normalization_words, text) and _matches_any(talks_words, text):
        return "normalization"

    # Anticipation is checked first — a hedging verb overrides everything else
    if _matches_any(anticipation_words, text):
        return "anticipation"
    if _matches_any(deescalation_words, text):
        return "de-escalation"
    if _matches_any(normalization_words, text):
        return "normalization"
    if _matches_any(escalation_words, text):
        return "escalation"
    return "realized"


def classify_persistence(headline: str) -> str:
    """Classify how long the headline's effects may last."""
    text = headline.lower()

    structural_words = [
        "policy", "law", "ban", "tariff", "sanction", "export control",
        "restrict", "subsidy", "premium", "investment control",
        "industrial policy", "nationalize", "quota", "embargo",
    ]
    transient_words = ["comment", "warning", "rumor", "meeting", "tweet"]
    medium_words = ["talks", "ceasefire", "deal", "strike", "attack"]

    if any(word in text for word in structural_words):
        return "structural"
    if any(word in text for word in transient_words):
        return "transient"
    if any(word in text for word in medium_words):
        return "medium"
    return "medium"
