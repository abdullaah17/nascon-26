import hashlib
import hmac
import json

from app.core.config import get_settings


def canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sign_record(record_id: str, payload: object) -> str:
    message = f"{record_id}|{canonical_json(payload)}".encode("utf-8")
    return hmac.new(get_settings().day1_salt.encode("utf-8"), message, hashlib.sha256).hexdigest()
