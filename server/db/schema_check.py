"""Refuse to start on a database that hasn't been upgraded to this code's schema.

Found in use: after pulling the projects/Gantt work, a server whose database
was never upgraded (``alembic upgrade head`` not run) started normally, then
answered 500 on the Projects tab and the Dashboard -- the code asked for
columns and a table the old database didn't have. Checking the version at
start-up turns that into one clear message with the command to fix it.

A database with no Alembic version record at all (one built straight from the
models, as the tests do) is not checked.
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

ALEMBIC_INI = Path(__file__).resolve().parent / "alembic.ini"
UPGRADE_COMMAND = "alembic -c server/db/alembic.ini upgrade head"


def code_head() -> str:
    """The newest migration this code ships with."""
    script = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))
    head = script.get_current_head()
    assert head is not None  # the repository always has migrations
    return head


def database_problem(bind: Engine | Connection) -> str | None:
    """A message saying what to do if the database's schema doesn't match this
    code, else None."""
    if isinstance(bind, Engine):
        with bind.connect() as connection:
            return database_problem(connection)
    if "alembic_version" not in inspect(bind).get_table_names():
        return None
    current = MigrationContext.configure(bind).get_current_revision()
    head = code_head()
    if current == head:
        return None
    known = {
        rev.revision
        for rev in ScriptDirectory.from_config(Config(str(ALEMBIC_INI))).walk_revisions()
    }
    if current is not None and current not in known:
        return (
            f"The database (version {current}) is newer than this copy of Kairos. "
            "Switch to the branch that upgraded it, or pull the latest code."
        )
    return (
        f"The database needs upgrading before the server can start "
        f"(it is at version {current}, this code needs {head}).\n"
        f"Stop here and run, from the Kairos folder:\n    {UPGRADE_COMMAND}"
    )
