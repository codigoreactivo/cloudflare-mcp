const HOST_NAME = "com.jesusjhoel.chatgpt_bridge";

let nativePort = null;

function connectNative() {
  if (nativePort) return;
  try {
    nativePort = chrome.runtime.connectNative(HOST_NAME);
    nativePort.onMessage.addListener(handleNativeMessage);
    nativePort.onDisconnect.addListener(() => {
      if (chrome.runtime.lastError) {
        console.warn("Native port desconectado:", chrome.runtime.lastError.message);
      }
      nativePort = null;
    });
    console.log("[chatgpt-bridge] conectado al host nativo");
  } catch (e) {
    console.error("[chatgpt-bridge] no se pudo conectar al host nativo:", e);
    nativePort = null;
  }
}

chrome.runtime.onStartup.addListener(connectNative);
chrome.runtime.onInstalled.addListener(connectNative);
connectNative();

// El service worker de MV3 se puede suspender por inactividad y tumbar el
// puerto nativo. Este alarm periódico reconecta si hace falta.
chrome.alarms.create("keepalive", { periodInMinutes: 0.4 });
chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "keepalive" && !nativePort) {
    connectNative();
  }
});

let dedicatedTabId = null;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

async function handleNativeMessage(msg) {
  if (!msg || msg.type !== "request") return;
  try {
    const tab = await getDedicatedTab();
    await openFreshChat(tab.id);
    const result = await sendToContentScript(tab.id, {
      type: "generate_image",
      prompt: msg.prompt,
      n: msg.n || 1,
    });
    const paths = await downloadImages(result.imageDataUrls, msg.id);
    if (nativePort) nativePort.postMessage({ type: "response", id: msg.id, paths });
  } catch (e) {
    if (nativePort) {
      nativePort.postMessage({
        type: "response",
        id: msg.id,
        error: String((e && e.message) || e),
      });
    }
  }
}

// Usa SIEMPRE una pestaña dedicada, en segundo plano, para no inyectar prompts
// en la conversación que el usuario tenga abierta. El daemon serializa las
// peticiones, así que nunca hay dos generaciones compitiendo por esta pestaña.
async function getDedicatedTab() {
  if (dedicatedTabId !== null) {
    try {
      const tab = await chrome.tabs.get(dedicatedTabId);
      if (tab && /chatgpt\.com|chat\.openai\.com/.test(tab.url || tab.pendingUrl || "")) {
        return tab;
      }
    } catch (e) {
      // la pestaña fue cerrada por el usuario; se recrea abajo
    }
    dedicatedTabId = null;
  }
  const tab = await chrome.tabs.create({ url: "https://chatgpt.com/", active: false });
  dedicatedTabId = tab.id;
  await waitForTabComplete(tab.id);
  return tab;
}

// Arranca una conversación nueva antes de cada petición, para no acumular
// mensajes en un hilo existente ni cruzar respuestas entre peticiones.
async function openFreshChat(tabId) {
  await chrome.tabs.update(tabId, { url: "https://chatgpt.com/" });
  await sleep(400); // deja que el estado de la pestaña pase a "loading"
  await waitForTabComplete(tabId);
  await sleep(1500); // margen para que content.js termine de inicializarse
}

function waitForTabComplete(tabId) {
  return new Promise((resolve, reject) => {
    chrome.tabs.get(tabId, (t) => {
      if (chrome.runtime.lastError || !t) {
        return reject(new Error("La pestaña dedicada ya no existe."));
      }
      if (t.status === "complete") return resolve();
      const listener = (id, info) => {
        if (id === tabId && info.status === "complete") {
          chrome.tabs.onUpdated.removeListener(listener);
          resolve();
        }
      };
      chrome.tabs.onUpdated.addListener(listener);
    });
  });
}

// Margen por encima del timeout interno de content.js (180s por defecto
// esperando la respuesta de ChatGPT) más tiempo para el fetch de la imagen.
// Es una red de seguridad: si el mensaje se pierde o la pestaña muere sin
// que content.js llegue a responder, esto evita un cuelgue indefinido.
const CONTENT_SCRIPT_TIMEOUT_MS = 210000;

function sendToContentScript(tabId, message, timeoutMs = CONTENT_SCRIPT_TIMEOUT_MS) {
  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error(`Timeout (${timeoutMs / 1000}s) esperando respuesta del content script`));
    }, timeoutMs);

    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (settled) return; // ya se rechazó por timeout
      settled = true;
      clearTimeout(timer);
      if (chrome.runtime.lastError) {
        return reject(new Error(chrome.runtime.lastError.message));
      }
      if (!response) return reject(new Error("Sin respuesta del content script"));
      if (response.error) return reject(new Error(response.error));
      resolve(response);
    });
  });
}

const MIME_TO_EXT = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/gif": "gif",
};

function extensionFromDataUrl(dataUrl) {
  const dataMatch = /^data:([^;,]+)[;,]/.exec(dataUrl || "");
  if (dataMatch) {
    const mime = dataMatch[1].toLowerCase();
    return MIME_TO_EXT[mime] || "png";
  }
  // Fallback: si content.js no pudo convertir la imagen a data URL (p.ej.
  // CORS) y devolvió la URL https cruda, se intenta inferir la extensión de
  // la propia URL antes de asumir ".png".
  try {
    const pathname = new URL(dataUrl).pathname.toLowerCase();
    const urlMatch = /\.(png|jpe?g|webp|gif)(?:$|[/?#])/.exec(pathname);
    if (urlMatch) {
      return urlMatch[1] === "jpeg" ? "jpg" : urlMatch[1];
    }
  } catch (e) {
    // dataUrl no es una URL válida; se usa el default de abajo.
  }
  return "png";
}

async function downloadImages(dataUrls, requestId) {
  const paths = [];
  for (let i = 0; i < dataUrls.length; i++) {
    const ext = extensionFromDataUrl(dataUrls[i]);
    const filename = `chatgpt_bridge/${requestId}_${i}.${ext}`;
    const downloadId = await new Promise((resolve, reject) => {
      chrome.downloads.download(
        { url: dataUrls[i], filename, conflictAction: "uniquify" },
        (id) => {
          if (chrome.runtime.lastError || id === undefined) {
            return reject(
              new Error(
                chrome.runtime.lastError
                  ? chrome.runtime.lastError.message
                  : "fallo de descarga"
              )
            );
          }
          resolve(id);
        }
      );
    });
    const filePath = await waitForDownloadComplete(downloadId);
    paths.push(filePath);
  }
  return paths;
}

function waitForDownloadComplete(downloadId) {
  return new Promise((resolve, reject) => {
    function listener(delta) {
      if (delta.id !== downloadId) return;
      if (delta.state && delta.state.current === "complete") {
        chrome.downloads.onChanged.removeListener(listener);
        chrome.downloads.search({ id: downloadId }, (results) => {
          resolve(results[0] ? results[0].filename : null);
        });
      } else if (delta.state && delta.state.current === "interrupted") {
        chrome.downloads.onChanged.removeListener(listener);
        reject(new Error("Descarga interrumpida"));
      }
    }
    chrome.downloads.onChanged.addListener(listener);
  });
}
