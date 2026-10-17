import hashlib
import hmac
import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import jwt
import redis
from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy import Column, Integer, MetaData, Table, create_engine, select, text, update
from sqlalchemy.dialects.postgresql import JSONB


DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://app:app@localhost:5432/nascon")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DAY1_SALT = os.getenv("DAY1_SALT", "")
JWT_SECRET = os.getenv("JWT_SECRET", "nascon-local-jwt-secret-change-me")

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
cache = redis.Redis.from_url(REDIS_URL, decode_responses=True)
metadata = MetaData()
state_table = Table(
    "app_state",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("revision", Integer, nullable=False, default=0),
    Column("data", JSONB, nullable=False),
)


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content={"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
    )


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_record(record_id: str, payload: Any) -> str:
    message = f"{record_id}|{canonical(payload)}".encode("utf-8")
    return hmac.new(DAY1_SALT.encode("utf-8"), message, hashlib.sha256).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_database() -> None:
    last = None
    for _ in range(60):
        try:
            metadata.create_all(engine)
            with engine.begin() as conn:
                if conn.execute(select(state_table.c.id).where(state_table.c.id == 1)).first() is None:
                    conn.execute(state_table.insert().values(id=1, revision=0, data={}))
            cache.ping()
            return
        except Exception as exc:  # pragma: no cover - startup retry
            last = exc
            time.sleep(1)
    raise RuntimeError("database/cache not ready") from last


@contextmanager
def locked_state():
    with engine.begin() as conn:
        row = conn.execute(
            select(state_table.c.data, state_table.c.revision)
            .where(state_table.c.id == 1)
            .with_for_update()
        ).mappings().one()
        data = dict(row["data"] or {})
        yield data
        conn.execute(
            update(state_table)
            .where(state_table.c.id == 1)
            .values(data=data, revision=row["revision"] + 1)
        )


def read_state() -> dict:
    with engine.connect() as conn:
        row = conn.execute(select(state_table.c.data).where(state_table.c.id == 1)).first()
        return dict(row[0] or {})


def replace_state(data: dict) -> None:
    with engine.begin() as conn:
        conn.execute(update(state_table).where(state_table.c.id == 1).values(data=data, revision=0))


def make_token(role: str, **claims: Any) -> str:
    payload = {
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + 7200,
        **claims,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") != "HS256":
            raise ValueError("invalid alg")
        return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    except Exception as exc:
        raise ApiError(401, "UNAUTHENTICATED", "Invalid or expired token.") from exc


def require_fields(body: dict, names: list[str]) -> None:
    missing = [name for name in names if name not in body]
    if missing:
        raise ApiError(400, "VALIDATION_ERROR", "Missing required fields.", {"fields": missing})


def body_fingerprint(body: Any) -> str:
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


async def body_limit_middleware(request: Request, call_next):
    length = request.headers.get("content-length")
    if request.method in {"POST", "PUT", "PATCH"} and length:
        try:
            if int(length) > 1024 * 1024:
                return error_response(ApiError(413, "PAYLOAD_TOO_LARGE", "Body exceeds 1 MB."))
        except ValueError:
            pass
    if request.method in {"POST", "PUT", "PATCH"}:
        body = await request.body()
        if len(body) > 1024 * 1024:
            return error_response(ApiError(413, "PAYLOAD_TOO_LARGE", "Body exceeds 1 MB."))
        request._body = body
    return await call_next(request)


def db_ready() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        cache.ping()
        return True
    except Exception:
        return False
