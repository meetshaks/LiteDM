#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

HOST_NAME = "com.litedm.native"
FIREFOX_EXTENSION_ID = "browser-extension@litedm.local"


def native_host_manifest(script_path: str, browser: str) -> dict:
    manifest = {
        "name": HOST_NAME,
        "description": "Secure bridge to the LiteDM desktop application",
        "path": script_path,
        "type": "stdio",
        "args": [],
    }
    if browser in {"chrome", "chromium"}:
        manifest["allowed_origins"] = []
    else:
        manifest["allowed_extensions"] = [FIREFOX_EXTENSION_ID]
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the LiteDM browser native-messaging host.")
    parser.add_argument(
        "chrome_extension_id",
        nargs="?",
        help="Chrome extension ID shown at chrome://extensions (32 letters a-p).",
    )
    parser.add_argument("--uninstall", action="store_true", help="Remove native-host manifests.")
    parser.add_argument(
        "--browsers",
        nargs="+",
        choices=("chrome", "chromium", "brave", "firefox"),
        default=("chrome", "chromium", "brave", "firefox"),
        help="Browsers to register (default: chrome chromium brave firefox).",
    )
    args = parser.parse_args()

    home = Path.home()
    host_directory = home / ".local" / "lib" / "litedm-browser-extension"
    host_script = host_directory / "native_host.py"
    manifest_directories = [
        (home / ".config" / "google-chrome" / "NativeMessagingHosts", "chrome"),
        (home / ".config" / "chromium" / "NativeMessagingHosts", "chromium"),
        (
            home / ".config" / "BraveSoftware" / "Brave-Browser" / "NativeMessagingHosts",
            "brave",
        ),
        (home / ".mozilla" / "native-messaging-hosts", "firefox"),
    ]

    if args.uninstall:
        for directory, _browser in manifest_directories:
            manifest_path = directory / f"{HOST_NAME}.json"
            manifest_path.unlink(missing_ok=True)
        host_script.unlink(missing_ok=True)
        try:
            host_directory.rmdir()
        except OSError:
            pass
        print("Removed LiteDM native-messaging host manifests.")
        return 0

    if {"chrome", "chromium", "brave"}.intersection(args.browsers) and (
        not args.chrome_extension_id
        or not re.fullmatch(r"[a-p]{32}", args.chrome_extension_id)
    ):
        parser.error("Provide the Chrome extension ID (32 letters a-p) from chrome://extensions.")
    extension_directory = Path(__file__).resolve().parent
    source_host = extension_directory / "native_host.py"
    if not source_host.is_file():
        parser.error(f"Native host script is missing: {source_host}")
    host_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    shutil.copyfile(source_host, host_script)
    host_script.chmod(0o700)
    for directory, browser in manifest_directories:
        if browser not in args.browsers:
            continue
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        manifest = native_host_manifest(str(host_script), browser)
        if browser in {"chrome", "chromium", "brave"}:
            manifest["allowed_origins"] = [
                f"chrome-extension://{args.chrome_extension_id}/"
            ]
        manifest_path = directory / f"{HOST_NAME}.json"
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        manifest_path.chmod(0o600)

    browser_names = {
        "chrome": "Chrome",
        "chromium": "Chromium",
        "brave": "Brave",
        "firefox": "Firefox",
    }
    selected_browsers = ", ".join(browser_names[name] for name in args.browsers)
    print(f"Installed LiteDM native-messaging host for {selected_browsers}.")
    print(f"Native host: {host_script}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
