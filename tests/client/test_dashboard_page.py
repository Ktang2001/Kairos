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
