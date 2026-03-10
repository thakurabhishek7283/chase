import uuid

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.crud import resume as crud
from app.deps import SessionDep
from app.schemas.resume import ResumeCreate, ResumeRead, ResumeUpdate
from app.services.latex.compiler import LatexCompileError, LatexEngineNotFoundError, compile_pdf
from app.services.markdown_pdf import MarkdownCompileError, PandocNotFoundError, compile_markdown_pdf

router = APIRouter(prefix="/resumes", tags=["resumes"])


@router.post("", response_model=ResumeRead, status_code=status.HTTP_201_CREATED)
async def create_resume(data: ResumeCreate, session: SessionDep) -> ResumeRead:
    return await crud.create_resume(session, data)


@router.get("", response_model=list[ResumeRead])
async def list_resumes(
    session: SessionDep,
    user_id: uuid.UUID | None = Query(default=None),
    master_only: bool = Query(default=False),
) -> list[ResumeRead]:
    return await crud.list_resumes(session, user_id, master_only)


@router.get("/{resume_id}", response_model=ResumeRead)
async def get_resume(resume_id: uuid.UUID, session: SessionDep) -> ResumeRead:
    resume = await crud.get_resume(session, resume_id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return resume


@router.get("/{resume_id}/versions", response_model=list[ResumeRead])
async def list_resume_versions(resume_id: uuid.UUID, session: SessionDep) -> list[ResumeRead]:
    return await crud.list_resume_versions(session, resume_id)


@router.patch("/{resume_id}", response_model=ResumeRead)
async def update_resume(resume_id: uuid.UUID, data: ResumeUpdate, session: SessionDep) -> ResumeRead:
    resume = await crud.get_resume(session, resume_id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    return await crud.update_resume(session, resume, data)


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume(resume_id: uuid.UUID, session: SessionDep) -> None:
    resume = await crud.get_resume(session, resume_id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")
    await crud.delete_resume(session, resume)


@router.get("/{resume_id}/pdf")
async def render_resume_pdf(resume_id: uuid.UUID, session: SessionDep) -> Response:
    """Compile any stored resume to PDF, dispatching on its content format.

    Markdown goes through Pandoc; LaTeX goes through the engine it was uploaded
    with. Both ultimately compile via Tectonic, so the same install failure
    (`LatexEngineNotFoundError`) can surface from either path.
    """
    resume = await crud.get_resume(session, resume_id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found")

    try:
        if resume.content_format == "latex":
            pdf = await compile_pdf(resume.content, resume.latex_engine)
        elif resume.content_format == "markdown":
            pdf = await compile_markdown_pdf(resume.content)
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Resumes stored as '{resume.content_format}' cannot be rendered to PDF.",
            )
    except (LatexEngineNotFoundError, PandocNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except (LatexCompileError, MarkdownCompileError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"PDF compilation failed:\n{exc}",
        ) from exc

    filename = "".join(c if c.isalnum() or c in "-_" else "-" for c in resume.title) or "resume"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )
