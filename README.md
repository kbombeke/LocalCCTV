# HomeTV - Multi-Camera RTSP Monitor

Monitors up to 16 home video camera feeds simultaneously using libVLC. The
viewer grid rescales automatically to the number of cameras you configure.

## Prerequisites

VLC media player must be installed (the app uses its engine).

- **macOS**: `brew install vlc` or download from videolan.org
- **Ubuntu**: `sudo apt install vlc libvlc-dev`

## Setup

```bash
chmod +x run.sh
./run.sh
```

On Ubuntu you may also need: `sudo apt install python3-venv`

## Usage

1. On first launch, go to **File > Camera Settings** (`Ctrl+,`)
2. Paste the full RTSP URL for each camera (same URL that works in VLC); leave
   a slot's URL empty to disable it
3. Click OK to save and connect — the grid resizes to fit the defined streams
4. **Ctrl+R** to reconnect all cameras
5. **F11** for fullscreen

Settings are saved to `~/.config/hometv/cameras.json`.
