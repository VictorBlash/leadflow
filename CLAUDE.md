## Project state (2026-10-23)

- **What it does:** FastAPI service that takes inbound leads at `POST /leads`, stores them, tags priority from the email domain, has Claude Haiku draft an outreach email, and posts to Slack, recording each step in `workflow_runs`.
- **Default branch:** `main`.
- **Tests:** `python -m pytest -q` (22 tests). Locally no env var has to be unset: `tests/conftest.py` forces `DATABASE_URL=sqlite://` and clears `LEADFLOW_API_KEY` per test, and Claude and Slack are stubbed. CI requires `ANTHROPIC_API_KEY`, `SLACK_WEBHOOK_URL` and `LEADFLOW_API_KEY` to be unset, so unset them to reproduce CI exactly.
- **CI** (`.github/workflows/ci.yml`): runs on push to `main` and on every pull request. Python 3.11 (matches the Dockerfile), installs `requirements.txt` and `requirements-dev.txt`, fails if any of those three secrets is set, then runs `python -m pytest -q`.
- **Security and reliability decisions in force:**
  - `X-API-Key` on every route except `/health` and the docs (`/docs`, `/redoc`, `/openapi.json`), via the `protected` router in `main.py`. Why: `POST /leads` writes data and triggers paid Claude calls and Slack posts; the docs describe the API's shape, not its data.
  - Fails closed: an unset or empty `LEADFLOW_API_KEY` rejects every protected route with 401 (`auth.py`). Missing and wrong keys get the same 401, compared in constant time. Why: a misconfigured deploy must not become an open one.
  - Anthropic client: 20 s timeout, 1 retry (`orchestrator.py`). Why: the workflow runs inside the HTTP request, so the worst case is about 41 s instead of the SDK default of 600 s x 3.
  - Slack text escaping of `&`, `<`, `>` in lead name, company and email. Why: lead input must not trigger mentions or links in the channel.
  - `db.rollback()` before recording a failed run. Why: a failed flush leaves the session unusable, and the failure itself could not be recorded (see `test_a_database_error_in_a_step_still_returns_a_recorded_failed_run`).
- **Known open items:**
  - Set Render's Health Check Path to `/health`. It is the only unauthenticated app route; `/` now returns 401.
  - The live service is key-protected; the key is in Render's environment, not in the repo.
- **Working rule for Claude Code sessions:** show a plan and wait for approval before editing; show each diff and wait; never commit, push or switch branches; the owner commits.
