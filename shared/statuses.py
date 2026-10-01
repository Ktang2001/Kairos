"""Status values shared by the FastAPI backend and the Qt client.

``StrEnum`` so each member *is* its string value: it is stored in the database
as plain text ("todo", "done", ...), serialises to JSON as that text, and
Pydantic rejects anything that is not one of the listed values.
"""

from enum import StrEnum


class TaskStatus(StrEnum):
    """Where a task or subtask is. Fixed on purpose: every dashboard number is
    a count of one of these, so a free-text status would make them ambiguous.
    """

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class ProjectStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"


#: Labels for display in the Qt client.
TASK_STATUS_DISPLAY_NAMES: dict[TaskStatus, str] = {
    TaskStatus.TODO: "To do",
    TaskStatus.IN_PROGRESS: "In progress",
    TaskStatus.DONE: "Done",
}
