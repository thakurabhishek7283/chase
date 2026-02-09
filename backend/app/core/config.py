import os
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

EmbeddingProviderName = Literal["local", "voyage", "openai", "gemini"]
LLMProviderName = Literal["anthropic", "google"]

#: Pydantic AI model-identifier prefix per provider. Keeping this a mapping
#: rather than an if/else means adding a provider is a data change.
LLM_PROVIDER_PREFIX: dict[str, str] = {
    "anthropic": "anthropic",
    "google": "google-gla",
}
#: The environment variable each provider's SDK reads its credential from.
LLM_PROVIDER_ENV_VAR: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
}


class Settings(BaseSettings):
    # The env file is overridable so the test suite can point at nothing and
    # stay hermetic. Without this, whatever a developer happens to have in
    # backend/.env — a real provider key, a different LLM_PROVIDER — silently
    # changes what the tests assert.
    model_config = SettingsConfigDict(
        env_file=os.environ.get("JARVIS_ENV_FILE", ".env"), extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://jarvis:jarvis_dev_password@localhost:5432/jarvis"
    cors_origins: str = "http://localhost:4200"

    # --- Phase 2: embeddings -------------------------------------------------
    # The vector column dimension is baked into the pgvector migration, so
    # switching providers to one with a different dimension requires a new
    # migration. Keep embedding_dim in sync with the active provider's model.
    embedding_provider: EmbeddingProviderName = "local"
    embedding_dim: int = 384
    local_embedding_model: str = "BAAI/bge-small-en-v1.5"
    voyage_api_key: str | None = None
    voyage_model: str = "voyage-3"
    openai_api_key: str | None = None
    openai_embedding_model: str = "text-embedding-3-small"
    gemini_embedding_model: str = "gemini-embedding-2"

    # --- Phases 3 & 4: the reasoning LLM -------------------------------------
    # `llm_provider` selects which vendor the ATS, autofix, and tailoring agents
    # talk to. `ats_model` is the model id *within* that provider, so the two
    # must be changed together — a Claude id under `google` will not resolve.
    llm_provider: LLMProviderName = "anthropic"
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    ats_model: str = "claude-opus-5"
    ats_max_autofix_iterations: int = 3
    #: Rate-limit (429) retries. Gemini's free tier allows 5 requests/minute,
    #: which one autofix loop can exhaust on its own — see `ai/limits.py`.
    llm_max_retries: int = 3
    llm_retry_max_wait_seconds: float = 65.0

    @property
    def llm_model_identifier(self) -> str:
        """The Pydantic AI model identifier, e.g. `google-gla:gemini-3.5-flash`."""
        return f"{LLM_PROVIDER_PREFIX[self.llm_provider]}:{self.ats_model}"

    @property
    def llm_api_key(self) -> str | None:
        """The configured credential for the active provider."""
        return {
            "anthropic": self.anthropic_api_key,
            "google": self.google_api_key,
        }[self.llm_provider]

    @property
    def llm_env_var(self) -> str:
        return LLM_PROVIDER_ENV_VAR[self.llm_provider]

    # --- Phase 5: LaTeX ------------------------------------------------------
    # Tectonic is the default engine because it is a single self-contained
    # binary that fetches the packages a document needs on first compile — no
    # multi-gigabyte TeX distribution and nothing to containerise. Point
    # `latex_engine_path` at any other binary to override.
    latex_engine_path: str = "tectonic"
    latex_compile_timeout_seconds: int = 120
    #: Upload ceiling for a .tex master. Resumes are a few tens of KB; anything
    #: far larger is a pasted book, not a resume.
    latex_max_upload_bytes: int = 2 * 1024 * 1024
    #: Section-heading macros to recognise beyond \section/\subsection. Resume
    #: classes love to define their own; add yours here rather than editing code.
    latex_section_macros: str = "section,subsection,cvsection,resumeSection,heading"

    @property
    def latex_section_macro_list(self) -> list[str]:
        return [m.strip() for m in self.latex_section_macros.split(",") if m.strip()]

    #: Pandoc converts markdown resumes to PDF, using `latex_engine_path` (Tectonic)
    #: as its `--pdf-engine` rather than requiring a separate TeX distribution.
    pandoc_path: str = "pandoc"
    pandoc_compile_timeout_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
