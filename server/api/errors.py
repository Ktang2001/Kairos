"""One table mapping service-layer refusals to HTTP responses.

Shared by every route module, so the same refusal always gets the same
status code and message whichever URL raised it.

Usage in a route:

    try:
        ...
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
"""

from fastapi import HTTPException, status

from server.services import (
    meeting_service,
    project_service,
    task_service,
    team_service,
    user_service,
)
from shared.date_rules import DATE_RANGE_MESSAGE

ERRORS: dict[type[Exception], tuple[int, str]] = {
    # Teams
    team_service.TeamNotFound: (status.HTTP_404_NOT_FOUND, "Team not found"),
    team_service.NotTeamManager: (
        status.HTTP_403_FORBIDDEN,
        "Only the team's lead or an admin can do this",
    ),
    team_service.TeamNameTaken: (
        status.HTTP_409_CONFLICT,
        "A team with that name already exists",
    ),
    team_service.TeamHasProjects: (
        status.HTTP_409_CONFLICT,
        "Delete or move the team's projects before deleting the team",
    ),
    team_service.UserNotFound: (status.HTTP_404_NOT_FOUND, "No user has that email"),
    team_service.AlreadyMember: (
        status.HTTP_409_CONFLICT,
        "That user is already on the team",
    ),
    team_service.NotAMember: (status.HTTP_404_NOT_FOUND, "That user is not on the team"),
    team_service.LeadCannotBeRemoved: (
        status.HTTP_409_CONFLICT,
        "Make someone else the lead before removing the current lead",
    ),
    team_service.NewLeadNotAMember: (
        status.HTTP_409_CONFLICT,
        "Add that user to the team before making them the lead",
    ),
    # Projects
    project_service.ProjectNotFound: (status.HTTP_404_NOT_FOUND, "Project not found"),
    # Tasks, subtasks and dependencies
    task_service.TaskNotFound: (status.HTTP_404_NOT_FOUND, "Task not found"),
    task_service.SubtaskNotFound: (status.HTTP_404_NOT_FOUND, "Subtask not found"),
    task_service.AssigneeNotOnTeam: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The assignee must be a member of this team",
    ),
    task_service.StartAfterDue: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The start date cannot be after the due date",
    ),
    task_service.DependencyNotInProject: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "A task can only depend on another task in the same project",
    ),
    task_service.DependencyCycle: (
        status.HTTP_409_CONFLICT,
        "That would make the tasks wait on each other in a loop",
    ),
    task_service.TaskChanged: (
        status.HTTP_409_CONFLICT,
        "Someone else changed this task while you were editing it - your changes weren't saved",
    ),
    task_service.SubtaskChanged: (
        status.HTTP_409_CONFLICT,
        "Someone else changed this subtask while you were editing it - your changes weren't saved",
    ),
    task_service.ProjectCompleted: (
        status.HTTP_409_CONFLICT,
        "This project is completed - reopen it to make changes",
    ),
    task_service.DependencyNotFound: (
        status.HTTP_404_NOT_FOUND,
        "This task does not depend on that task",
    ),
    # Meetings
    meeting_service.MeetingNotFound: (status.HTTP_404_NOT_FOUND, "Meeting not found"),
    meeting_service.ConversationNotFound: (status.HTTP_404_NOT_FOUND, "Conversation not found"),
    meeting_service.NotOnTeam: (
        status.HTTP_403_FORBIDDEN,
        "Only the team's members can start a meeting for it",
    ),
    meeting_service.NotMeetingHost: (
        status.HTTP_403_FORBIDDEN,
        "Only the meeting's host or an admin can cancel it",
    ),
    meeting_service.HostCannotRespond: (
        status.HTTP_409_CONFLICT,
        "You're hosting this meeting",
    ),
    meeting_service.MeetingCancelled: (status.HTTP_409_CONFLICT, "This meeting was cancelled"),
    meeting_service.MeetingEnded: (status.HTTP_409_CONFLICT, "This meeting has already ended"),
    meeting_service.StartInPast: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "A scheduled meeting can't start in the past",
    ),
    meeting_service.StartOutOfRange: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        DATE_RANGE_MESSAGE,
    ),
    meeting_service.ClientTokenReused: (
        status.HTTP_409_CONFLICT,
        "That request id was already used for something else - try again",
    ),
    # Users (admin)
    user_service.UserNotFound: (status.HTTP_404_NOT_FOUND, "User not found"),
    user_service.CannotChangeOwnRole: (
        status.HTTP_409_CONFLICT,
        "You can't change your own role - ask another admin",
    ),
}

#: For ``except KNOWN_ERRORS`` -- anything not listed is a bug and should 500.
KNOWN_ERRORS: tuple[type[Exception], ...] = tuple(ERRORS)


def http_error(exc: Exception) -> HTTPException:
    """The HTTPException (status code and message) that ERRORS lists for this refusal."""
    status_code, detail = ERRORS[type(exc)]
    return HTTPException(status_code=status_code, detail=detail)
