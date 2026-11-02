# LiteDM

LiteDM is a lightweight Linux download manager built with Python, PySide6, and requests. It is designed for Kali Linux XFCE and uses native Qt controls, desktop theme icons, and a responsive background-thread download engine.

## Features

- HTTP and HTTPS downloads, including redirects and unknown response lengths
- Image downloads with missing URL suffixes use the server's image content type to add the correct file extension
- Live byte progress, total size, percentage, and transfer speed
- Completed downloads show their completion date and time in the system's local timezone
- Pause, resume, cancel, and retry with retained `.part` data
- HTTP Range resume with safe restart when a server does not support ranges
- Persistent download queue with 1–8 parallel QThread workers
- Multi-select controls, search, and status filters
- Persistent light/dark theme toggle
- Folder selection and optional custom filenames
- SQLite download history and recovery after an interrupted application session
- Clear HTTP, network, filesystem, and partial-file error reporting
- Atomic no-overwrite finalization with automatic numbered filenames
- YouTube video/audio downloads with asynchronously loaded metadata, MP4-only video resolutions, and real available formats
- Format-reported size estimates, maximum-quality MP3 audio extraction, and queue-based progress/control
- Chrome, Chromium, Brave, and Firefox extension integration with live download progress in the toolbar and popup

## Install and run on Kali Linux XFCE

Python 3.10 or newer is required. From the project directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
chmod +x run_linux.sh build_linux.sh
./run_linux.sh
```

YouTube downloads require the `yt-dlp` Python package (installed from `requirements.txt`). Install FFmpeg for merging separate video/audio streams and MP3 conversion:

```bash
sudo apt install ffmpeg
```

Without FFmpeg, formats requiring a merge and MP3 conversion report a clear error. Download availability depends on the source video and extractor support; playlists and live streams are not supported. LiteDM does not bypass DRM.

The run script uses `.venv` when present. If the same dependencies are installed globally, development mode can also be launched directly:

```bash
python3 main.py
# or
python3 -m download_manager
```

Code changes take effect on the next Python launch; no PyInstaller rebuild is needed during development.

If Qt reports that the `xcb` platform plugin cannot load, install the usual X11 runtime libraries:

```bash
sudo apt install libxcb-cursor0 libxkbcommon-x11-0 libgl1 libegl1
```

## Use

1. Click **Add** or press **Ctrl+O**.
2. Enter an HTTP/HTTPS URL, choose a folder, and optionally provide a filename.
3. Use the pause/resume control at the right side of a download card to control that transfer.
4. Use **Pause All** and **Resume All** in the top action bar to control the queue.
5. Right-click a card for retry, cancel, file, and link actions.
6. Set **Parallel** to control how many queued downloads run simultaneously.
7. Use **Light** or **Dark** in the action bar to switch themes; your choice is saved.

For YouTube URLs, choose **Add**, paste the video link, then continue to the metadata dialog. LiteDM fetches the title, channel, duration, thumbnail, actual formats, codecs, and available size estimates asynchronously. The video format list contains one MP4 option per resolution, labeled with its resolution and file size, plus original audio and MP3 options; WebM video options and formats without a size estimate are omitted. When the source does not report a file size, LiteDM estimates one from its reported bitrate and duration. MP3 conversion uses FFmpeg's maximum-quality 320 kb/s setting automatically.

Load the extension from [litedm-browser-extension/](./litedm-browser-extension/) once in Chrome/Chromium, Brave, or Firefox, then start or restart LiteDM. LiteDM automatically registers the secure browser bridge for your user account; no extension ID or terminal installer step is needed. The toolbar badge shows active download progress; clicking the extension opens a table of all queued, active, and paused LiteDM downloads. YouTube video pages show a player overlay with format/size choices; selecting one adds it to LiteDM. Clicking an image sends it to LiteDM while preserving the page's normal navigation; the **Download with LiteDM** right-click menu is also available. LiteDM must be running to accept browser requests. Setup and security details are in [the extension guide](./litedm-browser-extension/README.md).

Closing the window gracefully pauses active transfers before exiting. Queued items and history remain in SQLite. Items interrupted by an unclean shutdown are restored as paused; resume them explicitly.

Cancellation does not remove the partial file. Use **Retry** to continue a cancelled or failed item. If a server ignores the resume range, LiteDM safely restarts only its own `.part` file from the beginning.

## Files and safety

- History: `${XDG_DATA_HOME:-~/.local/share}/litetdm/downloads.db`
- Settings: Qt's per-user `QSettings` location, normally `~/.config/LiteDM/LiteDM.conf`
- Default destination: the configured XDG Downloads directory, normally `~/Downloads`
- Partial transfers: `<destination>.part`

Existing final files and unrelated partial files are never reused, overwritten, or deleted. Name collisions produce names such as `file (1).zip`. Final files are published with exclusive creation; no destructive rename is used. Partial files and the history database are owner-readable/writable by default. YouTube partial data is retained in a private per-transfer subdirectory; cancelling, pausing, or closing LiteDM does not delete downloaded data.

For an isolated history database, use:

```bash
./run_linux.sh --data-dir /path/to/private/profile
```

## Improvement roadmap

The project is already stable, and the next set of upgrades focus on maintainability and operational quality rather than adding new download features:

1. Formalize the download lifecycle with an explicit state machine so each transition is validated instead of being inferred by hand in the manager.
2. Centralize startup configuration and runtime diagnostics, including sane defaults for concurrency and structured logging for startup and recovery events.
3. Harden the UI boundary by separating settings, actions, and state update logic from view-specific behavior as the app grows.
4. Keep the file-safety and retry contracts covered by regression tests so future refactors preserve the resilient behavior that makes LiteDM reliable.

The lifecycle validation, startup logging, settings boundary, and pure UI presentation helpers are implemented. The UI filtering, queue summaries, category counts, and bulk-action availability now live outside the main window and are covered by focused tests. Deeper widget/layout extraction remains an incremental follow-up as those UI areas change.

## Tests

Install the test dependencies and run the suite without an X server:

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q
```

The integration tests use a local HTTP server to exercise real transfers, byte ranges, redirects, unknown lengths, pause/resume, cancellation, retry, parallel scheduling, queue ordering, GUI behavior, SQLite history, and collision protection.

## Build a Linux executable

```bash
.venv/bin/python -m pip install -r requirements.txt -r requirements-dev.txt
./build_linux.sh
./dist/LiteDM/LiteDM
```

The script creates a self-contained PyInstaller `onedir` application in `dist/LiteDM/`. Build on the oldest Linux environment you intend to support; PyInstaller output is not cross-compiled. Keep the entire `LiteDM` directory together when moving the packaged application.

The PyInstaller bundle includes yt-dlp's Python resources. FFmpeg remains a system dependency and should be installed on the target machine for stream merging and MP3 conversion.

## Project layout

```text
main.py                         Development entry point
download_manager/
  app.py                        Application composition and CLI arguments
  manager.py                    Persistent queue and worker scheduling
  worker.py                     QThread HTTP transfer engine
  database.py                   SQLite history
  models.py                     Download states and data models
  utils.py                     XDG paths, safe filenames, app icon, and finalization
  settings.py                   Validated application settings
  ui/                           Main window, presentation helpers, and dialogs
tests/                          Unit and local-server integration tests
icons/                          Application icon sources (5.png is used by the app)
litedm-browser-extension/icons/  Browser extension icons (sourced from 5_32_px.png and 5_48_px.png)
run_linux.sh                    Development launcher
build_linux.sh                  PyInstaller build script
```
