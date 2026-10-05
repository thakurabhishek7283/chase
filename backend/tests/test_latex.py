import pytest

from app.ai.review import REVIEW_SYSTEM_PROMPT, build_outline
from app.ai.schemas import ResumeTailoring, TailoredGroup, TailoredRegion
from app.ai.slot_schema import ProposedBulletMacro, ProposedFieldMacro, SlotSchema
from app.services.latex import (
    BulletMacro,
    FieldMacro,
    GroupEdit,
    LatexParseError,
    LatexRenderError,
    RegionEdit,
    SlotConfig,
    SlotConfigError,
    Span,
    StaleEditError,
    TemplateDriftError,
    UnsafeLatexError,
    parse,
    render,
    slot_hashes,
    template_hash,
    to_markdown,
)
from app.services.latex.fingerprint import frozen_chunks
from app.services.latex.safety import (
    braces_balanced,
    coerce_fragment,
    escape_text,
    validate_fragment,
)
from app.services.slot_discovery import (
    SlotDiscoveryError,
    check_invariants,
    to_slot_config,
)
from app.services.tailoring import apply_tailoring

#: Every `parse()` in this file goes through the built-in shapes; the
#: configurable ones get their own section at the bottom.
SECTION_MACROS = SlotConfig.default(["section", "subsection"])

MASTER = r"""\documentclass[letterpaper,11pt]{article}
\usepackage[margin=0.6in]{geometry}
\usepackage{enumitem}

% A commented-out list must not confuse the environment scanner:
% \begin{itemize} \item ignore me \end{itemize}

\begin{document}

\begin{center}\textbf{\Huge Ada Lovelace}\end{center}

\section{Skills}
% jarvis:begin skills
\textbf{Languages}: Python, Go, SQL
% jarvis:end

\section{Experience}
\textbf{Senior Engineer}, Acme Corp \hfill 2021 -- Present
\begin{itemize}[leftmargin=0.2in]
    \item Designed a \textbf{multi-tenant} pipeline handling 40k events/sec.
    \item Cut p99 latency by 38\% using a work queue.
    \item Mentored four engineers.
\end{itemize}

\section{Education}
\textbf{B.Tech}, State University \hfill 2018

\end{document}
"""

JAKES_STYLE = r"""\documentclass{article}
\newcommand{\resumeItem}[1]{\item\small{#1}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}}
\begin{document}
\section{Experience}
\resumeItemListStart
    \resumeItem{Built a distributed scheduler in Go.}
    \resumeItem{Reduced build times by 60\%.}
\resumeItemListEnd
\end{document}
"""


def _parsed():
    return parse(MASTER, SECTION_MACROS)


# --- parsing -----------------------------------------------------------------


def test_parse_finds_bullets_and_marked_regions() -> None:
    resume = _parsed()

    assert [s.heading for s in resume.sections] == [
        "Header",
        "Skills",
        "Experience",
        "Education",
    ]
    assert len(resume.groups) == 1
    assert resume.bullet_count == 3
    assert len(resume.regions) == 1
    assert resume.regions[0].label == "skills"
    assert "Python, Go, SQL" in resume.regions[0].latex


def test_education_and_header_are_frozen() -> None:
    # Degrees and dates are facts. Tailoring must have no handle on them.
    resume = _parsed()
    frozen = [s.heading for s in resume.sections if not s.is_editable]
    assert frozen == ["Header", "Education"]


def test_commented_out_environment_is_ignored() -> None:
    # The preamble comment contains a full itemize; masking must hide it.
    resume = _parsed()
    assert all("ignore me" not in b.latex for g in resume.groups for b in g.bullets)


def test_parse_supports_macro_delimited_lists() -> None:
    resume = parse(JAKES_STYLE, SECTION_MACROS)
    assert len(resume.groups) == 1
    group = resume.groups[0]
    assert group.prefix == r"\resumeItem{"
    assert group.suffix == "}"
    assert [b.latex for b in group.bullets] == [
        "Built a distributed scheduler in Go.",
        r"Reduced build times by 60\%.",
    ]


def test_parse_rejects_a_fragment() -> None:
    with pytest.raises(LatexParseError, match=r"begin\{document\}"):
        parse(r"\section{Experience} \begin{itemize}\item hi\end{itemize}", SECTION_MACROS)


def test_parse_rejects_a_document_with_nothing_editable() -> None:
    with pytest.raises(LatexParseError, match="No editable content"):
        parse(
            r"\documentclass{article}\begin{document}\section{X}Just prose.\end{document}",
            SECTION_MACROS,
        )


def test_parse_rejects_an_unclosed_marker() -> None:
    source = MASTER.replace("% jarvis:end", "", 1)
    with pytest.raises(LatexParseError, match="no matching"):
        parse(source, SECTION_MACROS)


# --- rendering ---------------------------------------------------------------


def test_no_op_render_is_byte_identical() -> None:
    # The core guarantee: untouched content cannot drift.
    assert render(_parsed()) == MASTER


def test_render_preserves_everything_outside_the_edited_spans() -> None:
    resume = _parsed()
    tailored = render(resume, group_edits=[GroupEdit("g1", ["Rewrote it in Rust."])])

    assert tailored[: resume.body.start] == MASTER[: resume.body.start]
    assert r"\usepackage[margin=0.6in]{geometry}" in tailored
    assert r"\textbf{Senior Engineer}, Acme Corp \hfill 2021 -- Present" in tailored
    assert r"\textbf{B.Tech}, State University \hfill 2018" in tailored


def test_render_preserves_the_list_optional_argument() -> None:
    # Regression: `\begin{itemize}[leftmargin=0.2in]` must keep its option, or
    # every tailored resume silently changes indentation.
    tailored = render(_parsed(), group_edits=[GroupEdit("g1", ["One bullet."])])
    assert r"\begin{itemize}[leftmargin=0.2in]" in tailored


def test_render_can_reorder_drop_and_add_bullets() -> None:
    tailored = render(
        _parsed(),
        group_edits=[GroupEdit("g1", ["Mentored four engineers.", "A brand new bullet."])],
    )
    # Search from \begin{document}: the preamble holds a commented-out itemize.
    doc = tailored.index(r"\begin{document}")
    body = tailored[tailored.index(r"\begin{itemize}", doc) : tailored.index(r"\end{itemize}", doc)]

    assert body.count(r"\item ") == 2
    assert body.index("Mentored") < body.index("brand new")
    assert "40k events" not in body


def test_render_uses_the_documents_own_item_idiom() -> None:
    resume = parse(JAKES_STYLE, SECTION_MACROS)
    tailored = render(resume, group_edits=[GroupEdit("g1", ["Wrote Rust.", "Wrote more Rust."])])
    assert tailored.count(r"\resumeItem{Wrote") == 2
    assert r"\item " not in tailored


def test_render_replaces_a_marked_region() -> None:
    tailored = render(
        _parsed(), region_edits=[RegionEdit("r1", r"\textbf{Languages}: Rust, Python")]
    )
    assert r"\textbf{Languages}: Rust, Python" in tailored
    assert "Go, SQL" not in tailored
    # The markers themselves survive so the document stays re-tailorable.
    assert "% jarvis:begin skills" in tailored
    assert "% jarvis:end" in tailored


def test_render_keeps_the_original_list_when_every_bullet_is_dropped() -> None:
    # An empty itemize is a LaTeX error; a bulletless section is never intended.
    tailored = render(_parsed(), group_edits=[GroupEdit("g1", [])])
    assert tailored == MASTER


def test_render_rejects_an_unknown_slot_id() -> None:
    with pytest.raises(LatexRenderError, match="Unknown bullet group"):
        render(_parsed(), group_edits=[GroupEdit("g99", ["nope"])])


def test_render_output_reparses() -> None:
    # A tailored resume must itself be a valid master, or the version tree
    # breaks after one generation.
    tailored = render(_parsed(), group_edits=[GroupEdit("g1", ["Shipped Rust services."])])
    assert parse(tailored, SECTION_MACROS).bullet_count == 1


# --- fingerprints ------------------------------------------------------------


def test_template_hash_ignores_content_but_not_scaffolding() -> None:
    resume = _parsed()
    tailored = render(resume, group_edits=[GroupEdit("g1", ["Something else entirely."])])

    # Rewriting every bullet leaves the template hash alone...
    assert template_hash(parse(tailored, SECTION_MACROS)) == template_hash(resume)
    # ...but touching a single byte of the frozen half does not.
    drifted = MASTER.replace("margin=0.6in", "margin=0.4in")
    assert template_hash(parse(drifted, SECTION_MACROS)) != template_hash(resume)


def test_frozen_chunks_exclude_every_editable_slot() -> None:
    frozen = "".join(frozen_chunks(_parsed()))

    assert r"\usepackage[margin=0.6in]{geometry}" in frozen
    assert r"\textbf{B.Tech}, State University" in frozen
    assert "Mentored four engineers." not in frozen
    assert "Python, Go, SQL" not in frozen


def test_slot_hash_survives_rewrapping_but_not_rewording() -> None:
    # Reflowing a long \item across two lines is an editing habit, not an edit.
    rewrapped = MASTER.replace(
        r"    \item Mentored four engineers.",
        "    \\item Mentored\n        four engineers.",
    )
    assert slot_hashes(parse(rewrapped, SECTION_MACROS)) == slot_hashes(_parsed())

    reworded = MASTER.replace("Mentored four engineers.", "Mentored five engineers.")
    assert slot_hashes(parse(reworded, SECTION_MACROS)) != slot_hashes(_parsed())


def test_group_hash_changes_when_its_bullets_are_reordered() -> None:
    # A group-level edit competes with a reorder, so a reorder must invalidate it.
    resume = _parsed()
    reordered = render(
        resume,
        group_edits=[GroupEdit("g1", [b.latex for b in reversed(resume.groups[0].bullets)])],
    )
    assert parse(reordered, SECTION_MACROS).groups[0].content_hash != resume.groups[0].content_hash


def test_render_rejects_an_edit_written_against_stale_content() -> None:
    # The hazard this exists for: ids are positional, so an edit generated
    # against an older master would otherwise splice into whatever 'g1' is now.
    stale = slot_hashes(_parsed())
    edited_master = MASTER.replace("Mentored four engineers.", "Mentored a whole team.")

    with pytest.raises(StaleEditError, match="has changed since"):
        render(
            parse(edited_master, SECTION_MACROS),
            group_edits=[GroupEdit("g1", ["Shipped Rust."])],
            base_hashes=stale,
        )


def test_render_accepts_an_edit_whose_hashes_still_match() -> None:
    resume = _parsed()
    tailored = render(
        resume,
        group_edits=[GroupEdit("g1", ["Shipped Rust."])],
        region_edits=[RegionEdit("r1", r"\textbf{Languages}: Rust")],
        base_hashes=slot_hashes(resume),
    )
    assert "Shipped Rust." in tailored


def test_render_applies_slots_the_caller_supplied_no_hash_for() -> None:
    # A partial map must not be read as "everything else is stale".
    resume = _parsed()
    tailored = render(
        resume,
        group_edits=[GroupEdit("g1", ["Shipped Rust."])],
        base_hashes={"r1": resume.regions[0].content_hash},
    )
    assert "Shipped Rust." in tailored


def test_template_drift_is_caught_and_the_output_discarded() -> None:
    # Simulate the bug the check exists for: a span computed one byte too wide,
    # so the splice eats the \end{itemize} that closes the list.
    resume = _parsed()
    group = resume.groups[0]
    group.span = Span(group.span.start, group.span.end + len(r"\end{itemize}"))

    with pytest.raises(TemplateDriftError):
        render(resume, group_edits=[GroupEdit("g1", ["One bullet."])])


# --- configurable templates ---------------------------------------------------

#: A template the built-in shapes cannot read: no itemize, no \resumeItem, and
#: the employer/title/dates arriving as arguments to a custom macro.
CUSTOM = r"""\documentclass{article}
\newcommand{\achievement}[1]{\item #1}
\newcommand{\cventry}[4]{\textbf{#1} \hfill #3 \\ \textit{#2} \\ #4}
\begin{document}
\section{Experience}
\cventry{Acme Corp}{Senior Engineer}{2021 -- Present}{Led the platform team.}
    \achievement{Designed a multi-tenant pipeline handling 40k events/sec.}
    \achievement{Cut p99 latency by 38\% using a work queue.}
\section{Education}
\textbf{B.Tech}, State University \hfill 2018
\end{document}
"""

CUSTOM_CONFIG = SlotConfig(
    section_macros=("section",),
    bullet_macros=(BulletMacro("achievement"),),
    field_macros=(FieldMacro("cventry", arity=4, content_arg=4, label="experience"),),
)


def test_builtin_shapes_cannot_read_a_custom_template() -> None:
    # The gap the whole slot-config feature exists to close.
    with pytest.raises(LatexParseError, match="No editable content"):
        parse(CUSTOM, SECTION_MACROS)


def test_config_finds_standalone_runs_and_field_arguments() -> None:
    resume = parse(CUSTOM, CUSTOM_CONFIG)

    assert resume.bullet_count == 2
    group = resume.groups[0]
    assert group.standalone
    assert [b.latex for b in group.bullets] == [
        "Designed a multi-tenant pipeline handling 40k events/sec.",
        r"Cut p99 latency by 38\% using a work queue.",
    ]
    assert [(r.label, r.latex, r.origin) for r in resume.regions] == [
        ("experience", "Led the platform team.", "field")
    ]


def test_a_field_macro_freezes_every_argument_it_did_not_name() -> None:
    # The truthfulness guarantee for custom templates: naming argument 4 puts
    # the employer, the title and the dates outside every editable span, so
    # nothing in the pipeline can reach them.
    frozen = "".join(frozen_chunks(parse(CUSTOM, CUSTOM_CONFIG)))

    assert "Acme Corp" in frozen
    assert "Senior Engineer" in frozen
    assert "2021 -- Present" in frozen
    assert "Led the platform team." not in frozen


def test_a_standalone_run_is_rewritten_without_disturbing_the_template() -> None:
    resume = parse(CUSTOM, CUSTOM_CONFIG)
    tailored = render(
        resume,
        group_edits=[GroupEdit("g1", ["Shipped Rust services.", "Ran the on-call rotation."])],
        region_edits=[RegionEdit("r1", "Led the platform team of six.")],
    )

    assert tailored.count(r"\achievement{") == 2
    assert "Shipped Rust services." in tailored
    assert "Led the platform team of six." in tailored
    assert r"\cventry{Acme Corp}{Senior Engineer}{2021 -- Present}{" in tailored
    # The definitions and the frozen half survive the splice.
    assert template_hash(parse(tailored, CUSTOM_CONFIG)) == template_hash(resume)
    assert tailored.split(r"\begin{document}")[0] == CUSTOM.split(r"\begin{document}")[0]


def test_a_run_broken_by_template_text_is_two_groups() -> None:
    # Only whitespace may separate the calls in a run. Anything else is template,
    # and replacing across it would overwrite bytes that are not ours.
    source = CUSTOM.replace(
        r"    \achievement{Cut p99",
        "    \\textit{Selected work:}\n    \\achievement{Cut p99",
    )
    resume = parse(source, CUSTOM_CONFIG)

    assert [len(group.bullets) for group in resume.groups] == [1, 1]
    assert r"\textit{Selected work:}" in "".join(frozen_chunks(resume))


def test_no_op_render_of_a_custom_template_is_byte_identical() -> None:
    assert render(parse(CUSTOM, CUSTOM_CONFIG)) == CUSTOM


@pytest.mark.parametrize("name", ["documentclass", "begin", "item", "newcommand", "section"])
def test_slot_config_refuses_structural_macros(name: str) -> None:
    with pytest.raises(SlotConfigError, match="structural"):
        SlotConfig(bullet_macros=(BulletMacro(name),)).validate()


@pytest.mark.parametrize("name", ["textbf", "emph", "href", "textcolor"])
def test_slot_config_refuses_inline_formatting_as_a_slot(name: str) -> None:
    # Declaring \textbf a bullet macro would make every bold run in the document
    # editable and nest slots inside each other.
    with pytest.raises(SlotConfigError, match="inline formatting"):
        SlotConfig(bullet_macros=(BulletMacro(name),)).validate()


def test_slot_config_refuses_a_content_argument_it_does_not_have() -> None:
    with pytest.raises(SlotConfigError, match="only takes"):
        SlotConfig(field_macros=(FieldMacro("cventry", arity=2, content_arg=4),)).validate()


def test_slot_config_round_trips_through_json() -> None:
    # It is stored as JSONB and re-validated on the way back out.
    restored = SlotConfig.from_dict(CUSTOM_CONFIG.validate().to_dict())
    assert restored == CUSTOM_CONFIG.validate()
    assert SlotConfig.from_dict(None) is None


# --- slot discovery -----------------------------------------------------------


def test_a_multi_argument_bullet_macro_is_demoted_to_a_field() -> None:
    # The model told us where the prose is and only got the packaging wrong; a
    # bullet is reorderable and this one has siblings the renderer cannot
    # invent, so it becomes a field rather than being thrown away.
    schema = SlotSchema(
        bullet_macros=[
            ProposedBulletMacro(name="achievement"),
            ProposedBulletMacro(name="cvline", arity=2, content_arg=2),
        ],
    )
    config = to_slot_config(schema, ["section"])

    assert "achievement" in config.bullet_macro_names
    assert "cvline" not in config.bullet_macro_names
    assert ("cvline", 2, 2) in [(m.name, m.arity, m.content_arg) for m in config.field_macros]


def test_a_discovered_boundary_is_never_self_confirmed() -> None:
    schema = SlotSchema(
        bullet_macros=[ProposedBulletMacro(name="achievement")],
        field_macros=[ProposedFieldMacro(name="cventry", arity=4, content_arg=4, label="exp")],
    )
    config = to_slot_config(schema, ["section"])

    assert [(m.name, m.content_arg) for m in config.field_macros] == [("cventry", 4)]
    assert config.source == "discovered"
    assert config.confirmed is False


def test_discovery_keeps_the_builtin_shapes_alongside_the_proposal() -> None:
    # A template with a custom bullet macro very often still has a plain itemize.
    config = to_slot_config(SlotSchema(bullet_macros=[ProposedBulletMacro(name="achievement")]), [])
    assert "resumeItem" in config.bullet_macro_names
    assert "itemize" in config.environments


def test_discovery_refuses_a_proposal_that_claims_most_of_the_document() -> None:
    prose = "Built and operated distributed systems for many teams. " * 8
    source = (
        "\\documentclass{article}\n\\begin{document}\n\\section{Summary}\n"
        f"\\everything{{{prose}}}\n\\end{{document}}\n"
    )
    config = SlotConfig(field_macros=(FieldMacro("everything", arity=1, content_arg=1),))

    with pytest.raises(SlotDiscoveryError, match="editable"):
        check_invariants(parse(source, config), config)


def test_discovery_refuses_a_slot_holding_document_structure() -> None:
    source = (
        "\\documentclass{article}\n\\begin{document}\n\\section{Skills}\n"
        "\\block{\\begin{tabular}{ll} Python & Go \\end{tabular}}\n\\end{document}\n"
    )
    config = SlotConfig(field_macros=(FieldMacro("block", arity=1, content_arg=1),))

    with pytest.raises(SlotDiscoveryError, match="structural command"):
        check_invariants(parse(source, config), config)


# --- safety ------------------------------------------------------------------


def test_validate_accepts_ordinary_bullet_markup() -> None:
    fragment = r"Built \textbf{Rust} services, cutting cost by 30\%."
    assert validate_fragment(fragment) == fragment


@pytest.mark.parametrize(
    "fragment",
    [
        r"\input{/etc/passwd}",
        r"\write18{rm -rf /}",
        r"\renewcommand{\section}[1]{}",
        r"Unbalanced {braces",
        r"50% off",
        r"\begin{itemize}\item nested\end{itemize}",
    ],
)
def test_validate_rejects_unsafe_or_malformed_fragments(fragment: str) -> None:
    with pytest.raises(UnsafeLatexError):
        validate_fragment(fragment)


def test_escape_text_neutralises_every_special_character() -> None:
    assert escape_text("A & B 50% $9 #1 a_b {x}") == r"A \& B 50\% \$9 \#1 a\_b \{x\}"


def test_braces_balanced_ignores_escaped_braces() -> None:
    assert braces_balanced(r"\{ literal \}")
    assert not braces_balanced(r"{ unclosed")


def test_coerce_degrades_to_plain_words_instead_of_failing() -> None:
    # Losing markup in one bullet beats refusing to render the resume.
    assert coerce_fragment(r"\unknowncmd{Shipped Rust}") == "Shipped Rust"


# --- plain-text projection ---------------------------------------------------


def test_projection_keeps_bullets_frozen_prose_and_headings() -> None:
    markdown = to_markdown(_parsed())

    assert "## Skills" in markdown
    assert "Languages: Python, Go, SQL" in markdown
    assert "- Designed a multi-tenant pipeline handling 40k events/sec" in markdown
    assert "Senior Engineer, Acme Corp 2021 - Present" in markdown
    assert "B.Tech, State University 2018" in markdown
    assert "\\" not in markdown


def test_projection_separates_adjacent_macro_arguments() -> None:
    # `\cventry{Acme Corp}{Senior Engineer}` must not flatten to one run-on
    # word: an ATS matches neither "CorpSenior" nor the keywords inside it.
    markdown = to_markdown(parse(CUSTOM, CUSTOM_CONFIG))

    assert "Acme Corp Senior Engineer 2021 - Present" in markdown
    assert "CorpSenior" not in markdown


# --- splicing reviewed content -----------------------------------------------


def test_outline_exposes_slots_but_never_the_preamble() -> None:
    outline = build_outline(_parsed())

    assert "[group g1]" in outline
    assert "[region r1] label=skills" in outline
    assert "Mentored four engineers." in outline
    assert "documentclass" not in outline
    assert "Education" not in outline  # Frozen sections are not offered up.


def test_review_system_prompt_forbids_fabrication() -> None:
    # Safety property of the feature, not a style choice.
    assert "NEVER invent skills" in REVIEW_SYSTEM_PROMPT


_ACCEPTED = ResumeTailoring(
    groups=[
        TailoredGroup(
            group_id="g1",
            items=[
                r"Designed a \textbf{Rust} pipeline handling 40k events/sec.",
                r"Cut p99 latency by 38\% using a work queue.",
            ],
        )
    ],
    regions=[TailoredRegion(region_id="r1", latex=r"\textbf{Languages}: Rust, Python, Go")],
)


def test_accepted_patches_splice_without_touching_the_template() -> None:
    tailored = apply_tailoring(MASTER, _ACCEPTED, SECTION_MACROS)

    assert r"\textbf{Rust} pipeline" in tailored
    assert r"\textbf{Languages}: Rust, Python, Go" in tailored
    # Dropped bullet is gone; frozen facts and preamble are untouched.
    assert "Mentored four engineers" not in tailored
    assert tailored.split(r"\begin{document}")[0] == MASTER.split(r"\begin{document}")[0]
    assert r"\textbf{B.Tech}, State University \hfill 2018" in tailored


def test_an_unaccepted_slot_keeps_the_masters_own_text() -> None:
    # Rejecting a patch is the absence of an edit, not an edit that undoes one:
    # a slot the splicer is not given comes through byte-for-byte.
    only_region = ResumeTailoring(regions=list(_ACCEPTED.regions))
    tailored = apply_tailoring(MASTER, only_region, SECTION_MACROS)

    assert "Mentored four engineers." in tailored
    assert r"\textbf{Languages}: Rust, Python, Go" in tailored


def test_splicing_sanitises_unsafe_model_output() -> None:
    unsafe = ResumeTailoring(
        groups=[TailoredGroup(group_id="g1", items=[r"Shipped \input{/etc/passwd} services"])]
    )
    tailored = apply_tailoring(MASTER, unsafe, SECTION_MACROS)

    assert r"\input" not in tailored
    assert "Shipped" in tailored
