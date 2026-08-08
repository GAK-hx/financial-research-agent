from datetime import date
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    log_level: str = "INFO"
    identity_mode: Literal["local", "api_key"] = "local"
    agent_api_key: str = ""
    model_provider: str = "openai_compatible"
    model_name: str = "deepseek-v4-flash"
    model_api_key: str = ""
    model_base_url: str = ""
    model_timeout_seconds: int = Field(default=75, ge=10, le=120)
    model_max_retries: int = Field(default=4, ge=0, le=5)
    model_retry_backoff_seconds: float = Field(default=3.0, ge=0, le=30)
    model_retry_max_backoff_seconds: float = Field(default=20.0, ge=0, le=60)
    model_context_window_tokens: int = Field(default=131_072, ge=8_192, le=2_000_000)
    model_max_output_tokens: int | None = Field(default=None, ge=1, le=1_000_000)
    model_thinking_mode: Literal["disabled", "enabled", "omit"] = "disabled"
    model_reasoning_effort: Literal["high", "max"] = "high"
    business_timezone: str = "Asia/Shanghai"
    agent_framework: Literal["native", "langchain"] = "langchain"
    model_input_price_cny_per_million: float | None = Field(default=None, ge=0)
    model_cache_hit_price_cny_per_million: float | None = Field(default=None, ge=0)
    model_output_price_cny_per_million: float | None = Field(default=None, ge=0)
    iceberg_warehouse: str = "file:///lake/iceberg"
    iceberg_catalog_uri: str = "sqlite:////lake/iceberg_catalog.db"
    lake_root: str = "/lake"
    artifacts_root: str = "/artifacts"
    market_stock_codes: str = "600519,300750"
    analysis_universe_id: str = "demo_liquid_a_share"
    market_history_start: str = "20230101"
    market_adjust_type: str = "qfq"
    market_max_retries: int = Field(default=5, ge=0, le=8)
    market_retry_backoff_seconds: float = Field(default=3.0, ge=0, le=30)
    market_retry_max_backoff_seconds: float = Field(default=20.0, ge=0, le=120)
    milvus_host: str = "milvus"
    milvus_port: int = 19530
    reports_dir: str = "/data/reports"
    rag_embedding_model: str = "BAAI/bge-small-zh-v1.5"
    rag_keyword_index_path: str = "/lake/metadata/rag_indexes/research_reports_v2.sqlite"
    knowledge_source_path: str = ""
    knowledge_batch_limit: int = Field(default=100, ge=1, le=10_000)
    max_model_calls: int = Field(default=3, ge=1, le=10)
    max_tool_calls: int = Field(default=8, ge=1, le=20)
    max_plan_tasks: int = Field(default=6, ge=1, le=12)
    max_parallel_tools: int = Field(default=4, ge=1, le=8)
    max_evidence: int = Field(default=40, ge=1, le=100)
    max_tool_retries: int = Field(default=2, ge=0, le=3)
    max_report_revisions: int = Field(default=1, ge=0, le=1)
    max_replans: int = Field(default=1, ge=0, le=1)
    max_report_context_chars: int = Field(default=30000, ge=5000, le=100000)
    planner_prompt_version: str = "planner_v4"
    report_prompt_version: str = "report_v4"
    run_timeout_seconds: int = Field(default=420, ge=10, le=600)
    evaluation_reference_date: date | None = None
    orchestration_runtime: Literal["legacy", "langgraph"] = "langgraph"
    checkpoint_backend: Literal["memory", "postgres"] = "memory"
    checkpoint_database_url: str = (
        "postgresql://agent:agent-local@postgres:5432/financial_agent?sslmode=disable"
    )
    business_database_url: str = (
        "postgresql+asyncpg://agent:agent-local@postgres:5432/financial_agent"
    )
    database_pool_size: int = Field(default=8, ge=1, le=64)
    database_max_overflow: int = Field(default=8, ge=0, le=64)
    database_pool_timeout_seconds: float = Field(default=15.0, ge=1, le=120)
    checkpoint_encryption_enabled: bool = False
    checkpoint_aes_key: str = ""
    max_checkpoint_bytes: int = Field(default=2_000_000, ge=65_536, le=16_000_000)
    call_lease_seconds: int = Field(default=180, ge=30, le=600)
    skills_enabled: bool = True
    policy_version: str = "financial_read_only_v1"
    gateway_version: str = "gateway_v1"
    max_model_attempts: int = Field(default=9, ge=1, le=30)
    max_tool_attempts: int = Field(default=24, ge=1, le=60)
    max_run_tokens: int | None = Field(default=None, ge=1_000)
    max_run_cost_microunits: int | None = Field(default=None, ge=1)
    memory_enabled: bool = True
    session_memory_ttl_seconds: int = Field(
        default=2_592_000, ge=60, le=31_536_000
    )
    preference_memory_ttl_seconds: int | None = Field(
        default=None, ge=60, le=31_536_000
    )
    episodic_memory_ttl_seconds: int = Field(
        default=15_552_000, ge=60, le=31_536_000
    )
    context_model_summary_enabled: bool = False
    context_compression_enabled: bool = True
    context_summary_prompt_version: str = "context_summary_v1"
    job_worker_id: str = ""
    job_worker_concurrency: int = Field(default=2, ge=1, le=16)
    job_lease_seconds: int = Field(default=180, ge=30, le=600)
    job_poll_interval_seconds: float = Field(default=1.0, ge=0.1, le=30)
    job_sse_poll_interval_seconds: float = Field(
        default=0.5, ge=0.1, le=10
    )
    job_sse_heartbeat_seconds: float = Field(
        default=10.0, ge=1, le=60
    )
    analyze_via_jobs: bool = False
    analyze_sync_wait_seconds: float = Field(
        default=30.0, ge=0.1, le=300
    )
    job_global_queue_limit: int = Field(default=100, ge=1, le=10_000)
    job_tenant_queue_limit: int = Field(default=20, ge=1, le=1_000)
    job_user_queue_limit: int = Field(default=5, ge=1, le=200)
    job_global_running_limit: int = Field(default=8, ge=1, le=256)
    job_tenant_running_limit: int = Field(default=3, ge=1, le=64)
    job_user_running_limit: int = Field(default=2, ge=1, le=32)
    job_claim_scan_limit: int = Field(default=200, ge=10, le=10_000)
    job_admission_retry_after_seconds: int = Field(default=5, ge=1, le=300)
    provider_max_parallel_requests: int = Field(default=4, ge=1, le=64)
    provider_shared_rate_limit_enabled: bool = False
    provider_requests_per_minute: int = Field(default=60, ge=1, le=10_000)
    provider_rate_wait_seconds: int = Field(default=30, ge=0, le=300)
    demo_ui_enabled: bool = True

    @property
    def stock_codes(self) -> list[str]:
        return [code.strip() for code in self.market_stock_codes.split(",") if code.strip()]

    @property
    def allowed_stock_codes(self) -> list[str]:
        from financial_research_agent.analysis.registry import UniverseRegistry

        universe = UniverseRegistry.builtin().get(self.analysis_universe_id)
        return list(dict.fromkeys([*self.stock_codes, *universe.members]))


@lru_cache
def get_settings() -> Settings:
    return Settings()
