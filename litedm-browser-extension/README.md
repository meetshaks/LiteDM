# LiteDM Browser Extension

Send the current page or a link to LiteDM from Chrome or Firefox. The extension uses the browser's Native Messaging protocol and a user-only local socket; it does not expose a network listener or execute commands from page content.

The extension uses `icons/5_32_px.png` for the 32px icon and `icons/5_48_px.png` for the 48px icon. Matching browser assets are included at 16, 32, 48, and 128 pixels.

## Requirements

- LiteDM running in the current desktop login.
- Python 3 and the LiteDM dependencies already installed.
- Chrome/Chromium or Firefox with extension developer mode enabled for an unpacked install.
- For YouTube URLs, LiteDM opens its format-selection dialog. Choose a format and add it to the queue to complete the browser request.

## Install on Kali Linux

1. Load the extension:
   - **Chrome/Chromium/Brave:** open `chrome://extensions`, enable **Developer mode**, select **Load unpacked**, and choose this `litedm-browser-extension/` folder.
   - **Firefox:** open `about:debugging#/runtime/this-firefox`, select **Load Temporary Add-on**, and choose `manifest.firefox.json` from this folder. A temporary Firefox extension must be loaded again after restarting Firefox.
2. After updating extension files, click **Reload** for LiteDM on `chrome://extensions` (or reload it from Firefox's add-ons debugging page), then refresh the YouTube tab. Start or restart LiteDM if it is not already running. LiteDM automatically registers the local Native Messaging bridge for Chrome, Chromium, Brave, and Firefox in your user account; no extension ID, terminal command, or root access is needed.
3. On a YouTube video page, choose **Download with LiteDM** in the player overlay, then select a format/size to add it directly to the queue. Click a standalone image on other websites to send it to LiteDM while allowing the page's normal navigation to continue. Images inside links (such as video recommendation thumbnails) are left alone so clicking them navigates normally. When right-clicking an image inside a link, the extension downloads the image source rather than the link destination. You can also right-click a link, image, video, audio item, or page and choose **Download with LiteDM**.

Keep LiteDM running while using the extension. The toolbar badge shows the percentage for one active LiteDM download; with multiple active downloads it shows their count. Click the extension to open a table of all queued, downloading, pausing, paused, and cancelling downloads, including downloads added directly in LiteDM and downloads from before this extension update. Use the pause/resume icon on each eligible row to control that download from the popup. To add a download, use the right-click context menu. YouTube requests open LiteDM's metadata/format dialog; confirm **Add to queue** there.

When LiteDM is closed, the toolbar displays an **OFF** badge, the YouTube player button appears inactive, and the extension popup explains that LiteDM must be started. The player button remains clickable so it can show that message; it becomes active automatically after LiteDM connects.

## Security and privacy

- The extension requests `contextMenus` and `nativeMessaging`, plus HTTP/HTTPS page access to detect explicit image clicks. It does not access browser-internal pages.
- Native Messaging restricts Chrome/Chromium/Brave to the extension's fixed ID and Firefox to the ID in its manifest.
- The desktop IPC socket is inside LiteDM's private data directory and accepts connections from the current Unix user only.
- Progress data includes active items from LiteDM's local download queue so the extension popup stays consistent with the desktop application's queue.
- Pause and resume controls send only the selected LiteDM queue item ID and an allow-listed operation over the user-only local socket.
- Requests are limited to HTTP/HTTPS URLs. Embedded URL credentials, malformed messages, and oversized messages are rejected.
- Standalone image URLs are sent only after a trusted user click; images inside links are excluded to avoid downloading thumbnails when following links. The extension does not scan or automatically download images in the background.
- The YouTube player overlay gets format and estimated-size choices from LiteDM's yt-dlp metadata flow; format selections use short-lived one-time tokens and are added to the normal LiteDM queue.
- The bridge transfers only the requested URL and a result message. It does not run shell commands or download page scripts.

## Troubleshooting

- **Red `!` badge:** hover over the extension icon to read the error. Make sure LiteDM is running; if the Native Messaging host was not registered, restart LiteDM and try again.
- **Pause/resume controls unavailable:** restart LiteDM and reload the extension so both sides use the same control-capable protocol.
- **LiteDM is not running:** launch LiteDM before using the extension. Browser requests are not queued while the desktop app is closed.
- **YouTube:** the browser request remains pending while the format-selection dialog is open. Canceling the dialog cancels that browser request.
- **YouTube overlay is missing:** reload the LiteDM extension, then refresh the video tab. The overlay is enabled on `youtube.com`, `www.youtube.com`, and `m.youtube.com` watch pages. If the browser reports `Identifier 'api' has already been declared`, check that only one unpacked LiteDM extension is enabled, reload it, and refresh the tab to discard its previously injected scripts.
- **Firefox extension disappeared after restart:** temporary extensions are removed by Firefox on restart; load the add-on again from `about:debugging`.

To unregister the Native Messaging bridge, run `python3 litedm-browser-extension/install.py --uninstall` from the project root while LiteDM is closed. LiteDM will register it again the next time it starts.
