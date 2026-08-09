"""Clean-up for model output that is meant to *be* a document, not describe one.

An agent with `output_type=str` is asked for a whole resume and hands back a
whole resume — usually wrapped in a Markdown code fence, because that is how a
chat model presents a long verbatim block. Nothing downstream expects the fence,
and a stored document that starts with ```` ```latex ```` fails to compile on
line 1. Strip it once, here, where every such reply passes through.
"""

import re

#: The whole reply is one fence: opening line, body, closing line, nothing else.
#: Anchored at both ends deliberately — a reply that merely *contains* a fenced
#: block is prose about a document rather than the document, and unwrapping the
#: middle of it would silently discard the rest.
_WHOLE_FENCE = re.compile(
    r"\A\s*```[A-Za-z0-9_+.-]*[ \t]*\r?\n(?P<body>.*?)\r?\n?[ \t]*```\s*\Z",
    re.DOTALL,
)
_FENCE_LINE = re.compile(r"^[ \t]*```", re.MULTILINE)


def strip_code_fence(text: str) -> str:
    """Unwrap a reply that arrived inside a Markdown code fence."""
    match = _WHOLE_FENCE.match(text)
    if match is None:
        return text
    body = match.group("body")
    # Anchoring alone cannot tell one wrapper from several blocks back to back:
    # the outer fences of `a` and `b` also start and end the reply. A fence
    # surviving inside the body means this was never a single wrapper, and
    # returning the text untouched is the safe way to be wrong.
    return text if _FENCE_LINE.search(body) else body
