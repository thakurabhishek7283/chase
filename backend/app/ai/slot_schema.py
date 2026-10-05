r"""What a model is asked to say about an unfamiliar resume template's macros.

The deterministic parser can read any template — but only once it is told which
macros carry prose and which carry facts. For `\item` and `\resumeItem{…}` that
is built in. For the preamble somebody wrote themselves, where bullets live in
`\achievement{…}` and employers in `\cventry{}{}{}{}`, something has to read the
macro definitions and say so.

This module owns the *shape* of that answer and the rules for producing it. It
no longer owns an agent: the question is asked once, as one half of the upload
pass in `ai/intake.py`, because the model that has just worked out what a
template's macros mean is the same one that can see why it does not compile.

**The model returns a vocabulary, not positions.** It never sees a byte offset
and is never asked for one, because a language model cannot count characters and
a wrong offset is a splice into the middle of the document. It answers "`\achievement`
takes one argument and that argument is a bullet"; `services/latex/parser.py`
then finds every call by brace matching, exactly as it always has. Every span in
the system is still computed, never generated.

The second thing it is asked for is the *frozen* half, which matters more than
it looks. A model that lists `\cventry` arguments 1-3 as employer, title and
dates has demonstrated it understood the template; that reasoning is shown to
the author when they confirm the boundary.
"""

from pydantic import BaseModel, Field

#: The rules for reporting a template's vocabulary, composed into the intake
#: prompt in `ai/intake.py`. Kept here, next to the schema they describe, so the
#: instructions and the output type cannot drift apart.
SLOT_VOCABULARY_RULES = """\
Identify the macros that carry CONTENT a tailoring pass may rewrite, and the \
ones that carry FACTS it must never touch.

CONTENT (report these):
- Achievement and responsibility bullets.
- Professional summaries and taglines.
- Skill and technology lists.

FACTS — never report these as content:
- The candidate's name, email, phone, or links.
- Employer names, job titles, locations.
- Any date or date range.
- Degrees, institutions, grades, certification names.

How to report a macro:
- `bullet_macros`: takes exactly ONE argument, and that argument is one bullet. \
Example: `\\newcommand{\\achievement}[1]{\\item #1}` -> name "achievement".
- `field_macros`: takes SEVERAL arguments, and exactly one of them is prose. \
Give `arity` (how many braced arguments it takes in total) and `content_arg` \
(the 1-based index of the prose one). Example: \
`\\newcommand{\\cventry}[4]{...}` used as `\\cventry{Google}{Engineer}{2021--Now}{Built X}` \
-> arity 4, content_arg 4, label "experience". If a macro takes several \
arguments and NONE of them is prose, do not report it at all — list it in \
`frozen_macros` instead.
- `list_pairs`: a macro that opens a bullet list and the macro that closes it.
- `environments`: names of `\\begin{...}` environments holding `\\item` bullets, \
beyond the standard itemize and enumerate.
- `section_macros`: macros that render a section heading.

Hard rules:
- NEVER report a character offset, line number, or position. You are describing \
a vocabulary, not locations. The caller finds every occurrence itself.
- NEVER report a macro whose argument is a date, employer, title, or degree, \
even when it also contains prose. When in doubt, leave it frozen: a missed \
bullet costs the candidate one tailored line, a rewritten employer costs them \
their credibility.
- Only report macros you can actually see used in the document body.
- Report inline formatting (\\textbf, \\emph, \\href, ...) as neither: it is \
markup that appears *inside* slots, never a slot itself.
"""


class ProposedBulletMacro(BaseModel):
    r"""A single-argument macro whose argument is one bullet."""

    name: str = Field(description=r"Macro name without the backslash, e.g. 'achievement'.")
    arity: int = Field(
        default=1, description="Braced arguments the macro takes. A bullet macro takes exactly 1."
    )
    content_arg: int = Field(default=1, description="1-based index of the bullet text.")
    evidence: str = Field(
        default="",
        description="The definition or one use from the document that shows this is a bullet.",
    )


class ProposedFieldMacro(BaseModel):
    r"""A multi-argument macro with exactly one prose argument."""

    name: str = Field(description="Macro name without the backslash, e.g. 'cventry'.")
    arity: int = Field(description="Total number of braced arguments the macro takes.")
    content_arg: int = Field(
        description="1-based index of the argument holding prose. All others stay frozen."
    )
    label: str = Field(
        default="field", description="Short human label for this slot, e.g. 'experience'."
    )
    evidence: str = Field(default="", description="What the other arguments are, briefly.")


class ProposedListPair(BaseModel):
    r"""A macro that opens a bullet list and the one that closes it."""

    start: str = Field(description="Opening macro name without the backslash.")
    end: str = Field(description="Closing macro name without the backslash.")


class SlotSchema(BaseModel):
    """What a model believes this template's macros mean.

    Deliberately contains no spans, offsets, or line numbers — see the module
    docstring. It is a description of the template's vocabulary, and it is worth
    nothing until `services/slot_discovery.py` validates it and the parser
    proves the macros actually resolve to spans.
    """

    bullet_macros: list[ProposedBulletMacro] = Field(default_factory=list)
    field_macros: list[ProposedFieldMacro] = Field(default_factory=list)
    list_pairs: list[ProposedListPair] = Field(default_factory=list)
    environments: list[str] = Field(
        default_factory=list, description="Extra itemize-like environment names."
    )
    section_macros: list[str] = Field(
        default_factory=list, description="Macros that render a section heading."
    )
    frozen_macros: list[str] = Field(
        default_factory=list,
        description="Macros carrying facts — names, employers, titles, dates, degrees.",
    )
    reasoning: str = Field(
        default="",
        description="Two or three sentences on how this template is structured, shown to the author.",
    )


def preamble_end(source: str) -> int:
    r"""Where the preamble stops and the body starts.

    A document with no `\begin{document}` is all preamble as far as this is
    concerned — it will fail to parse a moment later anyway, and treating the
    whole file as definitions is the reading that shows the model most.
    """
    marker = source.find(r"\begin{document}")
    return marker if marker != -1 else len(source)


def build_template_prompt(source: str, cutoff: int, limit: int) -> str:
    """Show the model the macro definitions and as much body as the budget allows.

    The preamble is filtered to its definitions rather than sent whole: font
    setup, colour definitions and geometry are most of its bulk and none of its
    meaning. The body is sent as-is because usage is what disambiguates an
    argument list — a definition alone rarely says which argument is the dates.
    """
    preamble, body = source[:cutoff], source[cutoff:]
    definitions = [
        line
        for line in preamble.splitlines()
        if any(
            token in line
            for token in (
                "newcommand",
                "renewcommand",
                "def\\",
                "DeclareRobustCommand",
                "newenvironment",
            )
        )
    ]
    definition_text = "\n".join(definitions)[:limit] or "(no macro definitions in the preamble)"
    # The full preamble is included after the filtered definitions because the
    # correction half of intake needs to see `\pdfgentounicode` and friends,
    # which are settings rather than definitions and so survive no filter.
    return (
        f"# Macro definitions from the preamble\n```latex\n{definition_text}\n```\n\n"
        f"# Full preamble\n```latex\n{preamble[:limit]}\n```\n\n"
        f"# Document body\n```latex\n{body[:limit]}\n```"
    )
