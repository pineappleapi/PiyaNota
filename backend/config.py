"""Runtime settings for the Flask API, loaded from PIYA_* environment variables.

Every setting may be overridden via its PIYA_ variable (field name upper-cased). Secrets fall back
to fixed dev values only in dev/test: in prod a missing secret is a startup error, so a deployment
can never run with a publicly known HMAC or hash key.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from typing import Any, Literal, cast, get_args

# Flask app.config key under which create_app stores the Settings instance.
SETTINGS_KEY = "PIYA_SETTINGS"

Env = Literal["dev", "test", "prod"]
StorageBackend = Literal["b2", "memory"]
MailBackend = Literal["brevo", "memory", "log"]

_ENVS: tuple[str, ...] = get_args(Env)
_STORAGE_BACKENDS: tuple[str, ...] = get_args(StorageBackend)
_MAIL_BACKENDS: tuple[str, ...] = get_args(MailBackend)
_TRUE_WORDS = frozenset({"1", "true", "yes", "on"})
_FALSE_WORDS = frozenset({"0", "false", "no", "off"})

_MB = 1024 * 1024
_DEV_DATABASE_URL = "postgresql://piya:piya@localhost:5432/piya_dev"
_TEST_DATABASE_URL = "postgresql://piya:piya@localhost:55432/piya_test"
# Dev-only fallbacks. Public knowledge by design: only ever used when PIYA_ENV is dev or test.
_DEV_RESET_CODE_HMAC_KEY = "dev-only-reset-code-hmac-key"
_DEV_LOG_HASH_KEY = "dev-only-log-hash-key"


@dataclass(frozen=True)
class Settings:
    """Immutable process configuration. Build it with load_settings(), not directly."""

    env: Env
    database_url: str
    reset_code_hmac_key: bytes
    log_hash_key: bytes
    require_https: bool = False
    argon2_time_cost: int = 2
    argon2_memory_kib: int = 19456
    session_ttl_days: int = 30
    reset_code_ttl_minutes: int = 30
    storage_backend: StorageBackend = "memory"
    b2_endpoint: str = ""
    b2_bucket: str = ""
    b2_key_id: str = ""
    b2_app_key: str = ""
    # Thumbnails are short-lived; audio and page images outlive a session so playback survives a seek.
    signed_url_ttl_seconds: int = 3600
    media_url_ttl_seconds: int = 21600
    mail_backend: MailBackend = "memory"
    brevo_api_key: str = ""
    mail_from: str = "noreply@localhost"
    mail_from_name: str = "PiyaNota"
    trusted_proxy_count: int = 1
    max_content_length: int = 100 * _MB
    max_image_bytes: int = 10 * _MB
    max_pdf_bytes: int = 50 * _MB
    max_image_pixels: int = 50_000_000
    standard_max_side_px: int = 3000
    pdf_render_dpi: int = 200
    submit_limit_per_hour: int = 10
    status_reads_per_minute: int = 120
    login_ip_limit: int = 30
    login_ip_window_s: int = 900
    # A choir signs up together from one venue Wi-Fi (one public IP) and typos count as attempts.
    signup_ip_limit: int = 60
    signup_ip_window_s: int = 3600
    reset_request_email_per_hour: int = 5
    reset_request_ip_per_hour: int = 20
    reset_code_ip_per_hour: int = 30
    change_password_limit: int = 5
    change_password_window_s: int = 900
    queue_capacity: int = 50
    run_background: bool = False
    background_interval_s: int = 600
    db_pool_max_size: int = 6
    # None keeps server-side prepared statements off, which is safe behind PgBouncer transaction mode.
    db_prepare_threshold: int | None = None


_DEFAULTS: dict[str, Any] = {f.name: f.default for f in fields(Settings)}


def _var(name: str) -> str:
    return f"PIYA_{name.upper()}"


def _raw(env: Mapping[str, str], name: str, alias: str | None = None) -> str | None:
    value = env.get(_var(name))
    if value is None and alias is not None:
        value = env.get(alias)
    if value is None or not value.strip():
        return None
    return value.strip()


def _read_str(
    env: Mapping[str, str],
    name: str,
    *,
    default: str,
    required: bool = False,
    alias: str | None = None,
) -> str:
    value = _raw(env, name, alias)
    if value is not None:
        return value
    if required:
        raise RuntimeError(f"{_var(name)} is required but not set")
    return default


def _read_choice(
    env: Mapping[str, str],
    name: str,
    choices: tuple[str, ...],
    *,
    default: str,
    required: bool = False,
) -> str:
    value = _read_str(env, name, default=default, required=required)
    if value not in choices:
        raise ValueError(f"{_var(name)} must be one of {', '.join(choices)}; got {value!r}")
    return value


def _parse_int(name: str, raw: str) -> int:
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{_var(name)} must be an integer; got {raw!r}") from exc


def _read_int(env: Mapping[str, str], name: str) -> int:
    raw = _raw(env, name)
    if raw is None:
        default: int = _DEFAULTS[name]
        return default
    return _parse_int(name, raw)


def _read_optional_int(env: Mapping[str, str], name: str) -> int | None:
    raw = _raw(env, name)
    return None if raw is None else _parse_int(name, raw)


def _read_bool(env: Mapping[str, str], name: str) -> bool:
    raw = _raw(env, name)
    if raw is None:
        default: bool = _DEFAULTS[name]
        return default
    word = raw.lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    raise ValueError(f"{_var(name)} must be a boolean (true/false); got {raw!r}")


def load_settings(env: Mapping[str, str] = os.environ) -> Settings:
    """Build Settings from an environment mapping.

    Args:
        env: Source of PIYA_* variables. Defaults to the live process environment.

    Returns:
        A frozen Settings instance.

    Raises:
        RuntimeError: A required setting is missing; the message names the variable.
        ValueError: A value is not a valid choice, integer or boolean.
    """
    mode = cast(Env, _read_choice(env, "env", _ENVS, default="dev"))
    is_prod = mode == "prod"
    storage = cast(
        StorageBackend,
        _read_choice(env, "storage_backend", _STORAGE_BACKENDS, default="memory", required=is_prod),
    )
    mail = cast(
        MailBackend,
        _read_choice(env, "mail_backend", _MAIL_BACKENDS, default="memory", required=is_prod),
    )
    require_https = _read_bool(env, "require_https")
    if is_prod and not require_https:
        raise RuntimeError("PIYA_REQUIRE_HTTPS must be true when PIYA_ENV=prod")
    dev_database_url = _TEST_DATABASE_URL if mode == "test" else _DEV_DATABASE_URL

    return Settings(
        env=mode,
        database_url=_read_str(
            env,
            "database_url",
            default=dev_database_url,
            required=is_prod,
            alias="DATABASE_URL",
        ),
        reset_code_hmac_key=_read_str(
            env, "reset_code_hmac_key", default=_DEV_RESET_CODE_HMAC_KEY, required=is_prod
        ).encode("utf-8"),
        log_hash_key=_read_str(
            env, "log_hash_key", default=_DEV_LOG_HASH_KEY, required=is_prod
        ).encode("utf-8"),
        require_https=require_https,
        argon2_time_cost=_read_int(env, "argon2_time_cost"),
        argon2_memory_kib=_read_int(env, "argon2_memory_kib"),
        session_ttl_days=_read_int(env, "session_ttl_days"),
        reset_code_ttl_minutes=_read_int(env, "reset_code_ttl_minutes"),
        storage_backend=storage,
        b2_endpoint=_read_str(env, "b2_endpoint", default="", required=storage == "b2"),
        b2_bucket=_read_str(env, "b2_bucket", default="", required=storage == "b2"),
        b2_key_id=_read_str(env, "b2_key_id", default="", required=storage == "b2"),
        b2_app_key=_read_str(env, "b2_app_key", default="", required=storage == "b2"),
        signed_url_ttl_seconds=_read_int(env, "signed_url_ttl_seconds"),
        media_url_ttl_seconds=_read_int(env, "media_url_ttl_seconds"),
        mail_backend=mail,
        brevo_api_key=_read_str(env, "brevo_api_key", default="", required=mail == "brevo"),
        mail_from=_read_str(env, "mail_from", default="noreply@localhost", required=is_prod),
        mail_from_name=_read_str(env, "mail_from_name", default="PiyaNota"),
        trusted_proxy_count=_read_int(env, "trusted_proxy_count"),
        max_content_length=_read_int(env, "max_content_length"),
        max_image_bytes=_read_int(env, "max_image_bytes"),
        max_pdf_bytes=_read_int(env, "max_pdf_bytes"),
        max_image_pixels=_read_int(env, "max_image_pixels"),
        standard_max_side_px=_read_int(env, "standard_max_side_px"),
        pdf_render_dpi=_read_int(env, "pdf_render_dpi"),
        submit_limit_per_hour=_read_int(env, "submit_limit_per_hour"),
        status_reads_per_minute=_read_int(env, "status_reads_per_minute"),
        login_ip_limit=_read_int(env, "login_ip_limit"),
        login_ip_window_s=_read_int(env, "login_ip_window_s"),
        signup_ip_limit=_read_int(env, "signup_ip_limit"),
        signup_ip_window_s=_read_int(env, "signup_ip_window_s"),
        reset_request_email_per_hour=_read_int(env, "reset_request_email_per_hour"),
        reset_request_ip_per_hour=_read_int(env, "reset_request_ip_per_hour"),
        reset_code_ip_per_hour=_read_int(env, "reset_code_ip_per_hour"),
        change_password_limit=_read_int(env, "change_password_limit"),
        change_password_window_s=_read_int(env, "change_password_window_s"),
        queue_capacity=_read_int(env, "queue_capacity"),
        run_background=_read_bool(env, "run_background"),
        background_interval_s=_read_int(env, "background_interval_s"),
        db_pool_max_size=_read_int(env, "db_pool_max_size"),
        db_prepare_threshold=_read_optional_int(env, "db_prepare_threshold"),
    )
