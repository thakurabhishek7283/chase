r"""Turn a model's description of a template into a config the parser can trust.

The upload pass in `ai/intake.py` produces a *claim* about what a template's
macros mean. This module is what stands between that claim and the document,
and it exists because of a subtlety that is easy to miss:

**The template hash cannot protect this boundary.** `template_hash` is computed
from the same slot map the config produced. If a config wrongly declares the
preamble editable, the hash faithfully excludes the preamble and reports no
drift — it is self-consistently wrong. The hash catches a *splice* that escapes
its span; nothing but the checks here catches a *span* that should never have
existed.

So a proposal has to survive three stages before it is allowed to parse anything
for real:

1. **Static validation** (`SlotConfig.validate`) — the names are real macros, and
   none of them is structural or inline formatting.
2. **It must actually resolve.** The config is used to parse the document. A
   vocabulary that produces no slots described a different resume.
3. **The derived spans must be plausible** — inside the body, free of structural
   commands, and not claiming much more of the document than the built-in shapes
   already find. A config that widens the vocabulary until the template
   disappears into it did not find the content; it lost the template.

Even then the result is marked `confirmed=False`. Passing these checks means a
boundary is not obviously wrong, which is not the same as being right, and only
the author knows which of their lines are facts.
"""

from app.ai.slot_schema import SlotSchema
from app.core.config import get_settings
from app.services.latex.config import BulletMacro, FieldMacro, ListPair, SlotConfig, SlotConfigError
from app.services.latex.model import LatexResume
from app.services.latex.parser import LatexParseError, parse
from app.services.latex.safety import forbidden_command


class SlotDiscoveryError(ValueError):
    """Raised when a proposed slot configuration cannot be trusted with a document."""


def to_slot_config(schema: SlotSchema, section_macros: list[str]) -> SlotConfig:
    """Translate a model's proposal into a validated `SlotConfig`.

    A proposed "bullet macro" that takes more than one argument is silently
    demoted to a field macro rather than rejected. The model has told us
    something useful — where the prose is — and got only the packaging wrong;
    refusing the whole proposal over that would throw away the answer.
    """
    bullets: list[BulletMacro] = []
    fields: list[FieldMacro] = [
        FieldMacro(
            name=macro.name, arity=macro.arity, content_arg=macro.content_arg, label=macro.label
        )
        for macro in schema.field_macros
    ]
    for macro in schema.bullet_macros:
        if macro.arity > 1:
            # Reported as a bullet, but a bullet is reorderable and this one has
            # sibling arguments the renderer would have to invent. The useful
            # half of the answer — which argument holds the prose — survives the
            # demotion; rejecting the proposal outright would discard it.
            fields.append(
                FieldMacro(
                    name=macro.name,
                    arity=macro.arity,
                    content_arg=macro.content_arg,
                    label=macro.name,
                )
            )
        else:
            bullets.append(BulletMacro(name=macro.name))

    # The author's configured section macros are kept alongside anything the
    # model spotted: a template can use \section *and* its own heading macro.
    sections = list(dict.fromkeys([*section_macros, *schema.section_macros]))
    defaults = SlotConfig.default(sections)

    config = SlotConfig(
        section_macros=defaults.section_macros,
        # The built-in shapes are never dropped. A template with a custom bullet
        # macro very often still has a plain itemize somewhere in it.
        environments=tuple(dict.fromkeys([*defaults.environments, *schema.environments])),
        bullet_macros=tuple(dict.fromkeys([*defaults.bullet_macros, *bullets])),
        list_pairs=tuple(
            dict.fromkeys(
                [*defaults.list_pairs, *(ListPair(p.start, p.end) for p in schema.list_pairs)]
            )
        ),
        field_macros=tuple(fields),
        source="discovered",
        confirmed=False,
    )
    try:
        return config.validate()
    except SlotConfigError as exc:
        raise SlotDiscoveryError(f"The proposed slot configuration was rejected: {exc}") from exc


def check_invariants(resume: LatexResume, config: SlotConfig) -> None:
    """Refuse a derived slot map that no correct config could have produced."""
    settings = get_settings()
    body_length = resume.body.end - resume.body.start
    if body_length <= 0:  # pragma: no cover - parse() already rejects an empty body
        raise SlotDiscoveryError("The document body is empty.")

    spans = [group.span for group in resume.groups] + [region.span for region in resume.regions]
    for span in spans:
        if span.start < resume.body.start or span.end > resume.body.end:
            raise SlotDiscoveryError(
                "A proposed slot falls outside \\begin{document}…\\end{document}. "
                "Only the document body holds content."
            )

    # Inferred slots only. An author who wrote a `% jarvis:begin` marker around a
    # \begin{tabular} meant to, and has already taken responsibility for it.
    inferred = [group for group in resume.groups if group.standalone]
    inferred_text = [bullet.latex for group in inferred for bullet in group.bullets]
    inferred_text += [region.latex for region in resume.regions if region.origin == "field"]
    for text in inferred_text:
        if command := forbidden_command(text):
            raise SlotDiscoveryError(
                f"A proposed slot contains the structural command '\\{command}'. "
                "Slots hold prose, not document structure."
            )

    # The ceiling is on what the *proposal* claimed, not on what the document
    # is. A bullet-dense resume can legitimately be two-thirds editable text —
    # the built-in shapes read exactly that and are trusted to. What this catches
    # is a model widening the vocabulary until the template disappeared into it,
    # so the baseline the deterministic parser already finds is subtracted first.
    editable = sum(span.end - span.start for span in spans)
    baseline = _builtin_editable(resume.source, list(config.section_macros))
    claimed = max(0, editable - baseline) / body_length
    if claimed > settings.latex_max_editable_fraction:
        raise SlotDiscoveryError(
            f"The proposed configuration makes {editable / body_length:.0%} of the document "
            f"editable, which is {claimed:.0%} more than the built-in shapes find on their own "
            f"— over the {settings.latex_max_editable_fraction:.0%} ceiling. A resume is mostly "
            "template; a config this broad has lost the boundary rather than found it."
        )


def _builtin_editable(source: str, section_macros: list[str]) -> int:
    """How many characters the built-in shapes alone would call editable.

    Zero when they cannot read the document at all, which is the case automatic
    detection exists for — and the case where every character the proposal
    claims is the proposal's own doing.
    """
    try:
        default = parse(source, SlotConfig.default(section_macros))
    except LatexParseError:
        return 0
    spans = [group.span for group in default.groups] + [r.span for r in default.regions]
    return sum(span.end - span.start for span in spans)
