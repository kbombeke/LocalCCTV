import json
import os
import re
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

CONFIG_PATH = Path(os.path.expanduser("~")) / ".config" / "hometv" / "cameras.json"

MAX_CAMERAS = 16
DEFAULT_CAMERA_COUNT = 6

DEFAULT_CAMERA = {
    "name": "",
    "url": "",
}


def load_config() -> list[dict]:
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            data = json.load(f)
        # Migrate old format: if entries have "host" key, convert to url-only
        migrated = []
        for cam in data:
            if "host" in cam and "url" not in cam:
                migrated.append({"name": cam.get("name", ""), "url": ""})
            else:
                migrated.append(cam)
        return migrated[:MAX_CAMERAS]
    return [dict(DEFAULT_CAMERA) for _ in range(DEFAULT_CAMERA_COUNT)]


def save_config(cameras: list[dict]):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cameras, f, indent=2)


def get_rtsp_url(cam: dict) -> str:
    return cam.get("url", "").strip()


def derive_substream_url(url: str) -> str:
    """Derive a lower-bandwidth sub-stream URL from a main stream URL.

    Supports Hikvision, Dahua/Amcrest, Reolink, and generic patterns.
    Returns empty string if no sub-stream pattern is recognised.
    """
    if not url:
        return ""

    # Hikvision: /Streaming/Channels/101 -> /Streaming/Channels/102
    m = re.search(r"(/Streaming/Channels/)(\d+)", url, re.IGNORECASE)
    if m:
        ch = m.group(2)
        if ch.endswith("01"):
            return url[: m.start(2)] + ch[:-1] + "2" + url[m.end(2) :]

    # Dahua/Amcrest: subtype=0 -> subtype=1
    if re.search(r"subtype=0", url, re.IGNORECASE):
        return re.sub(r"subtype=0", "subtype=1", url, flags=re.IGNORECASE)

    # Reolink: _main -> _sub
    if re.search(r"_main", url, re.IGNORECASE):
        return re.sub(r"_main", "_sub", url, flags=re.IGNORECASE)

    # Generic: /stream1 -> /stream2
    if re.search(r"/stream1", url, re.IGNORECASE):
        return re.sub(r"/stream1", "/stream2", url, flags=re.IGNORECASE)

    # Dahua cam/realmonitor without subtype
    if re.search(r"/cam/realmonitor", url, re.IGNORECASE) and "subtype" not in url.lower():
        sep = "&" if "?" in url else "?"
        return url + sep + "subtype=1"

    return ""


class CameraConfigWidget(QGroupBox):
    def __init__(self, index: int, cam: dict, parent=None):
        super().__init__(f"Camera {index + 1}", parent)
        self.index = index
        layout = QFormLayout(self)

        self.name_edit = QLineEdit(cam.get("name", ""))
        self.name_edit.setPlaceholderText(f"Camera {index + 1}")
        layout.addRow("Name:", self.name_edit)

        self.url_edit = QLineEdit(cam.get("url", ""))
        self.url_edit.setPlaceholderText("rtsp://user:pass@192.168.1.100:554/stream1")
        layout.addRow("RTSP URL:", self.url_edit)

    def to_dict(self) -> dict:
        return {
            "name": self.name_edit.text(),
            "url": self.url_edit.text().strip(),
        }


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Camera Settings")
        self.setMinimumWidth(550)
        self.setMinimumHeight(500)

        layout = QVBoxLayout(self)

        info = QLabel(
            f"Configure up to {MAX_CAMERAS} cameras. Enter the full RTSP URL for each. "
            "Leave a URL empty to disable that slot — the viewer grid rescales "
            "automatically to the number of cameras you define."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QWidget()
        scroll_layout = QVBoxLayout(scroll_widget)

        cameras = load_config()
        while len(cameras) < MAX_CAMERAS:
            cameras.append(dict(DEFAULT_CAMERA))

        self.camera_widgets: list[CameraConfigWidget] = []
        for i in range(MAX_CAMERAS):
            w = CameraConfigWidget(i, cameras[i])
            self.camera_widgets.append(w)
            scroll_layout.addWidget(w)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_widget)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save_and_accept(self):
        cameras = [w.to_dict() for w in self.camera_widgets]
        save_config(cameras)
        self.accept()
