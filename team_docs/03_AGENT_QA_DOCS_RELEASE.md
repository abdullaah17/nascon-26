# Agent Brief 3 - QA, Documentation, and Release

Read `00_SHARED_EXECUTION_PLAN.md` first. You own black-box tests, documentation, traceability, coverage reporting, checkpoint tracking, and release verification. Do not edit `backend/**` or `mobile/**`; send reproducible failures to the relevant owner.

## Outcome

Continuously expose contract violations early, protect the team from reproducibility penalties, and ensure the final repository contains every required artifact.

## Owned files

- `tests/**`
- `run_tests.sh`
- `README.md`
- `TRACEABILITY.md`
- `COVERAGE.json`
- QA reports and release checklist

Coordinate root-file edits with Person 1. Do not place the real `DAY1_SALT` in any owned file or output.

## Black-box API test order

1. Compose startup, port 8080, `/health`, and reset repeatability.
2. Shared error envelope, validation precedence, body-size limit, and idempotency.
3. Sports and each fixture format.
4. Event sourcing, signatures, score projection, compensation, and standings.
5. Roster rules and audit history.
6. Concurrent checkout and PDF receipt extraction.
7. RBAC negative matrix, JWT attacks, tenant boundaries, and rate limiting.
8. Offline-sync ordering, stale bases, conflicts, and replay.

Write tests only against public HTTP behavior. A failure report must include method, URL, JSON body, setup sequence, expected status/body, actual status/body, and contract section.

## High-value probes

- Reset twice leaves identical state and seeded IDs.
- Appendix A HMAC signature matches exactly.
- Mystery sport works without restart or hard-coded names.
- Swiss pairing is globally minimal and rematch-free.
- Double-elimination GF2 becomes required only after the specified GF1 result.
- Three-way H2H uses only the tied mini-league and restarts criteria after a split.
- Twenty simultaneous purchases of stock one yield exactly one `201` and nineteen `409`.
- Cross-tenant access is `403`; absent IDs follow the documented `404` rules.
- Audit routes remain unthrottled while `/api/v1/ping` rate-limits and recovers.
- Offline request replay changes nothing and reports every action duplicate.

## Documentation

- `README.md`: exact startup command, host port 8080, environment setup without the real salt, five demo accounts, mobile base URL instructions, test command.
- `TRACEABILITY.md`: every FR/NFR ID mapped to implementation files and automated tests. Ask owners for evidence; do not guess.
- `COVERAGE.json`: six backend keys with measured line coverage only. Never inflate values.
- Keep a short list of unresolved contract ambiguities and organizer answers.

## Release control

- Track the four required push windows and warn the lead before each closes.
- Before freeze, test a fresh clone with no existing volumes or caches.
- Confirm Compose build finishes within ten minutes and health becomes ready within 120 seconds.
- Verify all root artifacts and `mobile/release/app-release.apk` exist.
- Run the full test suite, capture failures, and triage by scoring impact.
- Recommend the final push only after the clean-clone smoke test.

## Completion handoff

Report: test summary by backend area, unresolved failures ranked by points/risk, coverage values, traceability completeness, clean-clone result, required artifacts, push-window status, and final release recommendation.
