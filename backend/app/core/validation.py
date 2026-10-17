import re
from typing import Any

from app.core.errors import ApiError


IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def require_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value) or "|" in value:
        raise ApiError(400, "VALIDATION_ERROR", "Request validation failed.", {"fields": [field]})
    return value


def validation_error(*fields: str) -> ApiError:
    return ApiError(400, "VALIDATION_ERROR", "Request validation failed.", {"fields": sorted(set(fields))})
