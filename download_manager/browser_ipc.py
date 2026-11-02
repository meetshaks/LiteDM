from __future__ import annotations

import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .utils import default_data_dir, validate_url
from .youtube import is_youtube_url

MAX_REQUEST_BYTES = 16 * 1024


def browser_socket_path() -> Path:
    return default_data_dir() / "browser.sock"


def validate_browser_message(payload: bytes) -> dict[str, str]:
    if len(payload) > MAX_REQUEST_BYTES:
        raise ValueError("Browser request is too large.")
    try:
        request = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError("Browser request must be valid UTF-8 JSON.") from error
    if not isinstance(request, dict):
        raise ValueError("Browser request must be a JSON object.")
    if request == {"action": "status"}:
        return {"action": "status"}
    if (
        set(request) == {"action", "url"}
        and request.get("action") == "youtube_formats"
    ):
        url = _validated_url(request["url"])
        if not is_youtube_url(url):
            raise ValueError("YouTube format requests must use a YouTube URL.")
        return {"action": "youtube_formats", "url": url}
    if (
        set(request) == {"action", "video_token", "choice_id"}
        and request.get("action") == "youtube_add"
        and isinstance(request.get("video_token"), str)
        and re.fullmatch(r"[0-9a-f]{32}", request["video_token"])
        and isinstance(request.get("choice_id"), str)
        and re.fullmatch(r"[0-9a-f]{32}", request["choice_id"])
    ):
        return {
            "action": "youtube_add",
            "video_token": request["video_token"],
            "choice_id": request["choice_id"],
        }
    if (
        set(request) == {"action", "download_id", "operation"}
        and request.get("action") == "control"
        and request.get("operation") in {"pause", "resume"}
        and isinstance(request.get("download_id"), str)
        and re.fullmatch(r"[0-9a-f]{32}", request["download_id"])
    ):
        return {
            "action": "control",
            "download_id": request["download_id"],
            "operation": request["operation"],
        }
    if set(request) != {"action", "url"}:
        raise ValueError("Browser request has an unsupported message shape.")
    if request["action"] != "download" or not isinstance(request["url"], str):
        raise ValueError("Browser request has an unsupported action.")
    url = _validated_url(request["url"])
    return {"action": "download", "url": url}


def _validated_url(raw_url: object) -> str:
    if not isinstance(raw_url, str):
        raise ValueError("Browser request URL must be a string.")
    url = validate_url(raw_url)
    parsed = urlsplit(url)
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not accepted.")
    if len(url) > 8192:
        raise ValueError("The URL is too long.")
    return url


def validate_browser_request(payload: bytes) -> str:
    message = validate_browser_message(payload)
    if message["action"] != "download":
        raise ValueError("Browser request is not a download.")
    return message["url"]


class BrowserIpcServer(QObject):
    download_requested = Signal(str, object)
    status_requested = Signal(object)
    control_requested = Signal(str, str, object)
    youtube_formats_requested = Signal(str, object)
    youtube_add_requested = Signal(str, str, object)

    def __init__(self, socket_path: str | Path | None = None, parent=None):
        super().__init__(parent)
        self.socket_path = str(socket_path or browser_socket_path())
        self._server = QLocalServer(self)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        self._listening = False
        self._server.newConnection.connect(self._accept_connections)

    def listen(self) -> None:
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if self._server.listen(self.socket_path):
            self._listening = True
            return
        probe = QLocalSocket(self)
        probe.connectToServer(self.socket_path)
        if probe.waitForConnected(200):
            probe.abort()
            raise OSError(f"Another LiteDM browser listener is active at {self.socket_path}.")
        probe_error = probe.error()
        if probe_error not in {
            QLocalSocket.LocalSocketError.ConnectionRefusedError,
            QLocalSocket.LocalSocketError.ServerNotFoundError,
        }:
            error = probe.errorString()
            probe.abort()
            raise OSError(f"Could not verify the LiteDM browser socket: {error}")
        probe.abort()
        if probe_error == QLocalSocket.LocalSocketError.ConnectionRefusedError:
            QLocalServer.removeServer(self.socket_path)
        if not self._server.listen(self.socket_path):
            raise OSError(f"Could not start the LiteDM browser listener: {self._server.errorString()}")
        self._listening = True

    def close(self) -> None:
        if not self._listening:
            return
        self._server.close()
        QLocalServer.removeServer(self.socket_path)
        self._listening = False

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                return
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda current=socket: self._read_request(current))
            socket.disconnected.connect(lambda current=socket: self._drop_socket(current))
            if socket.bytesAvailable():
                self._read_request(socket)

    def _read_request(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > MAX_REQUEST_BYTES:
            self.reply(socket, False, "Browser request is too large.")
            return
        newline = buffer.find(b"\n")
        if newline < 0:
            return
        message = bytes(buffer[:newline])
        try:
            request = validate_browser_message(message)
        except ValueError as error:
            self.reply(socket, False, str(error))
            return
        if request["action"] == "status":
            self.status_requested.emit(socket)
        elif request["action"] == "control":
            self.control_requested.emit(request["download_id"], request["operation"], socket)
        elif request["action"] == "youtube_formats":
            self.youtube_formats_requested.emit(request["url"], socket)
        elif request["action"] == "youtube_add":
            self.youtube_add_requested.emit(
                request["video_token"], request["choice_id"], socket
            )
        else:
            self.download_requested.emit(request["url"], socket)

    def reply(self, socket: QLocalSocket, success: bool, message: str) -> None:
        self.reply_payload(socket, {"ok": success, "message": message})

    def reply_payload(self, socket: QLocalSocket, payload: dict) -> None:
        if socket.state() == QLocalSocket.LocalSocketState.UnconnectedState:
            return
        encoded = json.dumps(payload).encode("utf-8") + b"\n"
        socket.write(encoded)
        socket.flush()
        socket.disconnectFromServer()

    def _drop_socket(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)
        socket.deleteLater()
