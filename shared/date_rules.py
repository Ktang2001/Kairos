"""The range of dates a task or subtask may have.

Found by stress testing: the server accepted any date Python can hold (year 1
to 9999). A task dated in year 1 crashed the Gantt chart for everyone on the
project (there are no days before it to draw a margin with), and the client's
date picker can't show dates before 1752, so editing such a task silently
changed its date. A class-project planner has no use for dates outside this
range, and every screen can show all of it.

Used by the server's request checks and the client's date pickers, so both
agree (shared/ is imported by each).
"""

from datetime import date

EARLIEST_TASK_DATE = date(1900, 1, 1)
LATEST_TASK_DATE = date(2199, 12, 31)

#: The message both sides show for a date outside the range.
DATE_RANGE_MESSAGE = f"Dates must be between {EARLIEST_TASK_DATE.year} and {LATEST_TASK_DATE.year}."


def date_in_range(value: date | None) -> bool:
    """True for no date, or a date inside the allowed range."""
    return value is None or EARLIEST_TASK_DATE <= value <= LATEST_TASK_DATE
