"""Dependency-free language guess for assistant replies, by counting distinctive stopwords.

A heuristic, good enough for short replies in the three languages the datasets use; words
shared by two languages (e.g. "con", "una") are left out so they cannot tip the count.
"""

import re

from tests.evals.harness.cases import Language

STOPWORDS: dict[Language, frozenset[str]] = {  # Distinctive function words per language
    "it": frozenset(
        "il gli che per non sono ecco questa questo della delle dei ho più anche come brani "
        "canzoni vuoi puoi ciao grazie perfetto ti ecco ed nel alla".split()
    ),
    "en": frozenset(
        "the and you your with for this that here is are it of to songs tracks would like "
        "what great some playlist's i'm i've let me".split()
    ),
    "es": frozenset(
        "el los las que para y es aquí tu canciones quieres puedes hola gracias esta este "
        "del muy más pero como una lista temas".split()
    ),
}
WORD_RE = re.compile(r"[a-zà-ÿ']+")  # Lowercase words, accents and apostrophes included


def detect_language(text: str) -> Language | None:
    """Guess the language of a reply.

    Args:
        text: The assistant message.

    Returns:
        The language with the most stopword hits, or None on no hits or a tie.
    """
    words = WORD_RE.findall(text.lower())
    hits = {lang: sum(word in stop for word in words) for lang, stop in STOPWORDS.items()}
    ranked = sorted(hits.items(), key=lambda item: item[1], reverse=True)
    best, runner_up = ranked[0], ranked[1]
    return best[0] if best[1] > runner_up[1] else None
