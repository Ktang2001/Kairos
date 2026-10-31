"""Meeting routes: start, schedule, reply to, cancel and join Jitsi meetings.

The rules about who may do what live in ``server.services.meeting_service``;
this module calls the service, maps its exceptions to HTTP status codes via
``server.api.errors``, and tells the meeting's chat about changes over the
WebSocket (``meeting_updated``, plus ``chat_message`` for the announcement
and the "cancelled" notice). The client doesn't listen to the WebSocket yet
and polls instead; the events are there for when it does.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import get_current_user
from server.api.errors import KNOWN_ERRORS, http_error
from server.db.session import get_db
from server.models.chat_message import ChatMessage
from server.models.meeting import Meeting
from server.models.user import User
from server.realtime.connection_manager import manager
from server.schemas.chat_message import ChatMessageOut
from server.schemas.meeting import JoinOut, MeetingCreate, MeetingOut, RsvpIn, to_meeting_out
from server.services import conversation_service, meeting_service
from server.services.task_service import utcnow

router = APIRouter(tags=["meetings"])


def _out(meeting: Meeting, viewer: User) -> MeetingOut:
    return to_meeting_out(
        meeting, viewer, now=utcnow(), can_cancel=meeting_service.can_cancel(meeting, viewer)
    )


async def _announce(db: OrmSession, meeting: Meeting, message: ChatMessage | None = None) -> None:
    """Tell everyone in the meeting's chat that it changed (and about a new message)."""
    participant_ids = conversation_service.list_participant_user_ids(db, meeting.conversation_id)
    if message is not None:
        await manager.broadcast_to_users(
            participant_ids,
            {
                "type": "chat_message",
                "conversation_id": meeting.conversation_id,
                "message": ChatMessageOut.model_validate(message).model_dump(mode="json"),
            },
        )
    await manager.broadcast_to_users(
        participant_ids,
        {
            "type": "meeting_updated",
            "conversation_id": meeting.conversation_id,
            "meeting_id": meeting.id,
        },
    )


@router.post(
    "/conversations/{conversation_id}/meetings",
    response_model=MeetingOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_chat_meeting(
    conversation_id: int,
    payload: MeetingCreate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> MeetingOut:
    """Start or schedule a meeting in a chat. Everyone in the chat is invited."""
    try:
        meeting = meeting_service.create_in_conversation(
            db, conversation_id, current_user, **payload.model_dump(), now=utcnow()
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    await _announce(db, meeting, meeting.chat_message)
    return _out(meeting, current_user)


@router.post(
    "/teams/{team_id}/meetings", response_model=MeetingOut, status_code=status.HTTP_201_CREATED
)
async def create_team_meeting(
    team_id: int,
    payload: MeetingCreate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> MeetingOut:
    """Start or schedule a meeting for a team, in its team chat. The whole team is invited."""
    try:
        meeting = meeting_service.create_for_team(
            db, team_id, current_user, **payload.model_dump(), now=utcnow()
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    await _announce(db, meeting, meeting.chat_message)
    return _out(meeting, current_user)


@router.get("/conversations/{conversation_id}/meetings", response_model=list[MeetingOut])
def list_chat_meetings(
    conversation_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> list[MeetingOut]:
    """Every meeting in a chat the caller is in, oldest first (for its meeting cards)."""
    try:
        meetings = meeting_service.list_for_conversation(db, conversation_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return [_out(meeting, current_user) for meeting in meetings]


@router.get("/meetings/upcoming", response_model=list[MeetingOut])
def list_upcoming_meetings(
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> list[MeetingOut]:
    """Meetings the caller can see that aren't cancelled or over, soonest first."""
    return [
        _out(meeting, current_user)
        for meeting in meeting_service.upcoming_for(db, current_user, now=utcnow())
    ]


@router.get("/meetings/{meeting_id}", response_model=MeetingOut)
def get_meeting(
    meeting_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> MeetingOut:
    """One meeting. 404 unless the caller is in its chat (or an admin, for a team meeting)."""
    try:
        meeting = meeting_service.get_visible_meeting(db, meeting_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return _out(meeting, current_user)


@router.put("/meetings/{meeting_id}/response", response_model=MeetingOut)
async def respond_to_meeting(
    meeting_id: int,
    payload: RsvpIn,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> MeetingOut:
    """Accept, tentatively accept or decline. Sending it again changes the reply."""
    try:
        meeting = meeting_service.respond(
            db, meeting_id, current_user, response=payload.response, now=utcnow()
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    await _announce(db, meeting)
    return _out(meeting, current_user)


@router.post("/meetings/{meeting_id}/cancel", response_model=MeetingOut)
async def cancel_meeting(
    meeting_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> MeetingOut:
    """Cancel a meeting: its host or an admin only. Cancelling twice is harmless."""
    try:
        meeting, notice = meeting_service.cancel(db, meeting_id, current_user, now=utcnow())
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    if notice is not None:
        await _announce(db, meeting, notice)
    return _out(meeting, current_user)


@router.get("/meetings/{meeting_id}/join", response_model=JoinOut)
def join_meeting(
    meeting_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> JoinOut:
    """The Jitsi link to open, checked now: a cancelled or finished meeting is refused."""
    try:
        url = meeting_service.join_link(db, meeting_id, current_user, now=utcnow())
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return JoinOut(url=url)
