"""Request and response shapes for the meeting routes (server/api/meetings.py).

Times go out as UTC with an explicit offset ("...Z"), and a start time sent
in must carry one too: the two computers may not agree on a time zone, and a
bare "14:00" would be read differently by each.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from server.schemas.user import UserOut, to_user_out
from shared.meetings import (
    DEFAULT_DURATION_MINUTES,
    MAX_DURATION_MINUTES,
    MAX_MEETING_TITLE_LENGTH,
    MIN_DURATION_MINUTES,
    REMINDER_CHOICES,
    MeetingResponse,
    MeetingState,
)
from shared.text_rules import clean_display_text

if TYPE_CHECKING:
    from server.models.meeting import Meeting
    from server.models.user import User

#: Long enough for a uuid4 hex (what the client sends), short enough that
#: nobody stores an essay in the unique index.
MAX_CLIENT_TOKEN_LENGTH = 100


class MeetingCreate(BaseModel):
    """Body of POST /conversations/{id}/meetings and POST /teams/{id}/meetings.

    No ``starts_at`` means "start now" (an instant meeting).
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Annotated[str, BeforeValidator(clean_display_text)] = Field(
        min_length=1, max_length=MAX_MEETING_TITLE_LENGTH
    )
    starts_at: AwareDatetime | None = None
    duration_minutes: int = Field(
        default=DEFAULT_DURATION_MINUTES, ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES
    )
    #: Sending the same token again returns the meeting already made, so a
    #: double-click or a retry after a timeout never makes two meetings.
    client_token: str | None = Field(default=None, max_length=MAX_CLIENT_TOKEN_LENGTH)
    #: Reminders for everyone, in minutes before the start (REMINDER_CHOICES).
    #: Stored sorted and without repeats.
    reminder_minutes: list[int] = Field(default_factory=list, max_length=len(REMINDER_CHOICES))

    @field_validator("reminder_minutes")
    @classmethod
    def _known_reminder_times(cls, value: list[int]) -> list[int]:
        unknown = [minutes for minutes in value if minutes not in REMINDER_CHOICES]
        if unknown:
            raise ValueError(f"reminders can only be {', '.join(map(str, REMINDER_CHOICES))}")
        return sorted(set(value))


class MeetingUpdate(BaseModel):
    """Body of PATCH /meetings/{id}: only the fields sent change. None of them
    can be cleared (a meeting always has a title, a start and a length)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Annotated[str, BeforeValidator(clean_display_text)] | None = Field(
        default=None, min_length=1, max_length=MAX_MEETING_TITLE_LENGTH
    )
    starts_at: AwareDatetime | None = None
    duration_minutes: int | None = Field(
        default=None, ge=MIN_DURATION_MINUTES, le=MAX_DURATION_MINUTES
    )
    reminder_minutes: list[int] | None = Field(default=None, max_length=len(REMINDER_CHOICES))

    @field_validator("reminder_minutes")
    @classmethod
    def _known_reminder_times(cls, value: list[int] | None) -> list[int] | None:
        return MeetingCreate._known_reminder_times(value) if value is not None else None

    @model_validator(mode="after")
    def _nothing_cleared(self) -> "MeetingUpdate":
        for field in self.model_fields_set:
            if getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class RsvpIn(BaseModel):
    """Body of PUT /meetings/{id}/response."""

    response: MeetingResponse


class RsvpOut(BaseModel):
    user: UserOut
    response: MeetingResponse


class ResponseCounts(BaseModel):
    accepted: int
    tentative: int
    declined: int
    #: Invited (in the meeting's chat, apart from the host) but not replied yet.
    no_response: int


class MeetingOut(BaseModel):
    """A meeting as one viewer sees it: ``my_response``, ``is_host`` and
    ``can_cancel`` depend on who is asking."""

    id: int
    conversation_id: int
    #: Set for a team meeting (one held in a team's chat).
    team_id: int | None
    team_name: str | None
    title: str
    starts_at: datetime
    ends_at: datetime
    duration_minutes: int
    #: The host's reminders for everyone, minutes before the start.
    reminder_minutes: list[int]
    host: UserOut
    state: MeetingState
    cancelled_at: datetime | None
    created_at: datetime
    has_ended: bool
    is_host: bool
    can_cancel: bool
    #: None if the viewer hasn't replied, and always None for the host.
    my_response: MeetingResponse | None
    responses: list[RsvpOut]
    counts: ResponseCounts


class JoinOut(BaseModel):
    """Body of POST /meetings/{id}/join's answer: the Jitsi link to open."""

    url: str


def as_utc(value: datetime | None) -> datetime | None:
    """A stored naive-UTC time, marked as UTC for the response."""
    return None if value is None else value.replace(tzinfo=UTC)


def to_meeting_out(
    meeting: "Meeting", viewer: "User", *, now: datetime, can_cancel: bool
) -> MeetingOut:
    """Flatten a meeting (with its conversation, host and replies loaded) for ``viewer``.

    ``now`` is naive UTC. ``can_cancel`` comes from the service, which owns
    that rule (host or admin).
    """
    by_user = {rsvp.user_id: MeetingResponse(rsvp.response) for rsvp in meeting.rsvps}
    invited = {p.user_id for p in meeting.conversation.participants} - {meeting.host_user_id}
    replied = [response for user_id, response in by_user.items() if user_id in invited]
    team = meeting.conversation.team
    return MeetingOut(
        id=meeting.id,
        conversation_id=meeting.conversation_id,
        team_id=team.id if team is not None else None,
        team_name=team.name if team is not None else None,
        title=meeting.title,
        starts_at=as_utc(meeting.starts_at),
        ends_at=as_utc(meeting.ends_at),
        duration_minutes=meeting.duration_minutes,
        reminder_minutes=list(meeting.reminder_minutes or []),
        host=to_user_out(meeting.host),
        state=MeetingState.CANCELLED if meeting.cancelled_at else MeetingState.SCHEDULED,
        cancelled_at=as_utc(meeting.cancelled_at),
        created_at=as_utc(meeting.created_at),
        has_ended=meeting.ends_at <= now,
        is_host=meeting.host_user_id == viewer.id,
        can_cancel=can_cancel,
        my_response=by_user.get(viewer.id),
        responses=[
            RsvpOut(user=to_user_out(rsvp.user), response=MeetingResponse(rsvp.response))
            for rsvp in meeting.rsvps
        ],
        counts=ResponseCounts(
            accepted=replied.count(MeetingResponse.ACCEPTED),
            tentative=replied.count(MeetingResponse.TENTATIVE),
            declined=replied.count(MeetingResponse.DECLINED),
            no_response=len(invited) - len(replied),
        ),
    )
