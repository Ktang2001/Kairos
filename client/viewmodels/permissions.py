"""Who may do what, as the screens need to know it to hide actions.

These mirror the server's rules (``server.services.team_service`` and the
``require_role`` checks) so the screens only *offer* what will work. They are
not the security boundary: the server re-checks every request regardless,
so a stale or wrong answer here can only hide a button, never grant access.
"""

from shared.roles import ROLE_ADMIN, ROLE_PROJECT_LEAD


def is_admin(me: dict) -> bool:
    return me.get("role") == ROLE_ADMIN


def can_create_team(me: dict) -> bool:
    return me.get("role") in (ROLE_ADMIN, ROLE_PROJECT_LEAD)


def can_manage_team(me: dict, team: dict) -> bool:
    """Rename, delete, add/remove members, hand over the lead."""
    return is_admin(me) or team["lead"]["id"] == me.get("id")


def is_member(me: dict, team: dict) -> bool:
    return any(member["id"] == me.get("id") for member in team.get("members", []))


def can_leave_team(me: dict, team: dict) -> bool:
    """Members may leave; the lead must hand the lead over first."""
    return is_member(me, team) and team["lead"]["id"] != me.get("id")


def can_manage_users(me: dict) -> bool:
    return is_admin(me)
