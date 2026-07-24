// Selectores centralizados: la interfaz de chatgpt.com cambia con frecuencia.
// Si algo deja de funcionar, abre DevTools sobre el elemento en cuestión y
// actualiza el selector correspondiente aquí.
const SELECTORS = {
  composer: [
    "#prompt-textarea",
    'div[contenteditable="true"].ProseMirror',
    'form div[contenteditable="true"]',
  ],
  sendButton: [
    'button[data-testid="send-button"]',
    'button[aria-label="Send prompt"]',
  ],
  stopButton: [
    'button[data-testid="stop-button"]',
    'button[aria-label="Stop generating"]',
  ],
  // `[data-message-author-role="assistant"]` solo existe mientras el mensaje
  // está en streaming activo; una vez la conversación se asienta, ese
  // atributo desaparece del DOM (verificado en vivo: 0 coincidencias en una
  // conversación ya completada). `data-testid="conversation-turn-N"` es la
  // marca estable que persiste en el estado final; los turnos alternan
  // usuario/asistente en orden estricto, así que el último turno del DOM es
  // siempre el más reciente.
  conversationTurn: '[data-testid^="conversation-turn-"]',
};

function querySelectorFirst(selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function jitter(min, max) {
  return min + Math.random() * (max - min);
}

function blobToDataURL(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("No se pudo leer el contenido de la imagen"));
    reader.readAsDataURL(blob);
  });
}

// Las imágenes de ChatGPT se sirven desde una URL firmada (con token/expiry
// en la query string) que chrome.downloads no siempre puede resolver desde
// el service worker (no comparte la sesión de la pestaña). Por eso se
// descarga aquí, en el content script —que sí corre con la sesión de la
// página—, y se devuelve como data URL para que background.js la pase tal
// cual a chrome.downloads.download.
//
// Si esa URL firmada vive en un dominio distinto al de la página (p.ej. un
// bucket de un CDN), fetch() puede fallar por CORS aunque la misma URL cargue
// bien como <img src> (las <img> no están sujetas a CORS; fetch sí). Por eso
// se limita con un timeout y el llamador hace fallback a la URL cruda si esto
// falla, en vez de abortar toda la generación.
async function fetchAsDataURL(url, timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const resp = await fetch(url, { signal: controller.signal });
    if (!resp.ok) {
      throw new Error(`No se pudo descargar la imagen (HTTP ${resp.status})`);
    }
    const blob = await resp.blob();
    return await blobToDataURL(blob);
  } catch (e) {
    if (e && e.name === "AbortError") {
      throw new Error(`Timeout (${timeoutMs / 1000}s) descargando la imagen`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

// Teclea el prompt en trozos con pausas irregulares en vez de pegarlo de golpe,
// para que la interacción con la página no sea un evento instantáneo y robótico.
// Es un maquillaje "lite" de cara a heurísticas simples; NO derrota una
// detección de automatización del lado del servidor (ver README).
async function typeLikeHuman(composer, text) {
  composer.focus();
  const chunk = 3;
  for (let i = 0; i < text.length; i += chunk) {
    document.execCommand("insertText", false, text.slice(i, i + chunk));
    composer.dispatchEvent(new InputEvent("input", { bubbles: true }));
    await sleep(jitter(25, 110));
  }
}

async function sendPromptAndWaitForImages(prompt, timeoutMs = 180000) {
  const composer = querySelectorFirst(SELECTORS.composer);
  if (!composer) {
    throw new Error(
      "No se encontró el cuadro de texto (composer). Revisa/actualiza SELECTORS.composer en content.js."
    );
  }
  await typeLikeHuman(composer, prompt);
  // Pequeña pausa de "pensar" antes de enviar.
  await sleep(jitter(400, 1400));

  const sendBtn = querySelectorFirst(SELECTORS.sendButton);
  if (!sendBtn || sendBtn.disabled) {
    throw new Error(
      "No se encontró el botón de enviar o está deshabilitado. Revisa/actualiza SELECTORS.sendButton."
    );
  }

  const turnsBefore = document.querySelectorAll(SELECTORS.conversationTurn).length;
  sendBtn.click();

  const start = Date.now();

  // +2: el turno del propio usuario (echo) y el turno de respuesta del
  // asistente, que alternan estrictamente en el DOM. Esperar ambos evita
  // adelantarse a un estado donde solo existe el echo del usuario.
  while (document.querySelectorAll(SELECTORS.conversationTurn).length < turnsBefore + 2) {
    if (Date.now() - start > timeoutMs) {
      throw new Error("Timeout esperando la respuesta del asistente.");
    }
    await sleep(500);
  }

  while (querySelectorFirst(SELECTORS.stopButton)) {
    if (Date.now() - start > timeoutMs) {
      throw new Error("Timeout esperando a que termine la generación.");
    }
    await sleep(500);
  }
  // margen para que la(s) imagen(es) terminen de cargar en el DOM
  await sleep(1000);

  const lastMsg = Array.from(document.querySelectorAll(SELECTORS.conversationTurn)).pop();
  if (!lastMsg) {
    throw new Error("No se encontró el turno de respuesta del asistente.");
  }
  const imgs = Array.from(lastMsg.querySelectorAll("img")).filter(
    (img) => img.naturalWidth > 64
  );
  if (imgs.length === 0) {
    throw new Error(
      "No se encontraron imágenes en la respuesta (¿el prompt generó texto en vez de una imagen?)."
    );
  }

  // Normalmente data: URLs; puede contener alguna URL https cruda si el
  // fetch de esa imagen falló y se usó el fallback de abajo.
  const imageDataUrls = [];
  for (const img of imgs) {
    try {
      imageDataUrls.push(await fetchAsDataURL(img.src));
    } catch (e) {
      // Fallback al diseño anterior: si no se pudo convertir a data URL
      // (CORS, timeout, red), se pasa la URL https cruda para que
      // background.js intente chrome.downloads.download directamente en vez
      // de perder la imagen entera por este paso extra.
      console.warn(
        "[chatgpt-bridge] no se pudo descargar la imagen como data URL, usando URL cruda:",
        String((e && e.message) || e)
      );
      imageDataUrls.push(img.src);
    }
  }
  return imageDataUrls;
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message && message.type === "generate_image") {
    sendPromptAndWaitForImages(message.prompt)
      .then((imageDataUrls) => sendResponse({ imageDataUrls }))
      .catch((err) => sendResponse({ error: String((err && err.message) || err) }));
    return true; // respuesta asíncrona
  }
});
