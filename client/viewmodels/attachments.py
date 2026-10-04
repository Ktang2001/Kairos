"""Attachments for messages: files, images and audio (client side only).

This module covers *choosing* an attachment -- which file types each kind
accepts and how a picked file is described on screen. Uploading and storing
it is not built yet; see ``TODO(attachments)`` in
``client/viewmodels/home_viewmodel.py`` for where that goes.
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class AttachmentKind(StrEnum):
    """The three kinds offered by the Attach menu. The value is what the server will be sent."""

    FILE = "file"
    IMAGE = "image"
    AUDIO = "audio"


#: Shown on the Attach button's menu.
KIND_LABELS: dict[AttachmentKind, str] = {
    AttachmentKind.FILE: "File…",
    AttachmentKind.IMAGE: "Image…",
    AttachmentKind.AUDIO: "Audio…",
}

#: File-picker filters (Qt's "Description (*.ext *.ext)" format).
KIND_FILTERS: dict[AttachmentKind, str] = {
    AttachmentKind.FILE: "All files (*)",
    AttachmentKind.IMAGE: "Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)",
    AttachmentKind.AUDIO: "Audio (*.mp3 *.wav *.ogg *.m4a *.flac *.aac)",
}

#: Small icon in front of the file name in the chip.
KIND_ICONS: dict[AttachmentKind, str] = {
    AttachmentKind.FILE: "📎",
    AttachmentKind.IMAGE: "🖼",
    AttachmentKind.AUDIO: "🎵",
}


def human_size(size_bytes: int) -> str:
    """E.g. 999 -> "999 B", 2048 -> "2 KB", 5_300_000 -> "5.1 MB"."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.0f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


@dataclass(frozen=True)
class PendingAttachment:
    """A file the user picked but hasn't sent yet."""

    path: Path
    kind: AttachmentKind
    size_bytes: int

    @classmethod
    def from_path(cls, path: str | Path, kind: AttachmentKind) -> "PendingAttachment":
        """Raise ValueError (with a message fit to show) if it can't be attached."""
        file = Path(path)
        if not file.exists():
            raise ValueError(f"{file.name} no longer exists.")
        if not file.is_file():
            raise ValueError(f"{file.name} is a folder, not a file.")
        return cls(path=file, kind=kind, size_bytes=file.stat().st_size)

    @property
    def name(self) -> str:
        """The file name without its folder, for display."""
        return self.path.name

    def describe(self) -> str:
        """E.g. "🖼 photo.png (240 KB)"."""
        return f"{KIND_ICONS[self.kind]} {self.name} ({human_size(self.size_bytes)})"
