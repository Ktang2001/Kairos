"""Single source of truth for where the SQLite database lives.

Both the application engine (``session.py``) and Alembic
(``migrations/env.py``) import from here.

The path is resolved against *this file*, not the process working directory,
because SQLAlchemy resolves a relative ``sqlite:///some/rel/path.db`` URL
against the caller's CWD. When the URL was written directly into
``alembic.ini``, running alembic from anywhere except the repo root silently
created and migrated a *different* database file than the one the app reads.
"""

from pathlib import Path

#: Directory containing this module (``<repo>/server/db``).
DB_DIR = Path(__file__).resolve().parent

#: Absolute path to the SQLite database file.
DB_PATH = DB_DIR / "kairos.db"

#: SQLAlchemy URL. ``as_posix()`` keeps Windows backslashes out of the URL,
#: where they would otherwise be read as escape sequences.
DATABASE_URL = f"sqlite:///{DB_PATH.as_posix()}"
