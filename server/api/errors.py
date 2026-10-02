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

from server.services import team_service, user_service

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
    status_code, detail = ERRORS[type(exc)]
    return HTTPException(status_code=status_code, detail=detail)
