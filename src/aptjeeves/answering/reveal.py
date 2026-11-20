from __future__ import annotations

import re
from dataclasses import replace

from aptjeeves.answering.formatter import AnswerResponse
from aptjeeves.retrieval.context import QueryContext

_TOKEN = re.compile(r"CONTACTREF_\d+")


def reveal_contacts(answer: AnswerResponse, context: QueryContext) -> AnswerResponse:
    """Swap CONTACTREF_n tokens for real service-contact values.

    Runs after the LLM and the privacy guardrail, so the numbers never pass
    through either. Unknown tokens are removed rather than left in the text.
    """

    reveals: dict[str, str] = {}
    for fact in context.facts:
        reveals.update(fact.contact_reveals)
    text = _TOKEN.sub(lambda m: reveals.get(m.group(0), "[number unavailable]"), answer.answer)
    return replace(answer, answer=text) if text != answer.answer else answer
