"""Meetings: Jitsi calls started or scheduled from a chat or a team.

Who may do what:

* Anyone in a conversation may start or schedule a meeting in it, and becomes
  its host. A team meeting is one held in the team's chat, so any team member
  may start one; an admin who isn't on the team can't (they aren't in its chat).
* Invited means "in the meeting's conversation". A team chat follows the
  team's members, so a team meeting invites the whole team.
* A meeting is visible to the people in its conversation, and -- for a team
  meeting -- to every admin. To anyone else it does not exist (404), the same
  as teams.
* Anyone who can see a meeting may reply (accept / tentative / decline) and
  join it, except the host, who doesn't reply to their own meeting.
* Only the host or an admin may cancel it. Cancelling posts a message in the
  chat, so everyone in it sees it at their next poll.
* A cancelled or finished meeting can't be replied to or joined. Join asks
  the server every time, so a stale "Join" button on someone's screen can't
  open a cancelled meeting.

Kairos never talks to Jitsi: it hands out ``{jitsi_base_url}/{room_name}``
links, which the client opens in the browser. The room name is random and
unguessable because a public Jitsi room has no access control of its own.

Routes translate the exceptions below into HTTP status codes
(server/api/errors.py). Times passed in and stored are naive UTC.
"""

import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.chat_message import ChatMessage
from server.models.conversation import Conversation, ConversationParticipant
from server.models.meeting import Meeting, MeetingRsvp
from server.models.user import User
from server.services import conversation_service, server_settings_service, team_service
from shared.date_rules import date_in_range
from shared.meetings import MAX_DURATION_MINUTES, PAST_START_GRACE, MeetingResponse


class MeetingError(Exception):
    """Base class for meeting operations the API can refuse."""


class MeetingNotFound(MeetingError):
    """No such meeting, or the caller is not allowed to know it exists."""


class ConversationNotFound(MeetingError):
    """No such conversation, or the caller isn't in it."""


class NotOnTeam(MeetingError):
    """The caller can see the team (an admin) but isn't in its chat."""


class NotMeetingHost(MeetingError):
    """Only the host or an admin can cancel a meeting."""


class HostCannotRespond(MeetingError):
    """The host doesn't reply to their own meeting."""


class MeetingCancelled(MeetingError):
    """The meeting was cancelled."""


class MeetingEnded(MeetingError):
    """The meeting is already over."""


class StartInPast(MeetingError):
    """A scheduled start time that has already gone by."""


class StartOutOfRange(MeetingError):
    """A start date outside the range every screen can show (shared/date_rules.py)."""


class ClientTokenReused(MeetingError):
    """The request's client_token already belongs to a different message."""


def utc_naive(value: datetime) -> datetime:
    """A time-zone-aware time as naive UTC, the way times are stored."""
    return value.astimezone(UTC).replace(tzinfo=None)


def _meeting_query() -> Select[tuple[Meeting]]:
    """Select meetings with everything ``to_meeting_out`` reads loaded.

    ``populate_existing`` so a meeting re-read straight after a commit
    reflects the committed rows, not a stale identity-map copy.
    """
    return (
        select(Meeting)
        .options(
            selectinload(Meeting.conversation).selectinload(Conversation.participants),
            selectinload(Meeting.conversation).selectinload(Conversation.team),
            selectinload(Meeting.host).selectinload(User.role),
            selectinload(Meeting.rsvps).selectinload(MeetingRsvp.user).selectinload(User.role),
        )
        .execution_options(populate_existing=True)
    )


def _reload(db: OrmSession, meeting_id: int) -> Meeting:
    """The meeting just written, re-read. Deleted in between counts as not found."""
    meeting = db.scalar(_meeting_query().where(Meeting.id == meeting_id))
    if meeting is None:
        raise MeetingNotFound(meeting_id)
    return meeting


def _is_participant(db: OrmSession, conversation_id: int, user_id: int) -> bool:
    return db.get(ConversationParticipant, (conversation_id, user_id)) is not None


def can_see(db: OrmSession, meeting: Meeting, user: User) -> bool:
    """True if ``user`` may see ``meeting``: they're in its chat, or it's a
    team meeting and they're an admin."""
    if _is_participant(db, meeting.conversation_id, user.id):
        return True
    return meeting.conversation.team_id is not None and team_service.is_admin(user)


def can_cancel(meeting: Meeting, user: User) -> bool:
    """True if ``user`` may cancel ``meeting``: its host, or an admin."""
    return meeting.host_user_id == user.id or team_service.is_admin(user)


def get_visible_meeting(db: OrmSession, meeting_id: int, user: User) -> Meeting:
    """Return the meeting if ``user`` may see it, else raise MeetingNotFound."""
    meeting = db.scalar(_meeting_query().where(Meeting.id == meeting_id))
    if meeting is None or not can_see(db, meeting, user):
        raise MeetingNotFound(meeting_id)
    return meeting


def _require_open(meeting: Meeting, now: datetime) -> None:
    """Refuse replying to or joining a cancelled or finished meeting."""
    if meeting.cancelled_at is not None:
        raise MeetingCancelled(meeting.id)
    if meeting.ends_at <= now:
        raise MeetingEnded(meeting.id)


def _new_room_name(db: OrmSession) -> str:
    """A random room name no other meeting uses.

    128 random bits make a clash practically impossible; the check makes it
    impossible, and is race-free because writes hold the database lock.
    """
    while True:
        name = f"Kairos-{secrets.token_urlsafe(16)}"
        if db.scalar(select(Meeting.id).where(Meeting.room_name == name)) is None:
            return name


def create_in_conversation(
    db: OrmSession,
    conversation_id: int,
    host: User,
    *,
    title: str,
    starts_at: datetime | None,
    duration_minutes: int,
    client_token: str | None,
    now: datetime,
) -> Meeting:
    """Start (``starts_at`` None) or schedule a meeting in a conversation.

    Posts the chat message that announces it and creates the meeting in one
    commit. ``starts_at`` is time-zone aware; ``now`` is naive UTC.
    """
    if not _is_participant(db, conversation_id, host.id):
        raise ConversationNotFound(conversation_id)

    if client_token:
        existing = db.scalar(select(ChatMessage).where(ChatMessage.client_token == client_token))
        if existing is not None:
            if existing.meeting is not None and existing.sender_user_id == host.id:
                return _reload(db, existing.meeting.id)
            raise ClientTokenReused(client_token)

    if starts_at is None:
        start = now
    else:
        if not date_in_range(starts_at.date()):
            raise StartOutOfRange(starts_at)
        start = utc_naive(starts_at)
        if start < now - PAST_START_GRACE:
            raise StartInPast(starts_at)

    announcement = "Started a meeting" if starts_at is None else "Scheduled a meeting"
    message = ChatMessage(
        conversation_id=conversation_id,
        sender_user_id=host.id,
        body=f"{announcement}: {title}",
        client_token=client_token or None,
    )
    meeting = Meeting(
        conversation_id=conversation_id,
        chat_message=message,
        host_user_id=host.id,
        title=title,
        starts_at=start,
        duration_minutes=duration_minutes,
        room_name=_new_room_name(db),
        jitsi_base_url=server_settings_service.get_settings(db).jitsi_base_url,
    )
    db.add_all([message, meeting])
    db.commit()
    return _reload(db, meeting.id)


def create_for_team(db: OrmSession, team_id: int, host: User, **details) -> Meeting:
    """Start or schedule a meeting for a team, held in the team's chat.

    Takes the same keyword arguments as ``create_in_conversation``.
    """
    team = team_service.get_visible_team(db, team_id, host)
    if not any(member.id == host.id for member in team.members):
        raise NotOnTeam(team_id)
    conversation = conversation_service.get_team_conversation(db, team.id)
    if conversation is None:
        # Every team gets its chat at creation and at start-up; this only
        # covers a database edited by hand in between.
        conversation = conversation_service.sync_team_conversation(db, team)
        db.flush()
    return create_in_conversation(db, conversation.id, host, **details)


def respond(
    db: OrmSession, meeting_id: int, user: User, *, response: MeetingResponse, now: datetime
) -> Meeting:
    """Record (or change) ``user``'s reply to a meeting."""
    meeting = get_visible_meeting(db, meeting_id, user)
    if meeting.host_user_id == user.id:
        raise HostCannotRespond(meeting_id)
    _require_open(meeting, now)

    rsvp = next((r for r in meeting.rsvps if r.user_id == user.id), None)
    if rsvp is None:
        meeting.rsvps.append(MeetingRsvp(user_id=user.id, response=response.value))
    else:
        rsvp.response = response.value
    db.commit()
    return _reload(db, meeting_id)


def cancel(
    db: OrmSession, meeting_id: int, user: User, *, now: datetime
) -> tuple[Meeting, ChatMessage | None]:
    """Cancel a meeting (its host or an admin only).

    Returns the meeting and the "cancelled" chat message it posted -- None if
    the meeting was already cancelled, which is not an error: two people
    clicking Cancel at once both get what they wanted.
    """
    meeting = get_visible_meeting(db, meeting_id, user)
    if not can_cancel(meeting, user):
        raise NotMeetingHost(meeting_id)
    if meeting.cancelled_at is not None:
        return meeting, None
    if meeting.ends_at <= now:
        raise MeetingEnded(meeting_id)

    meeting.cancelled_at = now
    meeting.cancelled_by_user_id = user.id
    notice = ChatMessage(
        conversation_id=meeting.conversation_id,
        sender_user_id=user.id,
        body=f"Cancelled the meeting: {meeting.title}",
    )
    db.add(notice)
    db.commit()
    db.refresh(notice)
    return _reload(db, meeting_id), notice


def join_link(db: OrmSession, meeting_id: int, user: User, *, now: datetime) -> str:
    """The Jitsi link for a meeting ``user`` may join right now."""
    meeting = get_visible_meeting(db, meeting_id, user)
    _require_open(meeting, now)
    return meeting.join_url


def list_for_conversation(db: OrmSession, conversation_id: int, user: User) -> list[Meeting]:
    """Every meeting held in a conversation the caller is in, oldest first.

    How an open chat refreshes its meeting cards: the message feed only ever
    adds messages, so replies and cancellations would never reach a card
    already on screen.
    """
    if not _is_participant(db, conversation_id, user.id):
        raise ConversationNotFound(conversation_id)
    return list(
        db.scalars(
            _meeting_query().where(Meeting.conversation_id == conversation_id).order_by(Meeting.id)
        )
    )


def upcoming_for(db: OrmSession, viewer: User, *, now: datetime) -> list[Meeting]:
    """Meetings ``viewer`` can see that aren't cancelled or over, soonest first."""
    in_my_chats = select(ConversationParticipant.conversation_id).where(
        ConversationParticipant.user_id == viewer.id
    )
    visible = Meeting.conversation_id.in_(in_my_chats)
    if team_service.is_admin(viewer):
        team_chats = select(Conversation.id).where(Conversation.team_id.isnot(None))
        visible = or_(visible, Meeting.conversation_id.in_(team_chats))

    # The SQL filter is a coarse cut (nothing that started more than the
    # longest meeting ago can still be running); the exact end check needs
    # each meeting's own duration.
    earliest_start = now - timedelta(minutes=MAX_DURATION_MINUTES)
    candidates = db.scalars(
        _meeting_query()
        .where(visible, Meeting.cancelled_at.is_(None), Meeting.starts_at > earliest_start)
        .order_by(Meeting.starts_at, Meeting.id)
    )
    return [meeting for meeting in candidates if meeting.ends_at > now]
