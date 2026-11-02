(() => {
"use strict";

const api = globalThis.browser || globalThis.chrome;

document.addEventListener("click", (event) => {
  if (!event.isTrusted || !(event.target instanceof Element)) {
    return;
  }
  if (location.hostname.endsWith("youtube.com")) {
    return;
  }

  const image = event.target.closest("img");
  if (!image) {
    return;
  }
  if (image.closest("a")) {
    return;
  }

  const imageUrl = image.currentSrc || image.src;
  if (!/^https?:\/\//i.test(imageUrl)) {
    return;
  }

  api.runtime.sendMessage({ type: "download-image-click", url: imageUrl });
}, true);
  })();
