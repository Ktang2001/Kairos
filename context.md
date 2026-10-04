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

Note: a chat feature (people search, 1:1/group chats, file sharing) is being built as a deliberately separate track, not added to this goals list — the team chose to keep it out-of-list rather than block it on goals 1–8 or fold it into the stretch goals above. See Section 5 for its data model.

3. Tech Stack
Layer	Choice	Notes
Client / GUI	Qt for Python (PySide6)	Native desktop app, single codebase for Windows + Linux. Prefer PySide6 over PyQt6 for the LGPL license unless the team decides otherwise.
Backend	Python + FastAPI	Runs as a normal process on whichever teammate's computer is "hosting" for that session — not a real server, not a NAS, not cloud-hosted. Just one of the two team computers, reachable over the local network.
Database	SQLite	Owned entirely by the backend process — the client never touches the .db file directly, it only talks to the API. This avoids the file-locking risk of sharing a raw SQLite file over a network share.
Data access	SQLAlchemy + Alembic for migrations	Don't hand-write schema migrations.
Client↔Server	REST over HTTP (JSON) between the two computers	The client points at whichever machine/IP is hosting; make the host address configurable, not hardcoded.
Auth	Real signup/login exists (server/api/auth.py), but per-request authorization is still a placeholder	`POST /auth/signup` and `/auth/login` do real PBKDF2 password hashing/verification (server/services/auth_service.py) and are wired into the client (client/views/auth_dialog.py). But every other endpoint still just trusts a client-supplied `X-Kairos-User-Id` header with no session/token check (server/api/dependencies.py::get_current_user_id) - anyone who knows a user id can act as them over the network. JWT vs session-based (see Open Questions) is about replacing that header, not about signup/login, which already works.
Testing	pytest (backend), pytest-qt (client)	Every new feature needs at least a smoke test.
Formatting/Linting	black, ruff	Run before every commit.
Networking (stretch only)	Additional external calls (Jitsi, etc.) layer on top of the existing FastAPI backend	No new architecture needed for stretch goals — just new routes/integrations.
Architecture shape

Kairos is a client-server app split across two personal computers, not real server infrastructure: one teammate's machine runs the FastAPI backend and owns the SQLite database; both teammates' Qt clients (including the one on the host machine) talk to it over the local network via REST. There's no NAS, no cloud host, no dedicated server box — just whichever of the two computers is running the backend process at the time. Because only the backend process touches the database file, normal SQLite concurrency limits don't come into play the way they would with a shared file over a network drive. Do not put business logic in the Qt client beyond form validation and display — logic belongs server-side so both clients stay in sync.

Practical implication worth remembering: if the host machine is off or the backend isn't running, the other teammate can't use the app at all. That's an accepted tradeoff for an academic project, but worth being explicit about (see Open Questions) e.g., deciding who's "the host" for a given work session, and whether the client should fail gracefully with a clear "can't reach host" message rather than crashing.

Client screen flow: `client/main.py` → `ConnectWindow` → on success, hands off to `AppShell` and hides itself ("Switch Server / Account" in `AppShell` brings it back). `ConnectWindow` shows two live sections of clickable server tiles - "Discovered on this network" (populated by `client/net/discovery_listener.py`, which listens for UDP broadcasts from `server/discovery_announcer.py` wired into `server/gui.py`'s Start/Stop - no IP typing needed on the same LAN) and "Saved servers" (the older `ServerListViewModel`/QSettings-backed list, each with a remove button) - plus a manual "Add Server..." fallback for a different subnet/VPN, where broadcast doesn't reach. Clicking a discovered tile auto-saves it. `AppShell` is a Teams-style window: left nav list switching between Dashboard/Chat/Server Settings pages, the last only for global-admin users. The Chat page is a single split view (conversation list left, the selected thread inline on the right via `client/views/chat_thread_panel.py`) - there is no pop-up chat window anymore. The whole app is themed via one global QSS stylesheet (Light/Dark/Auto, `client/theme/theme_manager.py`, `client/resources/{light,dark}.qss`) rather than per-widget styling - a `ThemeSelector` combo box exists on both `ConnectWindow` and `AppShell` since the user can be on either screen when changing it.

A WebSocket push layer exists server-side (`server/api/ws_chat.py`, `server/realtime/connection_manager.py`) but the client doesn't use it yet - chat currently works via REST polling (a `QTimer` re-querying the cursor endpoint). Wiring the client up to it is a natural next step if polling ever becomes a real cost, not yet necessary.

App icon: `client/resources/kairos.svg` is set as the window icon for both GUIs via `QApplication.setWindowIcon()` - once in `client/main.py` (covers every window in the client app, since Qt applies it to any top-level window that doesn't set its own) and once in `server/gui.py` (the host's own control panel, which references the same file by relative path rather than duplicating it). The source file as supplied had a tall A4-page viewBox (210×297mm) with the actual artwork occupying only the top ~188×196 of it, which rendered letterboxed as a window icon; the `viewBox`/`width`/`height` were cropped to a square (-5 5 220 220) tightly framing just the artwork, found by rendering the original and scanning for the non-transparent pixel bounds rather than guessing from the path data. If the source artwork is ever replaced, re-check this crop - it's specific to this file's content, not a generic transform.

Taskbar icon (Linux/Wayland): `setWindowIcon()` only covers the title bar there - Wayland compositors look up the *taskbar* icon via the window's app_id matching an installed `.desktop` file's `Icon=` entry. Both entry points call `QApplication.setDesktopFileName()` (`"kairos-client"` / `"kairos-server"`) to supply that app_id, and `scripts/install_linux_desktop_entries.py` generates and installs the matching `.desktop` files into `~/.local/share/applications/` (user-scoped, no root, paths computed from the script's own location so it works from any checkout - not committed as static files since they'd otherwise hardcode one person's home directory). Each teammate needs to run this script once on their own Linux machine; it's a no-op on Windows/macOS, where the taskbar icon instead comes from how the app is eventually packaged (still open - see Packaging below).

4. Repository Structure

Use this layout unless there's a strong reason to deviate (flag it here if so):

Kairos/
├── client/                # PySide6 desktop application
│   ├── views/              # Qt widgets/screens/dialogs (one class per file; e.g. connect_window.py, app_shell.py, chat_page.py, chat_thread_panel.py, server_tile.py, auth_dialog.py)
│   ├── viewmodels/          # UI-facing logic, calls into api_client (server_list, identity, conversation_list, chat)
│   ├── api_client/          # thin wrapper around backend REST calls; host address is configurable
│   ├── net/                # DiscoveryListener - LAN auto-discovery client side (UDP, QtNetwork, no new dependency)
│   ├── theme/              # ThemeManager (Light/Dark/Auto, persisted via QSettings, applied as one global stylesheet)
│   └── resources/          # light.qss / dark.qss stylesheets, kairos.svg (app window icon, .ui files if any go here too)
├── server/                # FastAPI backend — runs on whichever teammate's computer is hosting
│   ├── api/                # route modules (health, messages, auth, people, conversations, chat_messages, attachments, server_settings, ws_chat)
│   ├── models/              # SQLAlchemy models (incl. chat: conversation, chat_message, attachment, server_settings)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # business logic, kept out of routes
│   ├── realtime/            # WebSocket connection manager (push layer; not yet consumed by the client)
│   ├── db/                  # session setup, Alembic migrations, kairos.db (not committed to git)
│   ├── discovery_announcer.py  # LAN auto-discovery server side (UDP broadcast), started/stopped alongside the backend in gui.py
│   └── gui.py              # the hosting teammate's own window: start/stop the backend, local server-settings panel
├── shared/                # types/constants shared by client and server (chat_enums.py; discovery.py - LAN auto-discovery packet format)
├── scripts/               # one-off dev tooling, not part of the app itself (e.g. install_linux_desktop_entries.py)
├── tests/
│   ├── client/             # pytest-qt, QT_QPA_PLATFORM=offscreen for headless runs
│   ├── server/
│   └── shared/
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

Chat feature (see server/models/{conversation,chat_message,attachment,server_settings}.py — kept separate from the Section 2 goals list, see the note at the end of Section 2):
Conversation: id, kind (direct/group), name (nullable, group display name), created_by_user_id, created_at
ConversationParticipant: conversation_id, user_id, role (admin/member — per-conversation, distinct from the global Role above), joined_at
ChatMessage: id, conversation_id, sender_user_id, body (nullable), client_token (nullable, unique — client-generated idempotency key), created_at — distinct from the legacy Message model (server/models/message.py), which is a connectivity smoke-test ping and not part of the chat feature
Attachment: id, chat_message_id, original_filename (display only), stored_filename (server-generated, unique, used for the on-disk path), content_type, size_bytes, uploaded_by_user_id, created_at
ServerSettings: singleton row (id=1) — display_name, upload_root, max_upload_size_bytes, updated_at

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
Resolved: PySide6 is the final choice (in use throughout client/). FastAPI is the final choice (in use throughout server/).
Who hosts, and when — LAN auto-discovery is done (shared/discovery.py, server/discovery_announcer.py, client/net/discovery_listener.py): the host broadcasts itself over UDP every 2s, the client lists discovered servers as clickable tiles with no IP typed, entries age out ~6s after a host stops. This solves "how the other person finds the current host's IP/address," but not "who hosts, when" as a team convention, and it doesn't work across subnets/VLANs/a VPN (broadcast-only by nature) - manual "Add Server" is the fallback there.
Client failure handling when the host is unreachable — resolved for the connect/chat flows: ConnectWindow shows a clear "Connection failed: ..." message rather than crashing or hanging; same pattern in the chat views.
Auth mechanism (JWT vs session-based) — still open. Real signup/login with hashed passwords exists (see Section 3's Auth row), but every other request still trusts a bare `X-Kairos-User-Id` header with no session/token verification. Replacing that header is what this question is actually about. Goal #2 ("role-based access") is only partially touched by this: a global admin/member Role gates one piece of chat-only UI (remote server settings), and a separate per-conversation admin/member role exists for group chat membership - neither of these is the Team/Project/Task permission system Goal #2 is actually asking for. Don't treat Goal #2 as done because of the chat feature's role gating.
Packaging/distribution plan for the native app on Windows and Linux (e.g., PyInstaller, Briefcase) — still open.

If you (the AI agent) hit one of these while working, stop and ask rather than assuming.
