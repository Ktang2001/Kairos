"""store login tokens hashed

``sessions.token`` now holds the SHA-256 of a login token, not the token
(server/services/session_service.py, ``hash_token``). Rows written before this
hold raw tokens, which can never match a hashed lookup, so they are deleted:
everyone signs in once more. That also ends the sessions whose raw tokens were
exposed in database backups committed to the repository on 2026-10-04.

No schema change, so this migration is data only (Alembic generated the file;
the DELETE was added by hand, since autogenerate only sees schema changes).

Revision ID: aecd4b8a1ef6
Revises: a04c4fb78442
Create Date: 2026-10-16 10:46:12.381150

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aecd4b8a1ef6"
down_revision: str | None = "a04c4fb78442"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DELETE FROM sessions")


def downgrade() -> None:
    # Hashed tokens can't be turned back into raw ones: sign everyone out again.
    op.execute("DELETE FROM sessions")
