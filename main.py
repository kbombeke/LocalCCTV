#!/usr/bin/env python3
"""HomeTV - Multi-camera RTSP viewer using libVLC."""

import math
import os
import sys
import platform
import tempfile

import vlc
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGridLayout,
    QLabel,
    QMainWindow,
    QVBoxLayout,
    QWidget,
)

from settings_dialog import SettingsDialog, derive_substream_url, get_rtsp_url, load_config

SNAPSHOT_DIR = tempfile.mkdtemp(prefix="hometv_")
MAX_RECONNECT_DELAY = 30  # seconds
HEALTH_CHECK_INTERVAL = 3000  # ms
SNAPSHOT_INTERVAL = 10000  # ms
CONNECTION_TIMEOUT = 10000  # ms


def _grid_dims(n: int) -> tuple[int, int]:
    """Return (rows, cols) for an n-camera grid, kept as square as possible."""
    if n <= 1:
        return 1, 1
    cols = math.ceil(math.sqrt(n))
    rows = math.ceil(n / cols)
    return rows, cols


def _vlc_instance_args():
    """Return VLC instance arguments.

    Frozen builds locate the bundled plugins via VLC_PLUGIN_PATH, set by
    hook-vlc.py at startup — VLC 3 removed the --plugin-path option.
    """
    return ["--no-xlib", "--quiet", "--no-video-title-show"]


class CameraView(QFrame):
    """A single camera viewport backed by a VLC media player."""

    def __init__(self, index: int, vlc_instance: vlc.Instance, parent=None):
        super().__init__(parent)
        self.index = index
        self.vlc_instance = vlc_instance
        self.player: vlc.MediaPlayer | None = None

        self._url = ""
        self._sub_url = ""
        self._using_sub = False
        self._sub_confirmed = False  # True once sub-stream has played successfully
        self._sub_attempted = False  # True once we've tried the sub-stream at all
        self._reconnect_count = 0
        self._snapshot_path = os.path.join(SNAPSHOT_DIR, f"cam_{index}.png")
        self._has_snapshot = False
        self._playing_confirmed = False

        self.setMinimumSize(320, 240)
        self.setStyleSheet("background-color: #1a1a1a; border: 1px solid #333;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Video surface — VLC renders directly into this widget
        self.video_widget = QWidget(self)
        self.video_widget.setStyleSheet("background-color: black;")
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        layout.addWidget(self.video_widget)

        # Snapshot fallback — shown when stream drops but we have a last good frame
        self.snapshot_label = QLabel(self)
        self.snapshot_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.snapshot_label.setScaledContents(True)
        self.snapshot_label.setStyleSheet("background-color: #1a1a1a;")
        self.snapshot_label.hide()

        # Overlay label for status messages
        self.status_label = QLabel(self)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setStyleSheet(
            "color: #666; font-size: 14px; background-color: transparent;"
        )
        self.status_label.setText("No camera configured")

        # Health check timer — polls VLC player state
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(HEALTH_CHECK_INTERVAL)
        self._health_timer.timeout.connect(self._check_health)

        # Snapshot timer — captures a fallback frame periodically
        self._snapshot_timer = QTimer(self)
        self._snapshot_timer.setInterval(SNAPSHOT_INTERVAL)
        self._snapshot_timer.timeout.connect(self._take_snapshot)

        # Reconnect timer (single-shot with backoff)
        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setSingleShot(True)
        self._reconnect_timer.timeout.connect(self._reconnect)

        # Connection timeout (single-shot)
        self._timeout_timer = QTimer(self)
        self._timeout_timer.setSingleShot(True)
        self._timeout_timer.timeout.connect(self._on_connection_timeout)

        # Deferred switch from main to sub-stream (single-shot). Owned by this
        # widget so it dies with the view instead of firing on a deleted object.
        self._sub_switch_timer = QTimer(self)
        self._sub_switch_timer.setSingleShot(True)
        self._sub_switch_timer.timeout.connect(lambda: self._connect(prefer_sub=True))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.status_label.setGeometry(self.rect())
        self.snapshot_label.setGeometry(self.rect())

    # -- public API --

    def play(self, url: str, sub_url: str = ""):
        """Start streaming. Connects with the main URL first, switches to
        the sub-stream (lower bandwidth) on subsequent reconnects once the
        main stream has proven reachable."""
        self.stop()
        self._url = url
        self._sub_url = sub_url
        self._sub_confirmed = False
        self._sub_attempted = False
        self._reconnect_count = 0
        # Always start with the main URL — it's the one the user configured
        self._connect(prefer_sub=False)

    def stop(self):
        self._health_timer.stop()
        self._snapshot_timer.stop()
        self._reconnect_timer.stop()
        self._timeout_timer.stop()
        self._sub_switch_timer.stop()
        self._stop_player()

    def set_status(self, text: str):
        self.status_label.setText(text)
        self.status_label.show()

    # -- connection management --

    def _connect(self, prefer_sub: bool = True):
        """Create a VLC player and start playback."""
        if prefer_sub and self._sub_url:
            active_url = self._sub_url
            self._using_sub = True
        else:
            active_url = self._url
            self._using_sub = False

        if not active_url:
            return

        self._stop_player()
        self.snapshot_label.hide()
        self.video_widget.show()
        self.status_label.setText("Connecting...")
        self.status_label.show()
        self._playing_confirmed = False

        media = self.vlc_instance.media_new(active_url)
        media.add_option(":network-caching=1500")
        media.add_option(":live-caching=1500")
        media.add_option(":rtsp-tcp")

        self.player = self.vlc_instance.media_player_new()
        self.player.set_media(media)

        win_id = int(self.video_widget.winId())
        if platform.system() == "Darwin":
            self.player.set_nsobject(win_id)
        else:
            self.player.set_xwindow(win_id)

        self.player.play()
        self._health_timer.start()
        self._snapshot_timer.start()
        self._timeout_timer.start(CONNECTION_TIMEOUT)

    def _stop_player(self):
        if self.player is not None:
            self.player.stop()
            self.player.release()
            self.player = None

    # -- health monitoring --

    def _check_health(self):
        """Poll VLC state and react to failures."""
        if self.player is None:
            return

        state = self.player.get_state()

        if state == vlc.State.Playing:
            if not self._playing_confirmed:
                self._playing_confirmed = True
                self._timeout_timer.stop()
                self.status_label.hide()
                self.snapshot_label.hide()
                self.video_widget.show()
                self._reconnect_count = 0
                if self._using_sub:
                    self._sub_confirmed = True
                # Main stream works — probe the sub-stream once to save
                # bandwidth. Guarded by _sub_attempted rather than
                # _sub_confirmed: a sub-stream that fails must never be
                # retried from here, or main and sub alternate forever.
                elif self._sub_url and not self._sub_attempted:
                    self._sub_attempted = True
                    self._sub_switch_timer.start(2000)
            return

        if state in (vlc.State.Error, vlc.State.Ended, vlc.State.Stopped):
            self._schedule_reconnect()

    def _on_connection_timeout(self):
        """Fired when the stream hasn't started playing within the timeout."""
        if not self._playing_confirmed:
            self._schedule_reconnect()

    def _schedule_reconnect(self):
        """Show fallback snapshot and queue a reconnect attempt."""
        self._health_timer.stop()
        self._snapshot_timer.stop()
        self._timeout_timer.stop()

        # Show last good frame so the user never sees a blank screen
        if self._has_snapshot:
            self._show_snapshot()

        self._reconnect_count += 1
        delay = min(5 * self._reconnect_count, MAX_RECONNECT_DELAY)
        self.status_label.setText(f"Reconnecting in {delay}s...")
        self.status_label.show()
        self._reconnect_timer.start(delay * 1000)

    def _reconnect(self):
        """Pick the best URL variant and reconnect."""
        if self._sub_confirmed and self._reconnect_count <= 3:
            # Sub-stream worked before — try it first
            prefer_sub = True
        elif self._sub_confirmed and self._reconnect_count > 3:
            # Sub-stream keeps failing — fall back to main
            prefer_sub = False
        else:
            # Sub-stream was never confirmed — stick with main
            prefer_sub = False
        self._connect(prefer_sub=prefer_sub)

    # -- snapshot fallback --

    def _take_snapshot(self):
        """Capture the current frame to disk so it can be shown during outages."""
        if self.player is None or self.player.get_state() != vlc.State.Playing:
            return
        try:
            self.player.video_take_snapshot(0, self._snapshot_path, 640, 360)
            if os.path.exists(self._snapshot_path):
                self._has_snapshot = True
        except Exception:
            pass

    def _show_snapshot(self):
        """Display the last captured snapshot as a fallback image."""
        if not os.path.exists(self._snapshot_path):
            return
        pixmap = QPixmap(self._snapshot_path)
        if pixmap.isNull():
            return
        self.snapshot_label.setPixmap(pixmap)
        self.snapshot_label.setGeometry(self.rect())
        self.snapshot_label.show()
        self.video_widget.hide()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HomeTV - Camera Monitor")
        self.resize(1280, 800)
        self.setStyleSheet("background-color: #111;")

        # Single shared VLC instance
        self.vlc_instance = vlc.Instance(*_vlc_instance_args())

        # Menu bar
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("&File")

        settings_action = QAction("&Camera Settings...", self)
        settings_action.setShortcut("Ctrl+,")
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

        reconnect_action = QAction("&Reconnect All", self)
        reconnect_action.setShortcut("Ctrl+R")
        reconnect_action.triggered.connect(self._start_streams)
        file_menu.addAction(reconnect_action)

        file_menu.addSeparator()

        quit_action = QAction("&Quit", self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        view_menu = menu_bar.addMenu("&View")
        fullscreen_action = QAction("Toggle &Fullscreen", self)
        fullscreen_action.setShortcut("F11")
        fullscreen_action.triggered.connect(self._toggle_fullscreen)
        view_menu.addAction(fullscreen_action)

        # Central widget — grid is rebuilt to match the number of configured cameras
        central = QWidget()
        self.setCentralWidget(central)
        self.grid = QGridLayout(central)
        self.grid.setSpacing(4)
        self.grid.setContentsMargins(4, 4, 4, 4)

        self.views: list[CameraView] = []

        self._start_streams()

    def _rebuild_grid(self, count: int):
        """Tear down existing views and lay out `count` fresh ones in a grid
        sized to keep the cells as square as possible."""
        for view in self.views:
            view.stop()
            self.grid.removeWidget(view)
            view.deleteLater()
        self.views = []

        if count == 0:
            placeholder = CameraView(0, self.vlc_instance)
            placeholder.set_status(
                "No cameras configured\nFile › Camera Settings (Ctrl+,)"
            )
            self.grid.addWidget(placeholder, 0, 0)
            self.views.append(placeholder)
            return

        rows, cols = _grid_dims(count)
        for i in range(count):
            view = CameraView(i, self.vlc_instance)
            row, col = divmod(i, cols)
            self.grid.addWidget(view, row, col)
            self.views.append(view)

    def _start_streams(self):
        self._stop_all()
        cameras = load_config()
        active = [cam for cam in cameras if get_rtsp_url(cam)]

        self._rebuild_grid(len(active))

        for i, cam in enumerate(active):
            url = get_rtsp_url(cam)
            sub_url = derive_substream_url(url)
            self.views[i].play(url, sub_url)

    def _stop_all(self):
        for view in self.views:
            view.stop()

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self._start_streams()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def closeEvent(self, event):
        self._stop_all()
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("HomeTV")
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(200, 200, 200))
    palette.setColor(QPalette.ColorRole.Base, QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(40, 40, 40))
    palette.setColor(QPalette.ColorRole.Text, QColor(200, 200, 200))
    palette.setColor(QPalette.ColorRole.Button, QColor(50, 50, 50))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(200, 200, 200))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    app.setPalette(palette)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
