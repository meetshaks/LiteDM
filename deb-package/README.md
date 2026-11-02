# Build a LiteDM Debian package

From this folder, run:

```bash
./build_deb.sh
```

The script uses the project's `.venv` when available, builds the PyInstaller
application, and packages the executable, application icon, and desktop menu
entry. Temporary
build and staging files are created inside this folder and removed afterward.
The resulting architecture-specific package is saved here as
`litedm_<version>_<architecture>.deb`.

To install it on a Debian-based system:

```bash
sudo apt install ./litedm_1.4.8_amd64.deb
```

Use the actual filename printed by the build script if the version or
architecture differs. To customize the package maintainer field:

```bash
MAINTAINER="Your Name <you@example.com>" ./build_deb.sh
```

The package bundles the current browser-extension files and yt-dlp resources.
After installing or upgrading LiteDM, restart the app and reload the unpacked
browser extension if you use it.

Build on the oldest Linux release you intend to support. The package bundles
the Python application but depends on the host's Qt/X11 runtime libraries.
