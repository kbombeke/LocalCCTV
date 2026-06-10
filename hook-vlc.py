"""Runtime hook: point VLC at the bundled plugins directory."""
import os
import sys

if getattr(sys, "frozen", False):
    base = sys._MEIPASS
    os.environ["VLC_PLUGIN_PATH"] = os.path.join(base, "plugins")
