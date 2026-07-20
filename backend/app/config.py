from functools import lru_cache
import re
from urllib.parse import urlparse

from pydantic import computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/serpstrategist"
    redis_url: str = ""

    secret_key: str = "change-me-in-production"
    oauth_bridge_secret: str = ""
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440

    ai_gateway_base_url: str = "https://api.17.wtf/v1"
    ai_gateway_api_key: str = ""
    ai_primary_model: str = "posiden/deepseek-v4-flash"
    ai_reasoning_model: str = "zeus/claude-sonnet-4-6"
    ai_fallback_model: str = "latina/gpt-5.6-terra"
    ai_secondary_fallback_model: str = "latina/gpt-5.6-luna"
    ai_gateway_timeout_seconds: float = 30.0

    serpapi_api_key: str = ""
    serpapi_base_url: str = "https://serpapi.com/search.json"
    serpapi_timeout_seconds: float = 20.0

    stripe_api_base_url: str = "https://api.stripe.com/v1"
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_growth_price_id: str = ""
    stripe_scale_price_id: str = ""
    stripe_timeout_seconds: float = 20.0

    google_integration_client_id: str = ""
    google_integration_client_secret: str = ""
    google_integration_redirect_uri: str = ""
    google_oauth_authorize_url: str = "https://accounts.google.com/o/oauth2/v2/auth"
    google_oauth_token_url: str = "https://oauth2.googleapis.com/token"
    google_userinfo_url: str = "https://openidconnect.googleapis.com/v1/userinfo"
    google_search_console_api_url: str = "https://www.googleapis.com/webmasters/v3"
    google_search_console_inspection_api_url: str = (
        "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
    )
    google_analytics_admin_api_url: str = "https://analyticsadmin.googleapis.com/v1beta"
    google_integration_timeout_seconds: float = 20.0

    github_api_url: str = "https://api.github.com"
    github_app_id: str = ""
    github_app_slug: str = ""
    github_app_private_key_base64: str = ""
    github_app_state_ttl_minutes: int = 10
    github_app_timeout_seconds: float = 20.0
    # Real repository mutation is an explicit production rollout gate. The App
    # authorization flow remains useful while this flag is disabled.
    github_execution_enabled: bool = False
    github_execution_branch_prefix: str = "serp-operator"
    github_execution_max_files: int = 20
    github_execution_max_file_bytes: int = 262_144
    github_execution_max_total_bytes: int = 1_048_576
    # Repository source is sent to the configured server-side AI gateway only
    # when this explicit planning gate is enabled. Generated full-file patches
    # still require operator approval before the GitHub adapter may execute.
    github_patch_planning_enabled: bool = False
    github_patch_planning_max_actions_per_refresh: int = 3
    github_patch_planning_max_tree_entries: int = 5_000
    github_patch_planning_max_source_files: int = 25
    github_patch_planning_max_candidate_bytes: int = 65_536
    github_patch_planning_max_changed_lines: int = 200

    wordpress_url: str = ""
    wordpress_user: str = ""
    wordpress_app_password: str = ""

    # LibreCrawl remains optional enrichment only. The first-party crawler is authoritative.
    librecrawl_host: str = "127.0.0.1"
    librecrawl_port: int = 5080
    librecrawl_mcp_port: int = 5081
    librecrawl_enabled: bool = False

    # Bounded first-party crawler settings.
    crawler_user_agent: str = "SERPStrategistsBot/1.0 (+https://serpstrategists.com/bot)"
    crawler_timeout_seconds: float = 20.0
    crawler_connect_timeout_seconds: float = 6.0
    crawler_concurrency: int = 4
    crawler_request_delay_ms: int = 150
    crawler_max_response_bytes: int = 2_000_000
    crawler_max_redirects: int = 5
    crawler_sitemap_limit: int = 10
    crawler_render_enabled: bool = False
    crawler_render_max_pages: int = 10
    crawler_render_timeout_seconds: float = 15.0
    crawler_device_compare_max_pages: int = 3
    crawler_adaptive_max_delay_seconds: float = 8.0

    # Durable crawl queue. PostgreSQL is authoritative; Redis only reduces wake-up latency.
    crawl_worker_enabled: bool = False
    crawl_worker_poll_seconds: int = 3
    crawl_worker_batch_size: int = 2
    crawl_job_lease_seconds: int = 120
    crawl_job_max_attempts: int = 3
    crawl_retry_base_seconds: int = 5
    crawl_queue_key: str = "serp:crawl:ready"

    # Durable Search Console ingestion and measurement worker.
    search_sync_worker_enabled: bool = False
    search_sync_worker_poll_seconds: int = 15
    search_sync_worker_batch_size: int = 2
    search_sync_job_lease_seconds: int = 180
    search_sync_job_max_attempts: int = 4
    search_sync_retry_base_seconds: int = 30
    search_sync_queue_key: str = "serp:gsc-sync:ready"
    search_sync_lookback_days: int = 90
    search_sync_finalization_lag_days: int = 3
    search_sync_page_size: int = 25_000
    search_sync_max_rows: int = 100_000
    search_sync_max_total_rows: int = 500_000
    search_sync_min_interval_minutes: int = 1_440
    search_opportunity_action_limit: int = 100

    # Durable URL Inspection queue. Keep disabled until migration 020 is applied.
    url_inspection_worker_enabled: bool = False
    url_inspection_worker_poll_seconds: int = 15
    url_inspection_worker_batch_size: int = 1
    url_inspection_job_lease_seconds: int = 180
    url_inspection_job_max_attempts: int = 4
    url_inspection_retry_base_seconds: int = 60
    url_inspection_queue_key: str = "serp:gsc-url-inspection:ready"
    url_inspection_max_urls_per_job: int = 50
    url_inspection_min_interval_minutes: int = 1_440

    app_env: str = "development"
    debug: bool = True
    frontend_url: str = "http://localhost:3000"
    cors_origins: str = ""
    scheduler_enabled: bool = False

    # Durable governed execution. Disabled by default until explicitly enabled on a worker service.
    execution_worker_enabled: bool = False
    execution_worker_poll_seconds: int = 5
    execution_worker_batch_size: int = 5
    execution_job_lease_seconds: int = 120
    execution_job_max_attempts: int = 3
    execution_retry_base_seconds: int = 5
    execution_queue_key: str = "serp:execution:ready"

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+asyncpg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @field_validator(
        "ai_gateway_base_url",
        "serpapi_base_url",
        "stripe_api_base_url",
        "google_oauth_authorize_url",
        "google_oauth_token_url",
        "google_userinfo_url",
        "google_search_console_api_url",
        "google_search_console_inspection_api_url",
        "google_analytics_admin_api_url",
        "github_api_url",
    )
    @classmethod
    def normalize_provider_url(cls, value: str) -> str:
        normalized = value.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Provider base URLs must be absolute HTTP or HTTPS URLs")
        if parsed.username or parsed.password:
            raise ValueError("Provider base URLs cannot contain embedded credentials")
        return normalized

    @field_validator("github_app_slug")
    @classmethod
    def normalize_github_app_slug(cls, value: str) -> str:
        normalized = value.strip()
        if normalized and not re.fullmatch(r"[A-Za-z0-9-]+", normalized):
            raise ValueError("GITHUB_APP_SLUG may contain only letters, numbers, and hyphens")
        return normalized

    @field_validator("github_execution_branch_prefix")
    @classmethod
    def normalize_github_execution_branch_prefix(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if not re.fullmatch(r"[A-Za-z0-9._-]+", normalized):
            raise ValueError(
                "GITHUB_EXECUTION_BRANCH_PREFIX may contain only letters, numbers, dots, underscores, and hyphens"
            )
        return normalized

    @model_validator(mode="after")
    def validate_secure_environment(self) -> "Settings":
        if self.app_env.lower() in {"staging", "production"}:
            if self.secret_key == "change-me-in-production" or len(self.secret_key) < 32:
                raise ValueError("SECRET_KEY must be at least 32 characters in staging and production")
            if not self.frontend_url.startswith(("http://", "https://")):
                raise ValueError("FRONTEND_URL must be an absolute URL")
        if self.oauth_bridge_secret and len(self.oauth_bridge_secret) < 32:
            raise ValueError("OAUTH_BRIDGE_SECRET must be at least 32 characters when configured")
        github_app_values = (
            self.github_app_id,
            self.github_app_slug,
            self.github_app_private_key_base64,
        )
        if any(github_app_values) and not all(github_app_values):
            raise ValueError(
                "GITHUB_APP_ID, GITHUB_APP_SLUG, and GITHUB_APP_PRIVATE_KEY_BASE64 must be configured together"
            )
        if self.github_app_state_ttl_minutes <= 0 or self.github_app_state_ttl_minutes > 60:
            raise ValueError("GITHUB_APP_STATE_TTL_MINUTES must be between 1 and 60")
        if (
            self.ai_gateway_timeout_seconds <= 0
            or self.serpapi_timeout_seconds <= 0
            or self.stripe_timeout_seconds <= 0
            or self.google_integration_timeout_seconds <= 0
            or self.github_app_timeout_seconds <= 0
            or self.crawler_timeout_seconds <= 0
            or self.crawler_connect_timeout_seconds <= 0
            or self.crawler_render_timeout_seconds <= 0
        ):
            raise ValueError("Provider and crawler timeouts must be greater than zero")
        if (
            self.github_patch_planning_max_actions_per_refresh <= 0
            or self.github_patch_planning_max_tree_entries <= 0
            or self.github_patch_planning_max_source_files <= 0
            or self.github_patch_planning_max_candidate_bytes <= 0
            or self.github_patch_planning_max_changed_lines <= 0
        ):
            raise ValueError("GitHub patch planning limits must be greater than zero")
        if self.github_patch_planning_enabled and not all(github_app_values):
            raise ValueError(
                "GitHub patch planning requires GITHUB_APP_ID, GITHUB_APP_SLUG, and GITHUB_APP_PRIVATE_KEY_BASE64"
            )
        if self.github_patch_planning_enabled and not self.ai_gateway_api_key:
            raise ValueError("GitHub patch planning requires AI_GATEWAY_API_KEY")
        if self.github_execution_enabled and not all(github_app_values):
            raise ValueError(
                "GitHub execution requires GITHUB_APP_ID, GITHUB_APP_SLUG, and GITHUB_APP_PRIVATE_KEY_BASE64"
            )
        if (
            self.execution_worker_poll_seconds <= 0
            or self.execution_worker_batch_size <= 0
            or self.execution_job_lease_seconds <= 0
            or self.execution_job_max_attempts <= 0
            or self.execution_retry_base_seconds <= 0
            or self.crawl_worker_poll_seconds <= 0
            or self.crawl_worker_batch_size <= 0
            or self.crawl_job_lease_seconds <= 0
            or self.crawl_job_max_attempts <= 0
            or self.crawl_retry_base_seconds <= 0
            or self.search_sync_worker_poll_seconds <= 0
            or self.search_sync_worker_batch_size <= 0
            or self.search_sync_job_lease_seconds <= 0
            or self.search_sync_job_max_attempts <= 0
            or self.search_sync_retry_base_seconds <= 0
            or self.search_sync_lookback_days < 28
            or not 2 <= self.search_sync_finalization_lag_days <= 7
            or self.search_sync_page_size <= 0
            or self.search_sync_page_size > 25_000
            or self.search_sync_max_rows <= 0
            or self.search_sync_max_total_rows <= 0
            or self.search_sync_min_interval_minutes < 0
            or not 1 <= self.search_opportunity_action_limit <= 500
            or self.url_inspection_worker_poll_seconds <= 0
            or self.url_inspection_worker_batch_size <= 0
            or self.url_inspection_job_lease_seconds <= 0
            or self.url_inspection_job_max_attempts <= 0
            or self.url_inspection_retry_base_seconds <= 0
            or not 1 <= self.url_inspection_max_urls_per_job <= 200
            or self.url_inspection_min_interval_minutes < 0
            or self.crawler_concurrency <= 0
            or self.crawler_max_response_bytes <= 0
            or self.crawler_max_redirects <= 0
            or self.crawler_sitemap_limit <= 0
            or self.crawler_render_max_pages < 0
            or self.crawler_device_compare_max_pages < 0
            or self.crawler_adaptive_max_delay_seconds <= 0
            or self.crawler_request_delay_ms < 0
            or not 1 <= self.github_execution_max_files <= 100
            or not 1_024 <= self.github_execution_max_file_bytes <= 2_000_000
            or self.github_execution_max_total_bytes < self.github_execution_max_file_bytes
            or self.github_execution_max_total_bytes > 10_000_000
        ):
            raise ValueError("Execution worker and crawler limits must be valid positive values")
        if self.stripe_secret_key and not self.stripe_secret_key.startswith(("sk_test_", "sk_live_")):
            raise ValueError("STRIPE_SECRET_KEY must be a Stripe secret key")
        if self.stripe_webhook_secret and not self.stripe_webhook_secret.startswith("whsec_"):
            raise ValueError("STRIPE_WEBHOOK_SECRET must be a Stripe webhook signing secret")
        if self.google_integration_redirect_uri:
            parsed = urlparse(self.google_integration_redirect_uri)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("GOOGLE_INTEGRATION_REDIRECT_URI must be an absolute URL")
        return self

    @computed_field
    @property
    def allowed_origins(self) -> list[str]:
        configured = [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]
        return list(dict.fromkeys([self.frontend_url, *configured]))

    @computed_field
    @property
    def stripe_price_plan_map(self) -> dict[str, str]:
        return {
            price_id: plan
            for price_id, plan in (
                (self.stripe_growth_price_id, "growth"),
                (self.stripe_scale_price_id, "scale"),
            )
            if price_id
        }

    model_config = {"env_file": ".env", "extra": "ignore", "case_sensitive": False}


@lru_cache
def get_settings() -> Settings:
    return Settings()
