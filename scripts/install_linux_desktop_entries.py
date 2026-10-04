#!/usr/bin/env python3
"""Install Linux desktop entries (.desktop files) for Kairos, so the client and
host windows get a real taskbar/app-switcher icon - not just a title-bar one.

QApplication.setWindowIcon() alone isn't enough under Wayland: compositors look
up the taskbar icon via the window's app_id matching an installed .desktop
file's Icon= entry, which is why client/main.py and server/gui.py also call
setDesktopFileName() with the same ids used here (kairos-client / kairos-server).

User-scoped only (writes to ~/.local/share/applications/) - no root needed.
Paths are computed from this script's own location, so it's safe to run from any
checkout (your machine, a teammate's) without hardcoding anyone's home directory.
Safe to re-run - it only overwrites the two files it creates itself.

Windows/macOS: this script is a no-op there; those platforms get their taskbar
icon from the packaged app/exe instead, which is still an open question (see
context.md's Open Questions section on packaging/distribution).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = REPO_ROOT / ".venv" / "bin" / "python"
ICON = REPO_ROOT / "client" / "resources" / "kairos.svg"
APPLICATIONS_DIR = Path.home() / ".local" / "share" / "applications"

# (desktop file id, display name, module to run) - ids must match the
# setDesktopFileName() calls in client/main.py and server/gui.py.
ENTRIES = [
    ("kairos-client", "Kairos", "client.main"),
    ("kairos-server", "Kairos Server", "server.gui"),
]


def main() -> None:
    if sys.platform != "linux":
        print("Not on Linux - nothing to install here (see this script's docstring).")
        return

    if not PYTHON.exists():
        raise SystemExit(f"No venv python found at {PYTHON} - create the venv first.")
    if not ICON.exists():
        raise SystemExit(f"Icon not found at {ICON}.")

    APPLICATIONS_DIR.mkdir(parents=True, exist_ok=True)

    for desktop_id, display_name, module in ENTRIES:
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={display_name}\n"
            f"Exec={PYTHON} -m {module}\n"
            f"Path={REPO_ROOT}\n"
            f"Icon={ICON}\n"
            "Terminal=false\n"
            "Categories=Office;\n"
        )
        target = APPLICATIONS_DIR / f"{desktop_id}.desktop"
        target.write_text(content)
        target.chmod(0o755)
        print(f"Wrote {target}")

    print(
        "\nDone. If your taskbar doesn't pick it up immediately, try restarting "
        "the app, or (rarely needed) logging out and back in."
    )


if __name__ == "__main__":
    main()
