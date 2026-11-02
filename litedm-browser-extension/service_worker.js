"use strict";

const HOST_NAME = "com.litedm.native";
const api = globalThis.browser || globalThis.chrome;
const pendingRequests = new Map();
let nativePort = null;
let nextRequestId = 1;
let reconnectTimer = null;
let statusRequestInFlight = false;
let latestDownloads = [];
let controlsSupported = false;
let liteDMConnected = false;

function setActionBadge(text, title, color = "#2563eb") {
  const action = api.action || api.browserAction;
  if (!action) {
    return;
  }
  action.setBadgeBackgroundColor({ color });
  action.setBadgeText({ text });
  action.setTitle({ title });
}

function setConnectionState(connected) {
  if (liteDMConnected === connected) {
    if (!connected) {
      setActionBadge("OFF", "LiteDM is not running. Start LiteDM to use the extension.", "#64748b");
    }
    return;
  }
  liteDMConnected = connected;
  if (!connected) {
    setActionBadge("OFF", "LiteDM is not running. Start LiteDM to use the extension.", "#64748b");
  }
  void api.runtime.sendMessage({
    type: "litedm-connection",
    connected
  }).catch(() => {});
}

function updateProgress(downloads) {
  latestDownloads = Array.isArray(downloads) ? downloads : [];
  if (!liteDMConnected) {
    setActionBadge("OFF", "LiteDM is not running. Start LiteDM to use the extension.", "#64748b");
    return;
  }
  const active = latestDownloads.filter((download) =>
    ["downloading", "pausing", "cancelling"].includes(download.status)
  );
  if (active.length === 1) {
    const download = active[0];
    const total = Number(download.total_bytes);
    const received = Number(download.downloaded_bytes);
    const percent = total > 0
      ? `${Math.min(100, Math.floor((received / total) * 100))}%`
      : "…";
    setActionBadge(
      percent,
      `${download.name}: ${percent} downloaded`
    );
  } else if (active.length > 1) {
    const names = active.map((download) => download.name).join(", ");
    setActionBadge(
      String(active.length),
      `${active.length} LiteDM downloads in progress: ${names}`
    );
  } else {
    setActionBadge(
      "",
      latestDownloads.length
        ? "Click to view queued or paused LiteDM downloads"
        : "Download current page with LiteDM"
    );
  }
}

function connectNativeHost() {
  if (nativePort) {
    return nativePort;
  }
  try {
    const port = api.runtime.connectNative(HOST_NAME);
    nativePort = port;
    port.onMessage.addListener((response) => {
      const pending = pendingRequests.get(response?.requestId);
      if (pending) {
        clearTimeout(pending.timeout);
        pendingRequests.delete(response.requestId);
        pending.resolve(response);
      }
      if (response?.action === "status") {
        setConnectionState(response.ok === true);
        updateProgress(response.downloads);
      }
    });
    port.onDisconnect.addListener(() => {
      const error = api.runtime.lastError;
      nativePort = null;
      setConnectionState(false);
      for (const [requestId, pending] of pendingRequests) {
        clearTimeout(pending.timeout);
        pending.reject(new Error(error?.message || "LiteDM native host disconnected."));
        pendingRequests.delete(requestId);
      }
      updateProgress([]);
      if (!reconnectTimer) {
        reconnectTimer = setTimeout(() => {
          reconnectTimer = null;
          connectNativeHost();
          void refreshProgress();
        }, 3000);
      }
    });
    return port;
  } catch (error) {
    setConnectionState(false);
    return null;
  }
}

function requestNative(message) {
  const port = connectNativeHost();
  if (!port) {
    return Promise.reject(new Error("Could not connect to LiteDM."));
  }
  const requestId = nextRequestId++;
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      pendingRequests.delete(requestId);
      reject(new Error("LiteDM did not respond in time."));
    }, message.action === "download" ? 300000
      : message.action === "youtube_formats" ? 90000
        : 10000);
    pendingRequests.set(requestId, { resolve, reject, timeout });
    try {
      port.postMessage({ ...message, requestId });
    } catch (error) {
      clearTimeout(timeout);
      pendingRequests.delete(requestId);
      reject(error);
    }
  });
}

async function refreshProgress() {
  if (statusRequestInFlight || !nativePort) {
    return latestDownloads;
  }
  statusRequestInFlight = true;
  try {
    const response = await requestNative({ action: "status" });
    if (!response?.ok) {
      throw new Error(response?.message || "Could not read LiteDM download status.");
    }
    setConnectionState(true);
    controlsSupported = response.controls_supported === true;
    updateProgress(response.downloads);
    return latestDownloads;
  } catch (_error) {
    setConnectionState(false);
    return latestDownloads;
  } finally {
    statusRequestInFlight = false;
  }
}

async function sendToLiteDM(url) {
  if (typeof url !== "string" || !/^https?:\/\//i.test(url)) {
    setActionBadge("", "LiteDM accepts HTTP and HTTPS URLs.");
    return { ok: false, message: "LiteDM accepts HTTP and HTTPS URLs." };
  }
  try {
    const response = await requestNative({ action: "download", url });
    if (!response?.ok) {
      setActionBadge("", response?.message || "LiteDM could not add this download.");
      return response || { ok: false, message: "LiteDM did not respond." };
    }
    await refreshProgress();
    return response;
  } catch (error) {
    setActionBadge("", `LiteDM: ${error.message}`);
    return { ok: false, message: error.message };
  }
}

api.runtime.onInstalled.addListener(() => {
  api.contextMenus.create({
    id: "litedm-download",
    title: "Download with LiteDM",
    contexts: ["link", "image", "page", "video", "audio"]
  });
  connectNativeHost();
  void refreshProgress();
});

api.runtime.onStartup?.addListener(() => {
  connectNativeHost();
  void refreshProgress();
});

api.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "get-downloads") {
    refreshProgress().then(() => sendResponse({
      ok: true,
      downloads: latestDownloads,
      controlsSupported,
      connected: liteDMConnected
    }));
    return true;
  }
  if (message?.type === "get-app-status") {
    refreshProgress().then(() => sendResponse({
      ok: true,
      connected: liteDMConnected
    }));
    return true;
  }
  if (message?.type === "control-download") {
    requestNative({
      action: "control",
      download_id: message.downloadId,
      operation: message.operation
    }).then(async (response) => {
      if (!response?.ok) {
        throw new Error(response?.message || "Could not control the download.");
      }
      sendResponse(response);
      await refreshProgress();
    }).catch((error) => {
      sendResponse({ ok: false, message: error.message });
    });
    return true;
  }
  if (message?.type === "download-image-click") {
    sendToLiteDM(message.url).then(sendResponse, (error) => {
      sendResponse({ ok: false, message: error.message });
    });
    return true;
  }
  if (message?.type === "youtube-formats" || message?.type === "youtube-add") {
    const senderUrl = _sender.url || "";
    if (!/^https:\/\/(?:www\.|m\.)?youtube\.com\//i.test(senderUrl)) {
      sendResponse({ ok: false, message: "YouTube player requests are only accepted from youtube.com." });
      return false;
    }
    const request = message.type === "youtube-formats"
      ? { action: "youtube_formats", url: message.url }
      : {
          action: "youtube_add",
          video_token: message.videoToken,
          choice_id: message.choiceId
        };
    requestNative(request).then(sendResponse, (error) => {
      sendResponse({ ok: false, message: error.message });
    });
    return true;
  }
  return false;
});

api.contextMenus.onClicked.addListener((info, tab) => {
  const url = info.srcUrl || info.linkUrl || info.pageUrl || tab?.url;
  void sendToLiteDM(url);
});

connectNativeHost();
void refreshProgress();
setInterval(() => void refreshProgress(), 1000);
