"""The admin Users screen, without any widgets (context.md goal #2).

Lists every account and changes roles. The server allows this for admins
only and never for your own account; the screen hides it accordingly, but
the server's answer is what counts.
"""

from PySide6.QtCore import QObject, Signal

from client.viewmodels.background import BackgroundRunner
from client.viewmodels.login_viewmodel import Session


class UsersViewModel(QObject):
    users_changed = Signal(list)
    busy_changed = Signal(bool)
    #: The message to show, or "" to clear it.
    error_changed = Signal(str)

    def __init__(
        self,
        session: Session,
        runner: BackgroundRunner | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._runner = runner or BackgroundRunner(self)
        self._busy = False
        self.users: list[dict] = []
        #: False until the first load finishes ("Loading..." until then).
        self.loaded = False

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def my_id(self) -> int:
        return self.session.user["id"]

    def refresh(self) -> None:
        self._run(None)

    def set_role(self, user_id: int, role: str) -> None:
        current = next((u for u in self.users if u["id"] == user_id), None)
        if current is not None and current["role"] == role:
            return
        self._run(lambda client: client.set_role(user_id, role))

    def _run(self, action) -> None:
        if self._busy:
            return
        client = self.session.client

        def job() -> list[dict]:
            if action is not None:
                action(client)
            return client.list_users()

        self.error_changed.emit("")
        self._set_busy(True)
        self._runner.run(job, on_success=self._loaded, on_error=self._failed)

    def _loaded(self, users: list[dict]) -> None:
        self.loaded = True
        self._set_busy(False)
        self.users = users
        self.users_changed.emit(users)

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.error_changed.emit(message)
        # Re-show the server's real roles, so a refused change snaps back.
        self.users_changed.emit(self.users)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
