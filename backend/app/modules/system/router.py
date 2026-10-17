from typing import Any

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.core.errors import ApiError
from app.modules.system.service import is_ready, reset_state


router = APIRouter()


@router.get("/health")
def health(session: Session = Depends(get_session)) -> dict:
    if not is_ready(session):
        raise ApiError(503, "NOT_READY", "Baseline data is not seeded.")
    return {"status": "ok"}


@router.post("/audit/v1/reset")
def reset(body: dict[str, Any] | None = Body(default=None), session: Session = Depends(get_session)) -> dict:
    body = body or {}
    seed = body.get("seed", 42)
    stock = body.get("stock")
    bad: list[str] = []
    if type(seed) is not int:
        bad.append("seed")
    if stock is not None:
        if not isinstance(stock, dict) or any(type(v) is not int or v < 0 for v in stock.values()):
            bad.append("stock")
    if bad:
        raise ApiError(400, "VALIDATION_ERROR", "Request validation failed.", {"fields": bad})
    return reset_state(session, seed, stock)
