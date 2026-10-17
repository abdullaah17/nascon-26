# Agent Brief 2 - Mobile Lead

Read `00_SHARED_EXECUTION_PLAN.md` first. You own only `mobile/**` and the installable application. Do not edit backend implementation files. Report API gaps to Person 1 with an exact request and expected behavior.

## Outcome

Deliver the required Android or iOS application, persistent offline workflow, and a reliable ten-minute judging path. Android is preferred because the required artifact path is explicit.

## Deliverable

- Source under `mobile/`.
- Android release at `mobile/release/app-release.apk`, installable on Android 10/API 29 or newer; or the official iOS device/simulator alternative.
- One configurable API base URL supporting `10.0.2.2:8080` for an Android emulator and the backend laptop's LAN address for a physical phone.
- Secure token storage through Android Keystore or iOS Keychain.

## Required screens

- Login and role-aware home.
- Fixtures list and match detail with live score, event timeline, and pinned product.
- Standings with qualification state.
- Club profile with roster, staff, and venue.
- Store, variant selection, cart, mock checkout, and receipt view/download.
- Club-manager roster action screen.
- Organizer scoring and compensation screen.
- Always-visible online/offline/syncing state and pending-action queue.

## Offline contract

- Cache fixtures, standings, and club profiles in SQLite/Room or another persistent local database.
- Queue one organizer score action and one manager roster action in the exact Section 5.14 format.
- Preserve the queue across force-close and restart.
- On reconnect, call `/audit/v1/offline-sync`, show each applied/rejected/duplicate result in plain language, and remove handled actions.
- Never recreate backend conflict rules locally. The server is authoritative.

## UI/HCI priorities

- Make Fixtures, Standings, Store, and Profile reachable without explanation.
- Use consistent typography, spacing, color, buttons, loading states, and errors.
- Keep tap targets around 48 dp, label icons, maintain contrast, and never communicate meaning only by color.
- Handle empty states, 360x640 dp, and rotation without overflow.
- Hide controls a role cannot use.

## Integration sequence

1. Build navigation, theme, local database, API client, and mocked data immediately.
2. Integrate login and read-only screens as Person 1 exposes endpoints.
3. Integrate checkout and receipt.
4. Integrate roster/scoring actions.
5. Complete persistent offline queue and sync.
6. Build/install the release artifact early, then rehearse the judging path.

## Tests

- API base URL switching and unreachable-server behavior.
- Airplane-mode cached reads.
- Queue persistence after force-close.
- Reconnect and per-action results.
- All five demo roles and control visibility.
- Store purchase and receipt opening.
- Small-screen/rotation layout.

## Completion handoff

Report: release artifact path, device/API address tested, screens complete, offline force-close result, sync result, role coverage, known backend gaps, and demo readiness.

