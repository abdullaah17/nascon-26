import re

from sqlalchemy.orm import Session

from app.core.errors import ApiError
from app.core.models import Sport


SPORT_ID_RE = re.compile(r"^[a-z0-9_-]{2,40}$")
EVENT_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MODELS = {"event", "innings", "round"}
OVERTIME = {"none", "extra_time", "shootout", "golden_score", "super_over"}
TIE_BREAKS = ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"]


def _positive_int(value: object) -> bool:
    return type(value) is int and value >= 1


def validate_sport(data: dict) -> dict:
    bad: list[str] = []
    sport_id = data.get("sport_id")
    name = data.get("name")
    model = data.get("scoring_model")
    periods = data.get("periods")
    events = data.get("scoring_events")
    draw_allowed = data.get("draw_allowed")
    overtime = data.get("overtime")
    roster = data.get("roster")
    ties = data.get("tie_break_order", TIE_BREAKS)

    if not isinstance(sport_id, str) or not SPORT_ID_RE.fullmatch(sport_id): bad.append("sport_id")
    if not isinstance(name, str) or not 1 <= len(name) <= 80: bad.append("name")
    if model not in MODELS: bad.append("scoring_model")
    if not isinstance(periods, dict): bad.append("periods")
    elif model == "event" and not all(_positive_int(periods.get(k)) for k in ("count", "duration_minutes")): bad.append("periods")
    elif model == "innings" and not all(_positive_int(periods.get(k)) for k in ("innings_per_team", "overs_per_innings", "balls_per_over", "wickets_per_innings")): bad.append("periods")
    elif model == "round" and (not _positive_int(periods.get("best_of")) or periods["best_of"] % 2 == 0): bad.append("periods")

    if not isinstance(events, dict) or not events: bad.append("scoring_events")
    elif any(not isinstance(key, str) or not EVENT_RE.fullmatch(key) for key in events): bad.append("scoring_events")
    elif model == "event" and any(not isinstance(v, dict) or not _positive_int(v.get("points")) for v in events.values()): bad.append("scoring_events")
    elif model == "innings" and any(not isinstance(v, dict) or type(v.get("runs")) is not int or v["runs"] < 0 or type(v.get("legal_ball")) is not bool or type(v.get("wicket")) is not bool for v in events.values()): bad.append("scoring_events")
    elif model == "round" and any(not isinstance(v, dict) or not _positive_int(v.get("rounds")) for v in events.values()): bad.append("scoring_events")
    if type(draw_allowed) is not bool: bad.append("draw_allowed")
    if not isinstance(overtime, dict) or overtime.get("policy") not in OVERTIME or ("duration_minutes" in overtime and (type(overtime["duration_minutes"]) is not int or overtime["duration_minutes"] < 0)): bad.append("overtime")
    if not isinstance(ties, list) or len(set(ties)) != len(ties) or any(t not in TIE_BREAKS for t in ties): bad.append("tie_break_order")
    if not isinstance(roster, dict): bad.append("roster")
    else:
        minimum, maximum, positions = roster.get("min_squad_size"), roster.get("max_squad_size"), roster.get("required_positions")
        if not _positive_int(minimum) or not _positive_int(maximum) or minimum > maximum or not isinstance(positions, dict) or any(not isinstance(k, str) or type(v) is not int or v < 0 for k, v in positions.items()): bad.append("roster")
    if bad:
        raise ApiError(400, "VALIDATION_ERROR", "Request validation failed.", {"fields": sorted(set(bad))})
    config = {key: data[key] for key in ("sport_id", "name", "scoring_model", "periods", "scoring_events", "draw_allowed", "overtime", "roster")}
    normalized_ties = [tie for tie in ties if tie != "draw_lots"] + ["draw_lots"]
    config["tie_break_order"] = normalized_ties
    return config


def create_sport(session: Session, data: dict) -> dict:
    config = validate_sport(data)
    if session.get(Sport, config["sport_id"]):
        raise ApiError(409, "SPORT_EXISTS", f"Sport {config['sport_id']} already exists.", {"sport_id": config["sport_id"]})
    session.add(Sport(sport_id=config["sport_id"], name=config["name"], config=config, baseline=False))
    session.commit()
    return {"sport_id": config["sport_id"], "status": "created", "config": config}
