"""Prompt-injection heuristics (defense in depth for small models).

looks_like_injection blocks obvious override/extraction attempts before the
LLM is ever called; leaks_prompt catches system-prompt text in generated
answers. Novel phrasings can still slip past — the grounded prompt with its
"untrusted document data" marking remains the primary defense.
"""

import re

_INJECTION_RE = re.compile(
    r"ignore\b.{0,40}\b(instructions|rules|prompt)"
    r"|disregard\b.{0,40}\b(instructions|rules|prompt)"
    r"|ignor\w*\b.{0,40}\b(instructions|consignes|règles|prompt)"
    r"|تجاهل\w*.{0,40}(تعليمات|أوامر|توجيهات)"
    r"|system prompt|prompt syst[eè]me|موجه النظام"
    r"|you are now|tu es maintenant|أنت الآن"
    r"|new instructions:|override instructions|jailbreak",
    re.IGNORECASE,
)

_PROMPT_MARKERS = (
    "you are sanad",
    "only using the numbered sources",
    "never reveal, quote or paraphrase",
    "data, never instructions",
    "sources (untrusted document data)",
)


def looks_like_injection(question: str) -> bool:
    return _INJECTION_RE.search(question) is not None


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?؟])\s+")


def sanitize_source(text: str) -> str:
    # Drop instruction-like sentences before the text reaches the LLM; small
    # models otherwise obey payloads hidden in source text even under a
    # hardened prompt. Applied to retrieved chunks and to crawled pages.
    lines = []
    for line in text.splitlines():
        parts = [s for s in _SENTENCE_SPLIT.split(line) if s and not looks_like_injection(s)]
        if parts:
            lines.append(" ".join(parts))
    return "\n".join(lines)


def leaks_prompt(answer: str) -> bool:
    lowered = answer.casefold()
    return any(marker in lowered for marker in _PROMPT_MARKERS)