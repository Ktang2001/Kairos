"""Tests for the Projects page (context.md goals #4-#6 and the Gantt chart),
driven like a user would, inside the real signed-in app window (``AppShell``),
against the real API (``live_server``).

Each test checks what the page shows *and* what the server ends up holding, so
a page that merely looks right can't pass.
"""

import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import QSettings, Qt
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient
from client.theme import ThemeManager
from client.views.app_shell import AppShell
from client.views.projects_view import ProjectsView
from shared.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_PROJECT_LEAD
from tests.client.conftest import SETUP_TIMEOUT, TEST_PASSWORD, set_live_role, unique_email

WAIT_MS = 8000
PROJECTS_ROW = 3  # Dashboard, Chat, Teams, Projects, [Users, Server Settings]


@dataclass
class Person:
    email: str
    client: ApiClient
    user: dict


def _person(live_server: str, name: str, role: str = ROLE_MEMBER) -> Person:
    """Sign someone up and give them ``role``."""
    email = unique_email(name.lower())
    body = httpx.post(
        f"{live_server}/auth/signup",
        json={"name": name, "email": email, "password": TEST_PASSWORD},
        timeout=SETUP_TIMEOUT,
    ).json()
    if role != ROLE_MEMBER:
        set_live_role(email, role)
    client = ApiClient(base_url=live_server, token=body["token"], user_id=body["id"])
    return Person(email=email, client=client, user=client.me())


@dataclass
class Crew:
    """A team led by ``lead`` with ``member`` on it."""

    lead: Person
    member: Person
    team: dict


@pytest.fixture
def crew(live_server: str) -> Crew:
    lead = _person(live_server, "Lena", ROLE_PROJECT_LEAD)
    member = _person(live_server, "Max")
    team = lead.client.create_team(f"Alpha {unique_email('t')}"[:90])
    lead.client.add_member(team["id"], member.email)
    return Crew(lead=lead, member=member, team=team)


def _theme_manager() -> ThemeManager:
    """Themes saved in a throwaway file, never the real per-user settings."""
    ini = Path(tempfile.mkdtemp()) / "theme.ini"
    return ThemeManager(settings=QSettings(str(ini), QSettings.Format.IniFormat))


def _open(qtbot: QtBot, person: Person) -> ProjectsView:
    """The signed-in app for ``person``, on the Projects page, loaded and ready."""
    role = person.user["role"]
    shell = AppShell(
        person.client,
        display_name=person.user["name"],
        server_label="Test Server",
        on_switch_account=lambda: None,
        is_admin=role == ROLE_ADMIN,
        theme_manager=_theme_manager(),
        role=role,
    )
    qtbot.addWidget(shell)
    shell.resize(1200, 760)
    shell.show()
    shell.nav_list.setCurrentRow(PROJECTS_ROW)  # opening the page loads it
    view = shell.projects_page
    # Keep the window alive as long as the test holds the page.
    view.shell = shell  # type: ignore[attr-defined]
    view.confirm = lambda _title, _question: True
    _settle(qtbot, view)
    return view


def _settle(qtbot: QtBot, view: ProjectsView) -> None:
    """Wait for the page's request (and any queued refresh) to finish."""
    qtbot.waitUntil(lambda: view.viewmodel.loaded and not view.viewmodel.busy, timeout=WAIT_MS)


def _fill_task(view: ProjectsView, title: str, **fields) -> None:
    """Type a task into the editor."""
    view.title_input.setText(title)
    view.title_input.textEdited.emit(title)
    if "assignee" in fields:
        view.assignee_combo.setCurrentIndex(view.assignee_combo.findData(fields["assignee"]))
    if "start" in fields:
        view.start_input.set_value(fields["start"])
    if "due" in fields:
        view.due_input.set_value(fields["due"])
    if "status" in fields:
        view.status_combo.setCurrentIndex(view.status_combo.findData(fields["status"]))


def _table_titles(view: ProjectsView) -> list[str]:
    table = view.tasks_table
    return [table.item(row, 0).text() for row in range(table.rowCount())]


def _project_with_tasks(crew: Crew, *tasks: dict) -> dict:
    """Make a project in the crew's team with ``tasks`` (API calls, not the screen)."""
    project = crew.lead.client.create_project(crew.team["id"], "Website")
    for fields in tasks:
        crew.lead.client.create_task(project["id"], **fields)
    return project


# ------------------------------------------------------------- empty states


def test_someone_on_no_team_is_told_to_join_one(qtbot: QtBot, live_server: str) -> None:
    view = _open(qtbot, _person(live_server, "Olga"))
    assert view.project_panel.isHidden()
    assert "not on any teams" in view.empty_label.text()


def test_the_lead_is_offered_to_create_the_first_project(qtbot: QtBot, crew: Crew) -> None:
    view = _open(qtbot, crew.lead)
    assert view.team_combo.currentData() == crew.team["id"]
    assert "Create one on the left" in view.empty_label.text()
    assert not view.project_manage_panel.isHidden()


def test_a_member_is_told_to_ask_the_lead(qtbot: QtBot, crew: Crew) -> None:
    view = _open(qtbot, crew.member)
    assert "Ask the team lead" in view.empty_label.text()
    assert view.project_manage_panel.isHidden()


# ----------------------------------------------------------------- projects


def test_the_lead_creates_a_project_and_it_opens(qtbot: QtBot, crew: Crew) -> None:
    view = _open(qtbot, crew.lead)
    view.new_project_input.setText("  Website  ")
    view.create_project_button.click()
    _settle(qtbot, view)

    assert [p["name"] for p in crew.lead.client.list_projects(crew.team["id"])] == ["Website"]
    assert view.project_title.full_text == "Website"
    assert not view.project_panel.isHidden()
    assert view.new_project_input.text() == ""


def test_a_blank_project_name_is_refused_without_a_request(qtbot: QtBot, crew: Crew) -> None:
    view = _open(qtbot, crew.lead)
    view.new_project_input.setText("   ")
    view.create_project_button.click()
    assert not view.viewmodel.busy
    assert view.error_label.text() == "Enter a project name."


def test_the_lead_completes_reopens_renames_and_deletes_a_project(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew)
    view = _open(qtbot, crew.lead)

    view.complete_project_button.click()
    _settle(qtbot, view)
    assert crew.lead.client.list_projects(crew.team["id"])[0]["status"] == "completed"
    assert view.complete_project_button.text() == "Reopen project"
    view.complete_project_button.click()
    _settle(qtbot, view)
    assert crew.lead.client.list_projects(crew.team["id"])[0]["status"] == "active"

    view.rename_project_input.setText("Public site")
    view.rename_project_button.click()
    _settle(qtbot, view)
    assert crew.lead.client.list_projects(crew.team["id"])[0]["name"] == "Public site"

    view.delete_project_button.click()
    _settle(qtbot, view)
    assert crew.lead.client.list_projects(crew.team["id"]) == []
    assert project["id"] not in [p["id"] for p in view.viewmodel.projects]


def test_switching_team_shows_that_teams_projects(qtbot: QtBot, crew: Crew) -> None:
    _project_with_tasks(crew)
    other = crew.lead.client.create_team(f"Beta {unique_email('t')}"[:90])
    crew.lead.client.create_project(other["id"], "Mobile app")
    view = _open(qtbot, crew.lead)

    index = view.team_combo.findData(other["id"])
    view.team_combo.setCurrentIndex(index)
    _settle(qtbot, view)
    assert view.viewmodel.team_id == other["id"]
    assert view.project_title.full_text == "Mobile app"


# -------------------------------------------------------------------- tasks


def test_a_member_creates_and_assigns_a_scheduled_task(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew)
    view = _open(qtbot, crew.member)
    assert view.save_task_button.text() == "Create task"

    _fill_task(
        view,
        "Write copy",
        assignee=crew.member.user["id"],
        start=date(2026, 11, 2),
        due=date(2026, 11, 6),
        status="in_progress",
    )
    view.save_task_button.click()
    _settle(qtbot, view)

    [task] = crew.lead.client.list_tasks(project["id"])
    assert task["title"] == "Write copy"
    assert task["assignee"]["id"] == crew.member.user["id"]
    assert (task["start_date"], task["due_date"]) == ("2026-11-02", "2026-11-06")
    assert task["status"] == "in_progress"
    # The new task is now open in the editor and listed.
    assert view.viewmodel.task_id == task["id"]
    assert view.save_task_button.text() == "Save changes"
    assert _table_titles(view) == ["Write copy"]
    assert view.tasks_table.item(0, 1).text() == "Max"


def test_the_assignee_list_is_the_teams_members(qtbot: QtBot, crew: Crew) -> None:
    _project_with_tasks(crew)
    view = _open(qtbot, crew.member)
    names = [view.assignee_combo.itemText(i) for i in range(view.assignee_combo.count())]
    assert names == ["Unassigned", "Lena", "Max"]


def test_a_start_after_the_due_date_is_refused_without_a_request(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew)
    view = _open(qtbot, crew.member)
    _fill_task(view, "Backwards", start=date(2026, 11, 9), due=date(2026, 11, 1))
    view.save_task_button.click()
    assert not view.viewmodel.busy
    assert view.error_label.text() == "The start date can't be after the due date."
    assert crew.lead.client.list_tasks(project["id"]) == []


def test_editing_a_task_saves_only_through_the_editor(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Draft"})
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)
    assert view.title_input.text() == "Draft"

    _fill_task(view, "Final draft", status="done", due=date(2026, 11, 30))
    view.save_task_button.click()
    _settle(qtbot, view)

    [task] = crew.lead.client.list_tasks(project["id"])
    assert (task["title"], task["status"], task["due_date"]) == (
        "Final draft",
        "done",
        "2026-11-30",
    )
    assert task["completed_at"] is not None


def test_a_refresh_does_not_overwrite_what_you_are_typing(qtbot: QtBot, crew: Crew) -> None:
    _project_with_tasks(crew, {"title": "Draft"})
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)

    _fill_task(view, "Half-typed title")
    view.viewmodel.refresh()
    _settle(qtbot, view)
    assert view.title_input.text() == "Half-typed title"


def test_new_task_clears_the_editor(qtbot: QtBot, crew: Crew) -> None:
    _project_with_tasks(crew, {"title": "Draft"})
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)

    view.new_task_button.click()
    _settle(qtbot, view)
    assert view.viewmodel.task is None
    assert view.title_input.text() == ""
    assert view.save_task_button.text() == "Create task"
    assert view.saved_task_panel.isHidden()


def test_only_the_lead_sees_delete_task(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Draft"})

    member_view = _open(qtbot, crew.member)
    member_view.tasks_table.selectRow(0)
    _settle(qtbot, member_view)
    assert member_view.delete_task_button.isHidden()

    lead_view = _open(qtbot, crew.lead)
    lead_view.tasks_table.selectRow(0)
    _settle(qtbot, lead_view)
    assert not lead_view.delete_task_button.isHidden()
    lead_view.delete_task_button.click()
    _settle(qtbot, lead_view)
    assert crew.lead.client.list_tasks(project["id"]) == []
    assert _table_titles(lead_view) == []


def test_declining_the_confirmation_deletes_nothing(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Draft"})
    view = _open(qtbot, crew.lead)
    view.confirm = lambda _title, _question: False
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)
    view.delete_task_button.click()
    view.delete_project_button.click()
    assert not view.viewmodel.busy
    assert len(crew.lead.client.list_tasks(project["id"])) == 1


# ------------------------------------------------- subtasks and dependencies


def test_subtasks_are_added_and_ticked_off(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Launch"})
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)

    view.subtask_input.setText("Write announcement")
    view.add_subtask_button.click()
    _settle(qtbot, view)
    assert view.subtasks_list.count() == 1
    assert view.subtask_input.text() == ""

    view.subtasks_list.item(0).setCheckState(Qt.CheckState.Checked)
    _settle(qtbot, view)
    [task] = crew.lead.client.list_tasks(project["id"])
    assert (task["subtasks_done"], task["subtasks_total"]) == (1, 1)
    assert view.tasks_table.item(0, 5).text() == "1/1"


def test_a_task_is_set_to_wait_on_another_and_back(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Design"}, {"title": "Build"})
    view = _open(qtbot, crew.member)
    build_row = _table_titles(view).index("Build")
    view.tasks_table.selectRow(build_row)
    _settle(qtbot, view)

    choices = [view.dependency_combo.itemText(i) for i in range(view.dependency_combo.count())]
    assert choices == ["Design"]
    view.add_dependency_button.click()
    _settle(qtbot, view)

    tasks = {t["title"]: t for t in crew.lead.client.list_tasks(project["id"])}
    assert tasks["Build"]["depends_on"] == [tasks["Design"]["id"]]
    assert view.dependencies_list.item(0).text() == "Design"
    assert view.dependency_combo.count() == 0

    view.dependencies_list.setCurrentRow(0)
    view.remove_dependency_button.click()
    _settle(qtbot, view)
    tasks = {t["title"]: t for t in crew.lead.client.list_tasks(project["id"])}
    assert tasks["Build"]["depends_on"] == []


def test_a_dependency_loop_shows_the_servers_reason(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Design"}, {"title": "Build"})
    tasks = {t["title"]: t for t in crew.lead.client.list_tasks(project["id"])}
    crew.lead.client.add_dependency(tasks["Build"]["id"], tasks["Design"]["id"])

    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(_table_titles(view).index("Design"))
    _settle(qtbot, view)
    view.add_dependency_button.click()
    _settle(qtbot, view)
    assert "loop" in view.error_label.text()


# -------------------------------------------------------------------- Gantt


def test_the_gantt_tab_draws_scheduled_tasks_and_lists_the_rest(qtbot: QtBot, crew: Crew) -> None:
    _project_with_tasks(
        crew,
        {"title": "Design", "start_date": "2026-11-02", "due_date": "2026-11-04"},
        {"title": "Build", "start_date": "2026-11-05", "due_date": "2026-11-12"},
        {"title": "Someday"},
    )
    view = _open(qtbot, crew.member)
    view.tabs.setCurrentIndex(1)

    assert [row["title"] for row in view.gantt_chart.rows] == ["Design", "Build"]
    assert not view.unscheduled_label.isHidden()
    assert "Someday" in view.unscheduled_label.text()
    view.zoom_in_button.click()
    view.zoom_out_button.click()


def test_clicking_a_gantt_bar_opens_the_task(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(
        crew, {"title": "Design", "start_date": "2026-11-02", "due_date": "2026-11-04"}
    )
    view = _open(qtbot, crew.member)
    view.tabs.setCurrentIndex(1)
    task_id = crew.lead.client.list_tasks(project["id"])[0]["id"]

    view.gantt_chart.task_clicked.emit(task_id)
    _settle(qtbot, view)
    assert view.tabs.currentIndex() == 0
    assert view.viewmodel.task_id == task_id
    assert view.title_input.text() == "Design"


def test_the_summary_counts_tasks_and_overdue(qtbot: QtBot, crew: Crew) -> None:
    _project_with_tasks(
        crew,
        {"title": "Old", "due_date": "2020-01-01"},
        {"title": "Done", "status": "done"},
    )
    view = _open(qtbot, crew.member)
    summary = view.project_summary.text()
    assert "2 tasks" in summary
    assert "1 done" in summary
    assert "1 overdue" in summary


def test_server_errors_are_shown(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Draft"})
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)
    # Someone else deletes the task meanwhile; saving now fails with the server's message.
    crew.lead.client.delete_task(crew.lead.client.list_tasks(project["id"])[0]["id"])
    _fill_task(view, "Too late")
    view.save_task_button.click()
    _settle(qtbot, view)
    assert view.error_label.text() == "Task not found"


# --------------------------------------------- input limits (stress test)


def test_the_date_pickers_cover_exactly_the_servers_range(qtbot: QtBot, crew: Crew) -> None:
    from client.views.projects_view import OptionalDateEdit

    picker = OptionalDateEdit("Start")
    qtbot.addWidget(picker)
    picker.set_value(date(1900, 1, 1))
    assert picker.value() == date(1900, 1, 1)
    picker.set_value(date(2199, 12, 31))
    assert picker.value() == date(2199, 12, 31)


def test_an_invisible_title_is_refused_before_sending(qtbot: QtBot, crew: Crew) -> None:
    _project_with_tasks(crew)
    view = _open(qtbot, crew.member)
    _fill_task(view, "\u200b\u2060")
    view.save_task_button.click()
    assert not view.viewmodel.busy
    assert view.error_label.text() == "Enter a task title."


def test_task_fields_problem_checks_the_date_range() -> None:
    from client.viewmodels.projects_viewmodel import task_fields_problem

    assert task_fields_problem({"title": "x", "due_date": date(1800, 1, 1)}) == (
        "Dates must be between 1900 and 2199."
    )
    assert task_fields_problem({"title": "x", "due_date": date(2026, 1, 1)}) is None


def test_a_big_project_redraws_quickly(qtbot: QtBot) -> None:
    """Found by stress testing: the task table redraw grew with the square of the
    task count (400 tasks froze the window for 12 s on every auto-refresh)."""
    import time

    from client.viewmodels.projects_viewmodel import ProjectsViewModel
    from client.viewmodels.session import Session

    me = {"id": 1, "name": "Lena", "email": "l@x.co", "role": "project_lead"}
    vm = ProjectsViewModel(
        Session(client=ApiClient(base_url="http://127.0.0.1:9", token="t", user_id=1), user=me)
    )
    tasks = [
        {
            "id": i,
            "project_id": 1,
            "title": f"Task {i}",
            "description": None,
            "status": "todo",
            "assignee": me,
            "start_date": "2026-11-02",
            "due_date": "2026-11-09",
            "created_at": "2026-01-01T00:00:00",
            "completed_at": None,
            "subtasks_done": 0,
            "subtasks_total": 1,
            "depends_on": [],
        }
        for i in range(1, 1001)
    ]
    vm.me, vm.loaded, vm.tasks = me, True, tasks
    vm.teams = [{"id": 1, "name": "Alpha", "lead": me, "member_count": 1}]
    vm.team = {"id": 1, "name": "Alpha", "lead": me, "members": [me]}
    vm.projects = [
        {
            "id": 1,
            "team_id": 1,
            "name": "Big",
            "description": None,
            "status": "active",
            "created_at": "x",
            "tasks": {"todo": 1000, "in_progress": 0, "done": 0, "total": 1000},
        }
    ]
    vm.project = vm.projects[0]
    view = ProjectsView(vm)
    qtbot.addWidget(view)
    view.show()

    started = time.perf_counter()
    vm.changed.emit()
    assert time.perf_counter() - started < 3
    assert view.tasks_table.rowCount() == 1000
    assert view.tasks_table.item(999, 0).text() == "Task 1000"


# ------------------------------------- subtask assignee and dates (goals 4, 6)


def _open_task_with_subtask(qtbot: QtBot, crew: Crew, person: Person) -> tuple:
    """The screen for ``person`` with task "Launch" open and its one subtask selected."""
    project = _project_with_tasks(crew, {"title": "Launch"})
    task_id = crew.lead.client.list_tasks(project["id"])[0]["id"]
    crew.lead.client.create_subtask(task_id, title="Write announcement")
    view = _open(qtbot, person)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)
    view.subtasks_list.setCurrentRow(0)
    return view, project, task_id


def test_the_subtask_editor_appears_only_for_a_selected_subtask(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Launch"})
    task_id = crew.lead.client.list_tasks(project["id"])[0]["id"]
    crew.lead.client.create_subtask(task_id, title="Write announcement")
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)
    assert view.subtask_editor.isHidden()
    view.subtasks_list.setCurrentRow(0)
    assert not view.subtask_editor.isHidden()
    names = [
        view.subtask_assignee_combo.itemText(i) for i in range(view.subtask_assignee_combo.count())
    ]
    assert names == ["Unassigned", "Lena", "Max"]


def test_a_member_assigns_and_dates_a_subtask(qtbot: QtBot, crew: Crew) -> None:
    view, _project, task_id = _open_task_with_subtask(qtbot, crew, crew.member)
    combo = view.subtask_assignee_combo
    combo.setCurrentIndex(combo.findData(crew.member.user["id"]))
    view.subtask_start_input.set_value(date(2026, 11, 2))
    view.subtask_due_input.set_value(date(2026, 11, 4))
    view.save_subtask_button.click()
    _settle(qtbot, view)

    [subtask] = crew.lead.client.get_task(task_id)["subtasks"]
    assert subtask["assignee"]["id"] == crew.member.user["id"]
    assert (subtask["start_date"], subtask["due_date"]) == ("2026-11-02", "2026-11-04")
    assert view.subtasks_list.item(0).text() == "Write announcement  (Max, Nov 02 - Nov 04)"
    # Still selected after the reload, showing what was saved.
    assert view.subtasks_list.currentRow() == 0
    assert combo.currentData() == crew.member.user["id"]
    # The dated subtask now has its own row on the Gantt chart.
    rows = view.gantt_chart.rows
    assert [(r["kind"], r["title"]) for r in rows] == [("subtask", "Write announcement")]


def test_clearing_a_subtasks_assignee_and_dates(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Launch"})
    task_id = crew.lead.client.list_tasks(project["id"])[0]["id"]
    crew.lead.client.create_subtask(
        task_id, title="Step", assignee_id=crew.member.user["id"], due_date="2026-11-04"
    )
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)
    view.subtasks_list.setCurrentRow(0)
    assert view.subtasks_list.item(0).text() == "Step  (Max, due Nov 04)"

    view.subtask_assignee_combo.setCurrentIndex(0)
    view.subtask_due_input.set_value(None)
    view.save_subtask_button.click()
    _settle(qtbot, view)
    [subtask] = crew.lead.client.get_task(task_id)["subtasks"]
    assert subtask["assignee"] is None and subtask["due_date"] is None
    assert view.subtasks_list.item(0).text() == "Step"


def test_subtask_dates_out_of_order_are_refused_before_sending(qtbot: QtBot, crew: Crew) -> None:
    view, _project, task_id = _open_task_with_subtask(qtbot, crew, crew.member)
    view.subtask_start_input.set_value(date(2026, 11, 9))
    view.subtask_due_input.set_value(date(2026, 11, 1))
    view.save_subtask_button.click()
    assert not view.viewmodel.busy
    assert view.error_label.text() == "The start date can't be after the due date."
    assert crew.lead.client.get_task(task_id)["subtasks"][0]["start_date"] is None


def test_a_refresh_keeps_unsaved_subtask_edits(qtbot: QtBot, crew: Crew) -> None:
    view, _project, _task_id = _open_task_with_subtask(qtbot, crew, crew.member)
    view.subtask_due_input.set_value(date(2026, 12, 1))
    view.subtask_due_input.check.toggled.emit(True)  # as a click would
    view.viewmodel.refresh()
    _settle(qtbot, view)
    assert view.subtask_due_input.value() == date(2026, 12, 1)


def test_deleting_a_subtask_names_it_without_its_details(qtbot: QtBot, crew: Crew) -> None:
    project = _project_with_tasks(crew, {"title": "Launch"})
    task_id = crew.lead.client.list_tasks(project["id"])[0]["id"]
    crew.lead.client.create_subtask(task_id, title="Step", due_date="2026-11-04")
    view = _open(qtbot, crew.lead)
    asked: list[str] = []
    view.confirm = lambda _title, question: asked.append(question) or True
    view.tasks_table.selectRow(0)
    _settle(qtbot, view)
    view.subtasks_list.setCurrentRow(0)
    view.delete_subtask_button.click()
    _settle(qtbot, view)
    assert asked == ["Delete Step?"]
    assert crew.lead.client.get_task(task_id)["subtasks"] == []


# ------------------------------------------------- finding your work (goal 4)


def test_only_my_work_shows_my_tasks_and_tasks_holding_my_subtasks(
    qtbot: QtBot, crew: Crew
) -> None:
    me, lead = crew.member.user["id"], crew.lead.user["id"]
    project = _project_with_tasks(
        crew,
        {"title": "Mine", "assignee_id": me},
        {"title": "Lena's, with my subtask", "assignee_id": lead},
        {"title": "Lena's only", "assignee_id": lead},
        {"title": "Nobody's"},
    )
    tasks = {t["title"]: t for t in crew.lead.client.list_tasks(project["id"])}
    crew.lead.client.create_subtask(
        tasks["Lena's, with my subtask"]["id"], title="Step", assignee_id=me
    )
    view = _open(qtbot, crew.member)
    assert len(_table_titles(view)) == 4

    view.only_mine_check.setChecked(True)
    assert sorted(_table_titles(view)) == ["Lena's, with my subtask", "Mine"]
    row = _table_titles(view).index("Lena's, with my subtask")
    assert view.tasks_table.item(row, 1).text() == "Lena (your subtasks)"

    # The filter survives the automatic refresh, and can be switched off.
    view.viewmodel.refresh()
    _settle(qtbot, view)
    assert sorted(_table_titles(view)) == ["Lena's, with my subtask", "Mine"]
    view.only_mine_check.setChecked(False)
    assert len(_table_titles(view)) == 4


def test_only_my_work_keeps_the_open_task_selected(qtbot: QtBot, crew: Crew) -> None:
    me = crew.member.user["id"]
    _project_with_tasks(crew, {"title": "Other"}, {"title": "Mine", "assignee_id": me})
    view = _open(qtbot, crew.member)
    view.tasks_table.selectRow(_table_titles(view).index("Mine"))
    _settle(qtbot, view)
    view.only_mine_check.setChecked(True)
    assert _table_titles(view) == ["Mine"]
    assert view.tasks_table.selectedItems()[0].text() == "Mine"
    assert view.viewmodel.task["title"] == "Mine"


def test_is_my_work_copes_with_an_older_server() -> None:
    from client.views.projects_view import is_my_work

    old_style = {"assignee": None}  # no subtask_assignee_ids field
    assert not is_my_work(old_style, 7)
    assert is_my_work({"assignee": {"id": 7}}, 7)
    assert not is_my_work({"assignee": {"id": 7}}, None)
