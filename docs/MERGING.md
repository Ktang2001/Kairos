# Merge record: Nick2 into Kaleb (2026-10-04)

Branch `merge/nick2-into-kaleb` combines both lines of work. **Kaleb's design is
kept for sign-in, chat, files, HTTPS, encryption and discovery. Nick2 adds teams,
app-wide roles, database locking and client stability fixes on top.**

Every spot that must survive future merges is marked in the code:

```
git grep -n "MERGE-CRITICAL"
```

## What comes from where

| Area | Source | Notes |
|---|---|---|
| Sign-up, login, two-factor, sessions, passwords (PBKDF2) | Kaleb | Unchanged except one robustness fix (below) |
| Chat, conversations, people, attachments, server settings, websocket | Kaleb | Unchanged |
| HTTPS + certificate pinning, encryption at rest, LAN discovery, themes | Kaleb | Unchanged |
| Connect window, sign-in dialog, app window (`AppShell`) | Kaleb | `AppShell` gains Teams and Users pages |
| Roles: admin / project_lead / member, team leads | Nick2 | `server/services/team_service.py`, `user_service.py` |
| `/teams` and `/users` routes | Nick2 | Use Kaleb's token check (`server/api/deps.py` wraps `dependencies.py`) |
| Teams and Users pages | Nick2 | `client/views/teams_view.py`, `users_view.py`, shown inside `AppShell` |
| Database locking for simultaneous edits | Nick2 | `server/db/session.py` (keeps Kaleb's `get_session_factory`) |
| 1 MB request limit, local-only API docs, oversized-id guard | Nick2 | The chat upload route keeps its own (admin-set) limit |
| Background requests and main-thread garbage collection | Nick2 | The crash fix; started in `client/main.py` |
| Server window | Both | Kaleb's HTTPS, settings box and discovery, plus Nick2's plain-text log, start-up check and port probe |

## Changes to Kaleb's files

These are small, but Kaleb should know about them:

1. **`server/services/session_service.py`, `resolve_session`:** the "last used"
   update is now best effort. When two requests arrive at the same moment, SQLite
   can refuse that write. The request then carries on instead of failing with a
   500, and the next request slides the expiry.
2. **`server/db/session.py`:** a request that changes data now holds the write
   lock for its whole length, including after `resolve_session` commits part-way
   through.
3. **`client/api_client/client.py`:** adds the team and user calls and `me()`,
   which raise `ApiError` with a readable message. `send_message` now sends the
   token, because test messages require sign-in.
4. **`client/views/app_shell.py`:** adds the Teams page (everyone) and the Users
   page (admins). Both load when first opened, then every 30 s while showing.
5. **`client/views/connect_window.py`:** passes the signed-in user's role to
   `AppShell`.
6. **`client/main.py`:** creates `MainThreadGarbageCollector` before the first window.
7. **`client/views/add_server_dialog.py`:** unchanged here. Kaleb's own "Fixed
   conneciton issues" commit (HTTPS probe) is already included.
8. **Tests:** Kaleb's tests are kept. Menu-entry checks in `test_app_shell.py`
   now include Teams/Users. `test_tls.py`'s permission check is skipped on
   Windows, which has no POSIX permissions.

## Removed

- **Nick2's sign-in internals** (scrypt passwords, hashed-token sessions,
  per-computer lockout) and their tests: Kaleb's sign-in is the one kept.
- **Nick2's own login and home windows**, and their tests: Kaleb's app is the one kept.
- **Nick2's test-message attachment notes:** Kaleb's chat attachments replace them.
- **Database files committed on `Kaleb`** (backups, temporary files, an upload)
  are no longer tracked. They stay on disk and are ignored from now on.

## Database

- The migrations form **one chain**: Kaleb's steps, then Nick2's team-leader
  step (`b3dc54a36214`, now following `ea03b89dc9da`). Nick2's separate sessions
  step was dropped, because Kaleb's sessions table is used.
- **Existing databases should start fresh:** rename `server/db/kairos.db`, then run
  `alembic -c server/db/alembic.ini upgrade head`.

## Known limits

- **A role change shows up in the menu at the next sign-in.** The Teams page
  updates its buttons straight away, but the Users menu entry is fixed when the
  app window opens.
- **Kaleb's chat screens make their network calls on the main thread,** so the
  window pauses briefly during each one. The Teams and Users pages already run
  theirs in the background (`client/viewmodels/background.py`).

## Checks

```
python -m pytest                          # everything must pass
alembic -c server/db/alembic.ini heads    # exactly one head
git grep -n "MERGE-CRITICAL"              # markers still present
```
