"""Every database table, imported in one place.

Importing this package registers all models on ``Base.metadata``, which is what
Alembic (migrations) and the tests use to know the full schema.

MERGE-CRITICAL: when merging another branch's models, add its imports here and
keep all of these. A model missing from this file is missing from every test
database, and its tests fail with "no such table".
"""

from server.models.attachment import Attachment
from server.models.base import Base
from server.models.chat_message import ChatMessage
from server.models.conversation import Conversation, ConversationParticipant
from server.models.message import Message
from server.models.pending_verification import PendingVerification
from server.models.project import Project
from server.models.role import Role
from server.models.server_settings import ServerSettings
from server.models.session import Session
from server.models.subtask import Subtask
from server.models.task import Task
from server.models.team import Team, team_members
from server.models.user import User

__all__ = [
    "Attachment",
    "Base",
    "ChatMessage",
    "Conversation",
    "ConversationParticipant",
    "Message",
    "PendingVerification",
    "Project",
    "Role",
    "ServerSettings",
    "Session",
    "Subtask",
    "Task",
    "Team",
    "User",
    "team_members",
]
