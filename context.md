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
Client↔Server	REST over HTTPS (JSON) between the two computers	The client points at whichever machine/IP is hosting; make the host address configurable, not hardcoded.
Auth	Real signup/login + opt-in, login-only email 2FA + real session tokens — resolved, no longer a placeholder	`POST /auth/signup` does real PBKDF2 password hashing (server/services/auth_service.py) and returns a usable session token immediately - no email step ever happens at signup. The signup form has a checkbox ("Require an emailed code when logging in") that sets `User.two_factor_enabled` (off by default) - a per-account, user-chosen preference, not a global setting. `POST /auth/login` checks that flag: if off, it returns a session immediately, same as signup; if on, it returns a `pending_token` and emails a 6-digit code (server/services/verification_service.py, server/email_sender.py) that must be confirmed via `POST /auth/verify-code` before a session is issued (server/services/session_service.py, server/models/session.py). (This was simpler at first - 2FA mandatory on both signup and login, then login-only, then made opt-in entirely once live use showed the SMTP dependency was too much friction to force on every account.) Every other endpoint requires `Authorization: Bearer <token>` from that session (server/api/dependencies.py::get_current_user_id) — the old placeholder (`X-Kairos-User-Id`, trusted with zero proof) is gone. `POST /auth/logout` invalidates a token; `POST /auth/resend-code` re-sends a login code (rate-limited); repeated failed logins/codes get a short in-memory cooldown (server/services/auth_service.py, server/services/verification_service.py). Sending real email requires `KAIROS_SMTP_USER`/`KAIROS_SMTP_PASSWORD` env vars on the host (a Gmail address + an App Password — see server/email_sender.py's docstring for the one-time Google-account setup this requires). Important: this app password must NOT be the user's real Google account password - Kairos's own signup/login password is a completely separate, app-local credential (PBKDF2-hashed, never sent to Google) from whatever Gmail account the *host* configures for sending mail; conflating the two was a real point of confusion during development, worth stating plainly here.
Transport security	Self-signed TLS, trust-on-first-use	`server/tls.py` generates a self-signed cert on first "Start Server" (server/gui.py); the client pins it the first time it connects to a given server (`client/net/cert_pinning.py`, `KnownServer.cert_pem`) and every later request fails closed if a different cert is ever presented. No paid CA — see Section 8 for the one gap this trust model can't close.
At-rest encryption	Chat message bodies + attachment files, server/crypto.py	`ChatMessage.body` is Fernet-encrypted transparently via a SQLAlchemy TypeDecorator (server/models/encrypted_text.py); attachment file bytes are encrypted chunk-by-chunk with AESGCM (streaming, so a large video isn't buffered whole in memory) and decrypted on download via a `StreamingResponse`. One server-local key (`server/db/kairos.key`, gitignored) — protects the DB/upload files if copied out on their own, not a full-host-compromise defense (see Section 8).
Testing	pytest (backend), pytest-qt (client)	Every new feature needs at least a smoke test.
Formatting/Linting	black, ruff	Run before every commit.
Networking (stretch only)	Additional external calls (Jitsi, etc.) layer on top of the existing FastAPI backend	No new architecture needed for stretch goals — just new routes/integrations.
Architecture shape

Kairos is a client-server app split across two personal computers, not real server infrastructure: one teammate's machine runs the FastAPI backend and owns the SQLite database; both teammates' Qt clients (including the one on the host machine) talk to it over the local network via REST. There's no NAS, no cloud host, no dedicated server box — just whichever of the two computers is running the backend process at the time. Because only the backend process touches the database file, normal SQLite concurrency limits don't come into play the way they would with a shared file over a network drive. Do not put business logic in the Qt client beyond form validation and display — logic belongs server-side so both clients stay in sync.

Practical implication worth remembering: if the host machine is off or the backend isn't running, the other teammate can't use the app at all. That's an accepted tradeoff for an academic project, but worth being explicit about (see Open Questions) e.g., deciding who's "the host" for a given work session, and whether the client should fail gracefully with a clear "can't reach host" message rather than crashing.

Client screen flow: `client/main.py` → `ConnectWindow` → on success, hands off to `AppShell` and hides itself ("Switch Server / Account" in `AppShell` brings it back). `ConnectWindow` shows two live sections of clickable server tiles - "Discovered on this network" (populated by `client/net/discovery_listener.py`, which listens for UDP broadcasts from `server/discovery_announcer.py` wired into `server/gui.py`'s Start/Stop - no IP typing needed on the same LAN) and "Saved servers" (the older `ServerListViewModel`/QSettings-backed list, each with a remove button) - plus a manual "Add Server..." fallback for a different subnet/VPN, where broadcast doesn't reach. Clicking a discovered tile auto-saves it. `AppShell` is a Teams-style window: left nav list switching between Dashboard/Chat/Server Settings pages, the last only for global-admin users. The Chat page is a single split view (conversation list left, the selected thread inline on the right via `client/views/chat_thread_panel.py`) - there is no pop-up chat window anymore. The whole app is themed via one global QSS stylesheet (Light/Dark/Auto, `client/theme/theme_manager.py`, `client/resources/{light,dark}.qss`) rather than per-widget styling - a `ThemeSelector` combo box exists on both `ConnectWindow` and `AppShell` since the user can be on either screen when changing it.

A WebSocket push layer exists server-side (`server/api/ws_chat.py`, `server/realtime/connection_manager.py`) but the client doesn't use it yet - chat currently works via REST polling (a `QTimer` re-querying the cursor endpoint). Wiring the client up to it is a natural next step if polling ever becomes a real cost, not yet necessary.

Two gotchas found while verifying this manually (worth knowing before "re-discovering" them): (1) the host's own Server GUI monitor log (`server/gui.py`'s `_poll_new_messages`) only watches the legacy smoke-test `messages` table - it never reflects real chat activity, so don't use it to check whether a chat message/file actually sent; query the DB or `/docs` instead (or see (2)). (2) Attachment delivery is pull-only and has no "you have unread stuff" signal: a recipient only sees a new message/file once their client polls while that conversation is open (every 3s) or they reopen/reselect it, and downloading a file always opens a fresh native Save As dialog - there's no persistent per-client default download folder yet.

App icon: `client/resources/kairos.svg` is set as the window icon for both GUIs via `QApplication.setWindowIcon()` - once in `client/main.py` (covers every window in the client app, since Qt applies it to any top-level window that doesn't set its own) and once in `server/gui.py` (the host's own control panel, which references the same file by relative path rather than duplicating it). The source file as supplied had a tall A4-page viewBox (210×297mm) with the actual artwork occupying only the top ~188×196 of it, which rendered letterboxed as a window icon; the `viewBox`/`width`/`height` were cropped to a square (-5 5 220 220) tightly framing just the artwork, found by rendering the original and scanning for the non-transparent pixel bounds rather than guessing from the path data. If the source artwork is ever replaced, re-check this crop - it's specific to this file's content, not a generic transform.

Security hardening pass: a live check (spinning up a real server instance and guessing a header value) found the placeholder `X-Kairos-User-Id` header let anyone impersonate any user with zero credentials. Fixed with three changes, each independently verifiable: (1) real session tokens (Section 3's Auth row) replace that header entirely — `resolve_ws_user_id`/`/ws/chat` take the same token as a `?token=` query param, since WebSocket handshakes can't always carry custom headers; (2) self-signed TLS with client-side trust-on-first-use pinning (Section 3's Transport security row) — `ApiClient` and `AuthDialog` both build their `httpx`/`ssl` calls around one pinned `ssl.SSLContext` per server rather than disabling verification; (3) at-rest encryption for chat bodies and attachment files (Section 3's row). None of these change any call site's day-to-day behavior — they're all "swap the one place that does X" changes, consistent with how the placeholder auth was documented as a single swap point from the start. A follow-up pass found and fixed a real bug introduced during (3): attachment chunks were nonce'd by chunk-index alone under one static server key, so chunk 0 of *every* file ever uploaded reused the same AES-GCM (key, nonce) pair - `server/crypto.py` now mixes in a random per-file nonce base (`generate_file_nonce`), closing the XOR/forgery exposure that reuse created. Caught by an automated multi-pass review (identify → independently fact-check each candidate finding), not by inspection alone - worth re-running that kind of review after any future crypto-adjacent change here.

Email-based 2FA: added after the hardening pass above, and narrowed twice based on live use - first from "mandatory on both signup and login" down to "login-only" (signup's email step was too much friction for creating an account), then from "mandatory on login" down to "opt-in per account via a signup checkbox" (even login-only 2FA was blocking iteration/testing whenever SMTP wasn't configured - see the real bug below). See Section 3's Auth row for the current flow and `server/email_sender.py` for the one-time Gmail setup (`KAIROS_SMTP_USER`/`KAIROS_SMTP_PASSWORD` env vars, an App Password from a Google account with 2-Step Verification already on - never the account's real password). This dev environment has no real Gmail account to send through, so verification here (and every automated test) mocks `email_sender.send_verification_code` - real delivery can only be confirmed once a teammate sets those env vars on their own machine. A live run surfaced one real bug worth knowing about if this area is touched again: `email_sender.send_verification_code`'s `RuntimeError` (raised when the SMTP env vars aren't set) wasn't being caught anywhere in `server/api/auth.py`, so a signup/login attempt with no SMTP configured crashed as an unhandled 500 instead of a clean error - fixed by wrapping every call site in `_send_code_or_503`, which now returns a proper 503 with the actual reason. Same lesson as the nonce-reuse bug above: a live end-to-end run caught something a unit test in isolation wouldn't have.

Taskbar icon (Linux/Wayland): `setWindowIcon()` only covers the title bar there - Wayland compositors look up the *taskbar* icon via the window's app_id matching an installed `.desktop` file's `Icon=` entry. Both entry points call `QApplication.setDesktopFileName()` (`"kairos-client"` / `"kairos-server"`) to supply that app_id, and `scripts/install_linux_desktop_entries.py` generates and installs the matching `.desktop` files into `~/.local/share/applications/` (user-scoped, no root, paths computed from the script's own location so it works from any checkout - not committed as static files since they'd otherwise hardcode one person's home directory). Each teammate needs to run this script once on their own Linux machine; it's a no-op on Windows/macOS, where the taskbar icon instead comes from how the app is eventually packaged (still open - see Packaging below).

4. Repository Structure

Use this layout unless there's a strong reason to deviate (flag it here if so):

Kairos/
├── client/                # PySide6 desktop application
│   ├── views/              # Qt widgets/screens/dialogs (one class per file; e.g. connect_window.py, app_shell.py, chat_page.py, chat_thread_panel.py, server_tile.py, auth_dialog.py)
│   ├── viewmodels/          # UI-facing logic, calls into api_client (server_list, identity, conversation_list, chat)
│   ├── api_client/          # thin wrapper around backend REST calls; host address is configurable
│   ├── net/                # DiscoveryListener (LAN auto-discovery, UDP/QtNetwork) + cert_pinning.py (TLS trust-on-first-use)
│   ├── theme/              # ThemeManager (Light/Dark/Auto, persisted via QSettings, applied as one global stylesheet)
│   └── resources/          # light.qss / dark.qss stylesheets, kairos.svg (app window icon, .ui files if any go here too)
├── server/                # FastAPI backend — runs on whichever teammate's computer is hosting
│   ├── api/                # route modules (health, messages, auth, people, conversations, chat_messages, attachments, server_settings, ws_chat)
│   ├── models/              # SQLAlchemy models (incl. chat: conversation, chat_message, attachment, server_settings; session.py; pending_verification.py; encrypted_text.py - the TypeDecorator used by chat_message.body)
│   ├── schemas/             # Pydantic request/response schemas
│   ├── services/            # business logic, kept out of routes (incl. session_service.py, verification_service.py)
│   ├── realtime/            # WebSocket connection manager (push layer; not yet consumed by the client)
│   ├── db/                  # session setup, Alembic migrations, kairos.db / tls/ / kairos.key (none committed to git)
│   ├── discovery_announcer.py  # LAN auto-discovery server side (UDP broadcast), started/stopped alongside the backend in gui.py
│   ├── tls.py              # self-signed cert generation + fingerprint (server/db/tls/), used by gui.py
│   ├── crypto.py           # at-rest encryption primitives (Fernet for text, chunked AESGCM for files) - see Section 3
│   ├── email_sender.py     # sends the 2FA code via Gmail SMTP (stdlib smtplib) - needs KAIROS_SMTP_USER/KAIROS_SMTP_PASSWORD env vars
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
User: id, name, email, password_hash, role, two_factor_enabled (default False - a signup-time checkbox choice, see Section 3's Auth row; controls whether POST /auth/login requires an emailed code)
Session: token (PK, opaque/unguessable), user_id, created_at, last_used_at, expires_at — a real login session (server/models/session.py); replaces the old placeholder where the client just claimed a user id with no proof. 30-day idle expiry, slid forward on each use.
PendingVerification: token (PK, opaque), user_id, code_hash (SHA-256 of the emailed 6-digit code, never stored raw), created_at, expires_at (10 min), attempt_count (locks out after 5 wrong guesses) — only created for logins by accounts with User.two_factor_enabled=True; never for signup (server/models/pending_verification.py, server/services/verification_service.py); deleted once verified (one-time use) or once expired/locked-out.
Team: id, name (unique, case-insensitive), lead_id → User, created_at, members (M2M to User via team_members). The lead is always a member; the lead and admins manage the team (server/services/team_service.py). Teams are visible only to members and admins.
Project: id, team_id, name, description, status, created_at
Task: id, project_id, title, description, assignee_id, due_date, status, created_at
Subtask: id, task_id, title, assignee_id, due_date, status
Role: what a user can view/edit app-wide: admin, project_lead, member (shared/roles.py). One role per user everywhere; rows are created at server start-up. Admins change roles in the Users page (never their own); admins and project leads create teams.
Status (2026-10-04): Project/Task/Subtask exist only as database tables - no API or screens yet (goals 4-7).

Chat feature (see server/models/{conversation,chat_message,attachment,server_settings}.py — kept separate from the Section 2 goals list, see the note at the end of Section 2):
Conversation: id, kind (direct/group), name (nullable, group display name), created_by_user_id, created_at
ConversationParticipant: conversation_id, user_id, role (admin/member — per-conversation, distinct from the global Role above), joined_at
ChatMessage: id, conversation_id, sender_user_id, body (nullable, encrypted at rest — see Section 3's At-rest encryption row; stored as a column type, no schema-level change, transparent to every call site), client_token (nullable, unique — client-generated idempotency key), created_at — distinct from the legacy Message model (server/models/message.py), which is a connectivity smoke-test ping and not part of the chat feature
Attachment: id, chat_message_id, original_filename (display only), stored_filename (server-generated, unique, used for the on-disk path — the file's actual bytes on disk are encrypted, not the literal upload), content_type, size_bytes, uploaded_by_user_id, created_at
ServerSettings: singleton row (id=1) — display_name, upload_root, max_upload_size_bytes, updated_at

Merge note (2026-10-04): the Nick2 branch (teams, roles, database locking, server window and client stability fixes) was merged into this branch, keeping this branch's sign-in. See docs/MERGING.md.

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
Auth mechanism (JWT vs session-based) — resolved: session-based (see Section 3's Auth row). A live exploit check (guessing the old placeholder header's value against a real running server, confirmed it granted full read access to another user's private conversation) is what triggered replacing it with real session tokens, self-signed TLS, and at-rest encryption in the same pass. Update (2026-10-04, Nick2 merged in): Goal #2's app-wide roles and Goal #1's teams now exist - admin / project_lead / member roles, team leads, the /teams and /users routes (server/api/teams.py, users.py, using server/api/deps.py on top of dependencies.py), and Teams and Users pages in the app. Before that merge, Goal #2 was only partially touched by any of this: a global admin/member Role gates one piece of chat-only UI (remote server settings), and a separate per-conversation admin/member role exists for group chat membership - neither of these is the Team/Project/Task permission system Goal #2 is actually asking for. Don't treat Goal #2 as done because of the chat feature's role gating or this security pass.
TLS trust model — accepted limitation, not a bug: trust-on-first-use (server/tls.py, client/net/cert_pinning.py) protects every connection *after* the first one to a given server, the same way SSH host keys work. The very first handshake to a brand-new server has nothing to verify against yet and could theoretically be intercepted on that one connection. `server/gui.py` displays the cert's SHA-256 fingerprint so the two teammates can optionally compare it over a trusted channel (a call, Signal, etc.) for stronger-than-TOFU assurance on that first connection - not required, just available.
At-rest encryption key scope — accepted limitation, not a bug: `server/db/kairos.key` protects the DB and upload folder if they're copied out on their own (a backup, a stolen drive). It does not protect against a full compromise of the host machine, since the running server needs that key readable to do its job and the key sits right next to what it encrypts. No backfill migration exists for data written before this change - pre-existing plaintext rows/files from earlier testing are expected to become unreadable (accepted - dev/test data only).
Packaging/distribution plan for the native app on Windows and Linux (e.g., PyInstaller, Briefcase) — still open.

If you (the AI agent) hit one of these while working, stop and ask rather than assuming.
