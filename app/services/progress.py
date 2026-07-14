"""Cross-process progress store.

Progress was previously tracked in module-level dicts, which only works with a
single worker: under gunicorn/uvicorn multi-worker each process has its own
memory, so a status poll can land on a different worker than the one doing the
work and see stale/empty state.

This stores each progress entry as a small JSON file in a shared directory that
every worker on the host can read, so polling is consistent regardless of which
worker handles it. Writes are atomic (write-temp-then-rename) so readers never
observe a partially written file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path

_PROGRESS_DIR = Path(
    os.getenv("PROGRESS_DIR", str(Path(tempfile.gettempdir()) / "voyageur_progress"))
)

_logger = logging.getLogger(__name__)


def _path(namespace: str, key: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", f"{namespace}__{key.lower().strip()}")
    return _PROGRESS_DIR / f"{safe}.json"


def set_progress(namespace: str, key: str, data: dict) -> None:
    """Persist a progress record atomically. Best-effort: a write that loses a
    race never raises, so a progress hiccup can't abort the work being tracked.

    On Windows, os.replace onto a file another thread has briefly opened for
    reading (the status poll) raises PermissionError. That is transient, so the
    replace is retried a few times before giving up.
    """
    try:
        _PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(_PROGRESS_DIR), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            target = _path(namespace, key)
            for attempt in range(10):
                try:
                    os.replace(tmp, target)  # atomic
                    return
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.02)
        finally:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass
    except Exception as exc:
        _logger.warning("Failed to persist progress for %s/%s: %s", namespace, key, exc)


def get_progress(namespace: str, key: str, default: dict) -> dict:
    try:
        return json.loads(_path(namespace, key).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, PermissionError, OSError):
        return default


def clear_all() -> None:
    """Remove all persisted progress. Called on server startup: any record left
    from a previous process is stale because its in-flight task didn't survive
    the restart, so treating it as active would show a zombie progress bar."""
    try:
        if _PROGRESS_DIR.exists():
            for p in _PROGRESS_DIR.glob("*.json"):
                try:
                    p.unlink()
                except OSError:
                    pass
    except Exception as exc:
        _logger.warning("Failed to clear progress store: %s", exc)
