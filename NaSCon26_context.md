# NaSCon '26 App Dev Competition: Context Brief for an AI Assistant

> **SUPERSEDED FOR PART I IMPLEMENTATION.** This pre-release note contains rules that conflict with the official Part I specification, including repository visibility, scoring, venue details, and API port. For current work, use `team_docs/00_SHARED_EXECUTION_PLAN.md` and the assigned agent brief. The official Part I PDF takes precedence over this file.

Paste this whole file at the start of the session. It tells you who the user is, what the competition rules are, what has been decided and verified, and how to help. Treat the rules section as authoritative; it comes from the official booklet.

---

## 0. How to work with this user
- User: **Abd** (Abdullah Ahsan), CS student at Air University, Islamabad. Backend lead of the team ("Role 1").
- Wants **concise, direct, token-efficient** answers. Correct course quickly if he says a reply is too long or off target.
- Acts as a senior engineer: write correct code, challenge bad decisions, explain architecture briefly.
- Under time pressure tomorrow. Prefer working code and exact commands over theory.
- He is on a **MacBook (Apple Silicon, arm64)**, zsh terminal, Docker Desktop running.
- AI tools (Claude, Cursor, ChatGPT, Copilot) are explicitly allowed by the competition.

---

## 1. The competition (from the official booklet)

**Event:** NaSCon '26 App Dev Competition, FAST-NUCES Islamabad. **Sat Oct 17 and Sun Oct 18, 2026.** Times are PKT.
**Prizes:** Winner PKR 35,000, Runner-up PKR 15,000. **Team size: 1 to 3 members.**
**Note:** Abd's team has 4 people. This conflicts with the rule. It must be confirmed with the organizers (see Open Questions).

### Schedule

| | Day 1 (Sat Oct 17) | Day 2 (Sun Oct 18) |
|---|---|---|
| Check-in | 10:00-10:44, empty repo check | 10:00-10:14, commit verification |
| Sprint | **10:45-15:00** (Part I, 4h15m) | **10:15-14:00** (Part II, 3h45m) |
| Autograder | 15:05-15:30, **40 pts**, permanently locked | 14:05-14:25, **45 pts** |
| Viva | none | Top 8 teams only, 14:30-15:50, **15 pts** |

- Venues: Day 1 rooms A01-A03, A103, A104. Day 2 rooms C-401 to C-405.
- **Part II is confidential until 10:15 on Day 2.** Nothing can be done overnight (Phase I is closed at 15:00 on Day 1).

### Repository and grading rules
1. Create a **private GitHub repo under the team lead's personal account** (2,000 free Actions minutes). **Invite `nascon-eval-26`.** (Teammates must be added as collaborators to push.)
2. **At 10:40 on Day 1 the repo must be completely empty: zero commits.** All scaffolding, Dockerfiles and source code must be committed **after 10:45**. Do not assume any pre-built repo or template exists.
3. **Push at least once every hour** during sprints. Each missed hourly push = **-2 points**.
4. Only commits **pushed to GitHub (server timestamp)** by **15:05:00 PKT Day 1** and **14:05:00 PKT Day 2** are graded. Local files, stashes and late pushes are ignored. Aim to push by 14:50 / 13:50.
5. **No commits between 15:05 Day 1 and 10:15 Day 2.** Day 2 history must continue from the locked Day 1 commit SHA.
6. **Grading mechanism:** an official **GitHub Actions autograder** runs the repo's **`docker-compose.yml`** on `ubuntu-latest` (16 GB RAM, **amd64**) at each deadline. So `docker compose up --build` must work **from a fresh clone with no manual steps**. The exact tests (ports, routes, response shapes) are defined in the Part I / Part II problem statement and have not been seen yet.
7. **Allowed:** AI tools. **Prohibited:** managed BaaS (Firebase, Supabase) and pre-built repositories.
8. **Top-8 viva (10 min):** a 5-minute live code mutation task, two hidden complexity scenarios, a defense of **8 short ADRs in `ADR.md`**, and a defense of the **traceability matrix in `TRACEABILITY.md`**.
9. **Scores and ties:** all item and total scores are floored at 0. Tie-breakers, in order: higher Day 2 objective score, more automated test vectors passed across both days, earlier final GitHub push on Day 2.

### Environment rules
- Campus Wi-Fi isolates devices (no device-to-device traffic). Use a **phone hotspot or travel router** for the team network.
- Campus Wi-Fi allows GitHub, AI tools, pypi.org, registry.npmjs.org, pub.dev, repo.maven.apache.org. Large Docker pulls are throttled, hence pre-pulling images.
- Low-RAM advice: split local testing across teammates' laptops. For Selenium containers use `shm_size: "1gb"` and `SE_START_VNC: "false"`.
- QA tooling expected: Appium 2 (UiAutomator2 or XCUITest), Selenium bindings, pytest/JUnit/TestNG, Allure or HTML reports, k6 or Locust.
- The Docker image bundle includes decoys. Some images belong to Phase I, some to Phase II, some are unused.

---

## 2. Team and stack decisions

**Stack (decided):**
- **Backend:** Python 3.12, **FastAPI** (not Django), SQLAlchemy, **PostgreSQL 16**, **Redis 7** (cache and auth/sessions).
- **Mobile:** **React Native**, on a separate laptop, using a physical phone over the shared hotspot.
- **Infra:** Docker Compose. Everything backend-side runs in containers.
- **Architecture:** a **modular monolith**. One FastAPI service. Auth is a module inside it, **not a separate service**. Only Postgres and Redis (and any needed extras) are separate containers. Reason: 4-hour sprints, and every extra service adds failure points for `docker compose up`. This is a good candidate for one of the 8 ADRs.

**Roles (4-person plan, pending the team-size ruling; for 3 people, merge Infra/Docs into the others):**

| Role | Owns |
|---|---|
| 1: Lead / Backend (Abd) | Repo, API, DB schema, business logic, merges |
| 2: Mobile | React Native app, API integration, test phone |
| 3: QA / Tests | Selenium, Appium, k6/Locust, Allure, test vectors |
| 4: Infra / Docs | `docker-compose.yml`, Actions, health checks, `ADR.md`, `TRACEABILITY.md`, hourly-push watch |

**Planned backend layout:**
```
backend/app/
  main.py        app setup, routers, lifespan startup (create tables, seed)
  config.py      env settings
  db.py          engine/session
  models.py      DB schema (SQLAlchemy tables)
  schemas.py     Pydantic request/response models
  auth.py        register/login, JWT, Redis sessions/refresh tokens
  routers/       one file per feature
```
Schema lives in `models.py` and is created **at API startup** (retry loop until the DB is ready) plus a seed step. There is no manual migration step. Use the `bcrypt` package directly for password hashing (passlib has compatibility problems with newer bcrypt).

**Network model for local testing:** Laptop A runs `docker compose up` and publishes the API on port 8000. The phone/mobile laptop connect to the same hotspot and call `http://<Laptop-A-LAN-IP>:8000` (find it on a Mac with `ipconfig getifaddr en0`). A phone's `localhost` is the phone itself, and Android emulators use `10.0.2.2`. The API base URL must be a single config constant. The grader never touches a phone.

---

## 3. Verified state of the user's machine (as of Oct 17, 03:00)

- Docker 29.8.2, Docker Compose v5.6.0, git 2.50.1. Docker daemon is running.
- **Images present:** postgres:16-alpine, redis:7-alpine, rabbitmq:3.13-management-alpine, nats:2.10-alpine, bluenviron/mediamtx:1.9.1, livekit/livekit-server:v1.7.2, binwiederhier/ntfy:v2.11.0, prom/prometheus:v2.54.1, grafana/grafana:11.2.0, grafana/k6:0.54.0, selenium/hub:4.24.0, selenium/node-chrome:4.24.0 (amd64, runs under emulation on this Mac), selenium/node-firefox:4.24.0, **selenium/node-chromium:4.24.0** (arm64 browser node; `seleniarm/node-chromium` no longer exists), python:3.12-slim, localstack/localstack:3.8.1.
- **MinIO problem:** `minio/minio:RELEASE.2024-09-22T00-33-43Z` is no longer pullable (Docker Hub: pull access denied; Quay: 401). The organizers replied that teams should either use a publicly pullable replacement (e.g. `cgr.dev/chainguard/minio:latest`) or **use `localstack/localstack:3.8.1` for S3** (their message was cut off at "update your compose file to use port..."; LocalStack's S3 edge port is normally **4566**; confirm).
- Packages needed in the backend (installed via `requirements.txt` inside Docker): `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `psycopg2-binary`, `redis`, `pyjwt`, `bcrypt`, `pydantic-settings`; for tests `pytest`, `httpx`; for S3 `boto3`.

### Practice stack that was run successfully tonight (`~/practice`)

Tested end to end: clean `docker compose down -v` then `up --build`, `/health` OK, `POST /notes` returned 201, `GET /notes` returned the row, `GET /notes/999` returned 404, `/hits` Redis counter incremented, and `GET /notes` returned `[]` on a fresh database. This is the verified baseline pattern to reuse.

`docker-compose.yml`:
```yaml
services:
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app
    volumes: [pgdata:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 3s
      timeout: 3s
      retries: 20

  redis:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 20

  api:
    build: ./backend
    environment:
      DATABASE_URL: postgresql+psycopg2://app:app@postgres:5432/app
      REDIS_URL: redis://redis:6379/0
    ports: ["8000:8000"]
    depends_on:
      postgres: {condition: service_healthy}
      redis: {condition: service_healthy}

volumes:
  pgdata:
```

`backend/Dockerfile`:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

`backend/main.py`:
```python
import os, time
from contextlib import asynccontextmanager
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
r = redis.from_url(os.environ["REDIS_URL"], decode_responses=True)

def init_db():
    for _ in range(30):
        try:
            with engine.begin() as c:
                c.execute(text("create table if not exists notes (id serial primary key, title text not null)"))
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError("database not ready")

@asynccontextmanager
async def lifespan(app):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

class NoteIn(BaseModel):
    title: str = Field(min_length=1)

@app.get("/health")
def health():
    with engine.connect() as c:
        c.execute(text("select 1"))
    r.ping()
    return {"status": "ok"}

@app.post("/notes", status_code=201)
def create_note(n: NoteIn):
    with engine.begin() as c:
        row = c.execute(text("insert into notes(title) values (:t) returning id, title"), {"t": n.title}).mappings().one()
    return dict(row)

@app.get("/notes")
def list_notes():
    with engine.connect() as c:
        return [dict(x) for x in c.execute(text("select id, title from notes order by id")).mappings()]

@app.get("/notes/{note_id}")
def get_note(note_id: int):
    with engine.connect() as c:
        row = c.execute(text("select id, title from notes where id=:i"), {"i": note_id}).mappings().first()
    if not row:
        raise HTTPException(404, "not found")
    return dict(row)

@app.get("/hits")
def hits():
    return {"hits": r.incr("hits")}
```
`backend/requirements.txt`: `fastapi`, `uvicorn[standard]`, `sqlalchemy`, `psycopg2-binary`, `redis`.

Optional S3 service (LocalStack), if the problem needs object storage:
```yaml
  s3:
    image: localstack/localstack:3.8.1
    environment:
      SERVICES: s3
    ports: ["4566:4566"]
```
Backend config: endpoint `http://s3:4566`, dummy creds `test`/`test`, region `us-east-1`, boto3 with path-style addressing (`Config(s3={"addressing_style": "path"})`), and create the bucket at API startup, ignoring "already exists".

---

## 4. Plan for tomorrow (Day 1)

| Time | Backend (Abd) |
|---|---|
| By 10:40 | Create the private repo under the lead's account, invite `nascon-eval-26`, add teammates as collaborators, confirm it has zero commits (no README, no .gitignore from GitHub's setup screen) |
| 10:45-11:00 | Read Part I fully. List entities, endpoints, required ports, response formats, scored behaviours |
| By ~11:15 | Send the API contract (routes + JSON shapes, auth scheme) to mobile and QA. FastAPI's `/docs` page doubles as the contract |
| By ~11:30 | First push: the skeleton from section 3 adapted to the real entities, with a green `docker compose up --build` |
| 11:30-14:00 | Implement endpoints in order of scoring weight. Push at least hourly. Merge teammates' PRs |
| 14:00-14:30 | Fix test failures from QA, finish features, update `TRACEABILITY.md` |
| 14:30 | **Freeze** (fixes only). Fresh-clone test: `git clone` into a new folder, then `docker compose up --build`, then run the checks |
| **14:50** | **Final push.** The cutoff is 15:05:00 server time, so never use the last minutes |

Day 2 follows the same structure, compressed: freeze at 13:30, final push at 13:50. Spend the first 15-20 minutes reading Part II and re-planning. Reuse Day 1's compose and test setup.

Team practices: feature branches and small PRs, Role 1 merges, `git pull --rebase` before pushing, no direct pushes to main in the last 30 minutes. Write ADRs as decisions are made (8 total) and update `TRACEABILITY.md` as features land. Everyone should be able to explain the whole codebase, because the viva picks anyone. Do a cross-walkthrough at the end of Day 1.

---

## 5. Compose and backend rules that decide the score
- Use **service names, not `localhost`**, between containers (`postgres:5432`, `redis:6379`).
- Every service has a `healthcheck`. The API uses `depends_on: condition: service_healthy`.
- Schema and seed data are created automatically at startup. No manual steps, no host-specific paths, no uncommitted `.env`. Commit defaults.
- Expose `/health`. Honour any ports and routes the problem statement requires exactly.
- Validate input and return correct status codes (400/401/404/409/422); test vectors usually check these. Consider pagination and idempotency.
- Enable CORS if there is a web client.
- Always test with: `docker compose down -v && docker compose up --build`, and finally from a fresh clone.
- `docker compose` must run from the folder that contains `docker-compose.yml`.
- Check images are on `amd64`-compatible bases (the runner is amd64; `python:3.12-slim` is multi-arch).

---

## 6. Open questions (unresolved as of Oct 17, 03:00)
1. **Team size:** the booklet says 1-3, the team has 4. Needs an organizer ruling. If not allowed, merge or drop a role.
2. **MinIO replacement:** confirm the LocalStack port and whether MinIO is even used (it may be a decoy).
3. The **Part I problem statement is unknown** (domain, entities, endpoints, required ports, test method).
4. Whether the autograder includes its own workflow file or expects one in the repo (check the Part I instructions).

---

## 7. What to do first when the user starts the session
1. Ask the user to paste the **Part I problem statement** (or read it from the file they attach).
2. Extract: entities, endpoints, auth requirements, required ports/routes, scoring criteria, which infra services are needed (decoys excluded).
3. Produce the API contract (routes, request and response JSON, status codes) as a short table, then the file layout and the `docker-compose.yml`.
4. Generate the skeleton adapted from section 3, and tell the user the exact commands to run and test it.
5. Remind them of the next push time.

Be concise, and give exact commands and working code, not theory.
