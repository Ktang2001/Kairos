"""Role identifiers shared by the FastAPI backend and the Qt client.

The backend stores roles as rows in the ``roles`` table; the client only needs
the names, so they live here rather than in either package alone.

MERGE-CRITICAL: these strings are stored in every database. Renaming one
(e.g. "project_lead" to "lead") makes existing accounts' roles unknown;
add a migration if a rename is ever really needed.
"""

ROLE_ADMIN = "admin"
ROLE_PROJECT_LEAD = "project_lead"
ROLE_MEMBER = "member"

#: Every role the app knows about, ordered most privileged first. Kept as a
#: tuple so callers cannot mutate the canonical list in place.
ALL_ROLES: tuple[str, ...] = (ROLE_ADMIN, ROLE_PROJECT_LEAD, ROLE_MEMBER)

#: Role handed to anyone who self-registers through the public route. Never
#: derive this from user input, or anyone could register themselves as admin.
DEFAULT_SELF_REGISTRATION_ROLE = ROLE_MEMBER

#: Labels for display in the Qt client.
ROLE_DISPLAY_NAMES: dict[str, str] = {
    ROLE_ADMIN: "Admin",
    ROLE_PROJECT_LEAD: "Project Lead",
    ROLE_MEMBER: "Member",
}
