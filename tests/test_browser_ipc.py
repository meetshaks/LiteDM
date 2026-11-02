from __future__ import annotations

import importlib.util
import json
import os
import select
import struct
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtNetwork import QLocalSocket

from download_manager.browser_ipc import (
    BrowserIpcServer,
    validate_browser_request,
)
from download_manager.browser_native_host import (
    _chrome_extension_id,
    register_browser_native_host,
)
from download_manager.database import DownloadDatabase
from download_manager.manager import DownloadManager
from download_manager.models import DownloadStatus
from download_manager.ui.main_window import MainWindow

EXTENSION_DIR = Path(__file__).resolve().parents[1] / "litedm-browser-extension"
NATIVE_HOST_PATH = EXTENSION_DIR / "native_host.py"


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (b'{"action":"download","url":"https://example.com/file.zip"}',
         "https://example.com/file.zip"),
        (b'{"action":"status"}', "status"),
        (
            b'{"action":"youtube_formats","url":"https://www.youtube.com/watch?v=example"}',
            "youtube_formats",
        ),
        (
            b'{"action":"youtube_add","video_token":"0123456789abcdef0123456789abcdef","choice_id":"fedcba9876543210fedcba9876543210"}',
            "youtube_add",
        ),
        (
            b'{"action":"youtube_formats","url":"https://example.com/video"}',
            ValueError,
        ),
        (
            b'{"action":"control","download_id":"0123456789abcdef0123456789abcdef","operation":"pause"}',
            "control",
        ),
        (b'{"action":"control","download_id":"bad-id","operation":"pause"}', ValueError),
        (b'{"action":"launch","url":"https://example.com/"}', ValueError),
        (b'{"action":"download","url":"file:///etc/passwd"}', ValueError),
        (b'{"action":"download","url":"https://user:password@example.com/"}', ValueError),
        (b'{"action":"download","url":"https://example.com/","extra":true}', ValueError),
        (b"x" * 16385, ValueError),
    ],
)
def test_validate_browser_requests(payload: bytes, expected):
    if expected is ValueError:
        with pytest.raises(ValueError):
            validate_browser_request(payload)
    else:
        if expected == "status":
            from download_manager.browser_ipc import validate_browser_message

            assert validate_browser_message(payload) == {"action": "status"}
        elif expected == "youtube_formats":
            from download_manager.browser_ipc import validate_browser_message

            assert validate_browser_message(payload) == {
                "action": "youtube_formats",
                "url": "https://www.youtube.com/watch?v=example",
            }
        elif expected == "youtube_add":
            from download_manager.browser_ipc import validate_browser_message

            assert validate_browser_message(payload) == {
                "action": "youtube_add",
                "video_token": "0123456789abcdef0123456789abcdef",
                "choice_id": "fedcba9876543210fedcba9876543210",
            }
        elif expected == "control":
            from download_manager.browser_ipc import validate_browser_message

            assert validate_browser_message(payload) == {
                "action": "control",
                "download_id": "0123456789abcdef0123456789abcdef",
                "operation": "pause",
            }
        else:
            assert validate_browser_request(payload) == expected


def test_user_only_socket_receives_browser_url(application, tmp_path: Path):
    socket_path = tmp_path / "browser.sock"
    server = BrowserIpcServer(socket_path)
    server.listen()
    socket_mode = stat.S_IMODE(socket_path.stat().st_mode)
    server.download_requested.connect(
        lambda url, client: server.reply(client, True, f"Queued {url}")
    )
    client = QLocalSocket()
    client.connectToServer(str(socket_path))
    assert client.waitForConnected(1000)
    client.write(b'{"action":"download","url":"https://example.com/file.zip"}\n')
    client.flush()

    deadline = time.monotonic() + 2
    while not client.canReadLine() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)

    assert socket_mode & 0o077 == 0
    assert json.loads(bytes(client.readLine())) == {
        "ok": True,
        "message": "Queued https://example.com/file.zip",
    }
    client.disconnectFromServer()
    server.close()
    assert not socket_path.exists()


def test_browser_request_adds_http_download_to_existing_queue(
    application, tmp_path: Path
):
    manager = DownloadManager(DownloadDatabase(tmp_path / "history.db"))
    settings_file = tmp_path / "settings.ini"
    settings = QSettings(str(settings_file), QSettings.Format.IniFormat)
    settings.setValue("downloads/lastFolder", str(tmp_path))
    window = MainWindow(manager, settings)
    server = BrowserIpcServer(tmp_path / "app.sock")
    server.listen()
    window.browser_server = server
    server.download_requested.connect(window.handle_browser_download)
    client = QLocalSocket()
    client.connectToServer(str(tmp_path / "app.sock"))
    assert client.waitForConnected(1000)
    client.write(b'{"action":"download","url":"https://example.com/file.zip"}\n')
    client.flush()

    deadline = time.monotonic() + 2
    while (not client.canReadLine() or not manager.items()) and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)

    items = manager.items()
    assert len(items) == 1
    assert items[0].url == "https://example.com/file.zip"
    assert items[0].status == DownloadStatus.QUEUED
    assert items[0].browser_origin is True
    assert json.loads(bytes(client.readLine()))["ok"] is True
    server.close()
    window.close()


def test_browser_status_returns_active_and_paused_queue_items(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "history.db"))
    browser_id = manager.add_download(
        "https://example.com/browser.bin",
        str(tmp_path),
        browser_origin=True,
    )
    regular_id = manager.add_download(
        "https://example.com/app.bin",
        str(tmp_path),
    )
    restored = {item.id: item for item in manager.database.load_all()}
    assert restored[browser_id].browser_origin is True
    assert restored[regular_id].browser_origin is False
    browser_item = manager._items[browser_id]
    browser_item.status = DownloadStatus.DOWNLOADING
    browser_item.downloaded_bytes = 25
    browser_item.total_bytes = 100
    browser_item.speed = 12.5
    manager.database.save(browser_item)
    regular_item = manager._items[regular_id]
    regular_item.status = DownloadStatus.PAUSED
    regular_item.downloaded_bytes = 150_800_000
    regular_item.total_bytes = 348_300_000
    manager.database.save(regular_item)
    window = MainWindow(
        manager,
        QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat),
    )
    server = BrowserIpcServer(tmp_path / "status.sock")
    server.listen()
    server.status_requested.connect(window.handle_browser_status)
    window.browser_server = server

    client = QLocalSocket()
    client.connectToServer(str(tmp_path / "status.sock"))
    assert client.waitForConnected(1000)
    client.write(b'{"action":"status"}\n')
    client.flush()
    deadline = time.monotonic() + 2
    while not client.canReadLine() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)

    response = json.loads(bytes(client.readLine()))
    assert response == {
        "ok": True,
        "controls_supported": True,
        "downloads": [
            {
                "id": browser_id,
                "name": "browser.bin",
                "status": "downloading",
                "downloaded_bytes": 25,
                "total_bytes": 100,
                "speed": 12.5,
            },
            {
                "id": regular_id,
                "name": "app.bin",
                "status": "paused",
                "downloaded_bytes": 150_800_000,
                "total_bytes": 348_300_000,
                "speed": 0.0,
            },
        ],
    }
    server.close()
    window.close()


def test_browser_pause_resume_controls_update_queue_status(application, tmp_path: Path):
    manager = DownloadManager(DownloadDatabase(tmp_path / "controls.db"))
    item_id = manager.add_download("https://example.com/control.bin", str(tmp_path))
    window = MainWindow(
        manager,
        QSettings(str(tmp_path / "controls-settings.ini"), QSettings.Format.IniFormat),
    )
    server = BrowserIpcServer(tmp_path / "controls.sock")
    server.listen()
    server.control_requested.connect(window.handle_browser_control)
    window.browser_server = server

    for operation, expected_status in (
        ("pause", DownloadStatus.PAUSED),
        ("resume", DownloadStatus.QUEUED),
    ):
        client = QLocalSocket()
        client.connectToServer(str(tmp_path / "controls.sock"))
        assert client.waitForConnected(1000)
        client.write(
            json.dumps(
                {
                    "action": "control",
                    "download_id": item_id,
                    "operation": operation,
                }
            ).encode("utf-8") + b"\n"
        )
        client.flush()
        deadline = time.monotonic() + 2
        while not client.canReadLine() and time.monotonic() < deadline:
            application.processEvents()
            time.sleep(0.005)

        response = json.loads(bytes(client.readLine()))
        assert response["ok"] is True
        current = manager.get(item_id)
        assert current is not None
        if expected_status == DownloadStatus.QUEUED:
            assert current.status in {DownloadStatus.QUEUED, DownloadStatus.DOWNLOADING}
        else:
            assert current.status == expected_status

    server.close()
    window.close()


def test_youtube_overlay_format_selection_adds_selected_format(
    application, tmp_path: Path
):
    manager = DownloadManager(DownloadDatabase(tmp_path / "youtube-overlay.db"))
    window = MainWindow(
        manager,
        QSettings(str(tmp_path / "youtube-overlay-settings.ini"), QSettings.Format.IniFormat),
    )
    server = BrowserIpcServer(tmp_path / "youtube-overlay.sock")
    server.listen()
    window.browser_server = server
    server.youtube_formats_requested.connect(
        lambda url, socket: window._browser_youtube_metadata_loaded(url, socket, info)
    )
    server.youtube_add_requested.connect(window.handle_browser_youtube_add)
    info = {
        "title": "Overlay test video",
        "channel": "Example channel",
        "duration": 120,
        "formats": [
            {
                "format_id": "22",
                "height": 720,
                "width": 1280,
                "ext": "mp4",
                "vcodec": "avc1",
                "acodec": "mp4a",
                "filesize": 12_000_000,
            }
        ],
    }
    formats_client = QLocalSocket()
    formats_client.connectToServer(str(tmp_path / "youtube-overlay.sock"))
    assert formats_client.waitForConnected(1000)
    formats_client.write(
        json.dumps(
            {
                "action": "youtube_formats",
                "url": "https://www.youtube.com/watch?v=example",
            }
        ).encode("utf-8") + b"\n"
    )
    formats_client.flush()
    deadline = time.monotonic() + 2
    while not formats_client.canReadLine() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert formats_client.canReadLine()
    format_response = json.loads(bytes(formats_client.readLine()))
    assert format_response["ok"] is True
    assert [entry["label"] for entry in format_response["formats"]] == ["720p · 11.4 MB"]

    selected = format_response["formats"][0]
    add_client = QLocalSocket()
    add_client.connectToServer(str(tmp_path / "youtube-overlay.sock"))
    assert add_client.waitForConnected(1000)
    application.processEvents()
    add_client.write(
        json.dumps(
            {
                "action": "youtube_add",
                "video_token": format_response["video_token"],
                "choice_id": selected["id"],
            }
        ).encode("utf-8") + b"\n"
    )
    add_client.flush()
    deadline = time.monotonic() + 2
    while not add_client.canReadLine() and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    assert add_client.canReadLine()
    add_response = json.loads(bytes(add_client.readLine()))

    item = manager.items()[0]
    assert add_response["ok"] is True
    assert item.media_format == "22"
    assert item.total_bytes == 12_000_000
    assert item.source_type == "youtube"
    assert item.browser_origin is True
    server.close()
    window.close()


def test_native_host_request_validation_and_installer(tmp_path: Path):
    spec = importlib.util.spec_from_file_location("litedm_native_host", NATIVE_HOST_PATH)
    assert spec and spec.loader
    native_host = importlib.util.module_from_spec(spec)
    bytecode_setting = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(native_host)
    finally:
        sys.dont_write_bytecode = bytecode_setting
    assert native_host._validate_request(
        {"action": "download", "url": "https://example.com/video"}
    ) == "https://example.com/video"
    assert native_host._validate_control_request(
        {
            "action": "control",
            "download_id": "0123456789abcdef0123456789abcdef",
            "operation": "resume",
        }
    ) == {
        "action": "control",
        "download_id": "0123456789abcdef0123456789abcdef",
        "operation": "resume",
    }
    assert native_host._validate_youtube_formats_request(
        {
            "action": "youtube_formats",
            "url": "https://www.youtube.com/watch?v=example",
        }
    ) == {
        "action": "youtube_formats",
        "url": "https://www.youtube.com/watch?v=example",
    }
    assert native_host._validate_youtube_add_request(
        {
            "action": "youtube_add",
            "video_token": "0123456789abcdef0123456789abcdef",
            "choice_id": "fedcba9876543210fedcba9876543210",
        }
    ) == {
        "action": "youtube_add",
        "video_token": "0123456789abcdef0123456789abcdef",
        "choice_id": "fedcba9876543210fedcba9876543210",
    }
    with pytest.raises(ValueError):
        native_host._validate_request(
            {"action": "download", "url": "javascript:alert(1)"}
        )

    environment = dict(os.environ, HOME=str(tmp_path))
    chrome_id = "a" * 32
    install = subprocess.run(
        [sys.executable, str(EXTENSION_DIR / "install.py"), chrome_id],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert "Installed" in install.stdout
    chrome_manifest = tmp_path / ".config/google-chrome/NativeMessagingHosts/com.litedm.native.json"
    chromium_manifest = tmp_path / ".config/chromium/NativeMessagingHosts/com.litedm.native.json"
    firefox_manifest = tmp_path / ".mozilla/native-messaging-hosts/com.litedm.native.json"
    chrome_data = json.loads(chrome_manifest.read_text())
    chromium_data = json.loads(chromium_manifest.read_text())
    firefox_data = json.loads(firefox_manifest.read_text())
    assert chrome_data["allowed_origins"] == [f"chrome-extension://{chrome_id}/"]
    assert chromium_data["allowed_origins"] == [f"chrome-extension://{chrome_id}/"]
    assert firefox_data["allowed_extensions"] == ["browser-extension@litedm.local"]
    assert Path(chrome_data["path"]).is_file()
    assert chrome_data["args"] == []

    subprocess.run(
        [sys.executable, str(EXTENSION_DIR / "install.py"), "--uninstall"],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert not chrome_manifest.exists()
    assert not chromium_manifest.exists()
    assert not firefox_manifest.exists()

    firefox_only = subprocess.run(
        [
            sys.executable,
            str(EXTENSION_DIR / "install.py"),
            "--browsers",
            "firefox",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert "Firefox" in firefox_only.stdout
    assert firefox_manifest.exists()
    assert not chrome_manifest.exists()
    assert not chromium_manifest.exists()


def test_extension_manifest_has_least_privilege_and_valid_assets():
    manifest = json.loads((EXTENSION_DIR / "manifest.json").read_text())
    firefox_manifest = json.loads((EXTENSION_DIR / "manifest.firefox.json").read_text())
    service_worker = (EXTENSION_DIR / "service_worker.js").read_text()
    popup_script = (EXTENSION_DIR / "popup.js").read_text()
    popup_html = (EXTENSION_DIR / "popup.html").read_text()
    image_click_script = (EXTENSION_DIR / "image_click.js").read_text()
    youtube_overlay_script = (EXTENSION_DIR / "youtube_video_overlay.js").read_text()

    assert manifest["manifest_version"] == 3
    assert set(manifest["permissions"]) == {"contextMenus", "nativeMessaging"}
    assert set(manifest["host_permissions"]) == {"http://*/*", "https://*/*"}
    assert manifest["content_scripts"][0]["matches"] == ["http://*/*", "https://*/*"]
    assert manifest["content_scripts"][0]["js"] == ["image_click.js"]
    assert manifest["content_scripts"][0]["run_at"] == "document_start"
    assert firefox_manifest["host_permissions"] == manifest["host_permissions"]
    assert firefox_manifest["content_scripts"] == manifest["content_scripts"]
    assert manifest["content_scripts"][1]["js"] == ["youtube_video_overlay.js"]
    assert manifest["content_scripts"][1]["matches"] == [
        "https://youtube.com/*",
        "https://www.youtube.com/*",
        "https://m.youtube.com/*",
    ]
    assert manifest["version"] == firefox_manifest["version"] == "1.4.8"
    assert manifest["action"]["default_popup"] == "popup.html"
    assert firefox_manifest["action"]["default_popup"] == "popup.html"
    assert (EXTENSION_DIR / "popup.html").is_file()
    assert (EXTENSION_DIR / "popup.css").is_file()
    for icon in manifest["icons"].values():
        assert (EXTENSION_DIR / icon).is_file()
    for size in (16, 32, 48, 128):
        icon = EXTENSION_DIR / "icons" / f"litedm-{size}.png"
        assert icon.is_file()
        with icon.open("rb") as image:
            image.seek(16)
            assert struct.unpack(">II", image.read(8)) == (size, size)
    assert (EXTENSION_DIR / "icons/litedm-32.png").read_bytes() == (
        EXTENSION_DIR.parent / "icons/5_32_px.png"
    ).read_bytes()
    assert (EXTENSION_DIR / "icons/litedm-48.png").read_bytes() == (
        EXTENSION_DIR.parent / "icons/5_48_px.png"
    ).read_bytes()
    assert "service_worker" in manifest["background"]
    assert "scripts" in firefox_manifest["background"]
    assert _chrome_extension_id(manifest) == "lagocknnocadlfljebkcephnjlkbjnlk"
    assert 'contexts: ["link", "image", "page", "video", "audio"]' in service_worker
    assert "const url = info.srcUrl || info.linkUrl || info.pageUrl || tab?.url;" in service_worker
    assert 'setInterval(() => void refreshProgress(), 1000)' in service_worker
    assert 'String(active.length)' in service_worker
    assert '"✓"' not in service_worker
    assert 'createElement("tr")' in popup_script
    assert 'createElement("progress")' in popup_script
    assert "Download this page" not in popup_html
    assert "download-current-page" not in service_worker
    assert "event.isTrusted" in image_click_script
    assert 'location.hostname.endsWith("youtube.com")' in image_click_script
    assert 'event.target.closest("img")' in image_click_script
    assert 'if (image.closest("a"))' in image_click_script
    assert 'type: "download-image-click"' in image_click_script
    assert 'type === "download-image-click"' in service_worker
    assert 'type === "youtube-formats"' in service_worker
    assert 'type === "youtube-add"' in service_worker
    assert 'type: "youtube-formats"' in youtube_overlay_script
    assert 'type: "youtube-add"' in youtube_overlay_script
    assert "textContent = format.label" in youtube_overlay_script
    assert "void preloadFormats(mountedUrl)" in youtube_overlay_script
    assert 'if (formatLoadState === "ready")' in youtube_overlay_script
    assert 'setMessage("Loading formats…")' not in youtube_overlay_script
    main_window_source = (
        EXTENSION_DIR.parent / "download_manager/ui/main_window.py"
    ).read_text()
    assert "time.monotonic() + 3600" in main_window_source
    assert "const youtubeExtensionApi =" in youtube_overlay_script
    assert "const api =" in image_click_script
    assert youtube_overlay_script.startswith("(() => {")
    assert image_click_script.startswith("(() => {")
    assert 'setAttribute("aria-label", "Download this YouTube video with LiteDM")' in youtube_overlay_script
    assert 'className = "download-control"' in popup_script
    assert 'className = "status-content"' in popup_script
    assert 'className = "control-spinner"' in popup_script
    assert ".control-spinner {" in (EXTENSION_DIR / "popup.css").read_text()
    assert 'type === "control-download"' in service_worker
    assert "controls_supported" in service_worker
    assert 'type === "get-app-status"' in service_worker
    assert 'type: "litedm-connection"' in service_worker
    assert 'message?.type === "litedm-connection"' in youtube_overlay_script
    assert "Start LiteDM to choose a video format." in youtube_overlay_script
    assert "Start LiteDM to send downloads and view your queue." in popup_script


def test_app_native_host_registration_needs_no_manual_extension_id(tmp_path: Path):
    registered = register_browser_native_host(
        extension_directory=EXTENSION_DIR,
        home_directory=tmp_path,
    )

    assert len(registered) == 4
    chrome_manifest = json.loads(registered[0].read_text())
    chromium_manifest = json.loads(registered[1].read_text())
    brave_manifest = json.loads(registered[2].read_text())
    firefox_manifest = json.loads(registered[3].read_text())
    expected_origin = "chrome-extension://lagocknnocadlfljebkcephnjlkbjnlk/"
    assert chrome_manifest["allowed_origins"] == [expected_origin]
    assert chromium_manifest["allowed_origins"] == [expected_origin]
    assert brave_manifest["allowed_origins"] == [expected_origin]
    assert firefox_manifest["allowed_extensions"] == ["browser-extension@litedm.local"]
    installed_host = Path(chrome_manifest["path"])
    assert installed_host.is_file()
    assert stat.S_IMODE(installed_host.stat().st_mode) == 0o700
    assert chrome_manifest["args"] == []
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in registered)


def test_installed_native_host_forwards_message_to_litedm_socket(
    application, monkeypatch, tmp_path: Path
):
    data_home = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    server = BrowserIpcServer()
    server.listen()
    requests = []
    server.download_requested.connect(
        lambda url, client: (
            requests.append(url),
            server.reply(client, True, "Added to LiteDM."),
        )
    )
    server.status_requested.connect(
        lambda client: server.reply_payload(
            client,
            {"ok": True, "downloads": [{"name": "file.zip", "status": "downloading"}]},
        )
    )
    controls = []
    server.control_requested.connect(
        lambda download_id, operation, client: (
            controls.append((download_id, operation)),
            server.reply(client, True, f"Download {operation} requested."),
        )
    )
    process = subprocess.Popen(
        [sys.executable, str(NATIVE_HOST_PATH)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(os.environ, XDG_DATA_HOME=str(data_home)),
    )
    request = json.dumps(
        {
            "action": "download",
            "url": "https://example.com/file.zip",
            "requestId": 1,
        }
    ).encode("utf-8")
    assert process.stdin and process.stdout
    process.stdin.write(struct.pack("<I", len(request)) + request)
    process.stdin.flush()
    deadline = time.monotonic() + 3
    while not select.select([process.stdout], [], [], 0)[0] and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    if not select.select([process.stdout], [], [], 0)[0]:
        process.kill()
        process.wait()
        pytest.fail("The persistent native host did not respond to the download request.")
    frame_size = struct.unpack("<I", process.stdout.read(4))[0]
    response = json.loads(process.stdout.read(frame_size).decode("utf-8"))
    assert response == {
        "ok": True,
        "message": "Added to LiteDM.",
        "requestId": 1,
    }

    status_request = json.dumps({"action": "status", "requestId": 2}).encode("utf-8")
    process.stdin.write(struct.pack("<I", len(status_request)) + status_request)
    process.stdin.flush()
    deadline = time.monotonic() + 3
    while not select.select([process.stdout], [], [], 0)[0] and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    if not select.select([process.stdout], [], [], 0)[0]:
        process.kill()
        process.wait()
        pytest.fail("The persistent native host did not respond to the status request.")
    frame_size = struct.unpack("<I", process.stdout.read(4))[0]
    status_response = json.loads(process.stdout.read(frame_size).decode("utf-8"))
    assert status_response == {
        "ok": True,
        "downloads": [{"name": "file.zip", "status": "downloading"}],
        "requestId": 2,
    }
    control_request = json.dumps(
        {
            "action": "control",
            "download_id": "0123456789abcdef0123456789abcdef",
            "operation": "pause",
            "requestId": 3,
        }
    ).encode("utf-8")
    process.stdin.write(struct.pack("<I", len(control_request)) + control_request)
    process.stdin.flush()
    deadline = time.monotonic() + 3
    while not select.select([process.stdout], [], [], 0)[0] and time.monotonic() < deadline:
        application.processEvents()
        time.sleep(0.005)
    if not select.select([process.stdout], [], [], 0)[0]:
        process.kill()
        process.wait()
        pytest.fail("The persistent native host did not respond to the control request.")
    frame_size = struct.unpack("<I", process.stdout.read(4))[0]
    control_response = json.loads(process.stdout.read(frame_size).decode("utf-8"))
    assert control_response == {
        "ok": True,
        "message": "Download pause requested.",
        "requestId": 3,
    }
    process.stdin.close()
    assert process.wait(timeout=3) == 0

    assert requests == ["https://example.com/file.zip"]
    assert controls == [("0123456789abcdef0123456789abcdef", "pause")]
    diagnostic_log = data_home / "litetdm" / "browser-native-host.log"
    assert "Native host started." in diagnostic_log.read_text()
    assert "Browser closed native messaging connection." in diagnostic_log.read_text()
    assert stat.S_IMODE(diagnostic_log.stat().st_mode) == 0o600
    server.close()
