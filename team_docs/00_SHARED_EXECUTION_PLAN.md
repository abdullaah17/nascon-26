# NaSCon '26 Part I - Shared Three-Person Execution Plan

Feed this file to every agent before its role-specific brief. This plan is derived from the official Part I specification and supersedes older workspace notes where they conflict.

## 1. Mission and authority

Build the complete Part I submission with one backend developer, one mobile developer, and one QA/documentation owner. The backend must be reachable at `http://localhost:8080` and implement the exact `/audit/v1/*` contract. The official PDF is authoritative. Never invent a different response shape, status code, validation order, or identifier.

Priority order when time is limited:

1. Fresh-clone reproducibility, `/health`, and `/audit/v1/reset`.
2. Exact audit endpoint behavior and deterministic error responses.
3. Hidden-vector correctness for the six backend areas.
4. Persistent mobile offline queue and backend synchronization.
5. Required mobile screens and the ten-minute judging path.
6. Broader production features not exercised by the audit contract.

## 2. Non-negotiable rules

- The repository must be public for grading.
- `docker compose up -d --build` must start everything without manual steps.
- The API must be published on host port `8080` and become healthy within 120 seconds.
- `DAY1_SALT` comes only from the environment. Compose must forward it as `DAY1_SALT: ${DAY1_SALT}`.
- Never commit, hard-code, print, log, or place the real salt in `.env.example`, source, tests, fixtures, screenshots, or agent responses.
- `.env.local` is already ignored and contains the authority-provided local value. Agents may use it, but must never display its contents.
- `/audit/v1/*` and `/health` are not rate-limited. Only `/api/v1/*` uses the specified rolling limit.
- Audit routes require no authorization except the seven RBAC probe routes.
- All non-2xx responses use the standard `{ "error": { "code", "message", "details" } }` envelope.
- Apply validation precedence exactly: schema/type `400`, missing referenced ID `404`, business/state conflict `409`, except checkout payment failures use `402`.
- Client-selected IDs are idempotent: identical replay returns the stored result with `200`; reuse with a different body returns the contract's duplicate-ID error.
- No domain branch may depend on a seeded sport or event name such as `football`, `cricket`, `goal`, or `wicket`.
- Push at least once inside each official checkpoint window: 10:45-11:45, 11:45-12:45, 12:45-13:45, and 13:45-14:45 PKT. Final eligible push is 15:05:00 PKT.

## 3. Ownership

| Person | Owns | Primary score areas |
|---|---|---|
| Person 1 - Backend Lead | All backend implementation, database, Compose, every `/audit/v1/*` endpoint, security, algorithms, concurrency, backend tests | All 36 backend points plus offline-sync API |
| Person 2 - Mobile Lead | Complete mobile app, local persistence, pending queue, role-aware screens, APK/device demo | 10 UI/HCI points plus on-device offline credit |
| Person 3 - QA, Docs, and Release | Black-box API tests, load/concurrency probes, traceability, coverage collection, README, checkpoint/release verification | Protects all areas; no backend implementation ownership |

Person 1 is the only person who edits `backend/**`, backend dependencies, or backend Compose service definitions. Person 2 edits `mobile/**`. Person 3 edits `tests/**`, release documentation, and test tooling. Changes outside those boundaries require Person 1 approval.

## 4. Required repository shape

```text
docker-compose.yml                 # Person 1
.env.example                       # Person 1; blank DAY1_SALT only
README.md                          # Person 3, reviewed by Persons 1 and 2
TRACEABILITY.md                    # Person 3, evidence supplied by Persons 1 and 2
COVERAGE.json                      # Person 3, truthful measurements
run_tests.sh                       # Person 3
tests/                             # Person 3; black-box and integration tests
backend/
  Dockerfile                       # Person 1
  requirements.txt                 # Person 1
  app/
    core/                          # Person 1
    modules/                       # Person 1: every backend domain
mobile/                            # Person 2
  release/app-release.apk
```

Backend modules should isolate their `models.py`, `schemas.py`, `service.py`, and `router.py`. Shared SQLAlchemy `Base`, session handling, error helpers, canonical JSON, and clock utilities belong in `app/core`. Person 3 tests only through public APIs unless Person 1 explicitly requests a focused unit test.

## 5. Integration contracts

### Backend to mobile

Person 1 publishes a concise route/JSON sheet and keeps FastAPI OpenAPI usable. Person 2 uses one configurable base URL and must not duplicate server business rules. Offline actions use the exact Section 5.14 envelope.

### QA to implementation

Person 3 reports failures as reproducible requests containing method, path, request body, expected result, actual result, and the relevant contract section. Person 3 does not patch backend code; Person 1 owns the fix.

### Signing

Person 1 supplies exactly one backend signing helper:

```python
sign_record(record_id: str, payload: object) -> str
```

It must use the UTF-8 environment value without trimming or hex decoding, canonical JSON with recursively sorted keys and no whitespace, and lowercase HMAC-SHA256 hex. The signed message is `id + "|" + canonical_payload`.

### Time and IDs

- Timestamps: UTC `YYYY-MM-DDTHH:MM:SSZ`.
- Dates: `YYYY-MM-DD`.
- Money: integer paisa; currency is `PKR`.
- Contract identifiers are stored and returned verbatim.
- Tests should inject a clock where output contains server time.

## 6. Integration cadence

1. Person 1 lands the backend skeleton, health, database startup, reset shell, and API contract first.
2. Person 2 builds mobile against the published contract and mock fixtures until endpoints land.
3. Person 3 starts black-box tests immediately and sends failures to the relevant owner without editing implementation files.
4. Synchronize at least every 45 minutes. Person 1 remains the final merge/release authority.
5. At freeze, run from a clean clone with no existing volumes:

```bash
DAY1_SALT='<authority value>' docker compose up -d --build
curl -fsS http://localhost:8080/health
./run_tests.sh
```

Do not paste the actual value into shell history if avoidable; locally load the ignored `.env.local` into the environment.

## 7. Definition of done

- Fresh Compose startup succeeds within limits.
- `/health` verifies both the database and seeded baseline.
- Two consecutive reset calls produce identical baseline state.
- Every required endpoint has happy-path, validation, not-found, conflict, and replay coverage as applicable.
- Signatures match Appendix A test vector 1.
- Draw-lots ordering follows ascending hash value; the correct Appendix A order for its three example teams is `t1`, `t3`, `t2`.
- The last-unit checkout test yields exactly one `201`, nineteen `409`, stock `0`, reserved `0`.
- RBAC negative cases return exactly `403`, not `404`.
- Offline-sync replay, stale-base handling, duplicate handling, and per-action results pass backend tests.
- The mobile queue survives force-close and shows per-action sync outcomes.
- `TRACEABILITY.md`, `COVERAGE.json`, README demo accounts, and `mobile/release/app-release.apk` are present.
