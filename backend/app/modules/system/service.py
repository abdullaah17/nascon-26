from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.core.models import AppState, AuditLog, Entity, IdempotencyRecord, Inventory, Sport, Tenant


DEFAULT_STOCK = {"var-jersey-001-M": 1, "var-jersey-001-L": 5}
TIE_BREAKS = ["h2h_points", "h2h_diff", "overall_diff", "scored", "fair_play", "draw_lots"]


def _sport(
    sport_id: str,
    name: str,
    scoring_model: str,
    periods: dict,
    scoring_events: dict,
    draw_allowed: bool,
    overtime: dict,
    min_size: int,
    max_size: int,
    positions: dict,
) -> Sport:
    config = {
        "sport_id": sport_id,
        "name": name,
        "scoring_model": scoring_model,
        "periods": periods,
        "scoring_events": scoring_events,
        "draw_allowed": draw_allowed,
        "overtime": overtime,
        "tie_break_order": TIE_BREAKS,
        "roster": {
            "min_squad_size": min_size,
            "max_squad_size": max_size,
            "required_positions": positions,
        },
    }
    return Sport(sport_id=sport_id, name=name, config=config, baseline=True)


def baseline_sports() -> list[Sport]:
    return [
        _sport("football", "Football", "event", {"count": 2, "duration_minutes": 45}, {"goal": {"points": 1}}, True, {"policy": "none"}, 11, 25, {"gk": 1}),
        _sport("basketball", "Basketball", "event", {"count": 4, "duration_minutes": 12}, {"free_throw": {"points": 1}, "two_pointer": {"points": 2}, "three_pointer": {"points": 3}}, False, {"policy": "extra_time", "duration_minutes": 5}, 5, 15, {}),
        _sport("cricket", "Cricket", "innings", {"innings_per_team": 1, "overs_per_innings": 20, "balls_per_over": 6, "wickets_per_innings": 10}, {"dot_ball": {"runs": 0, "legal_ball": True, "wicket": False}, "single": {"runs": 1, "legal_ball": True, "wicket": False}, "two": {"runs": 2, "legal_ball": True, "wicket": False}, "four": {"runs": 4, "legal_ball": True, "wicket": False}, "six": {"runs": 6, "legal_ball": True, "wicket": False}, "wide": {"runs": 1, "legal_ball": False, "wicket": False}, "no_ball": {"runs": 1, "legal_ball": False, "wicket": False}, "wicket": {"runs": 0, "legal_ball": True, "wicket": True}}, True, {"policy": "super_over"}, 11, 18, {"wicketkeeper": 1}),
        _sport("esports", "Esports", "round", {"best_of": 3}, {"round_win": {"rounds": 1}}, False, {"policy": "none"}, 5, 8, {}),
    ]


def reset_state(session: Session, seed: int = 42, stock: dict[str, int] | None = None) -> dict:
    chosen_stock = DEFAULT_STOCK.copy() if stock is None else stock.copy()
    for model in (AuditLog, IdempotencyRecord, Entity, Inventory, Sport, Tenant, AppState):
        session.execute(delete(model))

    session.add(AppState(key="reset", value={"seed": seed, "seeded": True}))
    session.add_all([Tenant(tenant_id="tenant-alpha", name="Alpha Sports"), Tenant(tenant_id="tenant-beta", name="Beta Athletics")])
    session.add_all(baseline_sports())

    entities = [
        ("product", "prod-jersey-001", "tenant-alpha", {}),
        ("league", "league-alpha-1", "tenant-alpha", {}),
        ("league", "league-alpha-2", "tenant-alpha", {}),
        ("league", "league-beta-1", "tenant-beta", {}),
        ("club", "club-alpha-1", "tenant-alpha", {}),
        ("club", "club-alpha-2", "tenant-alpha", {}),
        ("club", "club-beta-1", "tenant-beta", {}),
        ("player", "player-alpha-1", "tenant-alpha", {"club_id": "club-alpha-1"}),
        ("player", "player-alpha-2", "tenant-alpha", {"club_id": "club-alpha-2"}),
        ("player", "player-beta-1", "tenant-beta", {"club_id": "club-beta-1"}),
    ]
    session.add_all([Entity(kind=k, entity_id=e, tenant_id=t, data=d) for k, e, t, d in entities])
    for variant_id, quantity in chosen_stock.items():
        session.add(Inventory(variant_id=variant_id, product_id="prod-jersey-001", stock=quantity, reserved=0, price_minor=450000, currency="PKR"))
    session.commit()
    return {"status": "reset_complete", "seed": seed, "sports": ["football", "basketball", "cricket", "esports"], "tenants": ["tenant-alpha", "tenant-beta"], "stock": chosen_stock}


def is_ready(session: Session) -> bool:
    session.execute(text("SELECT 1"))
    state = session.scalar(select(AppState).where(AppState.key == "reset"))
    return bool(state and state.value.get("seeded"))
