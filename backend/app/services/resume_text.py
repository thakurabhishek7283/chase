"""Read a stored resume the way the rest of the app expects to read one.

The ATS half of the review call was written against readable prose. A LaTeX
resume handed to it raw scores its own preamble: `\\documentclass`,
`\\newcommand` bodies and `\\vspace` calls all read as keywords to a model that
was told it was looking at a resume. Anything that needs the *words* goes
through `readable_text` instead.

This also owns the one definition of "which slot vocabulary is this resume read
with", so the upload, review and render paths cannot disagree about what a given
master contains.
"""

from app.core.config import get_settings
from app.models.resume import Resume
from app.services.latex import SlotConfig, SlotConfigError, parse
from app.services.latex.parser import LatexParseError
from app.services.latex.plain_text import flatten_latex, to_markdown


def slot_config_for(resume: Resume) -> SlotConfig:
    """The vocabulary this resume is read with.

    A resume with nothing stored gets the built-in shapes, which is the common
    case — only a template the parser could not read unaided carries a config.
    A stored config that no longer validates falls back rather than failing: the
    document is still readable the ordinary way, and refusing to open a resume
    over a bad cached vocabulary would be the worse outcome.
    """
    try:
        stored = SlotConfig.from_dict(resume.latex_slot_config)
    except SlotConfigError:
        stored = None
    return stored or SlotConfig.default(get_settings().latex_section_macro_list)


def readable_text(resume: Resume) -> str:
    """The resume as an ATS would read it: words, headings, bullets, no markup.

    The projection is lossy and one-way by design — it approximates what gets
    extracted from the compiled PDF, which is the honest input for a question
    about how the resume screens.
    """
    try:
        return to_markdown(parse(resume.content, slot_config_for(resume)))
    except LatexParseError:
        # An unreadable template is a slot-config problem, not a scoring one —
        # the words are still in there. Fall back rather than refusing to score.
        return flatten_latex(resume.content)
