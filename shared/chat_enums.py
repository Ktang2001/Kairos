from enum import Enum


class ConversationKind(str, Enum):
    """Whether a conversation is a 1:1 direct chat or a multi-member group chat."""

    DIRECT = "direct"
    GROUP = "group"


class ParticipantRole(str, Enum):
    """A user's permission level within a single conversation.

    Distinct from the site-wide `Role` model (server/models/role.py), which governs
    global permissions - this only governs what a user can do inside one conversation
    (e.g. manage membership of a group chat).
    """

    ADMIN = "admin"
    MEMBER = "member"
