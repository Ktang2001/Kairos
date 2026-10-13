"""Routes for a single task and for subtasks.

Creating and listing tasks lives under ``/projects/{id}/tasks`` in
``server.api.projects``. Permission rules live in ``task_service``.

Subtask routes return the *parent task*, so after any subtask change the
client gets the task's updated progress (``subtasks_done``/``subtasks_total``)
in the same response.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import get_current_user
from server.api.errors import KNOWN_ERRORS, http_error
from server.db.session import get_db
from server.models.user import User
from server.schemas.task import (
    DependencyIn,
    SubtaskCreate,
    SubtaskUpdate,
    TaskDetail,
    TaskUpdate,
    to_task_detail,
)
from server.services import task_service

router = APIRouter(tags=["tasks"])


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(
    task_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TaskDetail:
    try:
        task, _ = task_service.get_visible_task(db, task_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_task_detail(task)


@router.patch("/tasks/{task_id}", response_model=TaskDetail)
def update_task(
    task_id: int,
    payload: TaskUpdate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TaskDetail:
    """Change any of title, description, assignee, start date, due date, status.

    Fields left out are unchanged; ``null`` clears ``assignee_id``,
    ``start_date``, ``due_date`` or ``description``.
    """
    try:
        task = task_service.update_task(
            db, task_id, current_user, payload.model_dump(exclude_unset=True)
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_task_detail(task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> Response:
    """Delete a task and its subtasks. Team lead or admin only."""
    try:
        task_service.delete_task(db, task_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/tasks/{task_id}/dependencies",
    response_model=TaskDetail,
    status_code=status.HTTP_201_CREATED,
)
def add_dependency(
    task_id: int,
    payload: DependencyIn,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TaskDetail:
    """Make this task wait on another task in the same project (a Gantt arrow).

    Refused with 422 if the other task is in another project, and 409 if the
    link would form a loop.
    """
    try:
        task = task_service.add_dependency(
            db, task_id, current_user, depends_on_id=payload.depends_on_id
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_task_detail(task)


@router.delete("/tasks/{task_id}/dependencies/{depends_on_id}", response_model=TaskDetail)
def remove_dependency(
    task_id: int,
    depends_on_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TaskDetail:
    """Remove a dependency. Returns the task with its remaining ``depends_on``."""
    try:
        task = task_service.remove_dependency(
            db, task_id, current_user, depends_on_id=depends_on_id
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_task_detail(task)


@router.post(
    "/tasks/{task_id}/subtasks",
    response_model=TaskDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_subtask(
    task_id: int,
    payload: SubtaskCreate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TaskDetail:
    """Add a subtask. Returns the parent task with its subtasks."""
    try:
        task = task_service.create_subtask(
            db,
            task_id,
            current_user,
            title=payload.title,
            assignee_id=payload.assignee_id,
            start_date=payload.start_date,
            due_date=payload.due_date,
            status=payload.status,
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_task_detail(task)


@router.patch("/subtasks/{subtask_id}", response_model=TaskDetail)
def update_subtask(
    subtask_id: int,
    payload: SubtaskUpdate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TaskDetail:
    """Change a subtask. Returns the parent task with its subtasks."""
    try:
        task = task_service.update_subtask(
            db, subtask_id, current_user, payload.model_dump(exclude_unset=True)
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_task_detail(task)


@router.delete("/subtasks/{subtask_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_subtask(
    subtask_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> Response:
    """Delete a subtask. Team lead or admin only."""
    try:
        task_service.delete_subtask(db, subtask_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)
