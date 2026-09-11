Kairos — AI Agent Context

This file is the shared source of truth for any AI coding agent (Claude Code, Gemini CLI, etc.) working on this repo. Read this in full before making changes. If something you're about to do conflicts with this file, stop and flag it instead of guessing.

1. Project Summary

Kairos is a team project-management and collaboration application. Team: Technical Difficulties (Kaleb Tangen, Nicholas Haines).

Problem it solves: Teams currently spread project coordination across a scattered set of disconnected tools. Kairos centralizes that into one platform so every team member can see what they and others are working on, what's due, and where shared resources live.

Core value prop: one accessible, simple, centralized system for scheduling, task tracking, and resource visibility — mission-critical info in one place instead of five.

2. Goals (in priority order)

These are the actual grading/success criteria — treat them as the backlog, roughly in this order:

Functional team management system (create teams, add/remove members)
Role-based access — users see/do only what their role permits
Working, efficient UI backed by clean data handling
Assign tasks and subtasks to specific people
Create tasks and subtasks
Set due dates and track completion status
Dashboard with overall project statistics
Runs natively on both Windows and Linux
Stretch goals (only after the above are solid)
Jitsi-based meeting link generation
Post-meeting notes/transcript download
Scheduling assistant showing teammate availability

Do not start stretch goals if any core goal (1–8) is incomplete or flaky.

3. Tech Stack
Layer	Choice	Notes
Client / GUI	Qt for Python (PySide6)	Native desktop app, single codebase for Windows + Linux. Prefer PySide6 over PyQt6 for the LGPL license unless the team decides otherwise.
Backend	Python + FastAPI	Runs as a normal process on whichever teammate's computer is "hosting" for that session — not a real server, not a NAS, not cloud-hosted. Just one of the two team computers, reachable over the local network.
Database	SQLite	Owned entirely by the backend process — the client never touches the .db file directly, it only talks to the API. This avoids the file-locking risk of sharing a raw SQLite file over a network share.
Data access	SQLAlchemy + Alembic for migrations	Don't hand-write schema migrations.
Client↔Server	REST over HTTP (JSON) between the two computers	The client points at whichever machine/IP is hosting; make the host address configurable, not hardcoded.
Auth	Not yet decided	See Open Questions.
Testing	pytest (backend), pytest-qt (client)	Every new feature needs at least a smoke test.
Formatting/Linting	black, ruff	Run before every commit.
Networking (stretch only)	Additional external calls (Jitsi, etc.) layer on top of the existing FastAPI backend	No new architecture needed for stretch goals — just new routes/integrations.
Architecture shape

Kairos is a client-server app split across two personal computers, not real server infrastructure: one teammate's machine runs the FastAPI backend and owns the SQLite database; both teammates' Qt clients (including the one on the host machine) talk to it over the local network via REST. There's no NAS, no cloud host, no dedicated server box — just whichever of the two computers is running the backend process at the time. Because only the backend process touches the database file, normal SQLite concurrency limits don't come into play the way they would with a shared file over a network drive. Do not put business logic in the Qt client beyond form validation and display — logic belongs server-side so both clients stay in sync.

Practical implication worth remembering: if the host machine is off or the backend isn't running, the other teammate can't use the app at all. That's an accepted tradeoff for an academic project, but worth being explicit about (see Open Questions) e.g., deciding who's "the host" for a given work session, and whether the client should fail gracefully with a clear "can't reach host" message rather than crashing.

4. Repository Structure

Use this layout unless there's a strong reason to deviate (flag it here if so):

Kairos/
├── client/                # PySide6 desktop application
│   ├── views/              # Qt widgets/screens
│   ├── viewmodels/          # UI-facing logic, calls into api_client
│   ├── api_client/          # thin wrapper around backend REST calls; host address is configurable
│   └── resources/          # icons, .ui files, qss stylesheets
├── server/                # FastAPI backend — runs on whichever teammate's computer is hosting
│   ├── api/                # route modules (users, projects, tasks, dashboard)
│   ├── models/              # SQLAlchemy models
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # business logic, kept out of routes
│   └── db/                  # session setup, Alembic migrations, kairos.db (not committed to git)
├── shared/                # types/constants shared by client and server, if any
├── tests/
│   ├── client/
│   └── server/
├── docs/
├── context.md              # userspecifified
├── README.md
└── Rules.md                # this will be user specified be sure to follow this rule
5. Data Model (initial sketch — expect this to evolve)
User: id, name, email, password_hash, role
Team: id, name, members (M2M to User)
Project: id, team_id, name, description, status, created_at
Task: id, project_id, title, description, assignee_id, due_date, status, created_at
Subtask: id, task_id, title, assignee_id, due_date, status
Role: defines what a user can view/edit (e.g., admin, project lead, member)

Update this section whenever the schema actually changes — it should never drift from server/models/.

6. Coding Conventions
Python 3.11+, type hints everywhere, docstrings on public functions/classes.
Format with black, lint with ruff — no PR should fail either.
Commit messages: Conventional Commits style (feat:, fix:, chore:, docs:, test:).
Branch per feature (feature/task-assignment, fix/dashboard-crash), PRs into main, no direct pushes to main.
Cross-platform discipline: use pathlib, avoid hardcoded path separators, avoid OS-specific calls without an abstraction — this runs on Windows and Linux equally.
Keep the Qt client thin: UI + validation only. Anything resembling a business rule goes in server/services/.
7. Rules for AI Agents (Claude Code / Gemini)
Both team members use IDE-based AI tools and share this file as common ground — don't make stack or architecture decisions that contradict it without updating it first.
Don't invent scope beyond Section 2's goals without asking.
Don't introduce a new major dependency (new framework, new DB, new build tool) without flagging it in chat first.
Never commit secrets, API keys, or .env files — check .gitignore covers them.
When a decision here turns out to be wrong or outdated, update this file in the same PR — it must stay accurate, not aspirational.
Prefer small, reviewable diffs over large speculative rewrites.
Write or update a test alongside any new feature or bugfix.
8. Open Questions / Not Yet Decided
Who hosts, and when — since there's no always-on server, the team needs a convention for who runs the backend during a given work session, and how the other person finds the current host's IP/address. Worth deciding before Goal #1 is usable by both of you.
Client failure handling when the host is unreachable — should fail with a clear message, not a crash or a silent hang.
Auth mechanism (JWT vs session-based) — needs a decision before Goal #2 (role-based access) can be built properly.
Whether PySide6 or PyQt6 is the final choice (license implications differ).
Final confirmation of FastAPI vs Django for the backend.
Packaging/distribution plan for the native app on Windows and Linux (e.g., PyInstaller, Briefcase).

If you (the AI agent) hit one of these while working, stop and ask rather than assuming.
