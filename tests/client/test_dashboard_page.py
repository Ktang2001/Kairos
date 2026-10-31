from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QDate

from client.views.dashboard_page import (
    DEADLINE_AND_MEETING_BACKGROUND,
    MEETING_BACKGROUND,
    ClockWidget,
    DashboardPage,
)
from tests.client.meeting_data import make_meeting


def test_dashboard_starts_with_empty_state_panels(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    assert page.due_dates_panel.list_widget.count() == 1
    assert "No due dates" in page.due_dates_panel.list_widget.item(0).text()
    assert page.tasks_panel.list_widget.count() == 1
    assert page.meetings_panel.list_widget.count() == 0
    assert not page.meetings_panel.empty_label.isHidden()
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


def test_subtasks_assigned_to_me_join_my_figures_and_deadlines(qtbot) -> None:
    from PySide6.QtCore import QDate

    page = DashboardPage()
    qtbot.addWidget(page)
    data = _data(
        subtasks_open=2,
        subtasks_overdue=1,
        subtasks_due_soon=1,
        upcoming_subtasks=[
            {
                "id": 9,
                "title": "Write announcement",
                "task_id": 2,
                "task_title": "Launch",
                "project_id": 5,
                "project_name": "Website",
                "status": "todo",
                "due_date": "2026-11-03",
            }
        ],
    )
    page.show_data(data)
    assert page.stat_tasks.value_label.text() == "5"  # 3 tasks + 2 subtasks
    assert page.stat_due_soon.value_label.text() == "3"
    assert page.stat_overdue.value_label.text() == "2"
    deadlines = [
        page.due_dates_panel.list_widget.item(i).text()
        for i in range(page.due_dates_panel.list_widget.count())
    ]
    assert deadlines == [
        "OVERDUE - Oct 30: Old report (Website)",
        "Nov 03: Write announcement (subtask of Launch, Website)",
        "Nov 04: Launch (Website)",
    ]
    assert page.calendar.dateTextFormat(QDate(2026, 11, 3)).background().color().alpha() > 0


# ------------------------------------------------------------------ meetings


def _with_meetings(*meetings: dict) -> dict:
    data = _data()
    data["overview"]["upcoming_meetings"] = len(meetings)
    data["meetings"] = list(meetings)
    return data


def _local_noon(year: int, month: int, day: int) -> datetime:
    """Noon on that day here, so the local calendar day is unambiguous."""
    return datetime(year, month, day, 12, 0).astimezone()


def test_upcoming_meetings_fill_the_tile_and_the_list(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    page.show_data(_with_meetings(make_meeting(id=1), make_meeting(id=2, title="Retro")))

    assert page.stat_meetings.value_label.text() == "2"
    assert set(page.meetings_panel.cards) == {1, 2}
    assert page.meetings_panel.cards[2].title_label.full_text == "Retro"


def test_a_server_without_meetings_still_works(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    page.show_data(_data())

    assert page.stat_meetings.value_label.text() == "0"
    assert page.meetings_panel.cards == {}


def test_meeting_days_are_blue_and_shared_days_purple(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    page.show_data(
        _with_meetings(
            make_meeting(id=1, starts=_local_noon(2026, 11, 4)),  # also a deadline
            make_meeting(id=2, starts=_local_noon(2026, 11, 9)),
        )
    )

    shared = page.calendar.dateTextFormat(QDate(2026, 11, 4))
    meeting_only = page.calendar.dateTextFormat(QDate(2026, 11, 9))
    assert shared.background().color() == DEADLINE_AND_MEETING_BACKGROUND
    assert meeting_only.background().color() == MEETING_BACKGROUND
    assert meeting_only.fontWeight() > 400


def test_a_new_load_unmarks_old_meeting_days(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)
    page.show_data(_with_meetings(make_meeting(id=2, starts=_local_noon(2026, 11, 9))))

    page.show_data(_with_meetings())

    assert page.calendar.dateTextFormat(QDate(2026, 11, 9)).fontWeight() <= 400


def test_without_meeting_actions_there_is_no_new_meeting_button(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)

    assert page.new_meeting_button.isHidden()


def test_the_month_arrows_are_text_in_the_themes_colour(qtbot) -> None:
    # Qt's own arrow icons are black, nearly invisible on the dark theme.
    from PySide6.QtWidgets import QToolButton

    page = DashboardPage()
    qtbot.addWidget(page)

    for name, arrow in (("qt_calendar_prevmonth", "‹"), ("qt_calendar_nextmonth", "›")):
        button = page.calendar.findChild(QToolButton, name)
        assert button.text() == arrow
        assert button.icon().isNull()


# ------------------------------------------------------------ exact deadlines


def _due_in(**delta) -> tuple[str, datetime]:
    """An API ``due_at`` this far from now, and the same moment here."""
    moment = (datetime.now().astimezone() + timedelta(**delta)).replace(second=0, microsecond=0)
    return moment.astimezone(UTC).isoformat(), moment


def _task(title: str, due_at: str, moment: datetime) -> dict:
    return {
        "id": hash(title) % 1000,
        "title": title,
        "project_id": 5,
        "project_name": "Website",
        "status": "todo",
        "due_date": moment.date().isoformat(),
        "due_at": due_at,
    }


def test_a_deadline_that_passed_an_hour_ago_is_overdue_even_today(qtbot) -> None:
    from client.views.time_text import show_due

    page = DashboardPage()
    qtbot.addWidget(page)
    past_at, past = _due_in(hours=-1)
    later_at, later = _due_in(days=1)

    page.show_data(
        _data(upcoming=[_task("Passed", past_at, past), _task("Later", later_at, later)])
    )

    lines = [
        page.due_dates_panel.list_widget.item(i).text()
        for i in range(page.due_dates_panel.list_widget.count())
    ]
    passed = show_due({"due_at": past_at}, year=False)
    upcoming = show_due({"due_at": later_at}, year=False)
    assert lines == [f"OVERDUE - {passed}: Passed (Website)", f"{upcoming}: Later (Website)"]
    # Marked on this computer's own day for each deadline.
    for moment in (past, later):
        day = QDate(moment.year, moment.month, moment.day)
        assert page.calendar.dateTextFormat(day).fontWeight() > 400


# ------------------------------------------------------------ selected day


def test_the_selected_day_lists_its_deadlines_and_meetings(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)
    start = datetime(2026, 11, 4, 15, 0).astimezone()
    page.show_data(_with_meetings(make_meeting(starts=start.astimezone(UTC), title="Stand-up")))

    page.calendar.setSelectedDate(QDate(2026, 11, 4))

    text = page.day_label.text()
    assert text.startswith("Wed, Nov 04: ")
    assert "Due end of day: Launch (Website)" in text
    assert "Meeting 3:00 PM" in text and "Stand-up" in text


def test_a_quiet_day_says_so(qtbot) -> None:
    page = DashboardPage()
    qtbot.addWidget(page)
    page.show_data(_data())

    page.calendar.setSelectedDate(QDate(2026, 11, 10))

    assert page.day_label.text() == "Tue, Nov 10: nothing due, no meetings."


def test_team_meetings_are_only_offered_for_teams_youre_on(qtbot) -> None:
    from client.viewmodels.meetings_viewmodel import MeetingsViewModel

    page = DashboardPage(meetings=MeetingsViewModel(client=None))
    qtbot.addWidget(page)
    page.show()

    page._ask_for_team_meeting([{"id": 1, "name": "Alpha", "is_member": False}])

    assert "not on any teams" in page.error_label.text()
