from copy import deepcopy


SPORTS = {
    "football": {
        "sport_id": "football", "name": "Football", "scoring_model": "event",
        "periods": {"count": 2, "duration_minutes": 45},
        "scoring_events": {"goal": {"points": 1}}, "draw_allowed": True,
        "overtime": {"policy": "none"},
        "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
        "roster": {"min_squad_size": 11, "max_squad_size": 25, "required_positions": {"gk": 1}},
    },
    "basketball": {
        "sport_id": "basketball", "name": "Basketball", "scoring_model": "event",
        "periods": {"count": 4, "duration_minutes": 12},
        "scoring_events": {"free_throw": {"points": 1}, "two_pointer": {"points": 2}, "three_pointer": {"points": 3}},
        "draw_allowed": False, "overtime": {"policy": "extra_time", "duration_minutes": 5},
        "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
        "roster": {"min_squad_size": 5, "max_squad_size": 15, "required_positions": {}},
    },
    "cricket": {
        "sport_id": "cricket", "name": "Cricket", "scoring_model": "innings",
        "periods": {"innings_per_team": 1, "overs_per_innings": 20, "balls_per_over": 6, "wickets_per_innings": 10},
        "scoring_events": {
            "dot_ball": {"runs": 0, "legal_ball": True, "wicket": False},
            "single": {"runs": 1, "legal_ball": True, "wicket": False},
            "two": {"runs": 2, "legal_ball": True, "wicket": False},
            "four": {"runs": 4, "legal_ball": True, "wicket": False},
            "six": {"runs": 6, "legal_ball": True, "wicket": False},
            "wide": {"runs": 1, "legal_ball": False, "wicket": False},
            "no_ball": {"runs": 1, "legal_ball": False, "wicket": False},
            "wicket": {"runs": 0, "legal_ball": True, "wicket": True},
        },
        "draw_allowed": True, "overtime": {"policy": "super_over"},
        "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
        "roster": {"min_squad_size": 11, "max_squad_size": 18, "required_positions": {"wicketkeeper": 1}},
    },
    "esports": {
        "sport_id": "esports", "name": "Esports", "scoring_model": "round",
        "periods": {"best_of": 3}, "scoring_events": {"round_win": {"rounds": 1}},
        "draw_allowed": False, "overtime": {"policy": "none"},
        "tie_break_order": ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"],
        "roster": {"min_squad_size": 5, "max_squad_size": 8, "required_positions": {}},
    },
}


def initial_state(seed: int = 42, stock: dict | None = None) -> dict:
    stock = stock or {"var-jersey-001-M": 1, "var-jersey-001-L": 5}
    return {
        "seed": seed,
        "sports": deepcopy(SPORTS),
        "tenants": {"tenant-alpha": {"name": "Alpha Sports"}, "tenant-beta": {"name": "Beta Athletics"}},
        "clubs": {
            "club-alpha-1": {"tenant_id": "tenant-alpha"}, "club-alpha-2": {"tenant_id": "tenant-alpha"},
            "club-beta-1": {"tenant_id": "tenant-beta"},
        },
        "players": {
            "player-alpha-1": {"tenant_id": "tenant-alpha", "club_id": "club-alpha-1"},
            "player-alpha-2": {"tenant_id": "tenant-alpha", "club_id": "club-alpha-2"},
            "player-beta-1": {"tenant_id": "tenant-beta", "club_id": "club-beta-1"},
        },
        "rbac_leagues": {
            "league-alpha-1": {"tenant_id": "tenant-alpha", "owner": True},
            "league-alpha-2": {"tenant_id": "tenant-alpha", "owner": False},
            "league-beta-1": {"tenant_id": "tenant-beta", "owner": False},
        },
        "leagues": {}, "matches": {}, "event_ids": {}, "rosters": {}, "roster_requests": {},
        "inventory": {k: {"stock": int(v), "reserved": 0} for k, v in stock.items()},
        "variants": {
            "var-jersey-001-M": {"product_id": "prod-jersey-001", "price_minor": 450000, "currency": "PKR"},
            "var-jersey-001-L": {"product_id": "prod-jersey-001", "price_minor": 450000, "currency": "PKR"},
        },
        "orders": {}, "offline_processed": {},
    }
