from client.views.dashboard_page import ClockWidget, DashboardPage


def test_dashboard_starts_with_empty_state_panels(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    assert page.due_dates_panel.list_widget.count() == 1
    assert "No due dates" in page.due_dates_panel.list_widget.item(0).text()
    assert page.tasks_panel.list_widget.count() == 1
    assert page.meetings_panel.list_widget.count() == 1
    assert page.stat_tasks.value_label.text() == "—"


def test_set_items_replaces_empty_state(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    page.tasks_panel.set_items(["Write report", "Review PR"])

    assert page.tasks_panel.list_widget.count() == 2
    assert page.tasks_panel.list_widget.item(0).text() == "Write report"


def test_set_items_empty_list_restores_empty_state(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    page.tasks_panel.set_items(["Write report"])
    page.tasks_panel.set_items([])

    assert page.tasks_panel.list_widget.count() == 1
    assert "No tasks" in page.tasks_panel.list_widget.item(0).text()


def test_stat_tile_set_value(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    page.stat_tasks.set_value("4")

    assert page.stat_tasks.value_label.text() == "4"


def test_dashboard_has_a_clock(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    assert isinstance(page.clock, ClockWidget)
    assert page.clock.time_label.text() != ""
    assert page.clock.date_label.text() != ""


def test_clock_refreshes_on_timer_tick(qtbot) -> None:
    clock = ClockWidget()
    qtbot.addWidget(clock)
    clock._timer.stop()  # drive it manually instead of waiting on real wall-clock time

    clock.time_label.setText("")
    clock._refresh()

    assert clock.time_label.text() != ""


# ------------------------------------------------------- real figures


def _data(**my_work) -> dict:
    """A /dashboard response with one deadline and one project."""
    mine = {
        "open": 3,
        "in_progress": 1,
        "overdue": 1,
        "due_soon": 2,
        "upcoming": [
            {
                "id": 1,
                "title": "Old report",
                "project_id": 5,
                "project_name": "Website",
                "status": "todo",
                "due_date": "2026-10-30",
            },
            {
                "id": 2,
                "title": "Launch",
                "project_id": 5,
                "project_name": "Website",
                "status": "in_progress",
                "due_date": "2026-11-04",
            },
        ],
    }
    mine.update(my_work)
    return {
        "today": "2026-11-02",
        "due_soon_days": 7,
        "recent_days": 7,
        "overview": {
            "teams": 1,
            "active_projects": 2,
            "completed_projects": 0,
            "tasks": {"todo": 2, "in_progress": 1, "done": 1, "total": 4},
            "overdue": 1,
            "due_soon": 2,
            "unassigned_open": 0,
            "completed_recently": 1,
        },
        "my_work": mine,
        "projects": [
            {
                "id": 5,
                "name": "Website",
                "team_id": 1,
                "team_name": "Alpha",
                "status": "active",
                "tasks": {"todo": 2, "in_progress": 1, "done": 1, "total": 4},
                "percent_complete": 25.0,
                "overdue": 1,
            }
        ],
        "workload": [],
    }


def test_show_data_fills_the_tiles_lists_and_calendar(qtbot) -> None:
    from PySide6.QtCore import QDate

    page = DashboardPage()
    qtbot.addWidget(page)
    page.show_data(_data())

    assert page.stat_tasks.value_label.text() == "3"
    assert page.stat_projects.value_label.text() == "2"
    assert page.stat_due_soon.value_label.text() == "2"
    assert page.stat_overdue.value_label.text() == "1"
    deadlines = [
        page.due_dates_panel.list_widget.item(i).text()
        for i in range(page.due_dates_panel.list_widget.count())
    ]
    assert deadlines == ["OVERDUE - Oct 30: Old report (Website)", "Nov 04: Launch (Website)"]
    assert page.tasks_panel.list_widget.item(0).text() == "Website (Alpha): 25% done, 1 overdue"
    assert page.calendar.dateTextFormat(QDate(2026, 11, 4)).fontWeight() > 400
    assert "Nov 02" in page.as_of_label.text()
    assert page.calendar.dateTextFormat(QDate(2026, 11, 4)).background().color().alpha() > 0


def test_a_new_load_unmarks_old_deadlines(qtbot) -> None:
    from PySide6.QtCore import QDate

    page = DashboardPage()
    qtbot.addWidget(page)
    page.show_data(_data())
    page.show_data(_data(upcoming=[]))
    assert page.calendar.dateTextFormat(QDate(2026, 11, 4)).fontWeight() <= 400
    assert "No due dates" in page.due_dates_panel.list_widget.item(0).text()


def test_refresh_without_a_viewmodel_does_nothing(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)
    page.refresh()


def test_the_dashboard_loads_real_figures_from_the_server(qtbot, live_server) -> None:
    import httpx

    from client.api_client import ApiClient
    from client.viewmodels.dashboard_viewmodel import DashboardViewModel
    from client.viewmodels.session import Session
    from shared.roles import ROLE_PROJECT_LEAD
    from tests.client.conftest import SETUP_TIMEOUT, TEST_PASSWORD, set_live_role, unique_email

    email = unique_email("dash")
    body = httpx.post(
        f"{live_server}/auth/signup",
        json={"name": "Dana", "email": email, "password": TEST_PASSWORD},
        timeout=SETUP_TIMEOUT,
    ).json()
    set_live_role(email, ROLE_PROJECT_LEAD)
    client = ApiClient(base_url=live_server, token=body["token"], user_id=body["id"])
    team = client.create_team(f"Dash {email}"[:90])
    project = client.create_project(team["id"], "Website")
    client.create_task(project["id"], title="Late", assignee_id=body["id"], due_date="2020-01-01")

    viewmodel = DashboardViewModel(Session(client=client, user=client.me()))
    page = DashboardPage(viewmodel)
    qtbot.addWidget(page)
    page.refresh()
    qtbot.waitUntil(lambda: viewmodel.data is not None, timeout=8000)

    assert page.stat_tasks.value_label.text() == "1"
    assert page.stat_overdue.value_label.text() == "1"
    assert page.stat_projects.value_label.text() == "1"
    assert "Late" in page.due_dates_panel.list_widget.item(0).text()


def test_a_failed_load_shows_the_reason(qtbot, dead_server) -> None:
    from client.api_client import ApiClient
    from client.viewmodels.dashboard_viewmodel import DashboardViewModel
    from client.viewmodels.session import Session

    client = ApiClient(base_url=dead_server, token="tok", user_id=1)
    viewmodel = DashboardViewModel(Session(client=client, user={"id": 1}))
    page = DashboardPage(viewmodel)
    qtbot.addWidget(page)
    page.refresh()
    page.refresh()  # ignored while the first is running
    qtbot.waitUntil(lambda: not viewmodel.busy, timeout=8000)
    assert "Can't reach the server" in page.error_label.text()
