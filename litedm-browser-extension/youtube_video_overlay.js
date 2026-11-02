(() => {
"use strict";

const youtubeExtensionApi = globalThis.browser || globalThis.chrome;
const supportedPath = () => /^\/(watch|shorts|live|embed)(\/|$)/.test(location.pathname);
let mountedPlayer = null;
let mountedUrl = "";
let shadowRoot = null;
let currentVideoToken = "";
let currentFormats = [];
let formatLoadState = "idle";
let formatLoadError = "";
let formatRequest = null;
let videoGeneration = 0;
let liteDMConnected = false;
let unavailableMessageTimer = null;

function sendMessage(message) {
  if (globalThis.browser) {
    return youtubeExtensionApi.runtime.sendMessage(message);
  }
  return new Promise((resolve, reject) => {
    youtubeExtensionApi.runtime.sendMessage(message, (response) => {
      const error = youtubeExtensionApi.runtime.lastError;
      if (error) {
        reject(new Error(error.message));
      } else if (!response?.ok) {
        reject(new Error(response?.message || "LiteDM could not complete the request."));
      } else {
        resolve(response);
      }
    });
  });
}

function setConnectionState(connected) {
  liteDMConnected = connected;
  const trigger = shadowRoot?.querySelector(".trigger");
  if (!trigger) {
    return;
  }
  trigger.classList.toggle("inactive", !connected);
  trigger.title = connected
    ? "Download with LiteDM"
    : "LiteDM is not running";
}

youtubeExtensionApi.runtime.onMessage.addListener((message) => {
  if (message?.type === "litedm-connection") {
    setConnectionState(message.connected === true);
  }
});

function setMessage(text) {
  const status = shadowRoot?.querySelector(".status");
  if (status) {
    status.textContent = text;
    status.hidden = !text;
  }
}

function hideMenu() {
  const menu = shadowRoot?.querySelector(".menu");
  if (menu) {
    menu.hidden = true;
    menu.replaceChildren();
  }
  setMessage("");
}

async function openFormatMenu() {
  const menu = shadowRoot.querySelector(".menu");
  menu.replaceChildren();
  if (formatLoadState === "ready") {
    for (const format of currentFormats) {
      const option = document.createElement("button");
      option.type = "button";
      option.className = "format";
      option.textContent = format.label;
      option.addEventListener("click", async () => {
        menu.querySelectorAll("button").forEach((button) => {
          button.disabled = true;
        });
        setMessage("Adding to LiteDM…");
        try {
          await sendMessage({
            type: "youtube-add",
            videoToken: currentVideoToken,
            choiceId: format.id
          });
          hideMenu();
        } catch (error) {
          setMessage(error.message);
          menu.querySelectorAll("button").forEach((button) => {
            button.disabled = false;
          });
        }
      });
      menu.append(option);
    }
    menu.hidden = false;
    setMessage("");
    return;
  }

  menu.hidden = false;
  const message = document.createElement("div");
  message.className = "format";
  message.textContent = formatLoadError || "Formats are not ready yet.";
  menu.append(message);
  if (formatLoadState === "error") {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "format";
    retry.textContent = "Retry";
    retry.addEventListener("click", () => {
      menu.hidden = true;
      void preloadFormats(mountedUrl);
    });
    menu.append(retry);
  }
}

async function preloadFormats(url) {
  if (!url || url !== mountedUrl) {
    return;
  }
  if (formatRequest) {
    return formatRequest;
  }

  const generation = videoGeneration;
  formatLoadState = "loading";
  formatLoadError = "";
  const trigger = shadowRoot?.querySelector(".trigger");
  if (trigger) {
    trigger.disabled = true;
    trigger.title = "Preparing video formats";
  }

  const request = sendMessage({ type: "youtube-formats", url });
  formatRequest = request;
  try {
    const response = await request;
    if (generation !== videoGeneration || url !== mountedUrl) {
      return;
    }
    currentVideoToken = response.video_token;
    currentFormats = response.formats;
    formatLoadState = "ready";
  } catch (error) {
    if (generation !== videoGeneration || url !== mountedUrl) {
      return;
    }
    formatLoadError = error.message;
    formatLoadState = "error";
  } finally {
    if (generation === videoGeneration) {
      formatRequest = null;
      if (trigger) {
        trigger.disabled = false;
        trigger.title = formatLoadState === "ready"
          ? "Download with LiteDM"
          : "Format lookup failed; click for details";
      }
    }
  }
}

function mountOverlay(player) {
  if (mountedPlayer === player && mountedUrl === location.href) {
    return;
  }
  if (mountedPlayer?.querySelector(".litedm-youtube-overlay")) {
    mountedPlayer.querySelector(".litedm-youtube-overlay").remove();
  }
  mountedPlayer = player;
  mountedUrl = location.href;
  videoGeneration += 1;
  formatRequest = null;
  currentFormats = [];
  formatLoadState = "idle";
  formatLoadError = "";
  currentVideoToken = "";

  const host = document.createElement("div");
  host.className = "litedm-youtube-overlay";
  host.style.cssText = "position:absolute;top:12px;right:12px;z-index:2147483647;";
  shadowRoot = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = `
    :host { all: initial; font-family: Arial, sans-serif; }
    .wrap { position: relative; display: flex; flex-direction: column; align-items: flex-end; gap: 6px; }
    .trigger { display: grid; width: 42px; height: 42px; place-items: center; border: 2px solid #fff; border-radius: 50%; padding: 0; background: #0e7490; color: #fff; font: 700 24px/1 Arial, sans-serif; cursor: pointer; box-shadow: 0 2px 10px #0009; }
    .trigger:hover:not(:disabled) { background: #155e75; }
    .trigger.inactive { border-color: #94a3b8; background: #64748b; opacity: .62; }
    .trigger.inactive:hover { background: #475569; opacity: .9; }
    .trigger:disabled { opacity: .72; cursor: wait; }
    .menu { width: 230px; max-height: 280px; overflow: auto; padding: 4px; border: 1px solid #cbd5e1; border-radius: 7px; background: #fff; box-shadow: 0 6px 20px #0005; }
    .menu[hidden], .status[hidden] { display: none; }
    .format { display: block; width: 100%; border: 0; border-radius: 4px; padding: 8px 10px; background: #fff; color: #172033; text-align: left; font: 13px/1.3 Arial, sans-serif; cursor: pointer; }
    .format:hover:not(:disabled) { background: #e0f2fe; color: #075985; }
    .format:disabled { color: #64748b; cursor: wait; }
    .status { max-width: 260px; padding: 7px 9px; border-radius: 5px; background: #fff; color: #334155; font: 12px/1.3 Arial, sans-serif; box-shadow: 0 2px 8px #0004; }
  `;
  const wrap = document.createElement("div");
  wrap.className = "wrap";
  const trigger = document.createElement("button");
  trigger.type = "button";
  trigger.className = "trigger";
  trigger.textContent = "↓";
  trigger.disabled = true;
  trigger.setAttribute("aria-label", "Download this YouTube video with LiteDM");
  trigger.title = "Download with LiteDM";
  trigger.addEventListener("click", () => {
    if (!liteDMConnected) {
      setMessage("Start LiteDM to choose a video format.");
      clearTimeout(unavailableMessageTimer);
      unavailableMessageTimer = setTimeout(() => setMessage(""), 4000);
      return;
    }
    const menu = shadowRoot.querySelector(".menu");
    if (menu.hidden) {
      void openFormatMenu();
    } else {
      hideMenu();
    }
  });
  const status = document.createElement("div");
  status.className = "status";
  status.setAttribute("role", "status");
  status.hidden = true;
  const menu = document.createElement("div");
  menu.className = "menu";
  menu.hidden = true;
  wrap.append(trigger, status, menu);
  shadowRoot.append(style, wrap);
  player.append(host);
  setConnectionState(false);
  void sendMessage({ type: "get-app-status" })
    .then((response) => setConnectionState(response.connected === true))
    .catch(() => setConnectionState(false));
  void preloadFormats(mountedUrl);
}

function findPlayer() {
  if (!supportedPath()) {
    return;
  }
  const player = document.querySelector("#movie_player");
  if (player) {
    mountOverlay(player);
  }
}

const observer = new MutationObserver(findPlayer);
observer.observe(document.documentElement, { childList: true, subtree: true });
window.addEventListener("popstate", findPlayer);
setInterval(findPlayer, 1000);
findPlayer();
})();
