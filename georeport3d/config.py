from pathlib import Path
from typing import Literal

import yaml
from pydantic import (
    BaseModel,
    Field,
    PositiveFloat,
    PositiveInt,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

CacheKeyField = Literal[
    "document_sha256",
    "figure_sha256",
    "model_id",
    "model_revision",
    "prompt_version",
    "preprocess_version",
]
CANONICAL_CACHE_KEY_FIELDS: tuple[CacheKeyField, ...] = (
    "document_sha256",
    "figure_sha256",
    "model_id",
    "model_revision",
    "prompt_version",
    "preprocess_version",
)


class BudgetPolicy(BaseModel):
    global_usd: PositiveFloat
    default_job_cap_usd: PositiveFloat
    require_confirmation_above_usd: float = Field(ge=0)
    hard_stop_usd: PositiveFloat

    @model_validator(mode="after")
    def validate_limits(self) -> "BudgetPolicy":
        if self.hard_stop_usd > self.global_usd:
            raise ValueError("hard_stop_usd must be <= global_usd")
        if self.default_job_cap_usd > self.hard_stop_usd:
            raise ValueError("default_job_cap_usd must be <= hard_stop_usd")
        return self


class LimitsPolicy(BaseModel):
    max_file_mb: PositiveInt
    max_pages: PositiveInt
    max_ai_pages_per_job: PositiveInt
    max_concurrent_gpu_jobs: PositiveInt


class CachePolicy(BaseModel):
    enabled: bool = True
    key_fields: list[CacheKeyField]

    @field_validator("key_fields")
    @classmethod
    def validate_key_fields(
        cls,
        key_fields: list[CacheKeyField],
    ) -> list[CacheKeyField]:
        if tuple(key_fields) != CANONICAL_CACHE_KEY_FIELDS:
            raise ValueError("key_fields must exactly match the canonical cache key fields")
        return key_fields


class ModalPolicy(BaseModel):
    gpu: Literal["L4"] = "L4"
    min_containers: Literal[0] = 0
    max_containers: Literal[1] = 1
    buffer_containers: Literal[0] = 0
    scaledown_window_seconds: PositiveInt = 10
    timeout_seconds: PositiveInt = 900


class Policy(BaseModel):
    budget: BudgetPolicy
    limits: LimitsPolicy
    cache: CachePolicy
    modal: ModalPolicy


class Settings(BaseSettings):
    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/georeport3d"
    storage_root: Path = Path(".data/documents")
    policy_path: Path = Path("config/policy.yaml")
    inference_provider: Literal["mock", "modal"] = "mock"
    model_id: str = "unsloth/Qwen3.6-27B-NVFP4"
    model_revision: str | None = None
    prompt_version: str = "v1"
    preprocess_version: str = "v1"
    modal_app_name: str = "georeport3d-qwen"
    modal_class_name: str = "QwenWorker"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def forbid_mock_in_production(self) -> "Settings":
        if self.app_env == "production" and self.inference_provider == "mock":
            raise ValueError("mock inference is forbidden in production")
        return self


def load_policy(path: Path) -> Policy:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Policy.model_validate(raw)
