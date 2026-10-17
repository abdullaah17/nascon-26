from typing import Any

from fastapi import APIRouter

from app.modules.fixtures.service import generate_fixtures


router = APIRouter(prefix="/audit/v1")


@router.post("/fixtures")
def fixtures(body: dict[str, Any]) -> dict:
    return generate_fixtures(body)
