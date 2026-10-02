"""Tests for the Teams and Users screens (context.md goals #1-#3), driven like
a user would, against the real API (``live_server``).

Each test signs people in with real accounts and roles, then checks both
what the screen *shows* (role-based hiding, goal #2) and what the server
ends up holding (so a screen that merely looks right can't pass).
"""

from dataclasses import dataclass

import httpx
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import Session
from client.views.home_view import HomeView
from client.views.teams_view import TeamsView
from shared.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_PROJECT_LEAD
from tests.client.conftest import TEST_PASSWORD, set_live_role, unique_email

WAIT_MS = 8000


@dataclass
class Person:
    email: str
    client: ApiClient
    user: dict


def _person(live_server: str, name: str, role: str = ROLE_MEMBER) -> Person:
    email = unique_email(name.lower())
    client = ApiClient(live_server)
    client.register(name, email, TEST_PASSWORD)
    if role != ROLE_MEMBER:
        set_live_role(email, role)
    user = client.me()
    return Person(email=email, client=client, user=user)


def _open(qtbot: QtBot, person: Person) -> HomeView:
    """The signed-in screen for ``person``, loaded and ready."""
    view = HomeView(HomeViewModel(Session(client=person.client, user=dict(person.user))))
    qtbot.addWidget(view)
    view.resize(900, 600)
    view.show()
    view.load()
    _settle(qtbot, view)
    return view


def _settle(qtbot: QtBot, view: HomeView) -> None:
    qtbot.waitUntil(
        lambda: not view.teams_viewmodel.busy and not view.users_viewmodel.busy, timeout=WAIT_MS
    )


def _teams(view: HomeView) -> TeamsView:
    return view.teams_view


def _team_names(view: HomeView) -> list[str]:
    widget = _teams(view).teams_list
    return [widget.item(i).text().rsplit("  (", 1)[0] for i in range(widget.count())]


def _select_team(qtbot: QtBot, view: HomeView, name: str) -> None:
    widget = _teams(view).teams_list
    for i in range(widget.count()):
        if widget.item(i).text().startswith(name + "  ("):
            widget.setCurrentRow(i)
            _settle(qtbot, view)
            return
    raise AssertionError(f"team {name!r} not in list {_team_names(view)}")


def _select_member(view: HomeView, email: str) -> None:
    widget = _teams(view).members_list
    for i in range(widget.count()):
        if f" - {email}" in widget.item(i).text():
            widget.setCurrentRow(i)
            return
    raise AssertionError(f"{email} not among members")


def _members(view: HomeView) -> list[str]:
    widget = _teams(view).members_list
    return [widget.item(i).text() for i in range(widget.count())]


def _create_team(qtbot: QtBot, view: HomeView, name: str) -> None:
    teams = _teams(view)
    teams.new_team_input.setText(name)
    qtbot.mouseClick(teams.create_team_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)


def _add(qtbot: QtBot, view: HomeView, email: str) -> None:
    teams = _teams(view)
    teams.add_member_input.setText(email)
    qtbot.mouseClick(teams.add_member_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)


def _always_yes(view: HomeView) -> list[str]:
    asked: list[str] = []
    _teams(view).confirm = lambda title, question: asked.append(question) or True
    return asked


def _always_no(view: HomeView) -> list[str]:
    asked: list[str] = []
    _teams(view).confirm = lambda title, question: asked.append(question) or False
    return asked


def _error(view: HomeView) -> str:
    label = _teams(view).error_label
    return "" if label.isHidden() else label.text()


# ============================================================ layout (#3)


def test_signed_in_screen_has_teams_and_messages_tabs(qtbot: QtBot, live_server: str) -> None:
    view = _open(qtbot, _person(live_server, "Max"))
    tabs = [view.tabs.tabText(i) for i in range(view.tabs.count())]
    assert tabs == ["Teams", "Messages"]
    assert view.tabs.currentWidget() is view.teams_view


def test_a_new_member_sees_an_empty_state_and_no_create_box(qtbot: QtBot, live_server: str) -> None:
    view = _open(qtbot, _person(live_server, "Max"))
    teams = _teams(view)
    assert _team_names(view) == []
    assert not teams.create_row.isVisible()
    assert "not on any teams" in teams.empty_label.text()
    assert "Ask a team lead" in teams.empty_label.text()
    assert not teams.detail_panel.isVisible()


# ======================================================= create a team (#1)


@pytest.mark.parametrize("role", [ROLE_PROJECT_LEAD, ROLE_ADMIN])
def test_leads_and_admins_can_create_a_team(qtbot: QtBot, live_server: str, role: str) -> None:
    creator = _person(live_server, "Lena", role)
    view = _open(qtbot, creator)
    assert _teams(view).create_row.isVisible()

    name = f"Team {unique_email()}"
    _create_team(qtbot, view, name)

    assert name in _team_names(view)
    teams = _teams(view)
    assert teams.detail_panel.isVisible()
    assert teams.team_title.full_text == name
    assert _members(view) == [f"Lena - {creator.email}  [lead, you]"]
    assert teams.new_team_input.text() == ""
    # ...and the server agrees.
    assert any(t["name"] == name for t in creator.client.list_teams())


def test_a_blank_team_name_is_caught_without_contacting_the_server(
    qtbot: QtBot, live_server: str
) -> None:
    view = _open(qtbot, _person(live_server, "Lena", ROLE_PROJECT_LEAD))
    _create_team(qtbot, view, "   ")
    assert _error(view) == "Enter a team name."
    assert _team_names(view) == []


def test_a_duplicate_team_name_shows_the_servers_answer(qtbot: QtBot, live_server: str) -> None:
    lead = _person(live_server, "Lena", ROLE_PROJECT_LEAD)
    name = f"Dup {unique_email()}"
    lead.client.create_team(name)
    view = _open(qtbot, lead)
    _create_team(qtbot, view, name.upper())
    assert _error(view) == "A team with that name already exists"


def test_a_double_click_creates_only_one_team(qtbot: QtBot, live_server: str) -> None:
    """Counts *requests*, not teams: the server's unique-name rule would hide a
    second request here, but not for actions without such a rule.
    """
    lead = _person(live_server, "Lena", ROLE_PROJECT_LEAD)
    view = _open(qtbot, lead)
    teams = _teams(view)
    calls: list[str] = []
    real_create = lead.client.create_team
    lead.client.create_team = lambda name: calls.append(name) or real_create(name)

    name = f"Once {unique_email()}"
    teams.new_team_input.setText(name)
    teams._create()
    teams.new_team_input.setText(name)
    teams._create()
    _settle(qtbot, view)

    assert calls == [name]
    assert _error(view) == ""
    assert [t["name"] for t in lead.client.list_teams()].count(name) == 1


# ===================================================== manage members (#1)


@pytest.fixture
def team_setup(qtbot: QtBot, live_server: str):
    """Lena leads a team with Max on it; Olga exists but isn't on it."""
    lena = _person(live_server, "Lena", ROLE_PROJECT_LEAD)
    max_ = _person(live_server, "Max")
    olga = _person(live_server, "Olga")
    name = f"Alpha {unique_email()}"
    team = lena.client.create_team(name)
    lena.client.add_member(team["id"], max_.email)
    return lena, max_, olga, name, team["id"]


def test_the_lead_adds_a_member_by_email(qtbot: QtBot, team_setup) -> None:
    lena, _max, olga, name, team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    assert _teams(view).manage_panel.isVisible()

    _add(qtbot, view, olga.email.upper())

    assert any(olga.email in line for line in _members(view))
    assert _teams(view).add_member_input.text() == ""
    assert olga.email in [m["email"] for m in lena.client.get_team(team_id)["members"]]


@pytest.mark.parametrize(
    ("email", "message"),
    [
        ("", "Enter the email of the person to add."),
        ("not-an-email", "That doesn't look like an email address."),
        ("ghost@example.com", "No user has that email"),
    ],
)
def test_adding_a_bad_email_explains_why(
    qtbot: QtBot, team_setup, email: str, message: str
) -> None:
    lena, *_rest, name, _team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    _add(qtbot, view, email)
    assert _error(view) == message


def test_adding_someone_already_on_the_team(qtbot: QtBot, team_setup) -> None:
    lena, max_, _olga, name, _team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    _add(qtbot, view, max_.email)
    assert _error(view) == "That user is already on the team"


def test_the_lead_removes_a_member_after_confirming(qtbot: QtBot, team_setup) -> None:
    lena, max_, _olga, name, team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    asked = _always_yes(view)
    _select_member(view, max_.email)
    qtbot.mouseClick(_teams(view).remove_member_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)

    assert asked == [f"Remove Max from {name}?"]
    assert not any(max_.email in line for line in _members(view))
    assert max_.email not in [m["email"] for m in lena.client.get_team(team_id)["members"]]


def test_saying_no_keeps_the_member(qtbot: QtBot, team_setup) -> None:
    lena, max_, _olga, name, team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    _always_no(view)
    _select_member(view, max_.email)
    qtbot.mouseClick(_teams(view).remove_member_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)
    assert max_.email in [m["email"] for m in lena.client.get_team(team_id)["members"]]


def test_the_lead_row_cannot_be_removed_or_made_lead(qtbot: QtBot, team_setup) -> None:
    lena, *_rest, name, _team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    _select_member(view, lena.email)
    assert not _teams(view).remove_member_button.isEnabled()
    assert not _teams(view).make_lead_button.isEnabled()


def test_handing_over_the_lead_swaps_who_sees_the_controls(qtbot: QtBot, team_setup) -> None:
    lena, max_, _olga, name, team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    _always_yes(view)
    _select_member(view, max_.email)
    qtbot.mouseClick(_teams(view).make_lead_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)

    teams = _teams(view)
    assert teams.lead_label.full_text == f"Lead: Max ({max_.email})"
    assert not teams.manage_panel.isVisible()  # Lena is no longer the lead
    assert teams.leave_team_button.isVisible()  # ...so now she may leave
    assert lena.client.get_team(team_id)["lead"]["id"] == max_.user["id"]


def test_the_lead_renames_the_team(qtbot: QtBot, team_setup) -> None:
    lena, *_rest, name, team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    new_name = f"Renamed {unique_email()}"
    _teams(view).rename_input.setText(new_name)
    qtbot.mouseClick(_teams(view).rename_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)
    assert _teams(view).team_title.full_text == new_name
    assert new_name in _team_names(view)
    assert lena.client.get_team(team_id)["name"] == new_name


def test_the_lead_deletes_the_team_after_confirming(qtbot: QtBot, team_setup) -> None:
    lena, *_rest, name, _team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    asked = _always_yes(view)
    qtbot.mouseClick(_teams(view).delete_team_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)

    assert asked == [f"Delete {name}? This can't be undone."]
    assert name not in _team_names(view)
    assert not _teams(view).detail_panel.isVisible()
    assert name not in [t["name"] for t in lena.client.list_teams()]


# ============================================== role-based hiding (#2)


def test_a_plain_member_sees_members_but_no_management(qtbot: QtBot, team_setup) -> None:
    lena, max_, _olga, name, _team_id = team_setup
    view = _open(qtbot, max_)
    assert _team_names(view) == [name]
    _select_team(qtbot, view, name)

    teams = _teams(view)
    assert not teams.manage_panel.isVisible()
    assert not teams.create_row.isVisible()
    assert teams.leave_team_button.isVisible()
    assert f"Max - {max_.email}  [you]" in _members(view)
    assert f"Lena - {lena.email}  [lead]" in _members(view)


def test_the_lead_cannot_leave_without_handing_over(qtbot: QtBot, team_setup) -> None:
    lena, *_rest, name, _team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    assert not _teams(view).leave_team_button.isVisible()


def test_a_member_leaves_and_the_team_disappears(qtbot: QtBot, team_setup) -> None:
    _lena, max_, _olga, name, _team_id = team_setup
    view = _open(qtbot, max_)
    _select_team(qtbot, view, name)
    _always_yes(view)
    qtbot.mouseClick(_teams(view).leave_team_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)
    assert _team_names(view) == []
    assert max_.client.list_teams() == []


def test_someone_not_on_the_team_doesnt_see_it(qtbot: QtBot, team_setup) -> None:
    *_people, olga, name, _team_id = team_setup
    view = _open(qtbot, olga)
    assert name not in _team_names(view)


def test_an_admin_sees_and_manages_every_team(qtbot: QtBot, live_server: str, team_setup) -> None:
    *_people, name, _team_id = team_setup
    view = _open(qtbot, _person(live_server, "Ada", ROLE_ADMIN))
    assert name in _team_names(view)
    _select_team(qtbot, view, name)
    assert _teams(view).manage_panel.isVisible()
    assert not _teams(view).leave_team_button.isVisible()  # not a member


def test_a_promotion_shows_up_after_refresh(qtbot: QtBot, live_server: str) -> None:
    max_ = _person(live_server, "Max")
    view = _open(qtbot, max_)
    assert not _teams(view).create_row.isVisible()

    set_live_role(max_.email, ROLE_PROJECT_LEAD)
    qtbot.mouseClick(_teams(view).refresh_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)

    assert _teams(view).create_row.isVisible()
    assert view.signed_in_label.full_text == "Signed in as Max (Project Lead)"


def test_a_server_refusal_is_shown_even_if_the_screen_was_stale(qtbot: QtBot, team_setup) -> None:
    """The screen hid nothing it should have, but rules changed underneath it."""
    lena, max_, _olga, name, team_id = team_setup
    view = _open(qtbot, lena)
    _select_team(qtbot, view, name)
    lena.client.change_lead(team_id, max_.user["id"])  # done elsewhere
    _teams(view).rename_input.setText("Sneaky")
    qtbot.mouseClick(_teams(view).rename_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)
    assert _error(view) == "Only the team's lead or an admin can do this"


# ===================================================== Users screen (#2)


def test_only_admins_get_a_users_tab(qtbot: QtBot, live_server: str) -> None:
    for role, expected in ((ROLE_MEMBER, False), (ROLE_PROJECT_LEAD, False), (ROLE_ADMIN, True)):
        view = _open(qtbot, _person(live_server, "Pat", role))
        assert view.users_tab_visible is expected, role


def test_the_users_tab_lists_people_with_their_roles(qtbot: QtBot, live_server: str) -> None:
    ada = _person(live_server, "Ada", ROLE_ADMIN)
    max_ = _person(live_server, "Max")
    view = _open(qtbot, ada)
    users = view.users_view
    assert users.role_box(max_.user["id"]).currentData() == ROLE_MEMBER
    assert users.role_box(ada.user["id"]).currentData() == ROLE_ADMIN
    assert not users.role_box(ada.user["id"]).isEnabled()  # can't change your own


def test_an_admin_promotes_someone_after_confirming(qtbot: QtBot, live_server: str) -> None:
    ada = _person(live_server, "Ada", ROLE_ADMIN)
    max_ = _person(live_server, "Max")
    view = _open(qtbot, ada)
    users = view.users_view
    asked: list[str] = []
    users.confirm = lambda title, question: asked.append(question) or True

    box = users.role_box(max_.user["id"])
    box.setCurrentIndex(box.findData(ROLE_PROJECT_LEAD))
    box.activated.emit(box.currentIndex())
    _settle(qtbot, view)

    assert asked == ["Change Max from Member to Project Lead?"]
    assert max_.client.me()["role"] == ROLE_PROJECT_LEAD
    assert users.role_box(max_.user["id"]).currentData() == ROLE_PROJECT_LEAD


def test_cancelling_a_role_change_puts_it_back(qtbot: QtBot, live_server: str) -> None:
    ada = _person(live_server, "Ada", ROLE_ADMIN)
    max_ = _person(live_server, "Max")
    view = _open(qtbot, ada)
    users = view.users_view
    users.confirm = lambda title, question: False

    box = users.role_box(max_.user["id"])
    box.setCurrentIndex(box.findData(ROLE_ADMIN))
    box.activated.emit(box.currentIndex())
    _settle(qtbot, view)

    assert box.currentData() == ROLE_MEMBER
    assert max_.client.me()["role"] == ROLE_MEMBER


def test_a_refused_role_change_snaps_back_with_the_reason(qtbot: QtBot, live_server: str) -> None:
    ada = _person(live_server, "Ada", ROLE_ADMIN)
    max_ = _person(live_server, "Max")
    view = _open(qtbot, ada)
    users = view.users_view
    users.confirm = lambda title, question: True
    set_live_role(ada.email, ROLE_MEMBER)  # demoted by someone else meanwhile

    box = users.role_box(max_.user["id"])
    box.setCurrentIndex(box.findData(ROLE_ADMIN))
    box.activated.emit(box.currentIndex())
    _settle(qtbot, view)

    assert "Requires one of: admin" in users.error_label.text()
    assert users.role_box(max_.user["id"]).currentData() == ROLE_MEMBER
    assert max_.client.me()["role"] == ROLE_MEMBER


def test_losing_admin_removes_the_users_tab_on_refresh(qtbot: QtBot, live_server: str) -> None:
    ada = _person(live_server, "Ada", ROLE_ADMIN)
    view = _open(qtbot, ada)
    assert view.users_tab_visible
    set_live_role(ada.email, ROLE_MEMBER)
    qtbot.mouseClick(_teams(view).refresh_button, Qt.MouseButton.LeftButton)
    _settle(qtbot, view)
    assert not view.users_tab_visible


def test_users_screen_shows_names_as_plain_text(qtbot: QtBot, live_server: str) -> None:
    ada = _person(live_server, "Ada", ROLE_ADMIN)
    _person(live_server, "<b>Boss</b>")
    view = _open(qtbot, ada)
    table = view.users_view.table
    names = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert "<b>Boss</b>" in names


def test_the_teams_list_uses_the_api_shape(live_server: str) -> None:
    """Guards the client against the server's response shape changing."""
    lead = _person(live_server, "Lena", ROLE_PROJECT_LEAD)
    lead.client.create_team(f"Shape {unique_email()}")
    [summary] = lead.client.list_teams()
    assert {"id", "name", "lead", "member_count"} <= set(summary)
    response = httpx.get(
        f"{lead.client.base_url}/teams/{summary['id']}",
        headers={"Authorization": f"Bearer {lead.client.token}"},
    )
    assert {"id", "name", "lead", "members"} <= set(response.json())
