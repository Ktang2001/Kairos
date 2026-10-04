"""Create the rows Kairos needs before it can be used at all.

Right now that means the three roles and one administrator account, so there is
somebody who can call the admin-only routes. Idempotent: running it twice is
harmless.

    python -m server.seed
    python -m server.seed --email me@example.com --name "Kaleb"

The password is generated and printed once, unless the KAIROS_ADMIN_PASSWORD
environment variable is set. There is deliberately no --password option: a
command-line argument lands in shell history and the process list. Nothing is
stored but the hash, so a generated password cannot be recovered afterwards.

PowerShell (5.1 or 7), choosing your own password without it reaching history
or the screen:

    $p = Read-Host "Admin password" -AsSecureString
    $env:KAIROS_ADMIN_PASSWORD = [System.Net.NetworkCredential]::new("", $p).Password
    python -m server.seed --email me@example.com
    Remove-Item Env:KAIROS_ADMIN_PASSWORD
"""

import argparse
import os
import secrets
import sys
from typing import NamedTuple

from sqlalchemy.exc import OperationalError

from server.db.session import SessionLocal
from server.services import auth_service
from shared.account_rules import MIN_PASSWORD_LENGTH, password_problem
from shared.roles import ROLE_ADMIN

DEFAULT_ADMIN_EMAIL = "admin@kairos.local"
DEFAULT_ADMIN_NAME = "Kairos Admin"

#: Length of a generated password. 16 bytes of urlsafe base64 is 22 characters,
#: comfortably past MIN_PASSWORD_LENGTH without being awkward to retype.
GENERATED_PASSWORD_BYTES = 16


#: Same advice the server gives at start-up (server.main.lifespan).
NOT_MIGRATED_MESSAGE = (
    "The database has not been set up. From the repo root, run:\n"
    "    alembic -c server/db/alembic.ini upgrade head"
)


class SeedResult(NamedTuple):
    """What ``seed`` did: the exit code, and whether this run created the account."""

    exit_code: int
    #: True only if this run created the account, i.e. ``password`` is now its
    #: password. Callers must not show a generated password otherwise.
    created: bool


def seed(*, email: str, password: str, name: str) -> SeedResult:
    """Ensure roles exist and an administrator account is present."""
    db = SessionLocal()
    # Everything that reads an ORM object happens inside the try, and only
    # plain strings escape it. Touching a mapped attribute after the session
    # has closed raises DetachedInstanceError, which is exactly how an earlier
    # version of this script failed.
    try:
        roles = auth_service.ensure_roles(db)
        roles_summary = ", ".join(role.name for role in roles)

        existing = auth_service.get_user_by_email(db, email)
        if existing is not None and existing.role.name != ROLE_ADMIN:
            # Not promoted: anyone who registered this address before the
            # seed ran would otherwise be handed the admin account.
            print(
                f"{existing.email} already exists but is a {existing.role.name}, not an admin. "
                "Use another --email, or have an admin change its role.",
                file=sys.stderr,
            )
            return SeedResult(1, created=False)
        if existing is not None:
            account_summary = f"admin already exists: {existing.email} (id {existing.id})"
            created = False
        else:
            # Sign-up always makes a member (Kaleb's create_user); promote it.
            user = auth_service.create_user(db, name=name, email=email, password=password)
            user.role_id = auth_service.get_role_by_name(db, ROLE_ADMIN).id
            db.commit()
            account_summary = f"created admin: {user.email} (id {user.id}, role {ROLE_ADMIN})"
            created = True
    except OperationalError:
        print(NOT_MIGRATED_MESSAGE, file=sys.stderr)
        return SeedResult(1, created=False)
    except ValueError as exc:
        print(f"could not create the admin account: {exc}", file=sys.stderr)
        return SeedResult(1, created=False)
    finally:
        db.close()

    print(f"roles present: {roles_summary}")
    print(account_summary)
    return SeedResult(0, created)


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point: read the options and KAIROS_ADMIN_PASSWORD, check the password,
    then seed.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--email",
        default=os.environ.get("KAIROS_ADMIN_EMAIL", DEFAULT_ADMIN_EMAIL),
        help=f"email for the administrator account (default: {DEFAULT_ADMIN_EMAIL})",
    )
    parser.add_argument(
        "--name",
        default=os.environ.get("KAIROS_ADMIN_NAME", DEFAULT_ADMIN_NAME),
        help="display name for the administrator account",
    )
    # Deliberately no --password option: a password typed on the command line
    # is saved in shell history and visible to other users in the process list.
    args = parser.parse_args(argv)

    password = os.environ.get("KAIROS_ADMIN_PASSWORD")
    generated = not password
    if generated:
        password = secrets.token_urlsafe(GENERATED_PASSWORD_BYTES)

    if len(password) < MIN_PASSWORD_LENGTH:
        parser.error(f"KAIROS_ADMIN_PASSWORD must be at least {MIN_PASSWORD_LENGTH} characters")
    if problem := password_problem(password, email=args.email, name=args.name):
        parser.error(f"KAIROS_ADMIN_PASSWORD rejected: {problem}")

    result = seed(email=args.email, password=password, name=args.name)

    # Only if it was actually saved: on a re-run the existing admin keeps
    # their password, and printing a new one would lock out whoever noted it.
    if result.created and generated:
        print()
        print(f"  generated admin password: {password}")
        print("  Write this down now - only its hash is stored, so it cannot be shown again.")
        print()

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
