"""Project routes, plus creating and listing the tasks inside a project.

Permission rules live in ``server.services.project_service`` and
``task_service``; refusals become HTTP errors via ``server.api.errors``.
"""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import get_current_user
from server.api.errors import KNOWN_ERRORS, http_error
from server.db.session import get_db
from server.models.user import User
from server.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate, to_project_out
from server.schemas.task import TaskCreate, TaskDetail, TaskOut, to_task_detail, to_task_out
from server.services import project_service, task_service
from shared.statuses import TaskStatus

router = APIRouter(tags=["projects"])


@router.post(
    "/teams/{team_id}/projects",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    team_id: int,
    payload: ProjectCreate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> ProjectOut:
    """Create a project in a team. Team lead or admin only."""
    try:
        project = project_service.create_project(
            db, team_id, current_user, name=payload.name, description=payload.description
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_project_out(project)


@router.get("/teams/{team_id}/projects", response_model=list[ProjectOut])
def list_projects(
    team_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> list[ProjectOut]:
    """The team's projects, active first, each with its task counts."""
    try:
        projects = project_service.list_projects(db, team_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return [to_project_out(project) for project in projects]


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> ProjectOut:
    try:
        project, _ = project_service.get_visible_project(db, project_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_project_out(project)


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> ProjectOut:
    """Rename, re-describe or complete a project. Team lead or admin only."""
    try:
        project = project_service.update_project(
            db, project_id, current_user, payload.model_dump(exclude_unset=True)
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_project_out(project)


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> Response:
    """Delete a project **with all its tasks and subtasks**. Team lead or admin only."""
    try:
        project_service.delete_project(db, project_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/projects/{project_id}/tasks",
    response_model=TaskDetail,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    project_id: int,
    payload: TaskCreate,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TaskDetail:
    """Create a task. Any team member may; the assignee must be on the team."""
    try:
        task = task_service.create_task(
            db,
            project_id,
            current_user,
            title=payload.title,
            description=payload.description,
            assignee_id=payload.assignee_id,
            due_date=payload.due_date,
            status=payload.status,
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_task_detail(task)


@router.get("/projects/{project_id}/tasks", response_model=list[TaskOut])
def list_tasks(
    project_id: int,
    # Named ``task_status`` here because ``status`` is the fastapi module
    # imported above; clients still write ``?status=done``.
    task_status: TaskStatus | None = Query(default=None, alias="status"),  # noqa: B008
    assignee_id: int | None = None,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> list[TaskOut]:
    """The project's tasks, soonest due first. Filter with ``?status=`` and/or
    ``?assignee_id=``.
    """
    try:
        tasks = task_service.list_tasks(
            db, project_id, current_user, status=task_status, assignee_id=assignee_id
        )
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return [to_task_out(task) for task in tasks]
