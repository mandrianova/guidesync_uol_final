from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, PositiveInt, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from guidesync_agent.llm.settings import DEFAULT_LLM_BASE_URL


class EnvironmentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_ignore_empty=True,
        extra="ignore",
    )


def environment_value(name: str) -> str | None:
    return os.environ.get(name)


class BrowserToolSettings(BaseModel):
    enabled: bool = True
    base_url: str | None = None
    screenshot_dir: Path = Path("outputs/browser-screenshots")
    timeout_ms: PositiveInt = 15_000
    binary: Path | None = None


class BrowserEnvironmentSettings(EnvironmentSettings):
    enabled: bool = Field(
        default=True,
        validation_alias="GUIDESYNC_BROWSER_TOOL_ENABLED",
    )
    base_url: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_BROWSER_BASE_URL",
    )
    screenshot_dir: Path = Field(
        default=Path("outputs/browser-screenshots"),
        validation_alias="GUIDESYNC_SCREENSHOT_DIR",
    )
    timeout_ms: PositiveInt = Field(
        default=15_000,
        validation_alias="GUIDESYNC_BROWSER_TIMEOUT_MS",
    )
    binary: Path | None = Field(
        default=None,
        validation_alias="GUIDESYNC_BROWSER_BINARY",
    )

    def tool_settings(self) -> BrowserToolSettings:
        return BrowserToolSettings.model_validate(self.model_dump())


class ArtifactEnvironmentSettings(EnvironmentSettings):
    bucket: str | None = Field(default=None, validation_alias="GUIDESYNC_S3_BUCKET")
    endpoint_url: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_S3_ENDPOINT_URL",
    )
    region: str = Field(default="us-east-1", validation_alias="AWS_DEFAULT_REGION")
    prefix: str = Field(default="reports", validation_alias="GUIDESYNC_S3_PREFIX")
    public_base_url: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_S3_PUBLIC_BASE_URL",
    )


class AuthEnvironmentSettings(EnvironmentSettings):
    mode: str = Field(default="none", validation_alias="GUIDESYNC_AUTH_MODE")
    username: str | None = Field(default=None, validation_alias="GUIDESYNC_AUTH_USERNAME")
    password: SecretStr | None = Field(
        default=None,
        validation_alias="GUIDESYNC_AUTH_PASSWORD",
    )


class CorsEnvironmentSettings(EnvironmentSettings):
    origins_csv: str = Field(default="", validation_alias="GUIDESYNC_CORS_ORIGINS")
    allow_credentials: bool = Field(
        default=True,
        validation_alias="GUIDESYNC_CORS_ALLOW_CREDENTIALS",
    )

    @property
    def origins(self) -> list[str]:
        return [
            origin.strip().rstrip("/")
            for origin in self.origins_csv.split(",")
            if origin.strip()
        ]


class StorageEnvironmentSettings(EnvironmentSettings):
    database_url: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_DATABASE_URL",
    )
    legacy_mode: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_STORAGE_MODE",
    )


class PathEnvironmentSettings(EnvironmentSettings):
    log_dir: Path = Field(default=Path("logs"), validation_alias="GUIDESYNC_LOG_DIR")
    repository_cache_dir: Path = Field(
        default=Path("var/repositories"),
        validation_alias="GUIDESYNC_REPOSITORY_CACHE_DIR",
    )
    project_profile_output_dir: Path = Field(
        default=Path("outputs/project-profiles"),
        validation_alias="GUIDESYNC_PROJECT_PROFILE_OUTPUT_DIR",
    )
    transcript_output_dir: Path = Field(
        default=Path("logs/llm-transcripts"),
        validation_alias="GUIDESYNC_LLM_TRANSCRIPT_OUTPUT_DIR",
    )


class QueueEnvironmentSettings(EnvironmentSettings):
    repository_sync_url: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_REPOSITORY_SYNC_QUEUE_URL",
    )
    repository_sync_name: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_REPOSITORY_SYNC_QUEUE_NAME",
    )
    sqs_endpoint_url: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_SQS_ENDPOINT_URL",
    )

    @field_validator("repository_sync_url", "repository_sync_name", "sqs_endpoint_url")
    @classmethod
    def normalize_optional_string(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class GoogleCloudEnvironmentSettings(EnvironmentSettings):
    credentials_path: Path | None = Field(
        default=None,
        validation_alias="GOOGLE_APPLICATION_CREDENTIALS",
    )
    project: str | None = Field(default=None, validation_alias="GOOGLE_CLOUD_PROJECT")
    location: str | None = Field(default=None, validation_alias="GOOGLE_CLOUD_LOCATION")


class CredentialEnvironmentSettings(EnvironmentSettings):
    openai_api_key: SecretStr | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )
    google_api_key: SecretStr | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    mistral_api_key: SecretStr | None = Field(default=None, validation_alias="MISTRAL_API_KEY")
    cohere_api_key: SecretStr | None = Field(default=None, validation_alias="COHERE_API_KEY")

    def api_key(self, environment_name: str | None) -> str | None:
        if not environment_name:
            return None
        known = {
            "OPENAI_API_KEY": self.openai_api_key,
            "ANTHROPIC_API_KEY": self.anthropic_api_key,
            "GOOGLE_API_KEY": self.google_api_key,
            "MISTRAL_API_KEY": self.mistral_api_key,
            "COHERE_API_KEY": self.cohere_api_key,
        }.get(environment_name)
        if known is not None:
            return known.get_secret_value()
        value = environment_value(environment_name)
        return value or None


class CommonModelEnvironmentSettings(EnvironmentSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_ignore_empty=False,
        extra="ignore",
    )

    bundle: str | None = Field(default=None, validation_alias="GUIDESYNC_MODEL_BUNDLE")
    provider_family: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_MODEL_PROVIDER_FAMILY",
    )
    llm_base_url: str = Field(
        default=DEFAULT_LLM_BASE_URL,
        validation_alias="GUIDESYNC_LLM_BASE_URL",
    )


class ModelRoleEnvironmentSettings(BaseModel):
    provider: str | None = None
    model: str | None = None
    name: str | None = None
    base_url: str | None = None
    api_key_env: str | None = None
    timeout_seconds: PositiveInt | None = None
    max_concurrent_agents: PositiveInt | None = None
    thinking: str | None = None
    max_output_tokens: PositiveInt | None = None
    context_budget_tokens: PositiveInt | None = None
    supports_structured_output: bool | None = None
    supports_tool_use: bool | None = None
    supports_vision: bool | None = None
    endpoint_type: str | None = None
    provider_family: str | None = None


def model_role_environment(prefix: str) -> ModelRoleEnvironmentSettings:
    numeric_fields = {
        "timeout_seconds",
        "max_concurrent_agents",
        "max_output_tokens",
        "context_budget_tokens",
    }
    boolean_fields = {
        "supports_structured_output",
        "supports_tool_use",
        "supports_vision",
    }
    values: dict[str, object] = {}
    for field_name in ModelRoleEnvironmentSettings.model_fields:
        value = environment_value(f"{prefix}_{field_name.upper()}")
        if value is None:
            continue
        if value == "" and field_name in numeric_fields:
            continue
        if value == "" and field_name in boolean_fields:
            value = False
        values[field_name] = value
    return ModelRoleEnvironmentSettings.model_validate(values)


class ModelEnvironmentSettings(BaseModel):
    common: CommonModelEnvironmentSettings = Field(
        default_factory=CommonModelEnvironmentSettings
    )
    orchestrator: ModelRoleEnvironmentSettings = Field(
        default_factory=lambda: model_role_environment("GUIDESYNC_AGENT")
    )
    project_profile: ModelRoleEnvironmentSettings = Field(
        default_factory=lambda: model_role_environment("GUIDESYNC_PROJECT_PROFILE_AGENT")
    )
    code_change: ModelRoleEnvironmentSettings = Field(
        default_factory=lambda: model_role_environment("GUIDESYNC_CODE_CHANGE_ANALYSIS")
    )
    screenshot_vision: ModelRoleEnvironmentSettings = Field(
        default_factory=lambda: model_role_environment("GUIDESYNC_SCREENSHOT_VISION")
    )
    embedding: ModelRoleEnvironmentSettings = Field(
        default_factory=lambda: model_role_environment("GUIDESYNC_EMBEDDING")
    )


class NlpEnvironmentSettings(EnvironmentSettings):
    spacy_model: str = Field(default="en_core_web_sm", validation_alias="GUIDESYNC_SPACY_MODEL")
    semantic_ranker_mode: str = Field(
        default="embedding_endpoint",
        validation_alias="GUIDESYNC_SEMANTIC_RANKER_MODE",
    )
    embedding_base_url: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_EMBEDDING_BASE_URL",
    )
    embedding_model: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_EMBEDDING_MODEL",
    )
    embedding_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="GUIDESYNC_EMBEDDING_API_KEY",
    )
    sentence_transformer_model: str | None = Field(
        default=None,
        validation_alias="GUIDESYNC_SENTENCE_TRANSFORMER_MODEL",
    )


class TokenBudgetEnvironmentSettings(EnvironmentSettings):
    run_budget: PositiveInt | None = Field(
        default=None,
        validation_alias="GUIDESYNC_RUN_TOKEN_BUDGET",
    )
    workflow_task_budget: PositiveInt | None = Field(
        default=None,
        validation_alias="GUIDESYNC_WORKFLOW_TASK_TOKEN_BUDGET",
    )
    mode: str = Field(default="warn", validation_alias="GUIDESYNC_TOKEN_BUDGET_MODE")

    @property
    def normalized_mode(self) -> str:
        return "fail" if self.mode.strip().lower() in {"fail", "error", "fail_fast"} else "warn"

    def role_budget(self, role: str) -> int | None:
        normalized = "".join(
            character if character.isalnum() else "_" for character in role.upper()
        )
        value = environment_value(f"GUIDESYNC_TOKEN_BUDGET_ROLE_{normalized}")
        if not value:
            return None
        try:
            parsed = int(value)
        except ValueError:
            return None
        return parsed if parsed > 0 else None


class ModelEvidenceEnvironmentSettings(EnvironmentSettings):
    max_commits: PositiveInt = Field(
        default=40,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_COMMITS",
    )
    max_commit_body_chars: PositiveInt = Field(
        default=700,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_COMMIT_BODY_CHARS",
    )
    max_files: PositiveInt = Field(
        default=25,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_FILES",
    )
    max_file_stats: PositiveInt = Field(
        default=16,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_FILE_STATS",
    )
    max_diff_hints: PositiveInt = Field(
        default=8,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_DIFF_HINTS",
    )
    max_diff_hint_chars: PositiveInt = Field(
        default=420,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_DIFF_HINT_CHARS",
    )
    max_docs: PositiveInt = Field(
        default=4,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_DOCS",
    )
    max_doc_chars: PositiveInt = Field(
        default=6_000,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_DOC_CHARS",
    )
    max_warnings: PositiveInt = Field(
        default=20,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_MAX_WARNINGS",
    )
    chunk_size: PositiveInt | None = Field(
        default=None,
        validation_alias="GUIDESYNC_MODEL_EVIDENCE_CHUNK_SIZE",
    )

    @property
    def effective_chunk_size(self) -> int:
        return self.chunk_size or self.max_commits


class VideoPresentationEnvironmentSettings(EnvironmentSettings):
    model_dir: Path = Field(
        default=Path("/models/tts/kokoro-en-v0_19"),
        validation_alias="GUIDESYNC_VIDEO_TTS_MODEL_DIR",
    )
    model_id: str = Field(
        default="kokoro-en-v0_19",
        validation_alias="GUIDESYNC_VIDEO_TTS_MODEL_ID",
    )
    voice: str = Field(default="bm_lewis", validation_alias="GUIDESYNC_VIDEO_TTS_VOICE")
    voice_id: int = Field(default=10, ge=0, validation_alias="GUIDESYNC_VIDEO_TTS_VOICE_ID")
    speed: float = Field(default=1.0, gt=0, le=2, validation_alias="GUIDESYNC_VIDEO_TTS_SPEED")
    num_threads: PositiveInt = Field(
        default=2,
        validation_alias="GUIDESYNC_VIDEO_TTS_NUM_THREADS",
    )
    render_timeout_ms: PositiveInt = Field(
        default=30_000,
        validation_alias="GUIDESYNC_VIDEO_RENDER_TIMEOUT_MS",
    )
    tts_timeout_seconds: PositiveInt = Field(
        default=240,
        validation_alias="GUIDESYNC_VIDEO_TTS_TIMEOUT_SECONDS",
    )
    ffmpeg_timeout_seconds: PositiveInt = Field(
        default=240,
        validation_alias="GUIDESYNC_VIDEO_FFMPEG_TIMEOUT_SECONDS",
    )
    max_duration_seconds: PositiveInt = Field(
        default=180,
        validation_alias="GUIDESYNC_VIDEO_MAX_DURATION_SECONDS",
    )
    slide_padding_seconds: float = Field(
        default=0.4,
        ge=0,
        le=2,
        validation_alias="GUIDESYNC_VIDEO_SLIDE_PADDING_SECONDS",
    )


class GuideSyncSettings(BaseModel):
    artifact: ArtifactEnvironmentSettings = Field(default_factory=ArtifactEnvironmentSettings)
    auth: AuthEnvironmentSettings = Field(default_factory=AuthEnvironmentSettings)
    browser: BrowserEnvironmentSettings = Field(default_factory=BrowserEnvironmentSettings)
    cors: CorsEnvironmentSettings = Field(default_factory=CorsEnvironmentSettings)
    credentials: CredentialEnvironmentSettings = Field(
        default_factory=CredentialEnvironmentSettings
    )
    google_cloud: GoogleCloudEnvironmentSettings = Field(
        default_factory=GoogleCloudEnvironmentSettings
    )
    storage: StorageEnvironmentSettings = Field(default_factory=StorageEnvironmentSettings)
    paths: PathEnvironmentSettings = Field(default_factory=PathEnvironmentSettings)
    queue: QueueEnvironmentSettings = Field(default_factory=QueueEnvironmentSettings)
    models: ModelEnvironmentSettings = Field(default_factory=ModelEnvironmentSettings)
    nlp: NlpEnvironmentSettings = Field(default_factory=NlpEnvironmentSettings)
    token_budget: TokenBudgetEnvironmentSettings = Field(
        default_factory=TokenBudgetEnvironmentSettings
    )
    model_evidence: ModelEvidenceEnvironmentSettings = Field(
        default_factory=ModelEvidenceEnvironmentSettings
    )
    video_presentation: VideoPresentationEnvironmentSettings = Field(
        default_factory=VideoPresentationEnvironmentSettings
    )


def get_settings() -> GuideSyncSettings:
    return GuideSyncSettings()
