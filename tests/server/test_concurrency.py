"""Collision tests: two requests acting on the same thing at the same instant.

Found by stress testing. Each rule was "check, then write", and without the
write lock (``server.db.session``) a second request could slip in between:

* hand the lead to X while removing X  -> a team whose lead isn't a member
* two admins demote each other         -> no admins left at all
* delete a team while adding members   -> 500 errors
* 30-40 people writing at once         -> "database is locked" 500s

These need a real multi-threaded server (``TestClient`` sends one request
at a time, so it can't collide), and many rounds, since a collision depends
on timing. Each test asserts the rule held in *every* round.
"""

import concurrent.futures as cf
import socket
import threading
import time
from collections import Counter
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi import Request
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from server.db.session import configure_sqlite, get_db, open_session
from server.main import create_app
from server.models import Base
from server.models.role import Role
from server.models.user import User
from server.services import auth_service, session_service

ROUNDS = 15


@pytest.fixture(scope="module")
def live(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, sessionmaker[Session]]]:
    database_file: Path = tmp_path_factory.mktemp("concurrency") / "c.db"
    engine = configure_sqlite(
        create_engine(
            f"sqlite:///{database_file.as_posix()}", connect_args={"check_same_thread": False}
        )
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db(request: Request = None) -> Iterator[Session]:  # type: ignore[assignment]
        yield from open_session(factory, request)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline and thread.is_alive(), "server did not start"
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", factory
    server.should_exit = True
    thread.join(timeout=5)
    engine.dispose()


_counter = iter(range(10**9))


def _accounts(factory: sessionmaker[Session], role: str, n: int) -> list[dict]:
    """Create ``n`` accounts directly (hashing once, not n times) with sessions."""
    pw_hash = auth_service.hash_password("concurrency-test-pw")
    db = factory()
    try:
        role_id = auth_service.get_role_by_name(db, role).id
        out = []
        for _ in range(n):
            k = next(_counter)
            user = User(
                name=f"{role} {k}",
                email=f"{role}{k}@c.test",
                password_hash=pw_hash,
                role_id=role_id,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            token = session_service.create_session(db, user.id).token
            out.append(
                {"id": user.id, "email": user.email, "h": {"Authorization": f"Bearer {token}"}}
            )
        return out
    finally:
        db.close()


def _together(*calls) -> list[int]:
    """Fire all calls at the same moment; return their status codes."""
    barrier = threading.Barrier(len(calls))

    def run(call):
        barrier.wait()
        return call()

    with cf.ThreadPoolExecutor(len(calls)) as pool:
        return [f.result() for f in [pool.submit(run, c) for c in calls]]


def _role_of(factory: sessionmaker[Session], user_id: int) -> str:
    db = factory()
    try:
        return db.scalar(
            select(Role.name).join(User, User.role_id == Role.id).where(User.id == user_id)
        )
    finally:
        db.close()


def test_handing_over_the_lead_while_removing_that_person(live) -> None:
    base, factory = live
    [lead] = _accounts(factory, "project_lead", 1)
    people = _accounts(factory, "member", 1)
    target = people[0]
    with httpx.Client(base_url=base, timeout=60) as c:
        for r in range(ROUNDS):
            team = c.post(
                "/teams", json={"name": f"Lead race {next(_counter)}"}, headers=lead["h"]
            ).json()
            c.post(
                f"/teams/{team['id']}/members", json={"email": target["email"]}, headers=lead["h"]
            )
            codes = _together(
                lambda team=team: (
                    httpx.put(
                        f"{base}/teams/{team['id']}/lead",
                        json={"user_id": target["id"]},
                        headers=lead["h"],
                        timeout=60,
                    ).status_code
                ),
                lambda team=team: (
                    httpx.delete(
                        f"{base}/teams/{team['id']}/members/{target['id']}",
                        headers=lead["h"],
                        timeout=60,
                    ).status_code
                ),
            )
            assert 500 not in codes, f"round {r}: {codes}"
            # Whoever ended up lead, the lead must still be on the team.
            db = factory()
            try:
                lead_id = db.execute(
                    text("select lead_id from teams where id=:t"), {"t": team["id"]}
                ).scalar()
                members = {
                    row[0]
                    for row in db.execute(
                        text("select user_id from team_members where team_id=:t"), {"t": team["id"]}
                    )
                }
            finally:
                db.close()
            assert lead_id in members, (
                f"round {r}: lead {lead_id} not among {members} (codes {codes})"
            )


def test_two_admins_demoting_each_other_always_leave_one(live) -> None:
    base, factory = live
    for r in range(ROUNDS):
        a, b = _accounts(factory, "admin", 2)
        codes = _together(
            lambda a=a, b=b: (
                httpx.put(
                    f"{base}/users/{b['id']}/role",
                    json={"role": "member"},
                    headers=a["h"],
                    timeout=60,
                ).status_code
            ),
            lambda a=a, b=b: (
                httpx.put(
                    f"{base}/users/{a['id']}/role",
                    json={"role": "member"},
                    headers=b["h"],
                    timeout=60,
                ).status_code
            ),
        )
        roles = {_role_of(factory, a["id"]), _role_of(factory, b["id"])}
        assert "admin" in roles, f"round {r}: both demoted, codes {codes}"
        assert sorted(codes) == [200, 403], f"round {r}: {codes}"


def test_deleting_a_team_while_members_are_added(live) -> None:
    base, factory = live
    [lead] = _accounts(factory, "project_lead", 1)
    people = _accounts(factory, "member", 5)
    seen: Counter = Counter()
    for r in range(ROUNDS):
        team = httpx.post(
            f"{base}/teams",
            json={"name": f"Delete race {next(_counter)}"},
            headers=lead["h"],
            timeout=60,
        ).json()
        calls = [
            lambda team=team: (
                httpx.delete(
                    f"{base}/teams/{team['id']}", headers=lead["h"], timeout=60
                ).status_code
            )
        ]
        calls += [
            (
                lambda p=p, team=team: (
                    httpx.post(
                        f"{base}/teams/{team['id']}/members",
                        json={"email": p["email"]},
                        headers=lead["h"],
                        timeout=60,
                    ).status_code
                )
            )
            for p in people
        ]
        codes = _together(*calls)
        seen.update(codes)
        assert codes[0] == 204, f"round {r}: delete got {codes[0]}"
        assert set(codes[1:]) <= {201, 404}, f"round {r}: adds got {codes[1:]}"
    db = factory()
    try:
        orphans = db.scalar(
            text("select count(*) from team_members where team_id not in (select id from teams)")
        )
    finally:
        db.close()
    assert orphans == 0
    assert 500 not in seen


def test_many_simultaneous_writers_never_get_database_is_locked(live) -> None:
    base, factory = live
    leads = _accounts(factory, "project_lead", 30)
    names = [f"Busy {next(_counter)}" for _ in range(240)]

    def create(i: int) -> int | str:
        try:
            return httpx.post(
                f"{base}/teams", json={"name": names[i]}, headers=leads[i % 30]["h"], timeout=90
            ).status_code
        except httpx.HTTPError as exc:
            return type(exc).__name__  # a dropped connection would show up here

    with cf.ThreadPoolExecutor(40) as pool:
        codes = Counter(pool.map(create, range(240)))
    assert codes == {201: 240}, codes


def test_many_simultaneous_logins_all_succeed(live) -> None:
    """Kaleb's login hashes, then writes a session, all under the write lock."""
    base, factory = live
    [person] = _accounts(factory, "member", 1)

    def login(_):
        return httpx.post(
            f"{base}/auth/login",
            json={"email": person["email"], "password": "concurrency-test-pw"},
            timeout=60,
        ).status_code

    with cf.ThreadPoolExecutor(25) as pool:
        assert set(pool.map(login, range(50))) == {200}


def test_reads_are_not_held_up_by_the_write_lock(live) -> None:
    """GETs use an ordinary transaction, so a queue of writes doesn't stall them."""
    base, factory = live
    [reader] = _accounts(factory, "member", 1)
    started = time.perf_counter()
    for _ in range(20):
        assert httpx.get(f"{base}/teams", headers=reader["h"], timeout=60).status_code == 200
    assert (time.perf_counter() - started) / 20 < 0.5


def test_the_database_runs_in_wal_mode_with_a_long_busy_timeout(live) -> None:
    _base, factory = live
    db = factory()
    try:
        assert db.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert db.execute(text("PRAGMA busy_timeout")).scalar() >= 30_000
    finally:
        db.close()


def test_many_simultaneous_sign_ups_all_succeed(live) -> None:
    """Sign-up writes the account, reads it back, then writes a session; in WAL
    mode that last write fails ("database is locked") if someone else wrote in
    between, unless the request holds the write lock from the start.
    """
    base, _factory = live
    emails = [f"signup{next(_counter)}@c.test" for _ in range(60)]

    def sign_up(email: str) -> int | str:
        try:
            return httpx.post(
                f"{base}/auth/signup",
                json={"name": "New", "email": email, "password": "concurrency-test-pw"},
                timeout=90,
            ).status_code
        except httpx.HTTPError as exc:
            return type(exc).__name__

    with cf.ThreadPoolExecutor(20) as pool:
        codes = Counter(pool.map(sign_up, emails))
    assert codes == {200: 60}, codes
