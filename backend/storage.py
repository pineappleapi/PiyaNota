"""Object storage: Backblaze B2 (S3 API) in production, an in-memory dict in tests."""

from __future__ import annotations

import hashlib
import hmac
import re
import time
import uuid
from typing import Any, Literal, Protocol
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from flask import current_app

from backend import db
from backend.config import Settings

KeyPrefix = Literal["pages", "thumbs", "audio", "timing", "midi"]
_NOT_FOUND_CODES = frozenset({"NoSuchKey", "404", "NotFound"})
# B2 S3 endpoints look like https://s3.us-west-004.backblazeb2.com
B2_CONNECT_TIMEOUT_S = 5
B2_READ_TIMEOUT_S = 15
B2_MAX_ATTEMPTS = 2
# Caps the memory backend so a 512 MB host fails with a clear error instead of being OOM-killed.
MEMORY_STORAGE_MAX_BYTES = 200 * 1024 * 1024
_REGION_RE = re.compile(r"s3\.([a-z0-9-]+)\.backblazeb2\.com")


class Storage(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None:
        """Remove ``key``; a missing key is not an error."""

    def size(self, key: str) -> int:
        """Stored byte length of ``key``."""

    def signed_url(self, key: str, *, ttl_seconds: int | None = None) -> str: ...


def new_key(prefix: KeyPrefix, ext: str) -> str:
    """Random object key; unguessable and free of user input."""
    return f"{prefix}/{uuid.uuid4()}.{ext}"


class MemoryStorageFull(RuntimeError):
    """The in-memory backend reached MEMORY_STORAGE_MAX_BYTES."""


class MemoryStorage:
    """Test double and no-account deploy backend, backed by a dict."""

    def __init__(self, default_ttl_seconds: int = 3600) -> None:
        self.objects: dict[str, bytes] = {}
        self.ttls: dict[str, int] = {}  # effective TTL of the last signed_url per key, for tests
        self._default_ttl = default_ttl_seconds

    def put(self, key: str, data: bytes, content_type: str) -> None:
        total = sum(map(len, self.objects.values())) - len(self.objects.get(key, b"")) + len(data)
        if total > MEMORY_STORAGE_MAX_BYTES:
            raise MemoryStorageFull(f"memory storage is full ({MEMORY_STORAGE_MAX_BYTES} bytes)")
        self.objects[key] = data

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    def size(self, key: str) -> int:
        return len(self.objects.get(key, b""))  # unknown key is 0: tests seed rows without blobs

    def signed_url(self, key: str, *, ttl_seconds: int | None = None) -> str:
        self.ttls[key] = ttl_seconds if ttl_seconds is not None else self._default_ttl
        return f"https://storage.test/{key}?sig=fake"


def sign_media(key: str, exp: int, hmac_key: bytes) -> str:
    """Hex HMAC-SHA256 over ``key\\nexp``; the newline keeps key and expiry unambiguous."""
    return hmac.new(hmac_key, f"{key}\n{exp}".encode("utf-8"), hashlib.sha256).hexdigest()


class DbStorage:
    """Objects in the ``blobs`` table, so the API and a separate worker process share files.

    Each call opens its own transaction; ``signed_url`` points at this API's /media route.
    """

    def __init__(self, settings: Settings) -> None:
        self._hmac_key = settings.media_hmac_key
        self._base_url = settings.public_base_url
        self._default_ttl = settings.signed_url_ttl_seconds

    def put(self, key: str, data: bytes, content_type: str) -> None:
        with db.transaction() as conn:
            conn.execute(
                "INSERT INTO blobs (key, content_type, data) VALUES (%s, %s, %s) "
                "ON CONFLICT (key) DO UPDATE SET content_type = EXCLUDED.content_type, "
                "data = EXCLUDED.data, created_at = now()",
                (key, content_type, data),
            )

    def get(self, key: str) -> bytes:
        with db.transaction() as conn:
            row = conn.execute("SELECT data FROM blobs WHERE key = %s", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return bytes(row["data"])

    def delete(self, key: str) -> None:
        with db.transaction() as conn:
            conn.execute("DELETE FROM blobs WHERE key = %s", (key,))

    def size(self, key: str) -> int:
        with db.transaction() as conn:
            row = conn.execute("SELECT octet_length(data) AS n FROM blobs WHERE key = %s", (key,)).fetchone()
        if row is None:
            raise KeyError(key)
        return int(row["n"])

    def signed_url(self, key: str, *, ttl_seconds: int | None = None) -> str:
        exp = int(time.time()) + (ttl_seconds if ttl_seconds is not None else self._default_ttl)
        sig = sign_media(key, exp, self._hmac_key)
        return f"{self._base_url}/media/{quote(key, safe='/')}?exp={exp}&sig={sig}"


class B2Storage:
    """Backblaze B2 through boto3's S3 client."""

    def __init__(self, settings: Settings) -> None:
        match = _REGION_RE.search(settings.b2_endpoint)
        if match is None:
            raise ValueError("PIYA_B2_ENDPOINT must look like https://s3.<region>.backblazeb2.com")
        self._bucket = settings.b2_bucket
        self._default_ttl = settings.signed_url_ttl_seconds
        # region_name is required for s3v4 presigning; B2 embeds it in the endpoint host.
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=settings.b2_endpoint,
            region_name=match.group(1),
            aws_access_key_id=settings.b2_key_id,
            aws_secret_access_key=settings.b2_app_key,
            config=Config(
                signature_version="s3v4",
                connect_timeout=B2_CONNECT_TIMEOUT_S,
                read_timeout=B2_READ_TIMEOUT_S,
                retries={"max_attempts": B2_MAX_ATTEMPTS},
            ),
        )

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data, ContentType=content_type)

    def get(self, key: str) -> bytes:
        body: bytes = self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        return body

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in _NOT_FOUND_CODES:
                raise

    def size(self, key: str) -> int:
        return int(self._client.head_object(Bucket=self._bucket, Key=key)["ContentLength"])

    def signed_url(self, key: str, *, ttl_seconds: int | None = None) -> str:
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=ttl_seconds if ttl_seconds is not None else self._default_ttl,
        )
        return url


def build_storage(settings: Settings) -> Storage:
    """Pick the backend named in settings."""
    if settings.storage_backend == "b2":
        return B2Storage(settings)
    if settings.storage_backend == "db":
        return DbStorage(settings)
    return MemoryStorage(settings.signed_url_ttl_seconds)


def get_storage() -> Storage:
    """Storage of the current app; needs an app context."""
    storage: Storage = current_app.extensions["storage"]
    return storage
