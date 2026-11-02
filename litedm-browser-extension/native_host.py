#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import socket
import struct
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

MAX_MESSAGE_SIZE = 1024 * 1024
MAX_RESPONSE_SIZE = 1024 * 1024
MAX_URL_SIZE = 8192
SOCKET_NAME = "browser.sock"


def _read_exact(stream, size: int) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            if not chunks:
                return None
            raise ValueError("Unexpected end of native messaging frame.")
        chunks.extend(chunk)
    return bytes(chunks)


def _runtime_socket() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "litetdm" / SOCKET_NAME


def _log_diagnostic(message: str) -> None:
    log_path = _runtime_socket().parent / "browser-native-host.log"
    try:
        log_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        descriptor = os.open(
            log_path,
            os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, f"{int(time.time())} {message}\n".encode("utf-8"))
        finally:
            os.close(descriptor)
    except OSError:
        pass


def _validate_request(message: object) -> str:
    if not isinstance(message, dict) or set(message) != {"action", "url"}:
        raise ValueError("Unsupported message.")
    if message["action"] != "download" or not isinstance(message["url"], str):
        raise ValueError("Unsupported action.")
    url = message["url"].strip()
    if len(url.encode("utf-8")) > MAX_URL_SIZE:
        raise ValueError("URL is too long.")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP and HTTPS URLs are supported.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not accepted.")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("URL contains an invalid port.") from error
    if any(ord(character) < 32 for character in url):
        raise ValueError("URL contains control characters.")
    return url


def _validate_control_request(message: object) -> dict[str, str]:
    if (
        not isinstance(message, dict)
        or set(message) != {"action", "download_id", "operation"}
        or message.get("action") != "control"
        or message.get("operation") not in {"pause", "resume"}
        or not isinstance(message.get("download_id"), str)
        or len(message["download_id"]) != 32
        or any(character not in "0123456789abcdef" for character in message["download_id"])
    ):
        raise ValueError("Unsupported download control request.")
    return {
        "action": "control",
        "download_id": message["download_id"],
        "operation": message["operation"],
    }


def _validate_youtube_formats_request(message: object) -> dict[str, str]:
    if not isinstance(message, dict) or set(message) != {"action", "url"}:
        raise ValueError("Unsupported YouTube format request.")
    if message.get("action") != "youtube_formats":
        raise ValueError("Unsupported YouTube format action.")
    url = message.get("url")
    if not isinstance(url, str) or len(url.encode("utf-8")) > MAX_URL_SIZE:
        raise ValueError("YouTube URL is invalid or too long.")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"} or parsed.hostname not in {
        "youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
        "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com",
    }:
        raise ValueError("A supported YouTube video URL is required.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing embedded credentials are not accepted.")
    try:
        parsed.port
    except ValueError as error:
        raise ValueError("YouTube URL contains an invalid port.") from error
    return {"action": "youtube_formats", "url": url}


def _validate_youtube_add_request(message: object) -> dict[str, str]:
    if (
        not isinstance(message, dict)
        or set(message) != {"action", "video_token", "choice_id"}
        or message.get("action") != "youtube_add"
        or not isinstance(message.get("video_token"), str)
        or len(message["video_token"]) != 32
        or any(character not in "0123456789abcdef" for character in message["video_token"])
        or not isinstance(message.get("choice_id"), str)
        or len(message["choice_id"]) != 32
        or any(character not in "0123456789abcdef" for character in message["choice_id"])
    ):
        raise ValueError("Unsupported YouTube format selection.")
    return {
        "action": "youtube_add",
        "video_token": message["video_token"],
        "choice_id": message["choice_id"],
    }


def _forward_request(message: dict) -> dict:
    if not isinstance(message, dict):
        raise ValueError("Unsupported message.")
    request_id = message.get("requestId")
    request = {key: value for key, value in message.items() if key != "requestId"}
    if request == {"action": "status"}:
        payload = b'{"action":"status"}\n'
    elif isinstance(request, dict) and request.get("action") == "control":
        payload = json.dumps(_validate_control_request(request)).encode("utf-8") + b"\n"
    elif isinstance(request, dict) and request.get("action") == "youtube_formats":
        payload = json.dumps(_validate_youtube_formats_request(request)).encode("utf-8") + b"\n"
    elif isinstance(request, dict) and request.get("action") == "youtube_add":
        payload = json.dumps(_validate_youtube_add_request(request)).encode("utf-8") + b"\n"
    else:
        url = _validate_request(request)
        payload = json.dumps({"action": "download", "url": url}).encode("utf-8") + b"\n"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(3)
        connection.connect(str(_runtime_socket()))
        connection.sendall(payload)
        connection.settimeout(300)
        response = bytearray()
        while len(response) <= MAX_RESPONSE_SIZE:
            chunk = connection.recv(4096)
            if not chunk:
                break
            response.extend(chunk)
            newline = response.find(b"\n")
            if newline >= 0:
                value = json.loads(response[:newline].decode("utf-8"))
                if not isinstance(value, dict) or not isinstance(value.get("ok"), bool):
                    raise ValueError("LiteDM returned an invalid response.")
                if request_id is not None:
                    value["requestId"] = request_id
                return value
        raise RuntimeError("LiteDM did not return a complete response.")


def _write_message(message: dict) -> None:
    payload = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(struct.pack("<I", len(payload)))
    sys.stdout.buffer.write(payload)
    sys.stdout.buffer.flush()


def main() -> int:
    incoming = sys.stdin.buffer
    _log_diagnostic("Native host started.")
    while True:
        try:
            frame_size = _read_exact(incoming, 4)
            if frame_size is None:
                _log_diagnostic("Browser closed native messaging connection.")
                return 0
            size = struct.unpack("<I", frame_size)[0]
            if size > MAX_MESSAGE_SIZE:
                _write_message({"ok": False, "message": "Native message is too large."})
                continue
            payload = _read_exact(incoming, size)
            if payload is None:
                _write_message({"ok": False, "message": "Native message ended unexpectedly."})
                return 0
            request_id = None
            try:
                message = json.loads(payload.decode("utf-8"))
                request_id = message.get("requestId") if isinstance(message, dict) else None
                response = _forward_request(message)
            except (UnicodeDecodeError, json.JSONDecodeError, OSError, ValueError, RuntimeError) as error:
                _log_diagnostic(f"Request failed: {type(error).__name__}: {error}")
                response = {"ok": False, "message": str(error) or "Could not contact LiteDM."}
                if request_id is not None:
                    response["requestId"] = request_id
            _write_message(response)
        except (OSError, ValueError, struct.error) as error:
            _log_diagnostic(f"Native host failed: {type(error).__name__}: {error}")
            print(f"LiteDM native host: {error}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
