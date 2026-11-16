from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Any

MISSING = object()


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def path_get(value, path, default=MISSING):
    if not isinstance(path, list):
        return default
    for key in path:
        try:
            if isinstance(value, dict) and isinstance(key, str):
                value = value[key]
            elif isinstance(value, list) and type(key) is int:
                value = value[key]
            else:
                return default
        except (KeyError, IndexError):
            return default
    return value


@dataclass
class Result:
    status: str
    observations: list[dict[str, Any]] = field(default_factory=list)
    error_code: str | None = None
    coverage: str = "unknown"
    expected_count: int | None = None
    candidates: list[dict[str, Any]] = field(default_factory=list)
