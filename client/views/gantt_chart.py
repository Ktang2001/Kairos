"""The Gantt chart: draws GET /projects/{id}/gantt (server/schemas/gantt.py).

One row per scheduled task, with its dated subtasks indented under it. Each bar
runs from its start day to its end day (both inclusive) and is filled to the
task's progress. On top of the bars:

* a dashed red line for today;
* an arrow from each task a task waits on to that task -- red when the dates
  are out of order (the server's ``conflicts``);
* a red outline on overdue bars, a dashed outline on "estimated" bars (a task
  with only one of its two dates, drawn as a single day).

Hovering a bar shows its details; clicking a bar emits ``task_clicked`` with
the task's id (a subtask's parent task), so the screen can open it.

Painted by hand with QPainter rather than with a charting library: no new
dependency, and every colour comes from the current theme's palette except the
status colours, which are mid-tones readable on light and dark backgrounds.
"""

from datetime import date, timedelta

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QToolTip, QWidget

LABEL_WIDTH = 220
HEADER_HEIGHT = 44
ROW_HEIGHT = 28
#: Pixels per day at each zoom step (the view's zoom buttons move along this list).
DAY_WIDTHS = (8, 14, 24, 36)
DEFAULT_DAY_WIDTH = 24
#: Blank days drawn before the first bar and after the last.
MARGIN_DAYS = 2
#: Today is pulled into the chart's range if it is within this many days of it.
TODAY_REACH_DAYS = 30

STATUS_COLOURS = {
    "todo": QColor("#7d8fa8"),
    "in_progress": QColor("#3b82f6"),
    "done": QColor("#22a06b"),
}
ALERT_RED = QColor("#e5484d")

STATUS_LABELS = {"todo": "To do", "in_progress": "In progress", "done": "Done"}


def parse_day(value: str | date | None) -> date | None:
    """An API date ("2026-11-02") as a ``date``; None stays None."""
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(value)


class GanttChart(QWidget):
    """Draws one project's chart. Call ``set_chart`` with the API response."""

    #: A bar was clicked: the task's id (for a subtask, its parent task's id).
    task_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMouseTracking(True)
        self._rows: list[dict] = []
        self._conflicts: set[tuple[int, int]] = set()
        self._today: date | None = None
        self._first_day: date | None = None
        self._days = 0
        self._day_width = DEFAULT_DAY_WIDTH

    # ---------------------------------------------------------------- data

    def set_chart(self, chart: dict | None) -> None:
        """Show ``chart`` (the /gantt response), or nothing when None."""
        self._rows = list(chart["rows"]) if chart else []
        self._conflicts = {
            (c["task_id"], c["depends_on_id"]) for c in (chart["conflicts"] if chart else [])
        }
        self._today = parse_day(chart["today"]) if chart else None
        self._first_day, self._days = self._date_range(chart)
        self.updateGeometry()
        self.update()

    def _date_range(self, chart: dict | None) -> tuple[date | None, int]:
        """The first day drawn and how many days are drawn."""
        if not chart or not chart["rows"]:
            return None, 0
        first = parse_day(chart["range_start"])
        last = parse_day(chart["range_end"])
        today = self._today
        if today is not None:
            if first - timedelta(days=TODAY_REACH_DAYS) <= today < first:
                first = today
            if last < today <= last + timedelta(days=TODAY_REACH_DAYS):
                last = today
        first -= timedelta(days=MARGIN_DAYS)
        last += timedelta(days=MARGIN_DAYS)
        return first, (last - first).days + 1

    @property
    def rows(self) -> list[dict]:
        """The rows being drawn, top to bottom."""
        return self._rows

    @property
    def first_day(self) -> date | None:
        """The leftmost day drawn, or None when the chart is empty."""
        return self._first_day

    # ---------------------------------------------------------------- zoom

    @property
    def day_width(self) -> int:
        """Pixels per day."""
        return self._day_width

    def zoom(self, steps: int) -> None:
        """Zoom in (positive) or out (negative) along ``DAY_WIDTHS``."""
        index = DAY_WIDTHS.index(self._day_width) if self._day_width in DAY_WIDTHS else 2
        index = max(0, min(len(DAY_WIDTHS) - 1, index + steps))
        self._day_width = DAY_WIDTHS[index]
        self.updateGeometry()
        self.update()

    # ------------------------------------------------------------ geometry

    def sizeHint(self) -> QSize:
        """Wide enough for every day and tall enough for every row (for the scroll area)."""
        width = LABEL_WIDTH + self._days * self._day_width + 16
        height = HEADER_HEIGHT + max(1, len(self._rows)) * ROW_HEIGHT + 16
        return QSize(width, height)

    def minimumSizeHint(self) -> QSize:
        """Same as ``sizeHint``: the scroll area scrolls rather than squashing the chart."""
        return self.sizeHint()

    def x_of(self, day: date) -> float:
        """The left edge of ``day``'s column."""
        assert self._first_day is not None
        return LABEL_WIDTH + (day - self._first_day).days * self._day_width

    def today_x(self) -> float | None:
        """Where the today line is drawn (the middle of today's column), or None
        when today is outside the chart."""
        if self._today is None or self._first_day is None:
            return None
        offset = (self._today - self._first_day).days
        if not 0 <= offset < self._days:
            return None
        return self.x_of(self._today) + self._day_width / 2

    def bar_rect(self, index: int) -> QRectF:
        """The bar for row ``index``."""
        row = self._rows[index]
        start, end = parse_day(row["start"]), parse_day(row["end"])
        inset = 9 if row["kind"] == "subtask" else 6
        top = HEADER_HEIGHT + index * ROW_HEIGHT + inset
        left = self.x_of(start)
        width = ((end - start).days + 1) * self._day_width
        return QRectF(left + 1, top, max(2.0, width - 2), ROW_HEIGHT - 2 * inset)

    def arrows(self) -> list[tuple[int, int, bool]]:
        """``(from_task_id, to_task_id, out_of_order)`` for every dependency
        whose two tasks are both drawn."""
        drawn = {row["id"] for row in self._rows if row["kind"] == "task"}
        found = []
        for row in self._rows:
            if row["kind"] != "task":
                continue
            for other in row["depends_on"]:
                if other in drawn:
                    found.append((other, row["id"], (row["id"], other) in self._conflicts))
        return found

    def row_at(self, point: QPointF) -> int | None:
        """The index of the row whose bar is under ``point``, or None."""
        for index in range(len(self._rows)):
            if self.bar_rect(index).adjusted(-2, -3, 2, 3).contains(point):
                return index
        return None

    # ------------------------------------------------------------- drawing

    def paintEvent(self, event: QPaintEvent) -> None:
        """Draw the whole chart."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        if self._first_day is None:
            painter.setPen(palette.placeholderText().color())
            painter.drawText(
                self.rect().adjusted(16, 16, -16, -16),
                Qt.AlignmentFlag.AlignLeft | Qt.TextFlag.TextWordWrap,
                "Nothing scheduled yet. Give tasks a start or due date and they appear here.",
            )
            painter.end()
            return
        self._draw_grid(painter)
        self._draw_labels(painter)
        self._draw_bars(painter)
        self._draw_arrows(painter)
        self._draw_today(painter)
        painter.end()

    def _grid_colour(self) -> QColor:
        """A faint line colour from the theme's text colour."""
        colour = QColor(self.palette().text().color())
        colour.setAlpha(40)
        return colour

    def _draw_grid(self, painter: QPainter) -> None:
        """Weekend shading, day and month labels, and the row lines."""
        palette = self.palette()
        bottom = HEADER_HEIGHT + len(self._rows) * ROW_HEIGHT
        weekend = QColor(palette.text().color())
        weekend.setAlpha(14)
        painter.setPen(palette.text().color())
        for offset in range(self._days):
            day = self._first_day + timedelta(days=offset)
            x = self.x_of(day)
            if day.weekday() >= 5:
                painter.fillRect(QRectF(x, HEADER_HEIGHT, self._day_width, bottom), weekend)
            if day.day == 1 or offset == 0:
                painter.drawText(QPointF(x + 2, 16), day.strftime("%b %Y"))
            # Day numbers when there is room; otherwise Mondays only.
            if self._day_width >= 20 or day.weekday() == 0:
                painter.drawText(
                    QRectF(x, 22, max(self._day_width, 20), 18),
                    Qt.AlignmentFlag.AlignLeft,
                    str(day.day),
                )
        painter.setPen(QPen(self._grid_colour(), 1))
        right = LABEL_WIDTH + self._days * self._day_width
        painter.drawLine(QPointF(0, HEADER_HEIGHT), QPointF(right, HEADER_HEIGHT))
        for index in range(1, len(self._rows) + 1):
            y = HEADER_HEIGHT + index * ROW_HEIGHT
            painter.drawLine(QPointF(0, y), QPointF(right, y))
        painter.drawLine(QPointF(LABEL_WIDTH, 0), QPointF(LABEL_WIDTH, bottom))

    def _draw_labels(self, painter: QPainter) -> None:
        """Each row's title in the left column (subtasks indented), cut short if too long."""
        metrics = painter.fontMetrics()
        for index, row in enumerate(self._rows):
            indent = 22 if row["kind"] == "subtask" else 8
            colour = self.palette().text().color()
            if row["kind"] == "subtask":
                colour = self.palette().placeholderText().color()
            painter.setPen(colour)
            text = metrics.elidedText(
                row["title"], Qt.TextElideMode.ElideRight, LABEL_WIDTH - indent - 8
            )
            painter.drawText(
                QRectF(
                    indent, HEADER_HEIGHT + index * ROW_HEIGHT, LABEL_WIDTH - indent, ROW_HEIGHT
                ),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                text,
            )

    def _draw_bars(self, painter: QPainter) -> None:
        """Each bar: a pale track, the done part solid, and its outline."""
        for index, row in enumerate(self._rows):
            rect = self.bar_rect(index)
            colour = STATUS_COLOURS.get(row["status"], STATUS_COLOURS["todo"])
            track = QColor(colour)
            track.setAlpha(80)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(rect, 3, 3)
            if row["progress"] > 0:
                done = QRectF(rect)
                done.setWidth(rect.width() * row["progress"] / 100)
                painter.setBrush(colour)
                painter.drawRoundedRect(done, 3, 3)
            if row["overdue"]:
                pen = QPen(ALERT_RED, 2)
            else:
                pen = QPen(colour.darker(130), 1)
            if row["estimated"]:
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect, 3, 3)

    def _draw_arrows(self, painter: QPainter) -> None:
        """An elbow arrow from the end of each prerequisite to the start of the task waiting on it."""
        index_of = {row["id"]: i for i, row in enumerate(self._rows) if row["kind"] == "task"}
        normal = QColor(self.palette().text().color())
        normal.setAlpha(150)
        for from_id, to_id, out_of_order in self.arrows():
            source = self.bar_rect(index_of[from_id])
            target = self.bar_rect(index_of[to_id])
            start = QPointF(source.right(), source.center().y())
            end = QPointF(target.left(), target.center().y())
            elbow_x = start.x() + 6
            path = QPainterPath(start)
            path.lineTo(elbow_x, start.y())
            path.lineTo(elbow_x, end.y())
            path.lineTo(end)
            colour = ALERT_RED if out_of_order else normal
            painter.setPen(QPen(colour, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
            head = QPainterPath(end)
            head.lineTo(end.x() - 6, end.y() - 4)
            head.lineTo(end.x() - 6, end.y() + 4)
            head.closeSubpath()
            painter.setBrush(colour)
            painter.drawPath(head)

    def _draw_today(self, painter: QPainter) -> None:
        """A dashed red line down today's column."""
        x = self.today_x()
        if x is None:
            return
        pen = QPen(ALERT_RED, 1.5)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        bottom = HEADER_HEIGHT + len(self._rows) * ROW_HEIGHT
        painter.drawLine(QPointF(x, 4), QPointF(x, bottom))

    # ---------------------------------------------------------- interaction

    def describe(self, index: int) -> str:
        """The hover text for row ``index``: what, when, who, how far along."""
        row = self._rows[index]
        start, end = parse_day(row["start"]), parse_day(row["end"])
        when = start.strftime("%b %d") if start == end else f"{start:%b %d} - {end:%b %d}"
        if row["estimated"]:
            when += " (only one date set)"
        lines = [
            row["title"],
            when,
            f"{STATUS_LABELS.get(row['status'], row['status'])}, {row['progress']}% done",
            f"Assigned to {row['assignee']['name']}" if row["assignee"] else "Unassigned",
        ]
        if row["overdue"]:
            lines.append("Overdue")
        return "\n".join(lines)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """Show the hovered bar's details."""
        index = self.row_at(event.position())
        if index is None:
            QToolTip.hideText()
        else:
            QToolTip.showText(event.globalPosition().toPoint(), self.describe(index), self)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """Clicking a bar opens its task."""
        index = self.row_at(event.position())
        if index is not None and event.button() == Qt.MouseButton.LeftButton:
            row = self._rows[index]
            self.task_clicked.emit(row["parent_task_id"] or row["id"])
        super().mousePressEvent(event)
