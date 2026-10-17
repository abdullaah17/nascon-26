# Agent Brief 1 - Sole Backend Lead

Read `00_SHARED_EXECUTION_PLAN.md` first. You are the only backend developer. You own `backend/**`, `docker-compose.yml`, backend dependencies, database design, every audit endpoint, and backend integration fixes. Do not wait for another person to implement a backend module.

## Outcome

Maximize the 36 backend points and the automated part of offline-sync with a reproducible service on host port 8080. Exact contract behavior matters more than broad product polish.

## Required endpoint checklist

- `GET /health`
- `POST /audit/v1/reset`
- `POST /audit/v1/sports`
- `POST /audit/v1/fixtures`
- `POST /audit/v1/leagues`
- `POST /audit/v1/events`
- `GET /audit/v1/score/{match_id}`
- `GET /audit/v1/standings/{league_id}`
- `POST /audit/v1/roster/setup`
- `POST /audit/v1/roster/transfer`
- `GET /audit/v1/roster/history/{player_id}`
- `POST /audit/v1/checkout`
- `GET /audit/v1/inventory/{variant_id}`
- `POST /audit/v1/rbac-matrix`
- Seven `/audit/v1/rbac/*` probes
- `GET /api/v1/ping`
- `POST /audit/v1/offline-sync`

## Implementation order

1. Compose, PostgreSQL, shared database session, standard errors, body limit, canonical JSON/signing, `/health`.
2. Deterministic `/reset` and all exact baseline IDs.
3. Generic sport storage, leagues, match event log, score read model.
4. Round-robin and single-elimination fixtures, then Swiss and double elimination.
5. Standings and H2H/tie-break logic.
6. Store reservation/payment/PDF receipt with database transactions.
7. Roster rules, loans, history, and idempotency.
8. RBAC/JWT probes, tenant isolation, and `/api/v1/ping` rate limit.
9. Offline-sync by directly invoking scoring/roster services.
10. Hidden-risk fixes from Person 3, clean-clone verification, freeze.

Land vertical slices. Do not leave all routers until the end.

## Architecture

Use a modular monolith. Keep each domain in `backend/app/modules/<domain>/` with separate schemas, service logic, router, and models where practical. Put only cross-cutting primitives in `app/core`.

Critical internal callables:

```python
sign_record(record_id: str, payload: object) -> str
apply_score_event(session, request_dict, *, replay_status_code=False)
apply_roster_transfer(session, request_dict, *, replay_status_code=False)
```

Offline-sync calls domain services directly, never internal HTTP. Reset deletes and seeds all domain state in one transaction.

## Correctness requirements

- Read `DAY1_SALT` only from the environment and forward it through Compose. Never expose the value.
- Validate in exact order: schema/type, referenced IDs, business conflict, payment exception.
- Identical client-ID replay returns stored output with `200`; different bodies use the contract's duplicate behavior.
- Do not hard-code sport or scoring-event names.
- Event history is append-only; compensations never mutate originals.
- Standings are rebuilt from event logs and implement recursive restart-on-split ties.
- Swiss uses global optimal rematch-free pairing rather than greedy pairing.
- Inventory uses database-level atomic reservation. The 20-request burst must yield one success.
- Authorization failures across tenants are `403`, while genuinely absent IDs are `404` according to the contract.
- `/audit/v1/*` and `/health` are rate-limit exempt.

## Fast feedback to teammates

By the first integration checkpoint, give Person 2:

- Base URL rules.
- Demo login behavior.
- Route/JSON examples needed by required screens.
- Exact offline action envelope.

Give Person 3 a running Compose stack and endpoint completion list. For every completed endpoint, provide one happy-path request so QA can start immediately.

## Tests to run personally

- Reset twice and compare results/state.
- Appendix A signature vector and draw-lots ordering (`t1`, `t3`, `t2`).
- Odd/even fixtures, Swiss no-rematch optimum, elimination byes and GF reset.
- All scoring models, compensation, idempotency, and standings three-way tie.
- Transfer validation order, deferred transfer, and one-time loan return.
- Twenty concurrent final-unit checkouts, decline/capture release, receipt parsing.
- Full RBAC negative matrix, tampered/expired/`alg:none` JWT, rate-limit recovery.
- Offline stale rebase, duplicate replay, future version, per-action ordering.

## Completion handoff

Report to the team: completed endpoints, known deviations, Compose startup time, tests passing/failing, schema changes, mobile-impacting contract changes, and final safe-push recommendation.

