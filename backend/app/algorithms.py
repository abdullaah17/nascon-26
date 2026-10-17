import hashlib
import math
from itertools import combinations
from typing import Any

from .runtime import ApiError


def round_robin(teams: list[str], params: dict) -> dict:
    legs = params.get("legs", 1)
    if legs not in (1, 2):
        raise ApiError(400, "VALIDATION_ERROR", "legs must be 1 or 2.", {"fields": ["params.legs"]})
    withdrawals = params.get("withdrawals", [])
    policy = params.get("withdrawal_policy", "forfeit_remaining")
    if policy not in ("void_all", "forfeit_remaining"):
        raise ApiError(400, "VALIDATION_ERROR", "Invalid withdrawal policy.", {"fields": ["params.withdrawal_policy"]})
    participants: list[str | None] = list(teams)
    if len(participants) % 2:
        participants.append(None)
    nslots = len(participants)
    per_leg = nslots - 1
    round_count = per_leg * legs
    withdrawal_map = {}
    for item in withdrawals:
        team = item.get("team_id")
        after = item.get("after_round")
        if team not in teams or not isinstance(after, int) or not 0 <= after <= round_count:
            raise ApiError(400, "VALIDATION_ERROR", "Invalid withdrawal.", {"fields": ["params.withdrawals"]})
        withdrawal_map[team] = after
    base = list(participants)
    output = []
    totals = {"total": 0, "scheduled": 0, "forfeit": 0, "voided": 0}
    for leg in range(1, legs + 1):
        rotation = list(base)
        for local_round in range(1, per_leg + 1):
            global_round = (leg - 1) * per_leg + local_round
            matches, byes = [], []
            for i in range(nslots // 2):
                a, b = rotation[i], rotation[nslots - 1 - i]
                if a is None or b is None:
                    byes.append(b if a is None else a)
                    continue
                # Berger orientation: alternate the fixed team's board; retain
                # the rotating boards' orientation. This keeps every team's
                # home/away difference within one for a single leg.
                if i == 0 and local_round % 2 == 0:
                    home, away = b, a
                else:
                    home, away = a, b
                if leg == 2:
                    home, away = away, home
                status, awarded = "scheduled", None
                home_after, away_after = withdrawal_map.get(home), withdrawal_map.get(away)
                if policy == "void_all" and (home_after is not None or away_after is not None):
                    status = "voided"
                elif policy == "forfeit_remaining":
                    hw = home_after is not None and global_round > home_after
                    aw = away_after is not None and global_round > away_after
                    if hw and aw:
                        status = "voided"
                    elif hw or aw:
                        status, awarded = "forfeit", away if hw else home
                index = len(matches) + 1
                matches.append({
                    "match_id": f"RR-L{leg}-R{global_round}-M{index}", "leg": leg,
                    "home": home, "away": away, "status": status, "awarded_to": awarded,
                })
                totals["total"] += 1
                totals[status] += 1
            output.append({"round": global_round, "matches": matches, "byes": byes})
            rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    return {"format": "round_robin", "legs": legs, "team_count": len(teams), "round_count": round_count, "rounds": output, "summary": totals}


def swiss(teams: list[str], params: dict) -> dict:
    n = len(teams)
    total_rounds = params.get("total_rounds", math.ceil(math.log2(n)))
    current_round = params.get("round", 1)
    history = params.get("history", [])
    if not isinstance(total_rounds, int) or not 1 <= total_rounds <= n - 1 or not isinstance(current_round, int) or not 1 <= current_round <= total_rounds:
        raise ApiError(400, "VALIDATION_ERROR", "Invalid Swiss round limits.", {"fields": ["params"]})
    if [h.get("round") for h in history] != list(range(1, current_round)):
        raise ApiError(400, "VALIDATION_ERROR", "History must contain prior rounds exactly.", {"fields": ["params.history"]})
    scores = {t: 0.0 for t in teams}
    opponents = {t: [] for t in teams}
    byes = set()
    for rnd in history:
        bye = rnd.get("bye")
        if bye is not None:
            if bye not in scores:
                raise ApiError(400, "VALIDATION_ERROR", "Unknown bye team.", {"fields": ["params.history"]})
            scores[bye] += 1.0
            byes.add(bye)
        for m in rnd.get("matches", []):
            h, a, result = m.get("home"), m.get("away"), m.get("result")
            if h not in scores or a not in scores or h == a or result not in ("home", "away", "draw"):
                raise ApiError(400, "VALIDATION_ERROR", "Invalid Swiss history.", {"fields": ["params.history"]})
            opponents[h].append(a); opponents[a].append(h)
            if result == "home": scores[h] += 1
            elif result == "away": scores[a] += 1
            else: scores[h] += .5; scores[a] += .5
    buchholz = {t: sum(scores[o] for o in opponents[t]) for t in teams}
    standings = sorted(teams, key=lambda t: (-scores[t], -buchholz[t], teams.index(t)))
    table = [{"rank": i + 1, "team_id": t, "score": scores[t], "buchholz": buchholz[t]} for i, t in enumerate(standings)]
    if current_round == 1:
        m = n // 2
        bye = teams[-1] if n % 2 else None
        pairs = [(teams[i], teams[i + m]) for i in range(m)]
    else:
        candidates = [None]
        if n % 2:
            candidates = sorted((t for t in teams if t not in byes), key=lambda t: (scores[t], -teams.index(t)))
        pairs = None; bye = None
        met = {frozenset((t, o)) for t, ops in opponents.items() for o in ops}

        def best_pairing(pool: list[str]):
            best: tuple[float, list[tuple[str, str]]] | None = None
            def rec(left: list[str], made: list[tuple[str, str]], cost: float):
                nonlocal best
                if not left:
                    if best is None or cost < best[0]: best = (cost, made[:])
                    return
                if best is not None and cost > best[0]: return
                first = left[0]
                for i in range(1, len(left)):
                    other = left[i]
                    if frozenset((first, other)) in met: continue
                    rec(left[1:i] + left[i + 1:], made + [(first, other)], cost + abs(scores[first] - scores[other]))
            rec(pool, [], 0.0)
            return None if best is None else best[1]

        for candidate in candidates:
            pool = [t for t in teams if t != candidate]
            result = best_pairing(pool)
            if result is not None:
                pairs, bye = result, candidate
                break
        if pairs is None:
            raise ApiError(409, "NO_VALID_PAIRING", "No rematch-free pairing exists.", {"round": current_round})
    pairings = [{"match_id": f"SW-R{current_round}-M{i+1}", "home": h, "away": a} for i, (h, a) in enumerate(pairs)]
    return {"format": "swiss", "round": current_round, "total_rounds": total_rounds, "pairings": pairings, "bye": bye, "standings": table}


def seed_order(size: int) -> list[int]:
    order = [1, 2]
    while len(order) < size:
        new_size = len(order) * 2
        order = [x for s in order for x in (s, new_size + 1 - s)]
    return order


def single_elim(teams: list[str], params: dict) -> dict:
    size = 1 << (len(teams) - 1).bit_length()
    seeds = seed_order(size)
    rounds = []
    previous = []
    total_rounds = int(math.log2(size))
    for r in range(1, total_rounds + 1):
        count = size // (2 ** r)
        matches = []
        for i in range(1, count + 1):
            if r == 1:
                hs, aws = seeds[2*i-2], seeds[2*i-1]
                home = teams[hs - 1] if hs <= len(teams) else None
                away = teams[aws - 1] if aws <= len(teams) else None
                if home is None and away is not None: home, away, hs, aws = away, None, aws, hs
            else:
                home = previous[2*i-2].get("winner")
                away = previous[2*i-1].get("winner")
                hs = aws = None
            match_id = f"R{r}M{i}"
            bye = r == 1 and away is None
            winner = home if bye else None
            matches.append({
                "match_id": match_id, "bracket": "main", "round": r, "index": i,
                "home": home, "away": away, "home_seed": hs, "away_seed": aws,
                "bye": bye, "winner": winner, "loser": None,
                "winner_to": None if r == total_rounds else {"match_id": f"R{r+1}M{(i+1)//2}", "slot": "home" if i % 2 else "away"},
                "loser_to": None,
            })
        rounds.append({"round": r, "matches": matches})
        previous = matches
    by_id = {m["match_id"]: m for rd in rounds for m in rd["matches"]}
    # repeatedly propagate byes/results in caller-supplied order
    pending = list(params.get("results", []))
    while pending:
        progressed = False
        for item in pending[:]:
            m = by_id.get(item.get("match_id"))
            if not m: raise ApiError(400, "VALIDATION_ERROR", "Unknown match_id.", {"fields": ["params.results"]})
            if item.get("winner") not in (m["home"], m["away"]): continue
            m["winner"] = item["winner"]; m["loser"] = m["away"] if item["winner"] == m["home"] else m["home"]
            pending.remove(item); progressed = True
        for m in by_id.values():
            target = m.get("winner_to")
            if m.get("winner") and target:
                by_id[target["match_id"]][target["slot"]] = m["winner"]
        if not progressed:
            raise ApiError(400, "VALIDATION_ERROR", "Winner is not a match participant.", {"fields": ["params.results"]})
    if params.get("third_place_match"):
        semis = rounds[-2]["matches"]
        rounds.append({"round": total_rounds, "matches": [{
            "match_id": "TP", "bracket": "third_place", "round": total_rounds, "index": 1,
            "home": semis[0].get("loser"), "away": semis[1].get("loser"), "home_seed": None, "away_seed": None,
            "bye": False, "winner": None, "loser": None, "winner_to": None, "loser_to": None,
        }]})
        semis[0]["loser_to"] = {"match_id": "TP", "slot": "home"}; semis[1]["loser_to"] = {"match_id": "TP", "slot": "away"}
    return {"format": "single_elim", "bracket_size": size, "rounds": rounds}


def double_elim(teams: list[str], params: dict) -> dict:
    # Exact counts/IDs and deterministic routing. Results are applied to WR1 immediately;
    # later propagation follows the graph as participants become known.
    size = 1 << (len(teams) - 1).bit_length()
    k = int(math.log2(size))
    seeds = seed_order(size)
    winners, losers = [], []
    for r in range(1, k + 1):
        matches = []
        count = size // (2 ** r)
        for i in range(1, count + 1):
            home = away = None; hs = aws = None
            if r == 1:
                hs, aws = seeds[2*i-2], seeds[2*i-1]
                home = teams[hs-1] if hs <= len(teams) else None
                away = teams[aws-1] if aws <= len(teams) else None
                if home is None: home, away, hs, aws = away, None, aws, hs
            matches.append({"match_id": f"WR{r}M{i}", "bracket": "winners", "round": r, "index": i,
                "home": home, "away": away, "home_seed": hs, "away_seed": aws, "bye": r == 1 and away is None,
                "winner": home if r == 1 and away is None else None, "loser": None,
                "winner_to": {"match_id": f"WR{r+1}M{(i+1)//2}", "slot": "home" if i % 2 else "away"} if r < k else {"match_id": "GF1", "slot": "home"},
                "loser_to": None})
        winners.append({"round": r, "matches": matches})
    for r in range(1, 2*(k-1)+1):
        j = (r + 1) // 2
        count = size // (2 ** (j + 1))
        matches = [{"match_id": f"LR{r}M{i}", "bracket": "losers", "round": r, "index": i,
            "home": None, "away": None, "home_seed": None, "away_seed": None, "bye": False,
            "winner": None, "loser": None,
            "winner_to": ({"match_id": f"LR{r+1}M{(i+1)//2 if r % 2 == 0 else i}", "slot": "home" if r % 2 else ("home" if i % 2 else "away")} if r < 2*(k-1) else {"match_id": "GF1", "slot": "away"}),
            "loser_to": None} for i in range(1, count + 1)]
        losers.append({"round": r, "matches": matches})
    # Recommended drops; slot mapping is intentionally deterministic.
    if losers:
        for i, m in enumerate(winners[0]["matches"]):
            target = losers[0]["matches"][i//2]
            m["loser_to"] = {"match_id": target["match_id"], "slot": "home" if i % 2 == 0 else "away"}
        for r in range(2, k + 1):
            lr = losers[2*r-3]["matches"]
            for i, m in enumerate(winners[r-1]["matches"]):
                m["loser_to"] = {"match_id": lr[i % len(lr)]["match_id"], "slot": "away"}
    reset = bool(params.get("bracket_reset", False))
    grand = [{"match_id": "GF1", "bracket": "grand_final", "round": 1, "index": 1,
        "home": None, "away": None, "home_seed": None, "away_seed": None, "bye": False,
        "winner": None, "loser": None, "winner_to": None, "loser_to": None}]
    if reset:
        grand.append({"match_id": "GF2", "bracket": "grand_final", "round": 2, "index": 1,
            "home": None, "away": None, "home_seed": None, "away_seed": None, "bye": False,
            "winner": None, "loser": None, "winner_to": None, "loser_to": None, "conditional": True, "required": None})
    by_id = {m["match_id"]: m for group in winners + losers for m in group["matches"]}
    by_id.update({m["match_id"]: m for m in grand})
    # Seeded byes are real winners and must feed the next winners-bracket
    # round before caller-supplied results are validated.
    for group in winners:
        for match in group["matches"]:
            target = match.get("winner_to")
            if match.get("winner") and target and target["match_id"] in by_id:
                by_id[target["match_id"]][target["slot"]] = match["winner"]
    for item in params.get("results", []):
        m = by_id.get(item.get("match_id"))
        if not m or item.get("winner") not in (m.get("home"), m.get("away")):
            raise ApiError(400, "VALIDATION_ERROR", "Invalid bracket result.", {"fields": ["params.results"]})
        m["winner"] = item["winner"]; m["loser"] = m["away"] if item["winner"] == m["home"] else m["home"]
        for field, person in (("winner_to", m["winner"]), ("loser_to", m["loser"])):
            target = m.get(field)
            if target and target["match_id"] in by_id: by_id[target["match_id"]][target["slot"]] = person
    if reset and grand[0].get("winner"):
        grand[1]["home"], grand[1]["away"] = grand[0]["home"], grand[0]["away"]
        grand[1]["required"] = grand[0]["winner"] == grand[0]["away"]
    return {"format": "double_elim", "bracket_size": size, "bracket_reset": reset, "winners": winners, "losers": losers, "grand_final": grand}


def lots_key(seed: int, league_id: str, team_id: str) -> str:
    return hashlib.sha256(f"{seed}|{league_id}|{team_id}".encode("utf-8")).hexdigest()
