from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.db import get_session
from app.modules.sports.service import create_sport


router = APIRouter(prefix="/audit/v1")


@router.post("/sports", status_code=201)
def sports(body: dict[str, Any], session: Session = Depends(get_session)) -> dict:
    return create_sport(session, body)
