import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, File, Form, HTTPException, Query, Response, UploadFile, status

from app.core.config import get_settings
from app.deps import SessionDep, require_llm_key
from app.models.job_profile import JobProfile
from app.models.resume import Resume
from app.schemas.latex import (
    BulletOut,
    EngineUpdateRequest,
    ItemGroupOut,
    LatexEngineStatus,
    LatexUploadResponse,
    MarkedRegionOut,
    PreviewTailoringRequest,
    ResumeOutline,
    SectionOut,
    TailorRequest,
    TailorResponse,
)
from app.services.latex import (
    ENGINE_NAMES,
    LatexCompileError,
    LatexEngineNotFoundError,
    LatexParseError,
    LatexRenderError,
    UnknownEngineError,
    compile_pdf,
    detect_engine,
    engine_available,
    engine_version,
    incompatibility,
    parse,
    validate_engine,
)
from app.services.latex.compiler import INSTALL_HINT
from app.services.latex.model import LatexResume
from app.services.tailoring import apply_tailoring, tailor_latex_resume

router = APIRouter(prefix="/latex", tags=["latex"])


def _section_macros() -> list[str]:
    return get_settings().latex_section_macro_list


def _parse_or_422(source: str) -> LatexResume:
    try:
        return parse(source, _section_macros())
    except LatexParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _effective_engine(stored: str | None) -> str | None:
    """The engine a resume actually compiles under: its own, or the server's."""
    return stored or get_settings().latex_engine_path


def _outline(
    resume: LatexResume,
    resume_id: uuid.UUID | None = None,
    engine: str | None = None,
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
                    bullets=[BulletOut(id=b.id, latex=b.latex) for b in group.bullets],
                )
                for group in section.groups
            ],
            regions=[
                MarkedRegionOut(id=r.id, label=r.label, latex=r.latex) for r in section.regions
            ],
        )
        for section in resume.sections
    ]
    effective = _effective_engine(engine)
    return ResumeOutline(
        resume_id=resume_id,
        sections=sections,
        group_count=len(resume.groups),
        bullet_count=resume.bullet_count,
        region_count=len(resume.regions),
        frozen_sections=[s.heading for s in resume.sections if not s.is_editable],
        latex_engine=engine,
        engine_available=engine_available(engine) if engine else engine_available(),
        engine_warning=incompatibility(resume.source, effective) if effective else None,
    )


async def _load_latex_resume(session: SessionDep, resume_id: uuid.UUID) -> Resume:
    resume = await session.get(Resume, resume_id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    if resume.content_format != "latex":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Resume {resume_id} is stored as '{resume.content_format}', not LaTeX.",
        )
    return resume


@router.get("/status", response_model=LatexEngineStatus)
async def latex_status() -> LatexEngineStatus:
    """Report whether PDF compilation is available, and how to fix it if not.

    Parsing and tailoring work without an engine — only the PDF step needs one —
    so this is advisory rather than a gate on the rest of the feature.
    """
    settings = get_settings()
    available = engine_available()
    return LatexEngineStatus(
        available=available,
        engine=settings.latex_engine_path,
        version=engine_version() if available else None,
        detail=None if available else INSTALL_HINT,
        engines={name: engine_available(name) for name in sorted(ENGINE_NAMES)},
    )


@router.post(
    "/resumes/upload", response_model=LatexUploadResponse, status_code=status.HTTP_201_CREATED
)
async def upload_master(
    session: SessionDep,
    user_id: uuid.UUID = Form(...),
    title: str = Form(...),
    file: UploadFile = File(...),
    latex_engine: str | None = Form(default=None),
) -> LatexUploadResponse:
    """Store a `.tex` master resume, after proving it can actually be tailored.

    Parsing happens before the insert so an unusable document is rejected at
    upload time — when the author is looking at it and can add markers — rather
    than at the first tailoring attempt weeks later.

    The engine is auto-detected from the preamble unless one is given: a resume
    loading `fontspec` gets a Unicode engine rather than failing on first render.
    Detection only upgrades, so an explicit `latex_engine` always wins.
    """
    settings = get_settings()
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

    parsed = _parse_or_422(source)
    engine = _validated_engine(latex_engine) or detect_engine(
        source, settings.latex_engine_path
    )
    # Detection can land on the configured default, which may be an absolute
    # path rather than an allowlisted name. Store NULL in that case so the
    # resume keeps tracking the server setting instead of pinning a path.
    stored_engine = engine if engine in ENGINE_NAMES else None

    resume = Resume(
        user_id=user_id,
        title=title,
        content_format="latex",
        content=source,
        version_label="Master",
        latex_engine=stored_engine,
    )
    session.add(resume)
    await session.commit()
    await session.refresh(resume)
    return LatexUploadResponse(
        resume_id=resume.id,
        title=resume.title,
        outline=_outline(parsed, resume.id, resume.latex_engine),
    )


def _validated_engine(name: str | None) -> str | None:
    """Reject an engine name that is not on the allowlist, with a 422."""
    if name is None or name == "":
        return None
    try:
        return validate_engine(name)
    except UnknownEngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/resumes/{resume_id}/outline", response_model=ResumeOutline)
async def resume_outline(resume_id: uuid.UUID, session: SessionDep) -> ResumeOutline:
    """Show what tailoring may change in this resume, and what is frozen."""
    resume = await _load_latex_resume(session, resume_id)
    return _outline(_parse_or_422(resume.content), resume.id, resume.latex_engine)


@router.patch("/resumes/{resume_id}/engine", response_model=ResumeOutline)
async def set_engine(
    resume_id: uuid.UUID, data: EngineUpdateRequest, session: SessionDep
) -> ResumeOutline:
    """Change the engine this resume compiles under.

    Returns the outline so the caller immediately sees whether the new engine is
    installed and whether it can actually handle the document.
    """
    resume = await _load_latex_resume(session, resume_id)
    resume.latex_engine = data.latex_engine
    resume.updated_at = datetime.now(timezone.utc)
    session.add(resume)
    await session.commit()
    await session.refresh(resume)
    return _outline(_parse_or_422(resume.content), resume.id, resume.latex_engine)


@router.get("/resumes/{resume_id}/render")
async def render_resume(
    resume_id: uuid.UUID,
    session: SessionDep,
    output: str = Query(default="pdf", pattern="^(pdf|tex)$"),
) -> Response:
    """Compile a stored resume to PDF, or hand back its `.tex` source."""
    resume = await _load_latex_resume(session, resume_id)
    filename = "".join(c if c.isalnum() or c in "-_" else "-" for c in resume.title) or "resume"

    if output == "tex":
        return Response(
            content=resume.content,
            media_type="application/x-tex",
            headers={"Content-Disposition": f'attachment; filename="{filename}.tex"'},
        )
    pdf = await _compile_or_error(resume.content, resume.latex_engine)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}.pdf"'},
    )


async def _compile_or_error(source: str, engine: str | None = None) -> bytes:
    # Catch a known-incompatible pairing here rather than letting it surface as
    # a hundred lines of TeX log.
    effective = _effective_engine(engine)
    if effective and (reason := incompatibility(source, effective)):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=reason)
    try:
        return await compile_pdf(source, engine)
    except LatexEngineNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except LatexCompileError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"LaTeX compilation failed:\n{exc}",
        ) from exc


@router.post("/resumes/{resume_id}/preview")
async def preview_tailoring(
    resume_id: uuid.UUID,
    data: PreviewTailoringRequest,
    session: SessionDep,
    output: str = Query(default="tex", pattern="^(pdf|tex)$"),
) -> Response:
    """Apply an already-reviewed tailoring and render it, without calling the model.

    Deterministic and free, which is what makes hand-editing the model's output
    practical: the client can re-render after every tweak.
    """
    resume = await _load_latex_resume(session, resume_id)
    try:
        tailored = apply_tailoring(resume.content, data.tailoring, _section_macros())
    except LatexParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LatexRenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    if output == "tex":
        return Response(content=tailored, media_type="application/x-tex")
    return Response(
        content=await _compile_or_error(tailored, resume.latex_engine),
        media_type="application/pdf",
    )


@router.post("/tailor", response_model=TailorResponse)
async def tailor(data: TailorRequest, session: SessionDep) -> TailorResponse:
    """Tailor a LaTeX master for one job, optionally saving it as a child version."""
    require_llm_key()
    resume = await _load_latex_resume(session, data.resume_id)
    job = await session.get(JobProfile, data.job_profile_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job profile not found")

    try:
        result = await tailor_latex_resume(
            resume.content,
            job.description,
            job.position_title,
            _section_macros(),
            score=data.score,
        )
    except LatexParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except LatexRenderError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    saved_id: uuid.UUID | None = None
    if data.save_as_tailored_version:
        # Tailored versions always hang off a master, never off another tailored
        # version — the same one-level-deep rule the autofix endpoint applies.
        now = datetime.now(timezone.utc)
        tailored = Resume(
            user_id=resume.user_id,
            master_resume_id=resume.master_resume_id or resume.id,
            title=resume.title,
            content_format="latex",
            content=result.tailored_latex,
            version_label=f"Tailored for {job.position_title}",
            # A child renders from its master's template, so it must compile
            # with the master's engine — inheriting it is what keeps the two
            # visually identical.
            latex_engine=resume.latex_engine,
            created_at=now,
            updated_at=now,
        )
        session.add(tailored)
        await session.commit()
        await session.refresh(tailored)
        saved_id = tailored.id

    return TailorResponse(
        resume_id=resume.id, job_profile_id=job.id, saved_resume_id=saved_id, result=result
    )
