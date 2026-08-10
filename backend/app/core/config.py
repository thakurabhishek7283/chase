import logging
import os
import secrets
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

EmbeddingProviderName = Literal["local", "voyage", "openai", "gemini"]
LLMProviderName = Literal["anthropic", "google"]

#: Fallback JWT signing key, regenerated on every process start.
#:
#: There is deliberately no committed default secret: a shipped constant would
#: let anyone holding the source forge a token for any account. Falling back to
#: a random value means an unconfigured deployment is merely *inconvenient*
#: (restarts invalidate sessions, and multiple workers can't verify each
#: other's tokens) rather than silently insecure.
_EPHEMERAL_JWT_SECRET = secrets.token_urlsafe(64)

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

    # --- Phase 6: authentication & authorization -----------------------------
    #: HMAC key for signing JWTs. Unset means a per-process random key — fine
    #: for a single dev server, unusable across restarts or multiple workers.
    jwt_secret_key: str | None = None
    jwt_algorithm: str = "HS256"
    #: Access tokens are short-lived because they cannot be revoked: nothing is
    #: looked up but the user row, so a forced logout only takes full effect
    #: once outstanding ones expire. Refresh tokens are rows in
    #: `refresh_tokens` and are revocable individually, by family, or wholesale
    #: through `users.token_version`.
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 14
    #: The account that is promoted to `admin` on registration. Explicit rather
    #: than "the first user to sign up wins", which races on a public instance.
    bootstrap_admin_email: str | None = None
    #: Minimum password length. Enforced at the schema boundary so it applies
    #: to registration and password changes alike.
    min_password_length: int = 12

    # --- credential-stuffing guardrails --------------------------------------
    #: Failed sign-ins tolerated from one client, per window, before the
    #: endpoint starts answering 429. Counted per IP *and* per email address:
    #: the first bounds one attacker spraying many accounts, the second bounds
    #: many hosts converging on one account.
    login_max_attempts: int = 10
    login_attempt_window_seconds: int = 300
    #: How long a tripped key stays blocked. Longer than the window on purpose
    #: — a limiter that forgives as fast as it counts is a speed bump.
    login_lockout_seconds: int = 900
    #: Registrations allowed per IP per window. Signup is unauthenticated and
    #: writes a row, so it needs its own ceiling.
    register_max_attempts: int = 5
    register_attempt_window_seconds: int = 3600
    #: Turn the limiter off. Intended for load tests, never for a deployment.
    login_throttle_enabled: bool = True

    #: Send `Access-Control-Allow-Credentials`. Off: auth is a bearer token
    #: from localStorage, so no cross-origin cookie ever needs to ride along,
    #: and the header only widens what a mistaken origin entry would grant.
    cors_allow_credentials: bool = False

    # --- moderation guardrails ----------------------------------------------
    #: How many submissions one user may have awaiting review at once, per
    #: table. Approval clears the count, so a good-faith contributor is never
    #: blocked for long — while an account bulk-inserting junk stops at this
    #: number instead of filling the shared tables.
    max_pending_submissions_per_user: int = 10
    #: How long a rejected row is kept so its contributor can read the reason
    #: before `POST /admin/purge-rejected` will remove it.
    rejected_retention_days: int = 30

    #: RFC 7518 §3.2 requires an HMAC key at least as long as the hash output —
    #: 32 bytes for SHA-256. A shorter key weakens the signature regardless of
    #: how random it looks, so it is refused outright rather than warned about.
    MIN_JWT_SECRET_BYTES: int = 32

    @property
    def jwt_secret(self) -> str:
        if self.jwt_secret_key:
            if len(self.jwt_secret_key.encode()) < self.MIN_JWT_SECRET_BYTES:
                raise ValueError(
                    f"JWT_SECRET_KEY must be at least {self.MIN_JWT_SECRET_BYTES} bytes "
                    "(RFC 7518 §3.2). Generate one with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
            return self.jwt_secret_key
        logger.warning(
            "JWT_SECRET_KEY is not set — signing tokens with a random per-process "
            "key. Sessions will not survive a restart and will not validate across "
            "workers. Set JWT_SECRET_KEY in backend/.env for anything but local dev."
        )
        return _EPHEMERAL_JWT_SECRET

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

    # --- The reasoning LLM ---------------------------------------------------
    # `llm_provider` selects which vendor the intake, review and revision agents
    # talk to. `ats_model` is the model id *within* that provider, so the two
    # must be changed together — a Claude id under `google` will not resolve.
    llm_provider: LLMProviderName = "anthropic"
    anthropic_api_key: str | None = None
    google_api_key: str | None = None
    ats_model: str = "claude-opus-5"
    #: Rate-limit (429) retries. Gemini's free tier allows 5 requests/minute,
    #: which a review of a long resume can exhaust — see `ai/limits.py`.
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

    # --- LaTeX ---------------------------------------------------------------
    # Every engine runs inside a separate worker service rather than being
    # installed on this host — see services/latex/compiler.py and
    # latex-worker/server.py. pdflatex is the default: fastest, and what most
    # LaTeX templates assume; detect_engine() upgrades a specific document to
    # xelatex/lualatex only when it actually needs one (services/latex/engines.py).
    latex_default_engine: str = "pdflatex"
    #: Where the LaTeX worker service listens. docker-compose.yml points this
    #: at the `latex-worker` service; for native development, start the image
    #: as a standalone container publishing 8100 and this default is correct
    #: unchanged. See services/latex/compiler.py.
    latex_worker_url: str = "http://localhost:8100"
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

    #: A resume is mostly template. A slot config that claims more of the body
    #: than this has lost the frozen/editable boundary rather than found it, so
    #: the proposal is refused. See services/slot_discovery.py.
    latex_max_editable_fraction: float = 0.6
    #: Ceiling on how much of a .tex is shown to the intake model. Applied
    #: separately to the preamble's macro definitions and to the body.
    latex_discovery_max_chars: int = 24000

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
