import base64
import io
import json
import math
import re
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .algorithms import double_elim, lots_key, round_robin, single_elim, swiss
from .baseline import initial_state
from .runtime import (
    ApiError, body_fingerprint, body_limit_middleware, cache, db_ready, decode_token,
    error_response, init_database, locked_state, make_token, read_state, replace_state,
    require_fields, sign_record, utc_now,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_database()
    if not read_state().get("sports"):
        replace_state(initial_state())
    yield


app = FastAPI(title="NaSCon 26 Part I", lifespan=lifespan)
app.middleware("http")(body_limit_middleware)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError):
    return error_response(exc)


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    fields = [".".join(str(x) for x in e["loc"][1:]) for e in exc.errors()]
    return error_response(ApiError(400, "VALIDATION_ERROR", "Request validation failed.", {"fields": fields}))


@app.exception_handler(Exception)
async def unexpected_handler(_: Request, exc: Exception):
    # Keep raw exceptions away from clients while retaining a valid contract body.
    if isinstance(exc, json.JSONDecodeError):
        return error_response(ApiError(400, "VALIDATION_ERROR", "Malformed JSON body.", {"fields": ["body"]}))
    return error_response(ApiError(500, "INTERNAL_ERROR", "Internal server error."))


@app.get("/health")
def health():
    state = read_state()
    if not db_ready() or not state.get("sports") or not state.get("tenants"):
        raise ApiError(503, "NOT_READY", "Dependencies or baseline data are not ready.")
    return {"status": "ok"}


@app.post("/audit/v1/reset")
async def reset(request: Request):
    raw = await request.body()
    if not raw:
        body = {}
    else:
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ApiError(400, "VALIDATION_ERROR", "Malformed JSON body.", {"fields": ["body"]}) from exc
    if body is None: body = {}
    if not isinstance(body, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    seed = body.get("seed", 42)
    stock = body.get("stock", {"var-jersey-001-M": 1, "var-jersey-001-L": 5})
    if not isinstance(seed, int) or not isinstance(stock, dict) or any(not isinstance(v, int) or v < 0 for v in stock.values()):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid reset parameters.", {"fields": ["seed", "stock"]})
    replace_state(initial_state(seed, stock))
    cache.flushdb()
    return {"status": "reset_complete", "seed": seed,
        "sports": ["football", "basketball", "cricket", "esports"],
        "tenants": ["tenant-alpha", "tenant-beta"], "stock": stock}


SPORT_RE = re.compile(r"^[a-z0-9_-]{2,40}$")
EVENT_RE = re.compile(r"^[a-z0-9_]{1,40}$")
TIE_TOKENS = {"h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"}


def validate_sport(body: dict) -> None:
    require_fields(body, ["sport_id", "name", "scoring_model", "periods", "scoring_events", "draw_allowed", "overtime", "roster"])
    bad = []
    sid = body.get("sport_id")
    if not isinstance(sid, str) or not SPORT_RE.fullmatch(sid): bad.append("sport_id")
    if not isinstance(body.get("name"), str) or not 1 <= len(body["name"]) <= 80: bad.append("name")
    model = body.get("scoring_model")
    if model not in ("event", "innings", "round"): bad.append("scoring_model")
    events = body.get("scoring_events")
    if not isinstance(events, dict) or not events: bad.append("scoring_events")
    elif any(not EVENT_RE.fullmatch(k) or not isinstance(v, dict) for k, v in events.items()): bad.append("scoring_events")
    periods = body.get("periods")
    if not isinstance(periods, dict): bad.append("periods")
    elif model == "event" and (not isinstance(periods.get("count"), int) or periods.get("count", 0) < 1 or not isinstance(periods.get("duration_minutes"), int) or periods.get("duration_minutes", 0) < 1): bad.append("periods")
    elif model == "innings" and any(not isinstance(periods.get(k), int) or periods.get(k, 0) < 1 for k in ("innings_per_team", "overs_per_innings", "balls_per_over", "wickets_per_innings")): bad.append("periods")
    elif model == "round" and (not isinstance(periods.get("best_of"), int) or periods.get("best_of", 0) < 1 or periods.get("best_of") % 2 == 0): bad.append("periods")
    if model == "event" and isinstance(events, dict) and any(not isinstance(v.get("points"), int) or v.get("points", 0) < 1 for v in events.values()): bad.append("scoring_events")
    if model == "innings" and isinstance(events, dict) and any(not isinstance(v.get("runs"), int) or v.get("runs", -1) < 0 or not isinstance(v.get("legal_ball"), bool) or not isinstance(v.get("wicket"), bool) for v in events.values()): bad.append("scoring_events")
    if model == "round" and isinstance(events, dict) and any(not isinstance(v.get("rounds"), int) or v.get("rounds", 0) < 1 for v in events.values()): bad.append("scoring_events")
    if not isinstance(body.get("draw_allowed"), bool): bad.append("draw_allowed")
    overtime = body.get("overtime")
    if not isinstance(overtime, dict) or overtime.get("policy") not in ("none", "extra_time", "shootout", "golden_score", "super_over"): bad.append("overtime")
    order = body.get("tie_break_order")
    if order is not None and (not isinstance(order, list) or len(set(order)) != len(order) or any(x not in TIE_TOKENS for x in order)): bad.append("tie_break_order")
    roster = body.get("roster")
    if not isinstance(roster, dict) or not isinstance(roster.get("min_squad_size"), int) or not isinstance(roster.get("max_squad_size"), int) or roster.get("min_squad_size", 0) < 1 or roster.get("max_squad_size", 0) < roster.get("min_squad_size", 1) or not isinstance(roster.get("required_positions"), dict): bad.append("roster")
    if bad: raise ApiError(400, "VALIDATION_ERROR", "Invalid sport configuration.", {"fields": sorted(set(bad))})


@app.post("/audit/v1/sports", status_code=201)
async def create_sport(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    validate_sport(body)
    body = deepcopy(body)
    body.setdefault("tie_break_order", ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"])
    if "draw_lots" not in body["tie_break_order"]: body["tie_break_order"].append("draw_lots")
    with locked_state() as state:
        if body["sport_id"] in state["sports"]:
            raise ApiError(409, "SPORT_EXISTS", "Sport already exists.")
        state["sports"][body["sport_id"]] = body
    return {"sport_id": body["sport_id"], "status": "created", "config": body}


@app.post("/audit/v1/fixtures")
async def fixtures(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    require_fields(body, ["format", "teams"])
    fmt, teams, params = body.get("format"), body.get("teams"), body.get("params", {})
    limits = {"round_robin": (2, 40), "swiss": (2, 64), "single_elim": (2, 128), "double_elim": (3, 128)}
    if fmt not in limits or not isinstance(teams, list) or len(teams) != len(set(teams)) or any(not isinstance(t, str) for t in teams) or not limits.get(fmt, (0,0))[0] <= len(teams) <= limits.get(fmt, (0,0))[1] or not isinstance(params, dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid fixture request.", {"fields": ["format", "teams", "params"]})
    if fmt == "round_robin": return round_robin(teams, params)
    if fmt == "swiss": return swiss(teams, params)
    if fmt == "single_elim": return single_elim(teams, params)
    return double_elim(teams, params)


@app.post("/audit/v1/leagues", status_code=201)
async def create_league(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    require_fields(body, ["league_id", "sport_id", "teams", "fixtures", "qualification"])
    teams, fixture_list = body.get("teams"), body.get("fixtures")
    if not isinstance(teams, list) or not 2 <= len(teams) <= 40 or any(not isinstance(team, str) for team in teams) or len(teams) != len(set(teams)) or not isinstance(fixture_list, list):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid teams or fixtures.", {"fields": ["teams", "fixtures"]})
    points = body.get("points", {"win": 3, "draw": 1, "loss": 0})
    order = body.get("tie_break_order")
    spots = body.get("qualification", {}).get("spots") if isinstance(body.get("qualification"), dict) else None
    if not isinstance(points, dict) or any(type(points.get(k)) is not int for k in ("win", "draw", "loss")) or not isinstance(spots, int) or not 1 <= spots <= len(teams):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid standings configuration.", {"fields": ["points", "qualification"]})
    if order is not None and (not isinstance(order, list) or len(order) != len(set(order)) or any(item not in TIE_TOKENS for item in order)):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid tie-break order.", {"fields": ["tie_break_order"]})
    with locked_state() as state:
        if body["sport_id"] not in state["sports"]: raise ApiError(404, "SPORT_NOT_FOUND", "Sport not found.")
        if body["league_id"] in state["leagues"]: raise ApiError(409, "LEAGUE_EXISTS", "League already exists.")
        fixture_ids: set[str] = set()
        for fixture in fixture_list:
            if not isinstance(fixture, dict) or not all(k in fixture for k in ("match_id", "home", "away")) or fixture["home"] not in teams or fixture["away"] not in teams or fixture["home"] == fixture["away"]:
                raise ApiError(400, "VALIDATION_ERROR", "Invalid fixture.", {"fields": ["fixtures"]})
            if not isinstance(fixture["match_id"], str):
                raise ApiError(400, "VALIDATION_ERROR", "Invalid fixture.", {"fields": ["fixtures"]})
            if fixture["match_id"] in state["matches"] or fixture["match_id"] in fixture_ids: raise ApiError(409, "MATCH_EXISTS", "Match already exists.")
            fixture_ids.add(fixture["match_id"])
        sport = state["sports"][body["sport_id"]]
        league = deepcopy(body)
        league["points"] = points
        league["tie_break_order"] = order or sport.get("tie_break_order", list(TIE_TOKENS))
        league["lots_seed"] = body.get("lots_seed", state["seed"])
        state["leagues"][body["league_id"]] = league
        for fixture in fixture_list:
            state["matches"][fixture["match_id"]] = {
                "match_id": fixture["match_id"], "sport_id": body["sport_id"], "league_id": body["league_id"],
                "home_team_id": fixture["home"], "away_team_id": fixture["away"], "events": []}
    return {"league_id": body["league_id"], "status": "created", "team_count": len(teams), "fixture_count": len(fixture_list)}


def active_events(match: dict) -> tuple[list[dict], set[str]]:
    compensated = {e["payload"]["compensates"] for e in match["events"] if e["type"] == "compensation"}
    return [e for e in match["events"] if e["event_id"] not in compensated and e["type"] != "compensation"], compensated


def project_match(match: dict, sport: dict) -> dict:
    active, compensated = active_events(match)
    status = "upcoming"
    for e in active:
        if e["type"] == "match_start": status = "in_progress"
        elif e["type"] == "match_end": status = "completed"
    teams = [match["home_team_id"], match["away_team_id"]]
    stats = {t: {"score": 0, "wickets": 0, "balls": 0, "fair_play": 0} for t in teams}
    tiebreak = None
    for e in active:
        p = e["payload"]
        if e["type"] == "score":
            rule = sport["scoring_events"][p["event_type"]]
            t = p["team_id"]
            if sport["scoring_model"] == "event": stats[t]["score"] += rule["points"]
            elif sport["scoring_model"] == "round": stats[t]["score"] += rule["rounds"]
            else:
                stats[t]["score"] += rule["runs"]
                stats[t]["balls"] += int(rule["legal_ball"])
                stats[t]["wickets"] += int(rule["wicket"])
        elif e["type"] == "discipline": stats[p["team_id"]]["fair_play"] += p["points"]
        elif e["type"] == "tiebreak_winner": tiebreak = p["team_id"]
    hs, aws = stats[teams[0]]["score"], stats[teams[1]]["score"]
    winner = teams[0] if hs > aws else teams[1] if aws > hs else tiebreak
    if status != "completed": outcome = "pending"
    elif hs > aws: outcome = "home_win"
    elif aws > hs: outcome = "away_win"
    elif tiebreak == teams[0]: outcome = "home_win"
    elif tiebreak == teams[1]: outcome = "away_win"
    elif sport["draw_allowed"]: outcome = "draw"
    else: outcome = "undecided"
    bpo = sport.get("periods", {}).get("balls_per_over", 6)
    def side(t):
        s = stats[t]
        innings = sport["scoring_model"] == "innings"
        return {"team_id": t, "score": s["score"], "wickets": s["wickets"] if innings else None,
            "balls": s["balls"] if innings else None, "overs": f"{s['balls']//bpo}.{s['balls']%bpo}" if innings else None,
            "fair_play": s["fair_play"]}
    event_rows = []
    by_id = {e["event_id"]: e for e in match["events"]}
    comp_by = {e["payload"]["compensates"]: e["event_id"] for e in match["events"] if e["type"] == "compensation"}
    for e in match["events"]:
        event_rows.append({"sequence": e["sequence"], "event_id": e["event_id"], "type": e["type"], "payload": e["payload"],
            "signature": e["signature"], "compensated": e["event_id"] in compensated, "compensated_by": comp_by.get(e["event_id"])})
    return {"match_id": match["match_id"], "sport_id": match["sport_id"], "league_id": match.get("league_id"),
        "status": status, "outcome": outcome, "winner_team_id": winner, "tiebreak_winner_team_id": tiebreak,
        "home": side(teams[0]), "away": side(teams[1]), "version": len(match["events"]), "events": event_rows}


def apply_event(state: dict, body: dict) -> tuple[dict, bool]:
    require_fields(body, ["event_id", "match_id", "type", "payload"])
    if not all(isinstance(body.get(k), str) for k in ("event_id", "match_id", "type")) or not isinstance(body.get("payload"), dict):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid event fields.", {"fields": ["event_id", "match_id", "type", "payload"]})
    event_id, match_id, typ, payload = body["event_id"], body["match_id"], body["type"], body["payload"]
    fingerprint = body_fingerprint(body)
    existing = state["event_ids"].get(event_id)
    if existing:
        if existing["fingerprint"] == fingerprint: return deepcopy(existing["response"]), True
        raise ApiError(409, "DUPLICATE_EVENT_ID", "Event ID already used with a different body.")
    if typ == "match_init":
        if match_id in state["matches"]: raise ApiError(409, "MATCH_EXISTS", "Match already exists.")
        require_fields(payload, ["sport_id", "home_team_id", "away_team_id"])
        if payload["sport_id"] not in state["sports"]: raise ApiError(404, "SPORT_NOT_FOUND", "Sport not found.")
        if payload["home_team_id"] == payload["away_team_id"]: raise ApiError(400, "VALIDATION_ERROR", "Teams must differ.", {"fields": ["payload"]})
        state["matches"][match_id] = {"match_id": match_id, "sport_id": payload["sport_id"], "league_id": payload.get("league_id"),
            "home_team_id": payload["home_team_id"], "away_team_id": payload["away_team_id"], "events": []}
    elif match_id not in state["matches"]:
        raise ApiError(404, "MATCH_NOT_FOUND", "Match not found.")
    match = state["matches"][match_id]
    sport = state["sports"][match["sport_id"]]
    projection = project_match(match, sport)
    if typ == "match_start" and projection["status"] != "upcoming": raise ApiError(409, "ILLEGAL_TRANSITION", "Match cannot start.")
    elif typ in ("score", "discipline", "tiebreak_winner") and projection["status"] != "in_progress": raise ApiError(409, "MATCH_NOT_IN_PROGRESS", "Match is not in progress.")
    elif typ == "match_end":
        if projection["status"] != "in_progress": raise ApiError(409, "ILLEGAL_TRANSITION", "Match cannot end.")
        if projection["home"]["score"] == projection["away"]["score"] and not sport["draw_allowed"] and not projection["tiebreak_winner_team_id"]:
            raise ApiError(409, "TIE_NOT_ALLOWED", "A tie-break winner is required.")
    elif typ == "score":
        require_fields(payload, ["team_id", "event_type"])
        if payload["team_id"] not in (match["home_team_id"], match["away_team_id"]): raise ApiError(400, "VALIDATION_ERROR", "Invalid team.", {"fields": ["payload.team_id"]})
        if payload["event_type"] not in sport["scoring_events"]: raise ApiError(400, "UNKNOWN_EVENT_TYPE", "Unknown scoring event type.")
        current = projection["home"] if payload["team_id"] == match["home_team_id"] else projection["away"]
        if sport["scoring_model"] == "innings":
            p = sport["periods"]
            if current["balls"] >= p["innings_per_team"]*p["overs_per_innings"]*p["balls_per_over"] or current["wickets"] >= p["innings_per_team"]*p["wickets_per_innings"]:
                raise ApiError(409, "INNINGS_COMPLETE", "Innings is complete.")
        if sport["scoring_model"] == "round" and current["score"] >= (sport["periods"]["best_of"] + 1)//2:
            raise ApiError(409, "SERIES_ALREADY_DECIDED", "Series is already decided.")
    elif typ == "discipline":
        if payload.get("team_id") not in (match["home_team_id"], match["away_team_id"]) or not isinstance(payload.get("points"), int): raise ApiError(400, "VALIDATION_ERROR", "Invalid discipline event.", {"fields": ["payload"]})
    elif typ == "tiebreak_winner":
        if payload.get("team_id") not in (match["home_team_id"], match["away_team_id"]): raise ApiError(400, "VALIDATION_ERROR", "Invalid tiebreak team.", {"fields": ["payload.team_id"]})
    elif typ == "compensation":
        require_fields(payload, ["compensates", "reason"])
        target = next((e for e in match["events"] if e["event_id"] == payload["compensates"]), None)
        _, compensated = active_events(match)
        if target is None:
            if payload["compensates"] in state["event_ids"]:
                raise ApiError(409, "INVALID_COMPENSATION", "Compensation target belongs to another match.")
            raise ApiError(404, "EVENT_NOT_FOUND", "Compensated event not found.")
        if target["type"] not in ("score", "discipline", "tiebreak_winner") or target["event_id"] in compensated:
            raise ApiError(409, "INVALID_COMPENSATION", "Invalid compensation target.")
    elif typ not in ("match_init", "match_start", "match_end"):
        raise ApiError(400, "VALIDATION_ERROR", "Unknown event type.", {"fields": ["type"]})
    sequence = len(match["events"]) + 1
    event = {"sequence": sequence, "event_id": event_id, "match_id": match_id, "type": typ,
        "payload": deepcopy(payload), "signature": sign_record(event_id, payload)}
    match["events"].append(event)
    response = {"event_id": event_id, "match_id": match_id, "type": typ, "sequence": sequence,
        "match_version": sequence, "signature": event["signature"]}
    state["event_ids"][event_id] = {"fingerprint": fingerprint, "response": deepcopy(response)}
    return response, False


@app.post("/audit/v1/events")
async def create_event(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    with locked_state() as state:
        response, replay = apply_event(state, body)
    return JSONResponse(status_code=200 if replay else 201, content=response)


@app.get("/audit/v1/score/{match_id}")
def get_score(match_id: str):
    state = read_state()
    match = state["matches"].get(match_id)
    if not match: raise ApiError(404, "MATCH_NOT_FOUND", "Match not found.")
    return project_match(match, state["sports"][match["sport_id"]])


def match_diff(side: dict, sport: dict) -> float:
    if sport["scoring_model"] != "innings": return float(side["score"])
    balls = side["balls"] or 0
    return float(side["score"]) / (balls / sport["periods"]["balls_per_over"]) if balls else 0.0


@app.get("/audit/v1/standings/{league_id}")
def standings(league_id: str):
    state = read_state()
    league = state["leagues"].get(league_id)
    if not league: raise ApiError(404, "LEAGUE_NOT_FOUND", "League not found.")
    sport = state["sports"][league["sport_id"]]
    teams = league["teams"]
    rows = {t: {"rank": 0, "team_id": t, "played": 0, "won": 0, "drawn": 0, "lost": 0,
        "scored": 0, "conceded": 0, "diff": 0, "points": 0, "fair_play": 0, "status": "still_possible", "resolved_by": None,
        "balls_for": 0, "balls_against": 0, "wickets_for": 0, "wickets_against": 0} for t in teams}
    h2h = {a: {b: {"played": 0, "points": 0, "scored": 0, "conceded": 0} for b in teams if b != a} for a in teams}
    completed = []
    remaining = {t: 0 for t in teams}
    for fixture in league["fixtures"]:
        match = state["matches"][fixture["match_id"]]
        p = project_match(match, sport)
        home, away = p["home"], p["away"]
        if p["status"] != "completed" or p["outcome"] == "undecided":
            remaining[home["team_id"]] += 1; remaining[away["team_id"]] += 1
            continue
        completed.append((home["team_id"], away["team_id"], p))
        rh, ra = rows[home["team_id"]], rows[away["team_id"]]
        for r in (rh, ra): r["played"] += 1
        rh["scored"] += home["score"]; rh["conceded"] += away["score"]
        ra["scored"] += away["score"]; ra["conceded"] += home["score"]
        rh["fair_play"] += home["fair_play"]; ra["fair_play"] += away["fair_play"]
        if sport["scoring_model"] == "innings":
            rh["balls_for"] += home["balls"]; rh["balls_against"] += away["balls"]
            ra["balls_for"] += away["balls"]; ra["balls_against"] += home["balls"]
            rh["wickets_for"] += home["wickets"]; rh["wickets_against"] += away["wickets"]
            ra["wickets_for"] += away["wickets"]; ra["wickets_against"] += home["wickets"]
        if p["outcome"] == "draw":
            rh["drawn"] += 1; ra["drawn"] += 1
            rh["points"] += league["points"]["draw"]; ra["points"] += league["points"]["draw"]
            hp = ap = league["points"]["draw"]
        else:
            winner = p["winner_team_id"]
            rw, rl = (rh, ra) if winner == home["team_id"] else (ra, rh)
            rw["won"] += 1; rl["lost"] += 1
            rw["points"] += league["points"]["win"]; rl["points"] += league["points"]["loss"]
            hp = league["points"]["win"] if winner == home["team_id"] else league["points"]["loss"]
            ap = league["points"]["win"] if winner == away["team_id"] else league["points"]["loss"]
        for a, b, sa, sb, pts in ((home["team_id"], away["team_id"], home["score"], away["score"], hp),
                                  (away["team_id"], home["team_id"], away["score"], home["score"], ap)):
            h2h[a][b]["played"] += 1; h2h[a][b]["points"] += pts; h2h[a][b]["scored"] += sa; h2h[a][b]["conceded"] += sb
    for t, r in rows.items():
        if sport["scoring_model"] == "innings":
            bpo = sport["periods"]["balls_per_over"]
            maxballs = sport["periods"]["overs_per_innings"] * bpo * sport["periods"]["innings_per_team"]
            bf = maxballs if r["wickets_for"] >= sport["periods"]["wickets_per_innings"] else r["balls_for"]
            ba = maxballs if r["wickets_against"] >= sport["periods"]["wickets_per_innings"] else r["balls_against"]
            r["diff"] = round((r["scored"]/(bf/bpo) if bf else 0) - (r["conceded"]/(ba/bpo) if ba else 0), 3)
        else: r["diff"] = r["scored"] - r["conceded"]

    order = [x for x in league["tie_break_order"] if x != "draw_lots"] + ["draw_lots"]
    def criterion_values(group: list[str], criterion: str) -> dict[str, Any]:
        if criterion == "h2h_points": return {t: sum(h2h[t][o]["points"] for o in group if o != t) for t in group}
        if criterion == "h2h_diff": return {t: sum(h2h[t][o]["scored"] - h2h[t][o]["conceded"] for o in group if o != t) for t in group}
        if criterion == "overall_diff": return {t: rows[t]["diff"] for t in group}
        if criterion == "scored": return {t: rows[t]["scored"] for t in group}
        if criterion == "fair_play": return {t: rows[t]["fair_play"] for t in group}
        return {t: lots_key(league["lots_seed"], league_id, t) for t in group}
    def resolve(group: list[str]) -> list[str]:
        if len(group) <= 1: return group
        for criterion in order:
            values = criterion_values(group, criterion)
            reverse = criterion != "draw_lots"
            buckets = {}
            for t in group: buckets.setdefault(values[t], []).append(t)
            if len(buckets) > 1:
                result = []
                sorted_keys = sorted(buckets, reverse=reverse)
                for bucket_index, key in enumerate(sorted_keys):
                    subgroup = buckets[key]
                    resolved = resolve(subgroup) if len(subgroup) > 1 else subgroup
                    if bucket_index < len(sorted_keys) - 1:
                        rows[resolved[-1]]["resolved_by"] = criterion
                    result.extend(resolved)
                return result
        return group
    point_groups = {}
    for t in teams: point_groups.setdefault(rows[t]["points"], []).append(t)
    ranked = []
    for pts in sorted(point_groups, reverse=True): ranked.extend(resolve(point_groups[pts]))
    k, win_pts = league["qualification"]["spots"], league["points"]["win"]
    for index, t in enumerate(ranked):
        r = rows[t]; r["rank"] = index + 1
        maximum = r["points"] + win_pts * remaining[t]
        if sum(1 for x in teams if x != t and rows[x]["points"] + win_pts*remaining[x] >= r["points"]) < k: r["status"] = "clinched"
        elif sum(1 for x in teams if x != t and rows[x]["points"] > maximum) >= k: r["status"] = "eliminated"
        for key in ("balls_for", "balls_against", "wickets_for", "wickets_against"): r.pop(key, None)
    return {"league_id": league_id, "sport_id": league["sport_id"], "qualification_spots": k,
        "table": [rows[t] for t in ranked], "h2h": h2h}


@app.post("/audit/v1/roster/setup", status_code=201)
async def roster_setup(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    require_fields(body, ["league", "squads", "players"])
    league, squads, players = body["league"], body["squads"], body["players"]
    if not isinstance(league, dict) or not isinstance(squads, list) or not isinstance(players, list): raise ApiError(400, "VALIDATION_ERROR", "Invalid roster setup.", {"fields": ["league", "squads", "players"]})
    require_fields(league, ["league_id", "tenant_id", "sport_id", "transfer_window"])
    with locked_state() as state:
        sport = state["sports"].get(league["sport_id"])
        if not sport: raise ApiError(404, "SPORT_NOT_FOUND", "Sport not found.")
        scenario = deepcopy(body)
        scenario["league"].setdefault("max_squad_size", sport["roster"]["max_squad_size"])
        scenario["league"].setdefault("required_positions", sport["roster"]["required_positions"])
        scenario["history"] = {p["player_id"]: [] for p in players}
        scenario["requests"] = {}
        scenario["players_by_id"] = {p["player_id"]: deepcopy(p) for p in players}
        scenario["squads_by_id"] = {s["squad_id"]: deepcopy(s) for s in squads}
        state["rosters"][league["league_id"]] = scenario
        counts = {s["squad_id"]: sum(1 for p in players if p.get("squad_id") == s["squad_id"]) for s in squads}
    return {"league_id": league["league_id"], "status": "configured", "squad_counts": counts}


def roster_transfer_apply(state: dict, body: dict) -> tuple[dict, bool]:
    required = ["request_id", "league_id", "player_id", "type", "from_squad_id", "effective_date", "reason", "requested_by"]
    require_fields(body, required)
    typ = body.get("type")
    bad = []
    if typ not in ("transfer", "loan", "release"): bad.append("type")
    if typ != "release" and not body.get("to_squad_id"): bad.append("to_squad_id")
    try: effective = date.fromisoformat(body["effective_date"])
    except Exception: bad.append("effective_date"); effective = date.today()
    loan_end = None
    if typ == "loan":
        try: loan_end = date.fromisoformat(body.get("loan_end_date", ""))
        except Exception: bad.append("loan_end_date")
        if loan_end and loan_end <= effective: bad.append("loan_end_date")
    if bad: raise ApiError(400, "VALIDATION_ERROR", "Invalid transfer request.", {"fields": sorted(set(bad))})
    scenario = state["rosters"].get(body["league_id"])
    if not scenario: raise ApiError(404, "LEAGUE_NOT_FOUND", "Roster league not found.")
    player = scenario["players_by_id"].get(body["player_id"])
    if not player: raise ApiError(404, "PLAYER_NOT_FOUND", "Player not found.")
    from_sq = scenario["squads_by_id"].get(body["from_squad_id"])
    to_sq = scenario["squads_by_id"].get(body.get("to_squad_id")) if body.get("to_squad_id") else None
    if not from_sq or (typ != "release" and not to_sq): raise ApiError(404, "SQUAD_NOT_FOUND", "Squad not found.")
    fingerprint = body_fingerprint(body)
    existing = scenario["requests"].get(body["request_id"])
    if existing:
        if existing["fingerprint"] == fingerprint: return deepcopy(existing["response"]), True
        raise ApiError(409, "VALIDATION_ERROR", "Request ID already used with a different body.")
    tenant = scenario["league"]["tenant_id"]
    if from_sq.get("tenant_id") != tenant or (to_sq and to_sq.get("tenant_id") != tenant): raise ApiError(409, "CROSS_TENANT_TRANSFER", "Cross-tenant move is forbidden.")
    if player.get("squad_id") != body["from_squad_id"]: raise ApiError(409, "NOT_IN_SQUAD", "Player is not in from squad.")
    window = scenario["league"]["transfer_window"]
    if typ != "release" and not date.fromisoformat(window["open"]) <= effective <= date.fromisoformat(window["close"]): raise ApiError(409, "TRANSFER_WINDOW_CLOSED", "Transfer window is closed.")
    if player.get("registration_type") == "loan": raise ApiError(409, "PLAYER_ON_LOAN", "Player is currently on loan.")
    if typ != "release":
        count = sum(1 for p in scenario["players_by_id"].values() if p.get("squad_id") == body["to_squad_id"])
        if count + 1 > scenario["league"]["max_squad_size"]: raise ApiError(409, "SQUAD_FULL", "Destination squad is full.")
    required_positions = scenario["league"].get("required_positions", {})
    if player.get("position") in required_positions:
        remaining = sum(1 for p in scenario["players_by_id"].values() if p.get("squad_id") == body["from_squad_id"] and p["player_id"] != body["player_id"] and p.get("position") == player.get("position"))
        if remaining < required_positions[player["position"]]: raise ApiError(409, "MIN_POSITION_VIOLATION", "Minimum position requirement violated.")
    blocking = next((m["match_id"] for m in scenario.get("matches_in_progress", []) if body["from_squad_id"] in (m.get("home_squad_id"), m.get("away_squad_id"))), None)
    state_name = "deferred_until_match_end" if blocking else "active"
    old_squad = player.get("squad_id")
    if not blocking:
        player["squad_id"] = body.get("to_squad_id")
        player["role"] = "substitute" if typ != "release" else player.get("role")
        player["registration_type"] = typ
        player["parent_squad_id"] = old_squad if typ == "loan" else None
        player["loan_end_date"] = body.get("loan_end_date")
    audit_id = f"au-{sum(len(v) for v in scenario['history'].values()) + 1:04d}"
    audit = {"audit_id": audit_id, "action": typ, "player_id": body["player_id"], "league_id": body["league_id"],
        "from_squad_id": old_squad, "to_squad_id": body.get("to_squad_id"), "effective_date": body["effective_date"],
        "state": state_name, "who": body["requested_by"], "when": utc_now(), "why": body["reason"]}
    scenario["history"][body["player_id"]].append(audit)
    registration = None if typ == "release" else {"player_id": body["player_id"], "league_id": body["league_id"],
        "squad_id": body.get("to_squad_id"), "parent_squad_id": old_squad if typ == "loan" else None,
        "registration_type": typ, "start_date": body["effective_date"], "loan_end_date": body.get("loan_end_date"), "role": "substitute"}
    response = {"request_id": body["request_id"], "status": "accepted", "state": state_name,
        "blocking_match_id": blocking, "registration": registration, "audit_entry": audit}
    scenario["requests"][body["request_id"]] = {"fingerprint": fingerprint, "response": deepcopy(response)}
    return response, False


@app.post("/audit/v1/roster/transfer")
async def roster_transfer(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    with locked_state() as state: response, replay = roster_transfer_apply(state, body)
    return JSONResponse(status_code=200 if replay else 201, content=response)


@app.get("/audit/v1/roster/history/{player_id}")
def roster_history(player_id: str, as_of: str | None = None):
    target = date.fromisoformat(as_of) if as_of else date.today()
    with locked_state() as state:
        for league_id, scenario in state["rosters"].items():
            player = scenario["players_by_id"].get(player_id)
            if not player: continue
            if player.get("registration_type") == "loan" and player.get("loan_end_date") and target > date.fromisoformat(player["loan_end_date"]):
                if not any(h["action"] == "loan_return" for h in scenario["history"][player_id]):
                    borrower, lender = player.get("squad_id"), player.get("parent_squad_id")
                    player["squad_id"] = lender; player["parent_squad_id"] = None; player["registration_type"] = "transfer"; player["role"] = "substitute"
                    scenario["history"][player_id].append({"audit_id": f"au-{sum(len(v) for v in scenario['history'].values()) + 1:04d}",
                        "action": "loan_return", "player_id": player_id, "league_id": league_id, "from_squad_id": borrower,
                        "to_squad_id": lender, "effective_date": str(date.fromisoformat(player["loan_end_date"]) + timedelta(days=1)),
                        "state": "active", "who": "system", "when": utc_now(), "why": "Automatic loan return"})
            return {"player_id": player_id, "as_of": str(target), "league_id": league_id,
                "current_squad_id": player.get("squad_id"), "parent_squad_id": player.get("parent_squad_id"),
                "history": scenario["history"][player_id]}
    raise ApiError(404, "PLAYER_NOT_FOUND", "Player not found.")


def receipt_pdf(order_id: str, total_minor: int) -> str:
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 18 Tf 72 760 Td (NaSCon Club Store Receipt) Tj 0 -40 Td /F1 12 Tf (Order: {esc(order_id)}) Tj 0 -20 Td (Total: PKR {total_minor / 100:.2f}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    pdf = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf)); pdf.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(pdf); pdf.extend(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: pdf.extend(f"{offset:010d} 00000 n \n".encode())
    pdf.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return base64.b64encode(bytes(pdf)).decode("ascii")


@app.post("/audit/v1/checkout")
async def checkout(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    require_fields(body, ["order_id", "customer_id", "items", "payment"])
    bad = []
    items = body.get("items")
    if not isinstance(body.get("order_id"), str): bad.append("order_id")
    if not isinstance(items, list) or not 1 <= len(items) <= 10: bad.append("items")
    elif any(not isinstance(x, dict) or not isinstance(x.get("variant_id"), str) or not isinstance(x.get("quantity"), int) or not 1 <= x["quantity"] <= 10 for x in items) or len({x["variant_id"] for x in items}) != len(items): bad.append("items")
    payment = body.get("payment")
    if not isinstance(payment, dict) or payment.get("token") not in ("tok_success", "tok_declined", "tok_capture_fail"): bad.append("payment.token")
    if bad: raise ApiError(400, "VALIDATION_ERROR", "Invalid checkout request.", {"fields": bad})
    fingerprint = body_fingerprint(body)
    with locked_state() as state:
        existing = state["orders"].get(body["order_id"])
        if existing:
            if existing["fingerprint"] == fingerprint: return JSONResponse(status_code=200, content=existing["response"])
            raise ApiError(409, "DUPLICATE_ORDER_ID", "Order ID already used with a different body.")
        for item in items:
            if item["variant_id"] not in state["variants"]: raise ApiError(404, "VARIANT_NOT_FOUND", "Variant not found.", {"variant_id": item["variant_id"]})
        discount_code = body.get("discount_code")
        if discount_code not in (None, "WELCOME10"): raise ApiError(400, "INVALID_DISCOUNT_CODE", "Unknown discount code.")
        for item in items:
            inv = state["inventory"].setdefault(item["variant_id"], {"stock": 0, "reserved": 0})
            if inv["stock"] < item["quantity"]: raise ApiError(409, "OUT_OF_STOCK", "Not enough stock.", {"variant_id": item["variant_id"]})
        # The state row is locked, so reservation/commit is serializable across workers.
        for item in items:
            inv = state["inventory"][item["variant_id"]]; inv["stock"] -= item["quantity"]; inv["reserved"] += item["quantity"]
        token = payment["token"]
        if token != "tok_success":
            for item in items:
                inv = state["inventory"][item["variant_id"]]; inv["stock"] += item["quantity"]; inv["reserved"] -= item["quantity"]
            code = "PAYMENT_DECLINED" if token == "tok_declined" else "PAYMENT_CAPTURE_FAILED"
            raise ApiError(402, code, "Mock payment failed.")
        result_items, subtotal = [], 0
        for item in items:
            variant = state["variants"][item["variant_id"]]
            result_items.append({"variant_id": item["variant_id"], "quantity": item["quantity"], "unit_price_minor": variant["price_minor"]})
            subtotal += variant["price_minor"] * item["quantity"]
            state["inventory"][item["variant_id"]]["reserved"] -= item["quantity"]
        discount = subtotal * 10 // 100 if discount_code == "WELCOME10" else 0
        total = subtotal - discount
        paid_at = utc_now()
        payload = {"order_id": body["order_id"], "customer_id": body["customer_id"], "items": result_items,
            "subtotal_minor": subtotal, "discount_minor": discount, "total_minor": total, "currency": "PKR", "paid_at": paid_at}
        response = {"order_id": body["order_id"], "status": "paid", "currency": "PKR", "items": result_items,
            "subtotal_minor": subtotal, "discount_minor": discount, "total_minor": total,
            "payment": {"authorization_id": f"auth_{body['order_id']}", "capture_id": f"cap_{body['order_id']}", "state": "captured"},
            "receipt": {"payload": payload, "signature": sign_record(body["order_id"], payload), "pdf_base64": receipt_pdf(body["order_id"], total)}}
        state["orders"][body["order_id"]] = {"fingerprint": fingerprint, "response": deepcopy(response)}
    return JSONResponse(status_code=201, content=response)


@app.get("/audit/v1/inventory/{variant_id}")
def inventory(variant_id: str):
    state = read_state()
    if variant_id not in state["variants"]: raise ApiError(404, "VARIANT_NOT_FOUND", "Variant not found.")
    inv = state["inventory"][variant_id]
    return {"variant_id": variant_id, "stock": inv["stock"], "reserved": inv["reserved"]}


RBAC_CONTEXT = {
    "tenant_id": "tenant-alpha", "foreign_tenant_id": "tenant-beta",
    "own_league_id": "league-alpha-1", "other_league_id": "league-alpha-2", "foreign_league_id": "league-beta-1",
    "own_club_id": "club-alpha-1", "other_club_id": "club-alpha-2", "foreign_club_id": "club-beta-1",
    "own_player_id": "player-alpha-1", "other_player_id": "player-alpha-2", "foreign_player_id": "player-beta-1",
}


@app.post("/audit/v1/rbac-matrix")
def rbac_matrix():
    return {"tokens": {
        "super_admin": make_token("super_admin"),
        "league_organizer": make_token("league_organizer", tenant_id="tenant-alpha", league_id="league-alpha-1"),
        "club_manager": make_token("club_manager", tenant_id="tenant-alpha", club_id="club-alpha-1"),
        "player": make_token("player", tenant_id="tenant-alpha", player_id="player-alpha-1", club_id="club-alpha-1"),
        "viewer": make_token("viewer", tenant_id="tenant-alpha"),
    }, "context": RBAC_CONTEXT}


def bearer(request: Request) -> dict:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "): raise ApiError(401, "UNAUTHENTICATED", "Authorization token is required.")
    return decode_token(header[7:])


def authorize_probe(claims: dict, probe: str, target: str | None = None) -> None:
    role = claims.get("role")
    if role == "super_admin": return
    allowed = False
    if probe == "P2": allowed = role == "league_organizer" and target == claims.get("league_id")
    elif probe in ("P3", "P4"): allowed = role == "club_manager" and target == claims.get("club_id")
    elif probe == "P5": allowed = (role == "player" and target == claims.get("player_id")) or (role == "club_manager" and target == "player-alpha-1" and claims.get("club_id") == "club-alpha-1")
    elif probe == "P6":
        state = read_state(); club = state["clubs"].get(target)
        allowed = bool(club and club["tenant_id"] == claims.get("tenant_id"))
    if not allowed: raise ApiError(403, "FORBIDDEN", "Operation is not permitted.")


def authorized_response(request: Request, probe: str, target: str | None = None):
    authorize_probe(bearer(request), probe, target)
    return {"authorized": True}


@app.post("/audit/v1/rbac/tenants")
def p1(request: Request): return authorized_response(request, "P1")
@app.post("/audit/v1/rbac/leagues/{league_id}/fixtures")
def p2(league_id: str, request: Request): return authorized_response(request, "P2", league_id)
@app.post("/audit/v1/rbac/clubs/{club_id}/roster")
def p3(club_id: str, request: Request): return authorized_response(request, "P3", club_id)
@app.post("/audit/v1/rbac/clubs/{club_id}/products")
def p4(club_id: str, request: Request): return authorized_response(request, "P4", club_id)
@app.patch("/audit/v1/rbac/players/{player_id}")
def p5(player_id: str, request: Request): return authorized_response(request, "P5", player_id)
@app.get("/audit/v1/rbac/clubs/{club_id}")
def p6(club_id: str, request: Request): return authorized_response(request, "P6", club_id)
@app.get("/audit/v1/rbac/platform/config")
def p7(request: Request): return authorized_response(request, "P7")


@app.get("/api/v1/ping")
def ping(request: Request):
    client = request.client.host if request.client else "unknown"
    key = f"rate:{client}"
    count = cache.incr(key)
    if count == 1: cache.expire(key, 10)
    if count > 100:
        retry_after = max(cache.ttl(key), 1)
        return JSONResponse(status_code=429, content={"error": {"code": "RATE_LIMITED", "message": "Rate limit exceeded.", "details": {}}}, headers={"Retry-After": str(retry_after)})
    return {"pong": True}


@app.post("/audit/v1/offline-sync")
async def offline_sync(request: Request):
    body = await request.json()
    if not isinstance(body, dict): raise ApiError(400, "VALIDATION_ERROR", "Body must be an object.", {"fields": ["body"]})
    require_fields(body, ["device_id", "actions"])
    actions = body.get("actions")
    if not isinstance(actions, list) or not 1 <= len(actions) <= 100:
        raise ApiError(400, "VALIDATION_ERROR", "actions must contain 1-100 items.", {"fields": ["actions"]})
    for action in actions:
        if (not isinstance(action, dict)
                or not isinstance(action.get("action_id"), str)
                or action.get("type") not in ("score_event", "roster_transfer")
                or not isinstance(action.get("queued_at"), str)
                or type(action.get("base_version")) is not int
                or action["base_version"] < 0
                or not isinstance(action.get("payload"), dict)):
            raise ApiError(400, "VALIDATION_ERROR", "Invalid action envelope.", {"fields": ["actions"]})
    indexed = list(enumerate(actions))
    try: ordered = sorted(indexed, key=lambda x: (x[1]["queued_at"], x[0]))
    except Exception: raise ApiError(400, "VALIDATION_ERROR", "Invalid action envelope.", {"fields": ["actions"]})
    results_by_index = {}
    with locked_state() as state:
        for processed_order, (original_index, action) in enumerate(ordered, 1):
            current = 0
            if not isinstance(action, dict) or not all(k in action for k in ("action_id", "type", "base_version", "payload")):
                raise ApiError(400, "VALIDATION_ERROR", "Invalid action envelope.", {"fields": ["actions"]})
            dedupe_key = f"{body['device_id']}|{action['action_id']}"
            previous = state["offline_processed"].get(dedupe_key)
            if previous:
                result = {"action_id": action["action_id"], "status": "duplicate", "resolution": "skipped_duplicate",
                    "error_code": None, "processed_order": processed_order, "server_version": previous["server_version"], "signature": None}
                results_by_index[original_index] = result; continue
            try:
                if action["type"] == "score_event":
                    match = state["matches"].get(action["payload"].get("match_id"))
                    if not match: raise ApiError(404, "MATCH_NOT_FOUND", "Match not found.")
                    current = len(match["events"])
                    if action["base_version"] > current: raise ApiError(409, "INVALID_BASE_VERSION", "Base version is in the future.")
                    response, replay = apply_event(state, action["payload"])
                    new_version = response["match_version"]
                    resolution = "rebased_append" if action["base_version"] < current else "appended"
                    status = "duplicate" if replay else "applied"
                    if replay: resolution = "skipped_duplicate"
                    signature = response["signature"] if not replay else None
                elif action["type"] == "roster_transfer":
                    scenario = state["rosters"].get(action["payload"].get("league_id"))
                    player = scenario and scenario["players_by_id"].get(action["payload"].get("player_id"))
                    if not player: raise ApiError(404, "PLAYER_NOT_FOUND", "Player not found.")
                    current = len(scenario["history"][player["player_id"]])
                    if action["base_version"] > current: raise ApiError(409, "INVALID_BASE_VERSION", "Base version is in the future.")
                    _, replay = roster_transfer_apply(state, action["payload"])
                    new_version = len(scenario["history"][player["player_id"]])
                    resolution = "rebased_append" if action["base_version"] < current else "appended"
                    status = "duplicate" if replay else "applied"
                    if replay: resolution = "skipped_duplicate"
                    signature = None
                else:
                    raise ApiError(400, "VALIDATION_ERROR", "Unknown action type.", {"fields": ["actions.type"]})
                result = {"action_id": action["action_id"], "status": status, "resolution": resolution,
                    "error_code": None, "processed_order": processed_order, "server_version": new_version, "signature": signature}
                state["offline_processed"][dedupe_key] = {"server_version": new_version}
            except ApiError as exc:
                result = {"action_id": action["action_id"], "status": "rejected", "resolution": "server_wins",
                    "error_code": exc.code, "processed_order": processed_order, "server_version": current, "signature": None}
                state["offline_processed"][dedupe_key] = {"server_version": current}
            results_by_index[original_index] = result
    results = [results_by_index[i] for i in range(len(actions))]
    summary = {"applied": sum(r["status"] == "applied" for r in results),
        "rejected": sum(r["status"] == "rejected" for r in results),
        "duplicate": sum(r["status"] == "duplicate" for r in results)}
    return {"device_id": body["device_id"], "results": results, "summary": summary}
