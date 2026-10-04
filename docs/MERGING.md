# Merging `Nick2` and `Kaleb`

Both branches grew from the same commit (`644d39a`). `Nick2` added real sign-in,
teams, admin roles, security fixes and a stable client. `Kaleb` (`7784de0`,
"Added Chat Features") added chat, conversations, people, attachments, server
settings, LAN discovery and themes. Most of that is new files that merge
cleanly. This page covers the parts that don't.

## Find the protected code

Every spot that must survive a merge is marked in the code:

```
git grep -n "MERGE-CRITICAL"
```

Each marker says what to keep, what breaks without it, and which test fails if
it's lost. If a merge conflict touches a marked block, keep that block and add
the other branch's lines around it. Don't pick one whole side.

## Files changed on both branches (expect conflicts)

| File | What to do |
|---|---|
| `server/main.py` | Keep `Nick2`'s `create_app` (start-up role check, protections, login lockout). **Add** Kaleb's `include_router` lines for attachments, chat, conversations, people, server settings and the websocket. |
| `server/api/auth.py`, `server/services/auth_service.py`, `server/schemas/auth.py` | Keep `Nick2`'s versions: token sign-in, scrypt hashing, validation, lockout. Kaleb's `/auth/signup` returns no token, and his PBKDF2 hashes can't be read by `password_service.py`. Point Kaleb's client at `/auth/register` and `/auth/login` instead. |
| `server/db/session.py` | Keep `Nick2`'s file and **add** Kaleb's `get_session_factory()` (the websocket needs it). It returns `SessionLocal`, which already has the locking settings. |
| `server/gui.py` | Keep `Nick2`'s version (plain-text log, start-up check, port probe, `proxy_headers=False`). **Add** Kaleb's settings box and discovery announcer. |
| `server/models/__init__.py` | Keep every import from both sides. |
| `client/main.py` | Kaleb's `main()` opens `ConnectWindow`, which is fine. Whatever `main()` ends up as, it must still create `MainThreadGarbageCollector(app)` before the first window (the crash fix). |
| `client/api_client/client.py` | Keep `Nick2`'s `ApiClient`. Re-add Kaleb's chat/people/conversation methods using `self._request(...)`, with no `X-Kairos-User-Id` header. |
| `tests/server/conftest.py`, `tests/client/conftest.py` | Keep both sides' fixtures. `Nick2`'s throwaway-database override and the automatic background-work fixture must stay. |
| `context.md` | Combine both sides' text by hand. |

## Things git won't flag, but that will break

1. **Two migration heads.** Kaleb's `80896866bfa4` and `Nick2`'s `e41a0d2a9bed`
   both follow `14bd78dc1837`. After merging, `alembic upgrade head` fails with
   "Multiple head revisions". Fix it by setting `down_revision = "b3dc54a36214"`
   in `80896866bfa4_add_chat_and_server_settings_tables.py`, then check that
   `alembic -c server/db/alembic.ini heads` prints one line.
2. **Who is calling.** Kaleb's new routes find the caller through the
   `X-Kairos-User-Id` header in `server/api/dependencies.py`, which anyone can
   set. The file says so itself, and says only its functions' bodies need to
   change once real sign-in exists. Now it does: make `get_current_user_id`
   return `get_current_user(...).id` (from `server/api/deps.py`, which checks the
   bearer token), and make `require_global_admin` use it too. Then the client
   sends the token instead of the header. The websocket check
   (`resolve_ws_user_id`) should take the token as well, resolved with
   `session_service.resolve_session`.
3. **Uploads in git.** `server/db/uploads/…txt` is committed on `Kaleb`.
   Delete it and add `server/db/uploads/` to `.gitignore`.
4. **Upload size.** The server refuses any request body over 1 MB
   (`server/api/protection.py`). Give the attachment route its own larger limit
   rather than raising the limit for every route.
5. **Message attachments, twice.** `Nick2` has `TODO(attachments)` notes for
   attachments on the test messages, and Kaleb built attachments for chat. Pick
   one design and delete the other's notes.

## When you're done

```
python -m pytest            # everything must pass
git grep -n "MERGE-CRITICAL" # every marker still present
alembic -c server/db/alembic.ini heads   # exactly one head
```
