"use strict";

const api = globalThis.browser || globalThis.chrome;
const downloadsBody = document.getElementById("downloads");
const summary = document.getElementById("summary");
const empty = document.getElementById("empty");
const message = document.getElementById("message");
let controlsSupported = false;
const pendingControls = new Map();
const statusNames = {
  downloading: "Downloading",
  pausing: "Pausing",
  paused: "Paused",
  queued: "Queued",
  cancelling: "Cancelling"
};

function formatSize(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) {
    return "—";
  }
  if (bytes < 1024) {
    return `${Math.floor(bytes)} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let unit = units[0];
  for (let index = 1; value >= 1024 && index < units.length; index += 1) {
    value /= 1024;
    unit = units[index];
  }
  return `${value.toFixed(1)} ${unit}`;
}

function progressCell(download) {
  const received = Number(download.downloaded_bytes);
  const total = Number(download.total_bytes);
  const wrapper = document.createElement("div");
  const label = document.createElement("div");
  const bar = document.createElement("progress");
  bar.max = 100;
  if (total > 0) {
    const percent = Math.min(100, received / total * 100);
    label.textContent = `${Math.floor(percent)}% · ${formatSize(received)} / ${formatSize(total)}`;
    bar.value = percent;
  } else {
    label.textContent = `${formatSize(received)} downloaded · size unknown`;
    bar.removeAttribute("value");
  }
  wrapper.append(label, bar);
  return wrapper;
}

function render(downloads) {
  downloadsBody.replaceChildren();
  const items = Array.isArray(downloads) ? downloads : [];
  summary.textContent = items.length
    ? `${items.length} LiteDM download${items.length === 1 ? "" : "s"}`
    : "No downloads in progress";
  empty.hidden = items.length > 0;
  for (const download of items) {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    name.className = "file-name";
    name.textContent = download.name || "Download";
    name.title = download.name || "Download";
    const progress = document.createElement("td");
    progress.className = "progress-detail";
    progress.append(progressCell(download));
    const status = document.createElement("td");
    status.className = "status-cell";
    const statusContent = document.createElement("div");
    statusContent.className = "status-content";
    const statusLabel = document.createElement("span");
    statusLabel.className = `status-label status-${download.status || "unknown"}`;
    statusLabel.textContent = statusNames[download.status] || download.status || "Unknown";
    statusContent.append(statusLabel);
    const operation = download.status === "paused"
      ? { action: "resume", icon: "▶", label: "Resume download" }
      : ["queued", "downloading"].includes(download.status)
        ? { action: "pause", icon: "Ⅱ", label: "Pause download" }
        : null;
    if (controlsSupported && operation && download.id) {
      const control = document.createElement("button");
      control.type = "button";
      control.className = "download-control";
      const pending = pendingControls.get(download.id);
      if (pending) {
        const spinner = document.createElement("span");
        spinner.className = "control-spinner";
        spinner.setAttribute("aria-hidden", "true");
        control.append(spinner);
        control.disabled = true;
        control.setAttribute("aria-busy", "true");
        control.setAttribute(
          "aria-label",
          `${pending.operation === "pause" ? "Pausing" : "Resuming"}: ${download.name || "Download"}`
        );
        control.title = pending.operation === "pause" ? "Pausing…" : "Resuming…";
      } else {
        control.textContent = operation.icon;
        control.setAttribute("aria-label", `${operation.label}: ${download.name || "Download"}`);
        control.title = operation.label;
        control.addEventListener("click", () => {
          void controlDownload(download.id, operation.action, control, download.name || "Download");
        });
      }
      statusContent.append(control);
    }
    status.append(statusContent);
    row.append(name, progress, status);
    downloadsBody.append(row);
  }
}

function showControlLoading(button, operation, name) {
  const spinner = document.createElement("span");
  spinner.className = "control-spinner";
  spinner.setAttribute("aria-hidden", "true");
  button.replaceChildren(spinner);
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  button.setAttribute(
    "aria-label",
    `${operation === "pause" ? "Pausing" : "Resuming"}: ${name}`
  );
  button.title = operation === "pause" ? "Pausing…" : "Resuming…";
}

async function controlDownload(downloadId, operation, button, name) {
  const timeout = setTimeout(() => {
    pendingControls.delete(downloadId);
    message.textContent = "LiteDM did not confirm the download state change in time.";
    message.hidden = false;
    void refresh();
  }, 30000);
  pendingControls.set(downloadId, { operation, accepted: false, timeout });
  showControlLoading(button, operation, name);
  void refresh();
  try {
    const response = await sendMessage({
      type: "control-download",
      downloadId,
      operation
    });
    if (!response?.ok) {
      throw new Error(response?.message || "Could not control the download.");
    }
    const pending = pendingControls.get(downloadId);
    if (pending) {
      pending.accepted = true;
    }
    await refresh();
  } catch (error) {
    clearTimeout(timeout);
    pendingControls.delete(downloadId);
    message.textContent = error.message;
    message.hidden = false;
    await refresh();
  }
}

function sendMessage(request) {
  return new Promise((resolve, reject) => {
    api.runtime.sendMessage(request, (response) => {
      const error = api.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
      } else {
        resolve(response);
      }
    });
  });
}

async function refresh() {
  try {
    const response = await sendMessage({ type: "get-downloads" });
    if (!response?.ok) {
      throw new Error(response?.message || "Could not read LiteDM downloads.");
    }
    if (response.connected !== true) {
      controlsSupported = false;
      downloadsBody.replaceChildren();
      summary.textContent = "LiteDM is not running";
      empty.hidden = true;
      message.textContent = "Start LiteDM to send downloads and view your queue.";
      message.hidden = false;
      return;
    }
    controlsSupported = response.controlsSupported === true;
    const downloads = Array.isArray(response.downloads) ? response.downloads : [];
    for (const [downloadId, pending] of pendingControls) {
      if (!pending.accepted) {
        continue;
      }
      const download = downloads.find((item) => item.id === downloadId);
      const isComplete = pending.operation === "pause"
        ? download?.status === "paused"
        : ["queued", "downloading"].includes(download?.status);
      if (isComplete) {
        clearTimeout(pending.timeout);
        pendingControls.delete(downloadId);
      }
    }
    render(downloads);
    if (controlsSupported) {
      message.hidden = true;
    } else {
      message.textContent = "Pause and resume require the updated LiteDM app. Restart LiteDM and reload this extension.";
      message.hidden = false;
    }
  } catch (error) {
    summary.textContent = "LiteDM connection unavailable";
    message.textContent = `Start LiteDM to send downloads and view your queue. Details: ${error.message}`;
    message.hidden = false;
  }
}

void refresh();
setInterval(() => void refresh(), 1500);
