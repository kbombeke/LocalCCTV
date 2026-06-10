import os

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal, QMutex

# Force TCP transport for RTSP, same as VLC default behavior
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"


class CameraWorker(QThread):
    """Worker thread that captures frames from an RTSP stream."""

    frame_ready = Signal(int, np.ndarray)  # camera_index, frame
    connection_lost = Signal(int, str)  # camera_index, error message
    connected = Signal(int)  # camera_index

    def __init__(self, camera_index: int, rtsp_url: str, parent=None):
        super().__init__(parent)
        self.camera_index = camera_index
        self.rtsp_url = rtsp_url
        self._running = False
        self._mutex = QMutex()

    def run(self):
        self._running = True
        cap = cv2.VideoCapture(self.rtsp_url)

        # Optimize for low latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            self.connection_lost.emit(
                self.camera_index, f"Cannot connect to {self.rtsp_url}"
            )
            return

        self.connected.emit(self.camera_index)

        consecutive_failures = 0
        while self._running:
            ret, frame = cap.read()
            if ret:
                consecutive_failures = 0
                self.frame_ready.emit(self.camera_index, frame)
            else:
                consecutive_failures += 1
                if consecutive_failures > 30:
                    self.connection_lost.emit(
                        self.camera_index, "Stream lost after repeated failures"
                    )
                    break
                self.msleep(100)

        cap.release()

    def stop(self):
        self._running = False
        self.wait(3000)
