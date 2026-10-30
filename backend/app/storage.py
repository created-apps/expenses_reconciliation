"""Supabase Storage (private bucket `recon-files`) through the service role."""

import logging
import time
from collections.abc import Callable

import httpx
from fastapi import Depends
from storage3.exceptions import StorageApiError

from app.config import Settings, get_settings
from app.db import supabase_client

log = logging.getLogger("app.storage")

RETRYABLE_STATUS = {"429", "500", "502", "503", "504"}


class SupabaseStorage:
    def __init__(
        self,
        client,
        bucket: str,
        base_url: str,
        attempts: int = 4,
        backoff: float = 0.5,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.bucket = client.storage.from_(bucket)
        self.base_url = base_url.rstrip("/")
        self.attempts = attempts
        self.backoff = backoff
        self.sleep = sleep

    def put(self, path: str, data: bytes, content_type: str) -> None:
        """Upload, retrying brief network failures.

        Several uploads run side by side over pooled connections, and a connection the server
        has already closed raises `RemoteProtocolError: Server disconnected`. That is transient,
        so it is retried with a growing pause. The key sits under the file's own id, so a
        "already exists" answer on a retry means the earlier attempt did arrive.
        """
        for attempt in range(1, self.attempts + 1):
            try:
                self.bucket.upload(path, data, {"content-type": content_type})
                return
            except StorageApiError as exc:
                if str(exc.status) == "409":
                    return
                if str(exc.status) not in RETRYABLE_STATUS or attempt == self.attempts:
                    raise
                reason = f"storage status {exc.status}"
            except httpx.TransportError as exc:
                if attempt == self.attempts:
                    raise
                reason = type(exc).__name__
            log.warning("Upload of %s failed (%s); retry %d of %d", path, reason, attempt, self.attempts - 1)
            self.sleep(self.backoff * 2 ** (attempt - 1))

    def get(self, path: str) -> bytes:
        """Download a stored file, retrying brief network failures like `put`."""
        for attempt in range(1, self.attempts + 1):
            try:
                return self.bucket.download(path)
            except StorageApiError as exc:
                if str(exc.status) not in RETRYABLE_STATUS or attempt == self.attempts:
                    raise
                reason = f"storage status {exc.status}"
            except httpx.TransportError as exc:
                if attempt == self.attempts:
                    raise
                reason = type(exc).__name__
            log.warning("Download of %s failed (%s); retry %d of %d", path, reason, attempt, self.attempts - 1)
            self.sleep(self.backoff * 2 ** (attempt - 1))
        raise RuntimeError("unreachable")  # pragma: no cover

    def signed_url(self, path: str, expires_in: int) -> str:
        res = self.bucket.create_signed_url(path, expires_in)
        url = res.get("signedURL") or res.get("signedUrl")
        if not url:
            raise RuntimeError("Storage did not return a signed URL")
        # Some client versions return a path relative to the storage API.
        return url if url.startswith("http") else f"{self.base_url}/storage/v1{url}"

    def remove(self, paths: list[str]) -> None:
        for i in range(0, len(paths), 100):
            self.bucket.remove(paths[i : i + 100])

    def purge_prefix(self, prefix: str) -> int:
        """Remove every object under `prefix` (for example `cycles/<id>`), whether or not the
        database knows about it. Layout is `<prefix>/<file id>/<name>`. Returns how many were removed.

        Needed because an upload can reach storage even when the client saw an error (a dropped
        connection), which leaves an object with no database row to point at it.
        """
        paths: list[str] = []
        for entry in self._list(prefix):
            name = f"{prefix}/{entry['name']}"
            if entry.get("id") is None:  # a folder: list what is inside
                paths.extend(f"{name}/{inner['name']}" for inner in self._list(name) if inner.get("id") is not None)
            else:
                paths.append(name)
        if paths:
            self.remove(paths)
        return len(paths)

    def _list(self, path: str) -> list[dict]:
        entries: list[dict] = []
        while True:
            page = self.bucket.list(path, {"limit": 100, "offset": len(entries)})
            entries.extend(page)
            if len(page) < 100:
                return entries


def get_storage(settings: Settings = Depends(get_settings)) -> SupabaseStorage:
    return SupabaseStorage(supabase_client(settings), settings.storage_bucket, settings.supabase_url)
