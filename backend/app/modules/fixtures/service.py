import math
from collections import defaultdict
from typing import Any

from app.core.errors import ApiError
from app.core.validation import require_identifier, validation_error


def _validate_teams(data: dict, minimum: int, maximum: int) -> tuple[list[str], dict]:
    teams = data.get("teams")
    params = data.get("params", {})
    if not isinstance(teams, list) or not minimum <= len(teams) <= maximum:
        raise validation_error("teams")
    if not isinstance(params, dict):
        raise validation_error("params")
    normalized = [require_identifier(team, "teams") for team in teams]
    if len(set(normalized)) != len(normalized):
        raise validation_error("teams")
    return normalized, params


def round_robin(data: dict) -> dict:
    teams, params = _validate_teams(data, 2, 40)
    legs = params.get("legs", 1)
    withdrawals = params.get("withdrawals", [])
    policy = params.get("withdrawal_policy", "forfeit_remaining")
    if legs not in (1, 2): raise validation_error("legs")
    if policy not in ("void_all", "forfeit_remaining"): raise validation_error("withdrawal_policy")
    if not isinstance(withdrawals, list): raise validation_error("withdrawals")

    rotation: list[str | None] = teams.copy()
    if len(rotation) % 2:
        rotation.append(None)
    rounds_per_leg = len(rotation) - 1
    total_rounds = rounds_per_leg * legs
    withdrawal_map: dict[str, int] = {}
    for item in withdrawals:
        if not isinstance(item, dict) or item.get("team_id") not in teams or type(item.get("after_round")) is not int or not 0 <= item["after_round"] <= total_rounds:
            raise validation_error("withdrawals")
        withdrawal_map[item["team_id"]] = item["after_round"]

    first_leg: list[list[tuple[str | None, str | None]]] = []
    current = rotation.copy()
    for round_index in range(rounds_per_leg):
        pairs: list[tuple[str | None, str | None]] = []
        for index in range(len(current) // 2):
            left, right = current[index], current[-1 - index]
            if index == 0 and round_index % 2:
                left, right = right, left
            pairs.append((left, right))
        first_leg.append(pairs)
        current = [current[0], current[-1], *current[1:-1]]

    result_rounds: list[dict] = []
    counts = {"total": 0, "scheduled": 0, "forfeit": 0, "voided": 0}
    for leg in range(1, legs + 1):
        for local_round, original_pairs in enumerate(first_leg, 1):
            global_round = (leg - 1) * rounds_per_leg + local_round
            matches, byes = [], []
            for home, away in original_pairs:
                if leg == 2:
                    home, away = away, home
                if home is None or away is None:
                    byes.append(away if home is None else home)
                    continue
                status, awarded_to = "scheduled", None
                home_out = home in withdrawal_map and (policy == "void_all" or global_round > withdrawal_map[home])
                away_out = away in withdrawal_map and (policy == "void_all" or global_round > withdrawal_map[away])
                if policy == "void_all" and (home_out or away_out) or (home_out and away_out):
                    status = "voided"
                elif home_out or away_out:
                    status, awarded_to = "forfeit", away if home_out else home
                counts[status] += 1
                counts["total"] += 1
                matches.append({"match_id": f"RR-L{leg}-R{global_round}-M{len(matches)+1}", "leg": leg, "home": home, "away": away, "status": status, "awarded_to": awarded_to})
            result_rounds.append({"round": global_round, "matches": matches, "byes": byes})
    return {"format": "round_robin", "legs": legs, "team_count": len(teams), "round_count": total_rounds, "rounds": result_rounds, "summary": counts}


def _swiss_state(teams: list[str], history: list[dict]) -> tuple[dict[str, float], dict[str, set[str]], set[str]]:
    scores = {team: 0.0 for team in teams}
    opponents = {team: set() for team in teams}
    byes: set[str] = set()
    for entry in history:
        bye = entry.get("bye")
        if bye is not None:
            if bye not in scores: raise validation_error("history")
            scores[bye] += 1.0
            byes.add(bye)
        matches = entry.get("matches")
        if not isinstance(matches, list): raise validation_error("history")
        for match in matches:
            if not isinstance(match, dict): raise validation_error("history")
            home, away, outcome = match.get("home"), match.get("away"), match.get("result")
            if home not in scores or away not in scores or home == away or outcome not in ("home", "away", "draw") or away in opponents[home]:
                raise validation_error("history")
            opponents[home].add(away); opponents[away].add(home)
            if outcome == "home": scores[home] += 1
            elif outcome == "away": scores[away] += 1
            else: scores[home] += .5; scores[away] += .5
    return scores, opponents, byes


def _optimal_pairing(players: list[str], scores: dict[str, float], opponents: dict[str, set[str]]) -> list[tuple[str, str]] | None:
    best: tuple[float, list[tuple[str, str]]] | None = None

    def search(remaining: list[str], pairs: list[tuple[str, str]], cost: float) -> None:
        nonlocal best
        if best is not None and cost > best[0]: return
        if not remaining:
            candidate = (cost, pairs.copy())
            if best is None or candidate[0] < best[0]: best = candidate
            return
        first = remaining[0]
        candidates = sorted((other for other in remaining[1:] if other not in opponents[first]), key=lambda t: (abs(scores[first] - scores[t]), players.index(t)))
        for other in candidates:
            search([p for p in remaining[1:] if p != other], [*pairs, (first, other)], cost + abs(scores[first] - scores[other]))

    search(players, [], 0.0)
    return None if best is None else best[1]


def swiss(data: dict) -> dict:
    teams, params = _validate_teams(data, 2, 64)
    maximum_rounds = len(teams) - 1
    total_rounds = params.get("total_rounds", math.ceil(math.log2(len(teams))))
    current_round = params.get("round", 1)
    history = params.get("history", [])
    if type(total_rounds) is not int or not 1 <= total_rounds <= maximum_rounds: raise validation_error("total_rounds")
    if type(current_round) is not int or not 1 <= current_round <= total_rounds: raise validation_error("round")
    if not isinstance(history, list) or [h.get("round") for h in history if isinstance(h, dict)] != list(range(1, current_round)):
        raise validation_error("history")
    scores, opponents, previous_byes = _swiss_state(teams, history)
    buchholz = {team: sum(scores[opp] for opp in opponents[team]) for team in teams}
    ordered = sorted(teams, key=lambda team: (-scores[team], -buchholz[team], teams.index(team)))
    standings = [{"rank": i + 1, "team_id": team, "score": scores[team], "buchholz": buchholz[team]} for i, team in enumerate(ordered)]

    if current_round == 1:
        bye = teams[-1] if len(teams) % 2 else None
        playing = teams[:-1] if bye else teams
        half = len(playing) // 2
        pairs = list(zip(playing[:half], playing[half:]))
    else:
        bye = None
        candidates: list[str | None]
        if len(teams) % 2:
            eligible = [t for t in teams if t not in previous_byes]
            candidates = sorted(eligible, key=lambda t: (scores[t], -teams.index(t)))
        else:
            candidates = [None]
        pairs = None
        for candidate in candidates:
            playing = [t for t in ordered if t != candidate]
            found = _optimal_pairing(playing, scores, opponents)
            if found is not None:
                bye, pairs = candidate, found
                break
        if pairs is None:
            raise ApiError(409, "NO_VALID_PAIRING", "No complete rematch-free pairing exists.", {"round": current_round})
    return {"format": "swiss", "round": current_round, "total_rounds": total_rounds, "pairings": [{"match_id": f"SW-R{current_round}-M{i+1}", "home": h, "away": a} for i, (h, a) in enumerate(pairs)], "bye": bye, "standings": standings}


def _seed_order(size: int) -> list[int]:
    order = [1, 2]
    while len(order) < size:
        next_size = len(order) * 2
        order = [value for seed in order for value in (seed, next_size + 1 - seed)]
    return order


def _match(match_id: str, bracket: str, round_number: int, index: int, home: str | None = None, away: str | None = None, home_seed: int | None = None, away_seed: int | None = None, winner_to: dict | None = None, loser_to: dict | None = None, bye: bool = False) -> dict:
    return {"match_id": match_id, "bracket": bracket, "round": round_number, "index": index, "home": home, "away": away, "home_seed": home_seed, "away_seed": away_seed, "bye": bye, "winner": home if bye else None, "loser": None, "winner_to": winner_to, "loser_to": loser_to}


def single_elim(data: dict) -> dict:
    teams, params = _validate_teams(data, 2, 128)
    if type(params.get("third_place_match", False)) is not bool or not isinstance(params.get("results", []), list): raise validation_error("params")
    size = 1 << (len(teams) - 1).bit_length()
    round_count = int(math.log2(size))
    rounds: list[dict] = []
    matches_by_id: dict[str, dict] = {}
    order = _seed_order(size)
    for round_number in range(1, round_count + 1):
        count = size // (2**round_number)
        matches = []
        for index in range(1, count + 1):
            match_id = f"R{round_number}M{index}"
            winner_to = None if round_number == round_count else {"match_id": f"R{round_number+1}M{(index+1)//2}", "slot": "home" if index % 2 else "away"}
            if round_number == 1:
                seeds = sorted(order[(index-1)*2:index*2])
                home_seed, away_seed = seeds
                home = teams[home_seed-1] if home_seed <= len(teams) else None
                away = teams[away_seed-1] if away_seed <= len(teams) else None
                if home is None: home, away, home_seed, away_seed = away, None, away_seed, None
                match = _match(match_id, "main", round_number, index, home, away, home_seed, away_seed, winner_to, None, away is None)
            else:
                match = _match(match_id, "main", round_number, index, winner_to=winner_to)
            matches.append(match); matches_by_id[match_id] = match
        rounds.append({"round": round_number, "matches": matches})

    def propagate(match: dict) -> None:
        target = match.get("winner_to")
        if target and match["winner"]:
            matches_by_id[target["match_id"]][target["slot"]] = match["winner"]

    for match in rounds[0]["matches"]: propagate(match)
    third_place = None
    if params.get("third_place_match"):
        third_place = _match("TP", "third_place", round_count, 1)
        matches_by_id["TP"] = third_place
        for index, semifinal in enumerate(rounds[-2]["matches"]):
            semifinal["loser_to"] = {"match_id": "TP", "slot": "home" if index == 0 else "away"}
    for result in params.get("results", []):
        if not isinstance(result, dict) or result.get("match_id") not in matches_by_id: raise validation_error("results")
        match = matches_by_id[result["match_id"]]
        winner = result.get("winner")
        if winner not in (match["home"], match["away"]): raise validation_error("results")
        match["winner"] = winner
        match["loser"] = match["away"] if winner == match["home"] else match["home"]
        propagate(match)
        if match.get("loser_to") and match["loser"]:
            target = matches_by_id[match["loser_to"]["match_id"]]
            target[match["loser_to"]["slot"]] = match["loser"]
    response = {"format": "single_elim", "bracket_size": size, "rounds": rounds}
    if third_place is not None: response["third_place"] = third_place
    return response


def double_elim(data: dict) -> dict:
    teams, params = _validate_teams(data, 3, 128)
    bracket_reset = params.get("bracket_reset", False)
    results = params.get("results", [])
    if type(bracket_reset) is not bool or not isinstance(results, list): raise validation_error("params")
    size = 1 << (len(teams) - 1).bit_length()
    k = int(math.log2(size))
    order = _seed_order(size)
    winners, losers, all_matches = [], [], {}
    for r in range(1, k + 1):
        matches = []
        for i in range(1, size // (2**r) + 1):
            mid = f"WR{r}M{i}"
            wt = {"match_id": f"WR{r+1}M{(i+1)//2}", "slot": "home" if i % 2 else "away"} if r < k else {"match_id": "GF1", "slot": "home"}
            lt = {"match_id": f"LR{1 if r == 1 else 2*r-2}M{max(1, (i+1)//2)}", "slot": "home" if i % 2 else "away"}
            if r == 1:
                seeds = sorted(order[(i-1)*2:i*2]); hs, aws = seeds
                home = teams[hs-1] if hs <= len(teams) else None; away = teams[aws-1] if aws <= len(teams) else None
                if home is None: home, away, hs, aws = away, None, aws, None
                match = _match(mid, "winners", r, i, home, away, hs, aws, wt, lt, away is None)
            else: match = _match(mid, "winners", r, i, winner_to=wt, loser_to=lt)
            matches.append(match); all_matches[mid] = match
        winners.append({"round": r, "matches": matches})
    for r in range(1, 2*(k-1)+1):
        j = (r + 1) // 2
        count = size // (2**(j+1))
        matches = []
        for i in range(1, count+1):
            mid = f"LR{r}M{i}"
            wt = {"match_id": f"LR{r+1}M{(i+1)//2}", "slot": "home" if r % 2 == 0 and i % 2 else "away"} if r < 2*(k-1) else {"match_id": "GF1", "slot": "away"}
            match = _match(mid, "losers", r, i, winner_to=wt)
            matches.append(match); all_matches[mid] = match
        losers.append({"round": r, "matches": matches})
    gf1 = _match("GF1", "grand_final", 1, 1, winner_to={"match_id": "GF2", "slot": "home"} if bracket_reset else None)
    gf2 = _match("GF2", "grand_final", 2, 1) if bracket_reset else None
    if gf2 is not None: gf2.update({"conditional": True, "required": None})
    all_matches["GF1"] = gf1
    if gf2: all_matches["GF2"] = gf2
    for first in winners[0]["matches"]:
        if first["winner"] and first["winner_to"]:
            all_matches[first["winner_to"]["match_id"]][first["winner_to"]["slot"]] = first["winner"]
    for result in results:
        if not isinstance(result, dict) or result.get("match_id") not in all_matches: raise validation_error("results")
        match = all_matches[result["match_id"]]; winner = result.get("winner")
        if winner not in (match["home"], match["away"]): raise validation_error("results")
        match["winner"] = winner; match["loser"] = match["away"] if winner == match["home"] else match["home"]
        for route, participant in ((match.get("winner_to"), match["winner"]), (match.get("loser_to"), match["loser"])):
            if route and route["match_id"] in all_matches: all_matches[route["match_id"]][route["slot"]] = participant
    if gf2 and gf1["winner"]:
        gf2["home"], gf2["away"] = gf1["home"], gf1["away"]
        gf2["required"] = gf1["winner"] == gf1["away"]
    return {"format": "double_elim", "bracket_size": size, "bracket_reset": bracket_reset, "winners": winners, "losers": losers, "grand_final": [gf1] + ([gf2] if gf2 else [])}


def generate_fixtures(data: dict[str, Any]) -> dict:
    if not isinstance(data, dict): raise validation_error("body")
    format_name = data.get("format")
    handlers = {"round_robin": round_robin, "swiss": swiss, "single_elim": single_elim, "double_elim": double_elim}
    if format_name not in handlers: raise validation_error("format")
    return handlers[format_name](data)
