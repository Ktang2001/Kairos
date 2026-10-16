"""Tests for the Gantt chart widget (client/views/gantt_chart.py), fed with
/gantt responses written by hand, so they don't need a server."""

from datetime import date

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPalette

from client.views.gantt_chart import (
    DAY_WIDTHS,
    DEFAULT_DAY_WIDTH,
    HEADER_HEIGHT,
    LABEL_WIDTH,
    MARGIN_DAYS,
    ROW_HEIGHT,
    GanttChart,
    parse_day,
)

MAX = {"id": 2, "name": "Max", "email": "max@example.com", "role": "member"}


def _row(id_: int, title: str, start: str, end: str, **extra) -> dict:
    row = {
        "kind": "task",
        "id": id_,
        "parent_task_id": None,
        "title": title,
        "status": "todo",
        "assignee": None,
        "start": start,
        "end": end,
        "estimated": False,
        "progress": 0,
        "overdue": False,
        "depends_on": [],
    }
    row.update(extra)
    return row


def _chart(rows: list[dict], *, today: str = "2026-11-05", conflicts=()) -> dict:
    drawn = [r for r in rows if r["start"]]
    return {
        "project_id": 1,
        "project_name": "Website",
        "today": today,
        "range_start": min(r["start"] for r in drawn) if drawn else None,
        "range_end": max(r["end"] for r in drawn) if drawn else None,
        "rows": rows,
        "unscheduled": [],
        "conflicts": [{"task_id": t, "depends_on_id": d} for t, d in conflicts],
    }


@pytest.fixture
def chart(qtbot) -> GanttChart:
    widget = GanttChart()
    qtbot.addWidget(widget)
    return widget


def _sample() -> dict:
    return _chart(
        [
            _row(1, "Design", "2026-11-02", "2026-11-06", status="done", progress=100),
            _row(
                10,
                "Sketch",
                "2026-11-02",
                "2026-11-03",
                kind="subtask",
                parent_task_id=1,
                status="done",
                progress=100,
            ),
            _row(2, "Build", "2026-11-05", "2026-11-12", depends_on=[1], assignee=MAX, progress=50),
            _row(3, "Launch", "2026-11-20", "2026-11-20", estimated=True, overdue=True),
        ],
        conflicts=[(2, 1)],
    )


def test_an_empty_chart_draws_its_message_and_has_no_range(chart: GanttChart) -> None:
    chart.set_chart(None)
    assert chart.first_day is None
    assert chart.rows == []
    chart.grab()  # paints without error
    chart.set_chart(_chart([]))
    assert chart.first_day is None


def test_the_range_has_a_margin_on_each_side(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    assert chart.first_day == date(2026, 10, 31)  # Nov 2 minus MARGIN_DAYS
    assert MARGIN_DAYS == 2
    width = chart.sizeHint().width()
    days = (date(2026, 11, 20) - date(2026, 11, 2)).days + 1 + 2 * MARGIN_DAYS
    assert width == LABEL_WIDTH + days * DEFAULT_DAY_WIDTH + 16
    assert chart.sizeHint().height() == HEADER_HEIGHT + 4 * ROW_HEIGHT + 16


def test_bars_run_from_start_to_end_inclusive(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    design = chart.bar_rect(0)
    # Starts at Nov 2's column and covers five days (Nov 2-6).
    assert design.left() == pytest.approx(chart.x_of(date(2026, 11, 2)) + 1)
    assert design.width() == pytest.approx(5 * DEFAULT_DAY_WIDTH - 2)
    # Each row sits in its own band; subtasks are drawn thinner.
    assert chart.bar_rect(2).top() > chart.bar_rect(1).top() > design.top()
    assert chart.bar_rect(1).height() < design.height()


def test_a_one_day_bar_is_one_column_wide(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    assert chart.bar_rect(3).width() == pytest.approx(DEFAULT_DAY_WIDTH - 2)


def test_dependency_arrows_and_conflicts(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    assert chart.arrows() == [(1, 2, True)]

    no_conflict = _sample()
    no_conflict["conflicts"] = []
    chart.set_chart(no_conflict)
    assert chart.arrows() == [(1, 2, False)]


def test_an_arrow_needs_both_tasks_drawn(chart: GanttChart) -> None:
    data = _chart([_row(2, "Build", "2026-11-05", "2026-11-06", depends_on=[99])])
    chart.set_chart(data)
    assert chart.arrows() == []


def test_the_today_line_is_in_the_middle_of_todays_column(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    assert chart.today_x() == pytest.approx(chart.x_of(date(2026, 11, 5)) + DEFAULT_DAY_WIDTH / 2)


def test_today_is_pulled_into_range_when_close(chart: GanttChart) -> None:
    chart.set_chart(_chart([_row(1, "Later", "2026-11-20", "2026-11-22")], today="2026-11-10"))
    assert chart.first_day == date(2026, 11, 8)
    assert chart.today_x() is not None


def test_today_far_away_is_left_off_the_chart(chart: GanttChart) -> None:
    chart.set_chart(_chart([_row(1, "Later", "2026-11-20", "2026-11-22")], today="2025-01-01"))
    assert chart.today_x() is None


def test_zoom_steps_through_the_day_widths_and_stops_at_the_ends(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    before = chart.sizeHint().width()
    chart.zoom(1)
    assert chart.day_width == DAY_WIDTHS[DAY_WIDTHS.index(DEFAULT_DAY_WIDTH) + 1]
    assert chart.sizeHint().width() > before
    for _ in range(10):
        chart.zoom(-1)
    assert chart.day_width == DAY_WIDTHS[0]
    for _ in range(10):
        chart.zoom(1)
    assert chart.day_width == DAY_WIDTHS[-1]


def test_hover_text_describes_the_bar(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    build = chart.describe(2)
    assert "Build" in build
    assert "Nov 05 - Nov 12" in build
    assert "In progress" not in build  # status is "todo" in the sample
    assert "50% done" in build
    assert "Assigned to Max" in build
    launch = chart.describe(3)
    assert "only one date set" in launch
    assert "Overdue" in launch
    assert "Unassigned" in launch


def test_row_at_finds_the_bar_under_the_pointer(chart: GanttChart) -> None:
    chart.set_chart(_sample())
    assert chart.row_at(chart.bar_rect(2).center()) == 2
    assert chart.row_at(QPointF(5, 5)) is None


def test_clicking_a_bar_opens_its_task_and_a_subtask_opens_its_parent(qtbot, chart) -> None:
    chart.set_chart(_sample())
    chart.resize(chart.sizeHint())
    chart.show()
    with qtbot.waitSignal(chart.task_clicked) as clicked:
        qtbot.mouseClick(chart, Qt.MouseButton.LeftButton, pos=chart.bar_rect(2).center().toPoint())
    assert clicked.args == [2]
    with qtbot.waitSignal(chart.task_clicked) as clicked:
        qtbot.mouseClick(chart, Qt.MouseButton.LeftButton, pos=chart.bar_rect(1).center().toPoint())
    assert clicked.args == [1]


def test_hovering_over_bars_and_empty_space_does_not_fail(qtbot, chart) -> None:
    chart.set_chart(_sample())
    chart.resize(chart.sizeHint())
    chart.show()
    qtbot.mouseMove(chart, chart.bar_rect(0).center().toPoint())
    qtbot.mouseMove(chart, QPointF(3, 3).toPoint())


@pytest.mark.parametrize("dark", [False, True])
def test_paints_in_light_and_dark_themes_at_every_zoom(chart: GanttChart, dark: bool) -> None:
    if dark:
        palette = chart.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#eeeeee"))
        chart.setPalette(palette)
    chart.set_chart(_sample())
    for _ in DAY_WIDTHS:
        image = chart.grab()
        assert not image.isNull()
        chart.zoom(-1)


def test_parse_day() -> None:
    assert parse_day("2026-11-02") == date(2026, 11, 2)
    assert parse_day(date(2026, 1, 1)) == date(2026, 1, 1)
    assert parse_day(None) is None


# ---------------------------------------------- extreme dates (stress test)


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("0001-01-01", "0001-01-02"),
        ("9999-12-30", "9999-12-31"),
        ("0001-01-01", "9999-12-31"),
        ("1900-01-01", "2199-12-31"),
    ],
)
def test_extreme_dates_never_crash_the_chart(chart: GanttChart, start: str, end: str) -> None:
    """Found by stress testing: a year-1 task raised OverflowError and broke the page."""
    from client.views.gantt_chart import MAX_DAYS

    chart.set_chart(_chart([_row(1, "Edge", start, end)], today="2026-10-15"))
    assert chart.sizeHint().width() <= LABEL_WIDTH + MAX_DAYS * DEFAULT_DAY_WIDTH + 16
    rect = chart.bar_rect(0)
    assert rect.right() <= chart.sizeHint().width()
    chart.resize(2000, 300)
    assert not chart.grab().isNull()
    chart.describe(0)
