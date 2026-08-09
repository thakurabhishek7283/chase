r"""Resumes: upload a `.tex`, read what it contains, render it.

Content enters here exactly once, through `POST /upload`, and only after the
intake pass has corrected it, the parser has found its slots, and the engine has
compiled it. There is no JSON create and no content update — every previous way
in was a way to store a document nobody had proved was renderable, and the
tailored resume that came back wrapped in a Markdown code fence got in through
one of them.

Everything about *changing* a resume lives in `routers/reviews.py`. This module
only reads.
"""

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status

from app.core.config import get_settings
from app.crud import resume as crud
from app.deps import CurrentUser, SessionDep, require_llm_key, require_owned_resume
from app.models.resume import Resume
from app.schemas.resume import (
    AppliedCorrection,
    BulletMacroOut,
    BulletOut,
    FieldMacroOut,
    ItemGroupOut,
    LatexEngineStatus,
    ListPairOut,
    MarkedRegionOut,
    ResumeOutline,
    ResumeRead,
    ResumeSummary,
    ResumeUploadResponse,
    SectionOut,
    SlotConfigOut,
    SlotConfigUpdate,
)
from app.services.intake import IntakeEngineMissing, IntakeError, ingest
from app.services.latex import (
    ENGINE_NAMES,
    BulletMacro,
    FieldMacro,
    LatexCompileError,
    LatexEngineNotFoundError,
    LatexErrorCode,
    LatexParseError,
    LatexResume,
    ListPair,
    SlotConfig,
    SlotConfigError,
    UnknownEngineError,
    compile_pdf,
    engine_available,
    engine_version,
    incompatibility,
    parse,
    template_hash,
    validate_engine,
)
from app.services.latex.compiler import INSTALL_HINT
from app.services.resume_text import slot_config_for

router = APIRouter(prefix="/resumes", tags=["resumes"])
logger = logging.getLogger(__name__)


# --- shared shaping ----------------------------------------------------------


def latex_error_detail(code: LatexErrorCode, message: str) -> dict[str, str]:
    """A 422 body a client can branch on, not just display.

    `code` says which of the two reasons this was: `invalid_latex` means the
    document itself needs fixing, `unsupported_latex` means the parser or the
    slot vocabulary describing it does. `message` is still the human-readable
    reason, unchanged from before this distinction existed.
    """
    return {"code": code.value, "message": message}


def _config_out(config: SlotConfig) -> SlotConfigOut:
    return SlotConfigOut(
        section_macros=list(config.section_macros),
        environments=list(config.environments),
        bullet_macros=[BulletMacroOut(name=m.name) for m in config.bullet_macros],
        list_pairs=[ListPairOut(start=p.start, end=p.end) for p in config.list_pairs],
        field_macros=[
            FieldMacroOut(name=m.name, arity=m.arity, content_arg=m.content_arg, label=m.label)
            for m in config.field_macros
        ],
        source=config.source,
        confirmed=config.confirmed,
    )


def _config_in(data: SlotConfigOut) -> SlotConfig:
    """Build a config from a client payload, 422ing on anything unsafe."""
    try:
        return SlotConfig(
            section_macros=tuple(
                data.section_macros or get_settings().latex_section_macro_list
            ),
            environments=tuple(data.environments),
            bullet_macros=tuple(BulletMacro(name=m.name) for m in data.bullet_macros),
            list_pairs=tuple(ListPair(start=p.start, end=p.end) for p in data.list_pairs),
            field_macros=tuple(
                FieldMacro(name=m.name, arity=m.arity, content_arg=m.content_arg, label=m.label)
                for m in data.field_macros
            ),
            source="author",
            confirmed=True,
        ).validate()
    except SlotConfigError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=latex_error_detail(LatexErrorCode.UNSUPPORTED_LATEX, str(exc)),
        ) from exc


def _parse_or_422(source: str, config: SlotConfig) -> LatexResume:
    try:
        return parse(source, config)
    except LatexParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=latex_error_detail(LatexErrorCode.UNSUPPORTED_LATEX, str(exc)),
        ) from exc


def effective_engine(stored: str | None) -> str:
    """The engine a resume actually compiles under: its own, or the server's."""
    return stored or get_settings().latex_default_engine


def build_outline(
    parsed: LatexResume, resume_id: uuid.UUID | None = None, engine: str | None = None
) -> ResumeOutline:
    sections = [
        SectionOut(
            id=section.id,
            heading=section.heading,
            editable=section.is_editable,
            groups=[
                ItemGroupOut(
                    id=group.id,
                    kind=group.kind,
                    content_hash=group.content_hash,
                    bullets=[
                        BulletOut(id=b.id, latex=b.latex, content_hash=b.content_hash)
                        for b in group.bullets
                    ],
                )
                for group in section.groups
            ],
            regions=[
                MarkedRegionOut(
                    id=r.id,
                    label=r.label,
                    latex=r.latex,
                    content_hash=r.content_hash,
                    origin=r.origin,
                )
                for r in section.regions
            ],
        )
        for section in parsed.sections
    ]
    effective = effective_engine(engine)
    return ResumeOutline(
        resume_id=resume_id,
        sections=sections,
        group_count=len(parsed.groups),
        bullet_count=parsed.bullet_count,
        region_count=len(parsed.regions),
        frozen_sections=[s.heading for s in parsed.sections if not s.is_editable],
        latex_engine=engine,
        engine_available=engine_available(engine) if engine else engine_available(),
        engine_warning=incompatibility(parsed.source, effective),
        template_hash=template_hash(parsed),
        slot_config=_config_out(parsed.config),
    )


async def compile_or_error(
    source: str, engine: str | None, *, resume_id: uuid.UUID | None = None
) -> bytes:
    """Compile, mapping each failure to the status that describes it.

    The incompatibility pre-flight runs first so a document/engine mismatch is
    one sentence naming the construct, not a hundred lines of TeX log saying the
    same thing less clearly.
    """
    if reason := incompatibility(source, effective_engine(engine)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=latex_error_detail(LatexErrorCode.INVALID_LATEX, reason),
        )
    try:
        return await compile_pdf(source, engine)
    except LatexEngineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except LatexCompileError as exc:
        logger.error("[compile] resume=%s failed: %s", resume_id, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=latex_error_detail(LatexErrorCode.INVALID_LATEX, f"LaTeX compilation failed:\n{exc}"),
        ) from exc


def attachment(title: str, suffix: str, *, inline: bool = False) -> dict[str, str]:
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in title) or "resume"
    disposition = "inline" if inline else "attachment"
    return {"Content-Disposition": f'{disposition}; filename="{safe}.{suffix}"'}


# --- engine status -----------------------------------------------------------


@router.get("/engine-status", response_model=LatexEngineStatus)
async def engine_status(user: CurrentUser) -> LatexEngineStatus:
    """Which engines are installed, so the upload form offers only usable ones."""
    settings = get_settings()
    available = engine_available()
    return LatexEngineStatus(
        available=available,
        engine=settings.latex_default_engine,
        version=engine_version() if available else None,
        detail=None if available else INSTALL_HINT,
        engines={name: engine_available(name) for name in sorted(ENGINE_NAMES)},
    )


# --- the only way in ---------------------------------------------------------


def _validated_engine(name: str | None) -> str | None:
    """Reject an engine name that is not on the allowlist, with a 422."""
    if not name:
        return None
    try:
        return validate_engine(name)
    except UnknownEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/upload", response_model=ResumeUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_master(
    session: SessionDep,
    user: CurrentUser,
    title: str = Form(...),
    file: UploadFile = File(...),
    latex_engine: str | None = Form(default=None),
) -> ResumeUploadResponse:
    r"""Store a `.tex` master, after proving it works.

    One model call reads the document: it returns the corrections needed to
    compile under the chosen engine *and* what the template's macros mean. The
    corrections are applied by exact match, the vocabulary has to resolve to real
    spans, and the engine has the last word — see `services/intake.py`.

    The engine is chosen here and fixed for life. The corrections were made for
    *this* engine, so a later switch would leave fixes that solve a problem the
    new engine does not have and miss ones it does.
    """
    require_llm_key()
    settings = get_settings()

    if file.filename and not file.filename.lower().endswith(".tex"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Only .tex files are accepted. {file.filename!r} is not one.",
        )

    raw = await file.read()
    if len(raw) > settings.latex_max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {settings.latex_max_upload_bytes // 1024} KB limit.",
        )
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="The .tex file must be UTF-8 encoded.",
        ) from None

    engine = _validated_engine(latex_engine)
    try:
        result = await ingest(source, engine)
    except IntakeEngineMissing as exc:
        # Their document may be perfectly fine; the machine cannot prove it.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except IntakeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=latex_error_detail(exc.code, str(exc)),
        ) from exc

    resume = Resume(
        user_id=user.id,
        title=title,
        content=result.source,
        version_label="Master",
        latex_engine=result.engine,
        latex_slot_config=result.config.to_dict(),
    )
    session.add(resume)
    await session.commit()
    await session.refresh(resume)

    return ResumeUploadResponse(
        resume_id=resume.id,
        title=resume.title,
        corrections=[
            AppliedCorrection(find=c.find, replace=c.replace, reason=c.reason)
            for c in result.corrections
        ],
        verdict=result.verdict,
        outline=build_outline(result.resume, resume.id, resume.latex_engine),
    )


# --- reading -----------------------------------------------------------------


@router.get("", response_model=list[ResumeSummary])
async def list_resumes(session: SessionDep, user: CurrentUser) -> list[Resume]:
    """The caller's resumes. There is no cross-user listing, by construction."""
    return await crud.list_resumes(session, user.id)


@router.get("/{resume_id}", response_model=ResumeRead)
async def get_resume(resume_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> Resume:
    return await require_owned_resume(session, resume_id, user)


@router.get("/{resume_id}/versions", response_model=list[ResumeSummary])
async def list_resume_versions(
    resume_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> list[Resume]:
    resume = await require_owned_resume(session, resume_id, user)
    # Asked of a child, this lists its siblings — every tailored version of the
    # same master, which is what a version list means from anywhere in the tree.
    return await crud.list_resume_versions(session, root_resume_id(resume), user_id=user.id)


@router.get("/{resume_id}/outline", response_model=ResumeOutline)
async def resume_outline(
    resume_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> ResumeOutline:
    """What a review may change in this resume, and what is frozen."""
    resume = await require_owned_resume(session, resume_id, user)
    parsed = _parse_or_422(resume.content, slot_config_for(resume))
    return build_outline(parsed, resume.id, resume.latex_engine)


@router.put("/{resume_id}/slots", response_model=ResumeOutline)
async def set_slot_config(
    resume_id: uuid.UUID, data: SlotConfigUpdate, session: SessionDep, user: CurrentUser
) -> ResumeOutline:
    """Correct the boundary between this resume's template and its content.

    The author's final say, and the only thing that sets `confirmed`. Intake
    proposes a vocabulary from one reading of the document; this is what exists
    for the times it drew the line in the wrong place. `config: null` resets to
    the built-in shapes.

    The new config has to parse the document before it is stored — a vocabulary
    that finds nothing would leave the resume unreviewable, and discovering that
    at the next review is too late to be useful.
    """
    resume = await require_owned_resume(session, resume_id, user)
    config = _config_in(data.config) if data.config is not None else None
    parsed = _parse_or_422(
        resume.content, config or SlotConfig.default(get_settings().latex_section_macro_list)
    )

    resume.latex_slot_config = config.to_dict() if config else None
    resume.updated_at = datetime.now(timezone.utc)
    session.add(resume)
    await session.commit()
    await session.refresh(resume)
    return build_outline(parsed, resume.id, resume.latex_engine)


@router.get("/{resume_id}/tex")
async def download_tex(
    resume_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Response:
    resume = await require_owned_resume(session, resume_id, user)
    return Response(
        content=resume.content,
        media_type="application/x-tex",
        headers=attachment(resume.title, "tex"),
    )


@router.get("/{resume_id}/pdf")
async def render_resume_pdf(
    resume_id: uuid.UUID, session: SessionDep, user: CurrentUser
) -> Response:
    """Compile a stored resume to PDF.

    Masters and finalized children only — a tailored document that has not been
    through review does not exist as a row, which is the point of the flow.
    """
    resume = await require_owned_resume(session, resume_id, user)
    pdf = await compile_or_error(resume.content, resume.latex_engine, resume_id=resume.id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers=attachment(resume.title, "pdf", inline=True),
    )


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: uuid.UUID, session: SessionDep, user: CurrentUser) -> None:
    """Delete a resume. A master takes its children and reviews with it."""
    resume = await require_owned_resume(session, resume_id, user)
    await crud.delete_resume(session, resume)


def root_resume_id(resume: Resume) -> uuid.UUID:
    """The master at the top of this resume's tree — itself, if it is one.

    The tree is one level deep on purpose (see `crud/resume.py`), and this is
    what keeps it that way now that a tailored child can be reviewed again.
    Finalizing a child's review hangs the result off this id, so improving a
    tailored version produces a *sibling* of it rather than a grandchild: the
    versions of one master stay a flat list however many rounds it took to get
    there, and deleting the master still takes all of them with it.
    """
    return resume.master_resume_id or resume.id
