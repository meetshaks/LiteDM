from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path

HOST_NAME = "com.litedm.native"
FIREFOX_EXTENSION_ID = "browser-extension@litedm.local"


def _extension_directory() -> Path:
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        return Path(bundle_dir) / "litedm-browser-extension"
    return Path(__file__).resolve().parents[1] / "litedm-browser-extension"


def _chrome_extension_id(manifest: dict) -> str:
    try:
        public_key = base64.b64decode(manifest["key"], validate=True)
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("The Chrome extension manifest must contain a valid public key.") from error
    digest = hashlib.sha256(public_key).digest()[:16]
    return "".join(
        chr(ord("a") + nibble)
        for byte in digest
        for nibble in (byte >> 4, byte & 0x0F)
    )


def _write_private_file(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(contents)
        os.chmod(temporary_path, stat.S_IRUSR | stat.S_IWUSR)
        os.replace(temporary_path, path)
    finally:
        try:
            os.unlink(temporary_path)
        except FileNotFoundError:
            pass


def register_browser_native_host(
    extension_directory: Path | None = None,
    home_directory: Path | None = None,
) -> list[Path]:
    extension_directory = extension_directory or _extension_directory()
    home_directory = home_directory or Path.home()
    source_host = extension_directory / "native_host.py"
    chrome_manifest_path = extension_directory / "manifest.json"
    firefox_manifest_path = extension_directory / "manifest.firefox.json"
    if not source_host.is_file():
        raise FileNotFoundError(f"LiteDM native host script is missing: {source_host}")

    chrome_manifest = json.loads(chrome_manifest_path.read_text(encoding="utf-8"))
    firefox_manifest = json.loads(firefox_manifest_path.read_text(encoding="utf-8"))
    chrome_id = _chrome_extension_id(chrome_manifest)
    firefox_id = firefox_manifest["browser_specific_settings"]["gecko"]["id"]

    host_directory = home_directory / ".local" / "lib" / "litedm-browser-extension"
    host_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(host_directory, 0o700)
    installed_host = host_directory / "native_host.py"
    shutil.copyfile(source_host, installed_host)
    os.chmod(installed_host, 0o700)

    registrations = (
        (
            home_directory / ".config/google-chrome/NativeMessagingHosts",
            "chrome",
            [f"chrome-extension://{chrome_id}/"],
        ),
        (
            home_directory / ".config/chromium/NativeMessagingHosts",
            "chrome",
            [f"chrome-extension://{chrome_id}/"],
        ),
        (
            home_directory
            / ".config/BraveSoftware/Brave-Browser/NativeMessagingHosts",
            "chrome",
            [f"chrome-extension://{chrome_id}/"],
        ),
        (
            home_directory / ".mozilla/native-messaging-hosts",
            "firefox",
            [firefox_id],
        ),
    )
    registered_manifests = []
    for directory, browser, allowed_ids in registrations:
        host_manifest = {
            "name": HOST_NAME,
            "description": "Secure bridge to the LiteDM desktop application",
            "path": str(installed_host),
            "type": "stdio",
            "args": [],
        }
        if browser == "chrome":
            host_manifest["allowed_origins"] = allowed_ids
        else:
            host_manifest["allowed_extensions"] = allowed_ids
        manifest_path = directory / f"{HOST_NAME}.json"
        _write_private_file(manifest_path, json.dumps(host_manifest, indent=2) + "\n")
        registered_manifests.append(manifest_path)
    return registered_manifests
