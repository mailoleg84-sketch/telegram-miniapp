// AI English Tutor Kids: Telegram Mini App frontend

const tg = window.Telegram?.WebApp || {
  initData: "",
  ready() {},
  expand() {},
  showAlert(message) { alert(message); },
  showConfirm(message, cb) { cb(confirm(message)); },
  MainButton: { hide() {}, show() {}, setText() {}, onClick() {}, offClick() {}, showProgress() {}, hideProgress() {} },
  BackButton: { hide() {}, show() {}, onClick() {}, offClick() {} },
  HapticFeedback: null,
};

tg.ready();
tg.expand();

const app = document.getElementById("app");
const state = {
  me: null,
  back: null,
  vocab: null,
  quiz: null,
  answers: [],
  game: null,
  learningPath: null,
  motivation: null,
  levelTest: null,
  training: null,
  admin: null,
  adminUsersQuery: "",
  dictionaryFilter: "all",
};
let fallbackAuth = window.location.search || "";
const LOGGED_OUT_KEY = "englishTutorKidsLoggedOut";

// Тема (светлая/тёмная) и возрастная адаптация дизайн-системы (design.css).
function applyAppearance() {
  const root = document.documentElement;
  const age = state.me?.user?.age_group;
  if (age) root.dataset.age = age;
  const scheme =
    tg.colorScheme ||
    (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  if (scheme) root.dataset.theme = scheme;
}
applyAppearance();
if (typeof tg.onEvent === "function") tg.onEvent("themeChanged", applyAppearance);

// iOS: экранная клавиатура перекрывает поле ввода чата (visual viewport сжимается,
// а layout — нет, поэтому sticky-инпут уходит под клавиатуру). Считаем перекрытие
// и поднимаем поле через CSS-переменную --kb-inset (на десктопе/Android = 0px,
// поведение не меняется — правка чисто аддитивная и под feature-detection).
function setupKeyboardInset() {
  const vv = window.visualViewport;
  if (!vv) return;
  const root = document.documentElement;
  const update = () => {
    const overlap = Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
    // Порог отсекает мелкие изменения вьюпорта (шапка Telegram) — реагируем
    // только на реальную клавиатуру.
    const inset = overlap > 120 ? Math.round(overlap) : 0;
    root.style.setProperty("--kb-inset", inset + "px");
    if (inset) {
      const msgs = document.getElementById("messages");
      if (msgs) msgs.scrollTop = msgs.scrollHeight;
    }
  };
  vv.addEventListener("resize", update);
  vv.addEventListener("scroll", update);
  if (typeof tg.onEvent === "function") tg.onEvent("viewportChanged", update);
  update();
}
setupKeyboardInset();

function authHeaders(contentType = "application/json") {
  const headers = {
    "X-Telegram-Init-Data": tg.initData || "",
    "X-App-Fallback-Auth": fallbackAuth,
  };
  if (contentType) headers["Content-Type"] = contentType;
  return headers;
}

// Дружелюбное сообщение вместо сырого «HTTP 503» детям. Срабатывает только когда
// бэкенд не отдал свой текст ошибки (err.error) — например, при сетевом/прокси-сбое.
function friendlyHttpError(status) {
  if (status === 429) return "Слишком много запросов. Подожди минутку и попробуй снова.";
  if (status === 401 || status === 403) return "Нужно открыть приложение заново через Telegram.";
  if (status >= 500) return "Сервер пока не отвечает. Попробуй ещё раз через минутку.";
  return "Что-то пошло не так. Попробуй ещё раз.";
}

async function api(path, method = "POST", body = null) {
  const res = await fetch(path, {
    method,
    headers: authHeaders(),
    body: method === "GET" ? undefined : JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || friendlyHttpError(res.status));
  }
  return res.json();
}

async function apiForm(path, formData) {
  const res = await fetch(path, {
    method: "POST",
    headers: authHeaders(null),
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || friendlyHttpError(res.status));
  }
  return res.json();
}

async function apiBlob(path, body, timeoutMs = 0) {
  const controller = timeoutMs ? new AbortController() : null;
  const timeoutId = controller
    ? setTimeout(() => controller.abort(), timeoutMs)
    : null;
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: authHeaders(),
      body: JSON.stringify(body || {}),
      signal: controller?.signal,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || friendlyHttpError(res.status));
    }
    return res.blob();
  } finally {
    if (timeoutId) clearTimeout(timeoutId);
  }
}

let wordAudio = null;
let wordAudioUrl = "";
let wordUtterance = null;
let englishSpeechVoice = null;
const wordAudioCache = new Map();
const WORD_AUDIO_CACHE_LIMIT = 80;
const WORD_AUDIO_DB_NAME = "englishTutorKidsWordAudio";
const WORD_AUDIO_DB_STORE = "audio";
const WORD_AUDIO_DB_VERSION = 1;
const WORD_AUDIO_CACHE_VERSION = "word-tts-v1";
const WORD_AUDIO_PRELOAD_LIMIT = 2;
const wordAudioPreloadQueue = [];
const wordAudioPreloadKeys = new Set();
const wordAudioPreloading = new Set();
let wordAudioDbPromise = null;
let wordAudioPreloadTimer = null;
const generatingWordImages = new Set();
let adminUsersRequestId = 0;

function wordAudioKey(text) {
  return `${WORD_AUDIO_CACHE_VERSION}:${String(text || "").trim().toLowerCase()}`;
}

function openWordAudioDb() {
  if (!window.indexedDB) return Promise.resolve(null);
  if (wordAudioDbPromise) return wordAudioDbPromise;
  wordAudioDbPromise = new Promise(resolve => {
    const request = indexedDB.open(WORD_AUDIO_DB_NAME, WORD_AUDIO_DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(WORD_AUDIO_DB_STORE)) {
        db.createObjectStore(WORD_AUDIO_DB_STORE);
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => resolve(null);
    request.onblocked = () => resolve(null);
  });
  return wordAudioDbPromise;
}

async function getStoredWordAudio(key) {
  const db = await openWordAudioDb();
  if (!db) return null;
  return new Promise(resolve => {
    try {
      const tx = db.transaction(WORD_AUDIO_DB_STORE, "readonly");
      const request = tx.objectStore(WORD_AUDIO_DB_STORE).get(key);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => resolve(null);
    } catch (_) {
      resolve(null);
    }
  });
}

async function storeWordAudio(key, blob) {
  const db = await openWordAudioDb();
  if (!db || !blob) return;
  await new Promise(resolve => {
    try {
      const tx = db.transaction(WORD_AUDIO_DB_STORE, "readwrite");
      tx.objectStore(WORD_AUDIO_DB_STORE).put(blob, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
    } catch (_) {
      resolve();
    }
  });
}

function speechSynthesisApi() {
  return window.speechSynthesis || null;
}

function warmWordVoices() {
  const synth = speechSynthesisApi();
  if (!synth) return;
  try {
    synth.getVoices();
    synth.onvoiceschanged = () => {
      englishSpeechVoice = null;
      pickEnglishWordVoice();
    };
  } catch (_) {}
}

function pickEnglishWordVoice() {
  if (englishSpeechVoice) return englishSpeechVoice;
  const synth = speechSynthesisApi();
  const voices = synth?.getVoices?.() || [];
  const preferred = [
    "Samantha", "Daniel", "Karen", "Moira", "Google US English",
    "Google UK English Female", "Microsoft Jenny", "Microsoft Aria",
  ];
  englishSpeechVoice =
    voices.find(voice => /^en[-_]/i.test(voice.lang) && preferred.some(name => voice.name.includes(name))) ||
    voices.find(voice => /^en[-_](US|GB|CA|AU)/i.test(voice.lang)) ||
    voices.find(voice => /^en/i.test(voice.lang)) ||
    null;
  return englishSpeechVoice;
}

function rememberWordAudio(key, blob) {
  if (wordAudioCache.has(key)) wordAudioCache.delete(key);
  wordAudioCache.set(key, blob);
  while (wordAudioCache.size > WORD_AUDIO_CACHE_LIMIT) {
    const oldestKey = wordAudioCache.keys().next().value;
    wordAudioCache.delete(oldestKey);
  }
}

async function getCachedWordAudio(key) {
  let audioBlob = wordAudioCache.get(key);
  if (audioBlob) return audioBlob;
  audioBlob = await getStoredWordAudio(key);
  if (audioBlob) rememberWordAudio(key, audioBlob);
  return audioBlob || null;
}

async function fetchAndCacheWordAudio(text, key) {
  const audioBlob = await apiBlob("/api/audio/speech", { text, mode: "word" }, 60000);
  rememberWordAudio(key, audioBlob);
  storeWordAudio(key, audioBlob).catch(() => {});
  return audioBlob;
}

function scheduleWordAudioPreload() {
  if (wordAudioPreloadTimer !== null) return;
  const run = () => {
    wordAudioPreloadTimer = null;
    processWordAudioPreload();
  };
  if (window.requestIdleCallback) {
    wordAudioPreloadTimer = requestIdleCallback(run, { timeout: 900 });
  } else {
    wordAudioPreloadTimer = setTimeout(run, 160);
  }
}

function queueWordAudioPreload(words, limit = 12) {
  const list = Array.isArray(words) ? words : [words];
  list.slice(0, limit).forEach(item => {
    const word = String(item?.word || item || "").trim();
    if (!word || word.length > 90) return;
    const key = wordAudioKey(word);
    if (wordAudioCache.has(key) || wordAudioPreloadKeys.has(key) || wordAudioPreloading.has(key)) return;
    wordAudioPreloadKeys.add(key);
    wordAudioPreloadQueue.push({ word, key });
  });
  scheduleWordAudioPreload();
}

async function processWordAudioPreload() {
  while (wordAudioPreloading.size < WORD_AUDIO_PRELOAD_LIMIT && wordAudioPreloadQueue.length) {
    const item = wordAudioPreloadQueue.shift();
    wordAudioPreloadKeys.delete(item.key);
    if (wordAudioCache.has(item.key) || wordAudioPreloading.has(item.key)) continue;
    wordAudioPreloading.add(item.key);
    (async () => {
      try {
        const stored = await getStoredWordAudio(item.key);
        if (stored) {
          rememberWordAudio(item.key, stored);
          return;
        }
        await fetchAndCacheWordAudio(item.word, item.key);
      } catch (_) {
        // Background preloading must never block the learning flow.
      } finally {
        wordAudioPreloading.delete(item.key);
        if (wordAudioPreloadQueue.length) scheduleWordAudioPreload();
      }
    })();
  }
}

async function speakWordLocally(word, button = null) {
  const synth = speechSynthesisApi();
  const text = String(word || "").trim().replace(/\s+/g, " ");
  if (!synth || !window.SpeechSynthesisUtterance || !/^[a-zA-Z][a-zA-Z' -]{0,80}$/.test(text)) {
    return false;
  }

  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  utterance.rate = text.includes(" ") ? 0.84 : 0.74;
  utterance.pitch = 1.02;
  utterance.volume = 1;
  const voice = pickEnglishWordVoice();
  if (voice) utterance.voice = voice;

  return new Promise(resolve => {
    let settled = false;
    const finishStart = ok => {
      if (settled) return;
      settled = true;
      if (!ok) button?.classList.remove("speaking");
      resolve(ok);
    };
    const startTimer = setTimeout(() => {
      finishStart(Boolean(synth.speaking || synth.pending));
    }, 260);

    utterance.onstart = () => {
      clearTimeout(startTimer);
      finishStart(true);
    };
    utterance.onerror = () => {
      clearTimeout(startTimer);
      if (wordUtterance === utterance) wordUtterance = null;
      finishStart(false);
    };
    utterance.onend = () => {
      if (wordUtterance === utterance) wordUtterance = null;
      button?.classList.remove("speaking");
    };

    try {
      synth.cancel();
      wordUtterance = utterance;
      button?.classList.add("speaking");
      synth.speak(utterance);
    } catch (_) {
      clearTimeout(startTimer);
      if (wordUtterance === utterance) wordUtterance = null;
      finishStart(false);
    }
  });
}

function stopWordAudio() {
  const synth = speechSynthesisApi();
  try {
    synth?.cancel?.();
  } catch (_) {}
  wordUtterance = null;
  document.querySelectorAll(".pronounce-btn.speaking").forEach(button => {
    button.classList.remove("speaking");
  });
  if (wordAudio) {
    wordAudio.pause();
    wordAudio = null;
  }
  if (wordAudioUrl) {
    URL.revokeObjectURL(wordAudioUrl);
    wordAudioUrl = "";
  }
}

async function playWordAudio(text, button = null) {
  const word = String(text || "").trim();
  if (!word) return;
  stopWordAudio();
  const cacheKey = wordAudioKey(word);
  const cachedBlob = await getCachedWordAudio(cacheKey);
  if (cachedBlob) {
    try {
      wordAudioUrl = URL.createObjectURL(cachedBlob);
      wordAudio = new Audio(wordAudioUrl);
      wordAudio.onended = stopWordAudio;
      wordAudio.onerror = stopWordAudio;
      button?.classList.add("speaking");
      await wordAudio.play();
      return;
    } catch (_) {
      stopWordAudio();
    }
  }

  queueWordAudioPreload([word], 1);
  if (await speakWordLocally(word, button)) return;

  const oldText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "…";
  }
  try {
    const audioBlob = await fetchAndCacheWordAudio(word, cacheKey);
    wordAudioUrl = URL.createObjectURL(audioBlob);
    wordAudio = new Audio(wordAudioUrl);
    wordAudio.onended = stopWordAudio;
    wordAudio.onerror = stopWordAudio;
    button?.classList.add("speaking");
    await wordAudio.play();
  } catch (e) {
    tg.showAlert(e.message || "Не удалось озвучить слово");
  } finally {
    if (button) {
      button.disabled = false;
      button.textContent = oldText || "🔊";
    }
  }
}

warmWordVoices();

function bindPronunciationButtons(root = document) {
  root.querySelectorAll(".pronounce-btn").forEach(button => {
    button.onclick = event => {
      event.preventDefault();
      event.stopPropagation();
      haptic();
      playWordAudio(button.dataset.word, button);
    };
  });
  bindWordImageStates(root);
}

function bindWordImageStates(root = document) {
  root.querySelectorAll(".word-visual").forEach(box => {
    const image = box.querySelector("img");
    const retry = box.querySelector(".word-image-retry");
    if (!image) return;
    const generationStatus = box.dataset.generationStatus || "";
    if (generationStatus === "failed") {
      box.classList.add("generation-fallback");
      setWordImageStatus(box, "AI-картинка не создалась. Проверьте лимит OpenAI и нажмите повторить.", "warning");
    }
    const markLoaded = () => {
      box.classList.remove("loading", "failed");
      box.classList.add("loaded");
    };
    const markFailed = () => {
      box.classList.remove("loading", "loaded");
      box.classList.add("failed");
    };
    if (image.complete && image.naturalWidth > 0) markLoaded();
    image.onload = markLoaded;
    image.onerror = () => {
      // Бесплатное фото не загрузилось (источник лёг) — мягко падаем на SVG-сцену.
      const fb = box.dataset.fallbackSrc || "";
      if (fb && !image.dataset.triedFallback && image.src.indexOf(fb) === -1) {
        image.dataset.triedFallback = "1";
        box.classList.remove("failed");
        box.classList.add("loading");
        image.src = fb;
        return;
      }
      markFailed();
    };
    if (retry) {
      retry.onclick = async () => {
        haptic();
        if (box.dataset.generate === "1" && box.dataset.wordId) {
          await requestGeneratedWordImage(box, image, true);
          return;
        }
        box.classList.remove("failed", "loaded");
        box.classList.add("loading");
        const base = image.dataset.src || image.src.split("&retry=")[0];
        image.dataset.src = base;
        image.src = `${base}${base.includes("?") ? "&" : "?"}retry=${Date.now()}`;
      };
    }
    if (
      box.dataset.generate === "1" &&
      box.dataset.wordId &&
      !box.dataset.generationRequested &&
      !["generated", "needs_review", "failed"].includes(box.dataset.generationStatus || "")
    ) {
      requestGeneratedWordImage(box, image, false);
    }
  });
}

function setWordImageStatus(box, message = "", tone = "") {
  const status = box.querySelector(".word-image-status");
  const placeholder = box.querySelector(".word-image-placeholder");
  if (placeholder && message && box.classList.contains("generating")) {
    placeholder.textContent = message;
  }
  if (!status) return;
  status.textContent = message;
  status.hidden = !message;
  status.dataset.tone = tone || "";
}

async function requestGeneratedWordImage(box, image, force = false) {
  const wordId = box.dataset.wordId;
  if (!wordId || (box.dataset.generate !== "1" && !force)) return;
  if (generatingWordImages.has(wordId)) return;
  generatingWordImages.add(wordId);
  box.dataset.generationRequested = "1";
  const previousStatus = box.dataset.generationStatus || "";
  const previousSrc = image.dataset.src || image.src;
  box.classList.remove("failed");
  box.classList.remove("generation-fallback");
  box.classList.add("generating");
  setWordImageStatus(box, "Генерирую AI-картинку…", "progress");
  try {
    const data = await api("/api/vocab/image/generate", "POST", {
      word_id: Number(wordId),
      force,
    });
    const nextUrl = data?.image_url || "";
    const fallbackUrl = data?.fallback_image_url || box.dataset.fallbackSrc || previousSrc;
    const status = data?.generation_status || "missing";
    box.dataset.generationStatus = status;
    if (nextUrl && status !== "failed") {
      const imageUrl = force
        ? `${nextUrl}${nextUrl.includes("?") ? "&" : "?"}v=${Date.now()}`
        : nextUrl;
      image.dataset.src = nextUrl;
      image.src = imageUrl;
      box.classList.remove("failed");
      box.classList.remove("generation-fallback");
      box.classList.add("generated-ai");
      setWordImageStatus(box, "AI-картинка готова.", "success");
      setTimeout(() => {
        if (box.dataset.generationStatus === status) setWordImageStatus(box);
      }, 1600);
    } else if (fallbackUrl) {
      image.dataset.src = fallbackUrl;
      image.src = fallbackUrl;
      box.classList.add("generation-fallback");
      setWordImageStatus(box, "AI-картинка не создалась. Нажмите повторить позже.", "warning");
    }
  } catch (e) {
    box.dataset.generationStatus = previousStatus || "failed";
    if (previousSrc) image.src = previousSrc;
    box.classList.add("generation-fallback");
    setWordImageStatus(box, e.message || "AI-картинка не создалась. Нажмите повторить позже.", "warning");
    console.warn("Vocabulary image generation failed", e);
  } finally {
    box.classList.remove("generating");
    generatingWordImages.delete(wordId);
  }
}

async function apiSdp(path, sdp) {
  const res = await fetch(path, {
    method: "POST",
    headers: authHeaders("application/sdp"),
    body: sdp,
  });
  if (!res.ok) {
    const raw = await res.text().catch(() => "");
    let message = raw || `HTTP ${res.status}`;
    try {
      const parsed = JSON.parse(raw);
      message = parsed.error || message;
    } catch (_) {}
    throw new Error(message);
  }
  return res.text();
}

async function openaiRealtimeSdp(ephemeralKey, sdp) {
  const res = await fetch("https://api.openai.com/v1/realtime/calls", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${ephemeralKey}`,
      "Content-Type": "application/sdp",
    },
    body: sdp,
  });
  if (!res.ok) {
    const raw = await res.text().catch(() => "");
    throw new Error(raw || `OpenAI HTTP ${res.status}`);
  }
  return res.text();
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function normalizeDictionarySearch(value) {
  return String(value ?? "")
    .normalize("NFKC")
    .toLocaleLowerCase("ru-RU")
    .replaceAll("ё", "е")
    .replace(/\s+/g, " ")
    .trim();
}

function ageYearsLabel(value) {
  const age = Number(value);
  if (!Number.isInteger(age) || age <= 0) return "не указан";
  const lastTwo = age % 100;
  const last = age % 10;
  const suffix = lastTwo >= 11 && lastTwo <= 14
    ? "лет"
    : last === 1
      ? "год"
      : last >= 2 && last <= 4
        ? "года"
        : "лет";
  return `${age} ${suffix}`;
}

// Правильное склонение: 1 день, 2-4 дня, 5-20 дней, 21 день и т.д.
function daysLabel(value) {
  const n = Math.max(0, Number(value) || 0);
  const lastTwo = n % 100;
  const last = n % 10;
  const suffix = lastTwo >= 11 && lastTwo <= 14
    ? "дней"
    : last === 1
      ? "день"
      : last >= 2 && last <= 4
        ? "дня"
        : "дней";
  return `${n} ${suffix}`;
}

function pronunciationButtonHtml(word, small = false) {
  return `<button type="button" class="pronounce-btn ${small ? "small" : ""}" data-word="${esc(word)}" aria-label="Озвучить ${esc(word)}">🔊</button>`;
}

function wordImageHtml(wordData, small = false) {
  const src = wordData?.image_url || "";
  const fallbackSrc = wordData?.fallback_image_url || src;
  const wordId = wordData?.id || wordData?.word_id || "";
  const canGenerate = wordData?.image_can_generate ? "1" : "0";
  const generationStatus = wordData?.image_generation_status || "";
  const promptHash = wordData?.image_prompt_hash || "";
  const label = wordData?.image_alt || wordData?.word || wordData?.translation || "word";
  const emoji = wordData?.emoji || "";
  if (emoji) {
    // Бесплатная «картинка»: нативный цветной эмодзи, без генерации и без запросов.
    return `
      <div class="word-visual word-emoji-box loaded ${small ? "small" : ""}" data-word-id="${esc(wordId)}">
        <span class="word-emoji" role="img" aria-label="${esc(label)}">${esc(emoji)}</span>
      </div>`;
  }
  if (!src) {
    return `
      <div class="word-visual failed ${small ? "small" : ""}" data-word-id="${esc(wordId)}" data-generate="${canGenerate}" data-generation-status="${esc(generationStatus)}" data-prompt-hash="${esc(promptHash)}" data-fallback-src="${esc(fallbackSrc)}">
        <div class="word-image-placeholder">Сцена появится позже</div>
        <div class="word-image-status" hidden></div>
      </div>`;
  }
  return `
    <div class="word-visual loading ${small ? "small" : ""}" data-word-id="${esc(wordId)}" data-generate="${canGenerate}" data-generation-status="${esc(generationStatus)}" data-prompt-hash="${esc(promptHash)}" data-fallback-src="${esc(fallbackSrc)}">
      <img class="word-image ${small ? "small" : ""}" src="${esc(src)}" data-src="${esc(src)}" alt="${esc(label)}" loading="lazy">
      <div class="word-image-placeholder">Готовим сцену…</div>
      <div class="word-image-status" hidden></div>
      <button type="button" class="word-image-retry">Загрузить картинку ещё раз</button>
    </div>`;
}

function wordStudyCard(wordData, options = {}) {
  const badge = options.badge || "";
  const prompt = options.prompt || "";
  const showTranslation = options.showTranslation !== false;
  const showLearningDetails = options.showLearningDetails !== false;
  const example = wordData.example_sentence || wordData.example || "";
  const showRussianHint = wordData.show_russian_hint !== false && wordData.russian_hint;
  const conditionalVisual = wordData.image_needs_review || wordData.needs_review || Number(wordData.image_confidence || 1) < 0.7;
  return `
    <div class="card word-card ${options.compact ? "compact" : ""}">
      <div class="word-card-top">
        ${badge ? `<div class="daily-badge">${esc(badge)}</div>` : "<span></span>"}
        ${pronunciationButtonHtml(wordData.word)}
      </div>
      ${options.showImage ? wordImageHtml(wordData) : ""}
      ${options.showImage && conditionalVisual ? `<div class="visual-note">Условная сцена: смотри пример и подсказку</div>` : ""}
      <div class="word-main">${esc(wordData.word)}</div>
      ${wordData.transcription ? `<div class="word-transcription">${esc(wordData.transcription)}</div>` : ""}
      ${showTranslation && wordData.translation ? `<div class="word-translation">${esc(wordData.translation)}</div>` : ""}
      ${showLearningDetails && example ? `
        <div class="word-detail">
          <div>
            <span>Пример</span>
            <b>${esc(example)}</b>
          </div>
          ${pronunciationButtonHtml(example, true)}
        </div>` : ""}
      ${showLearningDetails && wordData.simple_meaning ? `
        <div class="word-explain">${esc(wordData.simple_meaning)}</div>` : ""}
      ${showLearningDetails && showRussianHint ? `
        <div class="word-hint">${esc(wordData.russian_hint)}</div>` : ""}
      ${prompt ? `<p class="hint mt-12">${esc(prompt)}</p>` : ""}
    </div>`;
}

function reviewWordRow(wordData) {
  return `
    <div class="word-review-row">
      <div class="word-review-main">
        <b>${esc(wordData.word)}</b>
        ${wordData.transcription ? `<small class="transcription">${esc(wordData.transcription)}</small>` : ""}
        <span>${esc(wordData.translation)}</span>
      </div>
      ${pronunciationButtonHtml(wordData.word, true)}
    </div>`;
}

function haptic(type = "light") {
  try {
    if (["success", "error", "warning"].includes(type)) tg.HapticFeedback?.notificationOccurred(type);
    else tg.HapticFeedback?.impactOccurred(type);
  } catch (_) {}
}

function confirmAction(message) {
  return new Promise(resolve => {
    try {
      tg.showConfirm(message, ok => resolve(Boolean(ok)));
    } catch (_) {
      resolve(confirm(message));
    }
  });
}

function isLoggedOut() {
  try {
    return localStorage.getItem(LOGGED_OUT_KEY) === "1";
  } catch (_) {
    return false;
  }
}

function clearAccountLocalState() {
  state.me = null;
  state.vocab = null;
  state.quiz = null;
  state.answers = [];
  state.game = null;
  state.learningPath = null;
  state.motivation = null;
  state.levelTest = null;
  state.quizSession = null;
  state.dailyVocab = null;
  state.dailyQuiz = null;
  state.dailyResult = null;
  state.dailyAnswers = [];
  state.dictionaryFilter = "all";
  removeBottomNav();
  try {
    localStorage.removeItem("stableVoiceUntil");
    localStorage.removeItem("stableVoiceReason");
    const keys = [];
    for (let i = 0; i < localStorage.length; i += 1) keys.push(localStorage.key(i));
    keys.forEach(key => {
      if (key && (key.startsWith("voiceHelpHintIndex:") || key.startsWith("voiceStarterIndex:"))) {
        localStorage.removeItem(key);
      }
    });
  } catch (_) {}
}

function stripFallbackAuthFromUrl() {
  try {
    const url = new URL(window.location.href);
    ["fa_user_id", "fa_first_name", "fa_auth_date", "fa_hash"].forEach(key => url.searchParams.delete(key));
    history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
    fallbackAuth = window.location.search || "";
  } catch (_) {}
}

function logoutFromApp() {
  try {
    localStorage.setItem(LOGGED_OUT_KEY, "1");
  } catch (_) {}
  clearAccountLocalState();
  stripFallbackAuthFromUrl();
  renderLoggedOut();
}

function loginAgain() {
  try {
    localStorage.removeItem(LOGGED_OUT_KEY);
  } catch (_) {}
  location.reload();
}

function setBack(handler) {
  if (state.back) tg.BackButton.offClick(state.back);
  state.back = handler || null;
  if (handler) {
    tg.BackButton.onClick(handler);
    tg.BackButton.show();
  } else {
    tg.BackButton.hide();
  }
}

function loading() {
  app.innerHTML = `<div class="screen card center">Загрузка...</div>`;
}

function friendlyError(message) {
  const raw = String(message || "");
  if (/network|failed to fetch|networkerror|соедин|интернет/i.test(raw))
    return "Нет интернета. Проверь связь и попробуй ещё раз.";
  if (/50\d|internal|server|шлюз|gateway/i.test(raw))
    return "Сервер немного устал. Попробуй чуть позже.";
  return "Что-то пошло не так. Нажми «Перезагрузить».";
}

function renderError(message) {
  setBack(null);
  removeBottomNav();
  app.innerHTML = `
    <div class="screen">
      <div class="error-box"><b>Упс! 🙈</b><div class="mt-8">${esc(friendlyError(message))}</div></div>
      <button class="btn mt-12" id="reload">Перезагрузить</button>
    </div>`;
  document.getElementById("reload").onclick = () => location.reload();
}

function optionButtons(items, className = "choice") {
  return items.map(item => `
    <button class="btn btn-secondary ${className}" data-value="${esc(item.value)}">${esc(item.label)}</button>
  `).join("");
}

function ageToGroup(age) {
  if (age >= 5 && age <= 7) return "5_7";
  if (age >= 8 && age <= 10) return "8_10";
  if (age >= 11 && age <= 13) return "11_13";
  if (age >= 14 && age <= 18) return "14_18";
  return "";
}

function suggestedActionLabel(action) {
  const labels = {
    level: "Пройти тест уровня",
    daily: "Продолжить урок",
    vocab: "Учить слова",
    review: "Начать повторение",
    learn: "Начать тренировку",
    training: "Начать тренировку",
  };
  return labels[action] || "Продолжить";
}

function runSuggestedAction(action) {
  haptic();
  if (action === "level") return renderLevelTestIntro();
  if (action === "daily") return renderDailyLesson();
  if (action === "vocab") return renderVocabStart();
  if (action === "review") return startTrainingSession("choice", "review");
  if (action === "learn" || action === "training") return startTrainingSession("choice", "all");
  return renderLearningHub();
}

function bindSuggestedActionButton(id, action) {
  const button = document.getElementById(id);
  if (button) button.onclick = () => runSuggestedAction(action);
}

function learningPathHtml(data) {
  const action = data.next_action || "learn";
  const actionButton = `<button class="btn mt-12" id="learningPathAction">${esc(suggestedActionLabel(action))}</button>`;
  return `
    <div class="learning-path-head">
      <div>
        <div class="daily-badge">${esc(data.title || "Дневной план")}</div>
        <h2>${esc(data.next_title || "Продолжить обучение")}</h2>
      </div>
      <strong>${data.progress_percent || 0}%</strong>
    </div>
    <p class="hint">${esc(data.next_text || "Выбери следующий шаг.")}</p>
    <div class="path-progress"><span style="width:${Math.max(0, Math.min(100, Number(data.progress_percent) || 0))}%"></span></div>
    ${actionButton}`;
}

async function loadLearningPath() {
  const box = document.getElementById("learningPath");
  if (!box) return;
  box.innerHTML = `<div class="hint">Подбираю следующий шаг...</div>`;
  try {
    const data = await api("/api/learning/path", "GET");
    state.learningPath = data;
    box.innerHTML = learningPathHtml(data);
    bindSuggestedActionButton("learningPathAction", data.next_action);
  } catch (_) {
    box.innerHTML = `
      <div class="learning-path-head">
        <div>
          <div class="daily-badge">Дневной план</div>
          <h2>Начать короткий урок</h2>
        </div>
      </div>
      <p class="hint">Не удалось обновить план. Можно сразу открыть практические занятия.</p>
      <button class="btn mt-12" id="learningPathRetry">Открыть практику</button>`;
    bindSuggestedActionButton("learningPathRetry", "learn");
  }
}

// SRS-нудж: сколько слов «пора повторить» сегодня (из payload /api/learning/path).
function reviewDueCount() {
  const n = Number(state.learningPath && state.learningPath.review_words);
  return Number.isFinite(n) && n > 0 ? n : 0;
}

// Подтягивает learning path в кэш без рендера (для экранов, куда пришли не с главной).
async function ensureLearningPath() {
  if (!state.learningPath) {
    try { state.learningPath = await api("/api/learning/path", "GET"); } catch (_) {}
  }
  return state.learningPath;
}

// Обновляет видимые нуджи повторения: бейдж на тайле и строку в меню повторения.
function updateReviewNudges() {
  const n = reviewDueCount();
  const badge = document.getElementById("reviewTileBadge");
  if (badge) { badge.textContent = String(n); badge.hidden = n <= 0; }
  const line = document.getElementById("reviewDueLine");
  if (line) {
    const slot = document.getElementById("reviewDueCount");
    if (slot) slot.textContent = String(n);
    line.hidden = n <= 0;
  }
}

function motivationPreviewHtml(data) {
  const summary = data.summary || {};
  const streak = data.streak || {};
  const badges = `${summary.unlocked_badges || 0}/${summary.total_badges || 0}`;
  return `
    <div class="motivation-head">
      <div>
        <div class="daily-badge">${esc(data.title || "Достижения")}</div>
        <h2>${daysLabel(streak.current)} подряд</h2>
      </div>
      <strong>${esc(badges)}</strong>
    </div>
    <p class="hint">${esc(data.coach_message || "Поддерживаем короткий учебный темп.")}</p>
    <div class="motivation-stats">
      <span><b>${streak.longest || 0}</b><small>лучшая серия</small></span>
      <span><b>${summary.words_learned || 0}</b><small>слов</small></span>
      <span><b>${summary.accuracy || 0}%</b><small>точность</small></span>
    </div>`;
}

async function loadMotivationPreview() {
  const box = document.getElementById("motivationPreview");
  if (!box) return;
  box.innerHTML = `<div class="hint">Собираю достижения...</div>`;
  try {
    const data = await api("/api/motivation/status", "GET");
    state.motivation = data;
    box.innerHTML = motivationPreviewHtml(data);
  } catch (_) {
    box.innerHTML = `
      <div class="motivation-head">
        <div>
          <div class="daily-badge">Достижения</div>
          <h2>Учебный прогресс</h2>
        </div>
      </div>
      <p class="hint">Достижения появятся после первых уроков и тестов.</p>`;
  }
}

function renderRegistration() {
  setBack(null);
  tg.MainButton.hide();
  removeBottomNav();

  const firstName = state.me.tg_user?.first_name || "";
  app.innerHTML = `
    <div class="screen">
      <h1>AI English Tutor Kids</h1>
      <p class="hint">Создайте профиль ребенка. Родитель сможет видеть занятия, слова и результаты тестов.</p>

      <div class="card">
        <h2>Родитель</h2>
        <input id="parentName" type="text" placeholder="Имя родителя" value="${esc(firstName)}" maxlength="30">
      </div>

      <div class="card">
        <h2>Ребенок</h2>
        <input id="childName" type="text" placeholder="Имя ребенка" maxlength="30">
        <input id="childAge" type="text" inputmode="numeric" placeholder="Возраст от 5 до 18" maxlength="2">
        <p class="hint">Программа автоматически подстроится под возраст ребёнка.</p>
      </div>

      <div class="card">
        <h2>Цель обучения</h2>
        <div id="goals">${optionButtons(state.me.goals || [], "goal")}</div>
      </div>

      <button class="btn" id="register">Создать профиль</button>
    </div>`;

  let goal = "";

  function choose(selector, button, setter) {
    document.querySelectorAll(selector).forEach(btn => btn.classList.add("btn-secondary"));
    button.classList.remove("btn-secondary");
    setter(button.dataset.value);
    haptic();
  }

  document.querySelectorAll(".goal").forEach(btn => {
    btn.onclick = () => choose(".goal", btn, value => { goal = value; });
  });

  document.getElementById("register").onclick = async () => {
    const parent_name = document.getElementById("parentName").value.trim();
    const child_name = document.getElementById("childName").value.trim();
    const child_age = document.getElementById("childAge").value.trim();
    if (child_name.length < 2) return tg.showAlert("Введите имя ребенка");
    if (!child_age || Number(child_age) < 5 || Number(child_age) > 18) return tg.showAlert("Возраст должен быть от 5 до 18");
    if (!goal) return tg.showAlert("Выберите цель обучения");
    // Блокируем кнопку на время запроса — иначе двойной тап = двойная регистрация.
    const btn = document.getElementById("register");
    const btnText = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Создаём профиль…";
    try {
      // Возрастную группу больше не выбираем вручную — сервер выведет её из возраста.
      await api("/api/register", "POST", { parent_name, child_name, child_age, goal });
      state.me = await api("/api/me", "GET");
      applyAppearance();
      haptic("success");
      renderLevelTestIntro({ afterRegistration: true });
    } catch (e) {
      btn.disabled = false;
      btn.textContent = btnText;
      tg.showAlert(e.message);
    }
  };
}

const NAV_ITEMS = [
  { key: "learn", icon: "🏠", label: "Учёба", go: () => renderMenu() },
  { key: "tutor", icon: "🎙", label: "Репетитор", go: () => renderChat() },
  { key: "progress", icon: "📈", label: "Прогресс", go: () => renderProgressHub() },
  { key: "parent", icon: "👤", label: "Профиль", go: () => renderParentZone() },
];

function removeBottomNav() {
  document.getElementById("bottomNav")?.remove();
  document.body.classList.remove("has-bottom-nav");
}

function ensureBottomNav(activeKey = "learn") {
  if (!state.me || !state.me.registered) { removeBottomNav(); return; }
  let nav = document.getElementById("bottomNav");
  if (!nav) {
    nav = document.createElement("nav");
    nav.id = "bottomNav";
    nav.innerHTML = NAV_ITEMS.map(it =>
      `<button class="nav-item" data-nav="${it.key}"><span class="nav-ic">${it.icon}</span>${it.label}</button>`
    ).join("");
    document.body.appendChild(nav);
    nav.querySelectorAll(".nav-item").forEach(btn => {
      const item = NAV_ITEMS.find(i => i.key === btn.dataset.nav);
      btn.onclick = () => { haptic(); item.go(); };
    });
  }
  document.body.classList.add("has-bottom-nav");
  nav.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("on", b.dataset.nav === activeKey));
}

function renderMenu() {
  setBack(null);
  tg.MainButton.hide();
  ensureBottomNav("learn");
  const u = state.me.user;
  app.innerHTML = `
    <div class="screen dashboard">
      <div class="dashboard-hero">
        <div>
          <div class="daily-badge">Сегодня</div>
          <h1>Привет, ${esc(u.child_name)}!</h1>
          <p>Уровень - ${esc(u.level_label || "Beginner / A1")}</p>
        </div>
        <div class="points-orb">
          <b>${u.points}</b>
          <span>баллов</span>
        </div>
      </div>

      <div class="card learning-path" id="learningPath">
        <div class="hint">Подбираю лучший следующий шаг...</div>
      </div>

      <div class="action-grid main-actions">
        <button class="action-tile primary" id="chat">
          <i class="tile-ic ic-mic">🎙</i>
          <b>Разговорная практика</b>
          <small>говорить, слушать, задавать вопросы</small>
        </button>
        <button class="action-tile learn" id="learnHub">
          <i class="tile-ic ic-learn">📚</i>
          <b>Практические занятия</b>
          <small>урок, тренировки, словарь, игры</small>
        </button>
        <button class="action-tile progress" id="progressHub">
          <i class="tile-ic ic-progress">🏆</i>
          <b>Достижения</b>
          <small>серии, бейджи, рейтинг</small>
        </button>
        <button class="action-tile profile" id="parentZone">
          <i class="tile-ic ic-parent">👤</i>
          <b>Профиль</b>
          <small>ребёнок, кабинет, настройки</small>
        </button>
      </div>
      ${state.me.is_admin ? `
        <button class="action-row admin-entry" id="adminPanel">
          <i class="tile-ic ic-admin">⚙️</i>
          <div class="action-row-text">
            <b>Управление приложением</b>
            <small>пользователи, словарь, картинки, диагностика</small>
          </div>
        </button>
      ` : ""}

    </div>`;

  document.getElementById("chat").onclick = () => { haptic(); renderChat(); };
  document.getElementById("learnHub").onclick = () => { haptic(); renderLearningHub(); };
  document.getElementById("progressHub").onclick = () => { haptic(); renderProgressHub(); };
  document.getElementById("parentZone").onclick = () => { haptic(); renderParentZone(); };
  const adminPanel = document.getElementById("adminPanel");
  if (adminPanel) adminPanel.onclick = () => { haptic(); renderAdminPanel(); };
  loadLearningPath();
}

function renderLearningHub() {
  setBack(renderMenu);
  tg.MainButton.hide();
  ensureBottomNav("learn");
  const u = state.me.user;
  app.innerHTML = `
    <div class="screen">
      <h1>Учеба</h1>
      <div class="section-label">Сегодня</div>
      <div class="action-list">
        <button class="action-row primary" id="daily">
          <i class="tile-ic ic-mic">⭐</i>
          <div class="action-row-text">
            <b>Короткий маршрут</b>
            <small>слова, мини-тест и простая фраза</small>
          </div>
        </button>
      </div>

      <div class="section-label">Практика</div>
      <div class="hub-grid">
        <button class="action-tile learn" id="vocab">
          <i class="tile-ic ic-learn">📚</i>
          <b>Учим слова</b>
          <small>карточки и короткий тест</small>
        </button>
        <button class="action-tile review" id="training">
          <span class="tile-badge" id="reviewTileBadge" hidden>0</span>
          <i class="tile-ic ic-review">🔁</i>
          <b>Работа над ошибками</b>
          <small>ошибки и закрепление</small>
        </button>
        <button class="action-tile dictionary" id="dictionary">
          <i class="tile-ic ic-dict">📖</i>
          <b>Словарь</b>
          <small>транскрипция и озвучка</small>
        </button>
        <button class="action-tile game" id="games">
          <i class="tile-ic ic-game">🎮</i>
          <b>Игровая практика</b>
          <small>закрепить слова в игре</small>
        </button>
      </div>

      <div class="section-label">Настройка уровня</div>
      <button class="btn btn-secondary" id="levelTest">${u.level_test_completed ? "Обновить уровень" : "Пройти тест уровня"}</button>
    </div>`;

  document.getElementById("daily").onclick = () => { haptic(); renderDailyLesson(); };
  document.getElementById("vocab").onclick = () => { haptic(); renderVocabStart(); };
  document.getElementById("training").onclick = () => { haptic(); renderTrainingMenu("review"); };
  document.getElementById("dictionary").onclick = () => { haptic(); renderDictionary(); };
  document.getElementById("games").onclick = () => { haptic(); renderGamesMenu(); };
  document.getElementById("levelTest").onclick = () => { haptic(); renderLevelTestIntro(); };
  updateReviewNudges();
  ensureLearningPath().then(updateReviewNudges);
}

function renderProgressHub() {
  setBack(renderMenu);
  tg.MainButton.hide();
  ensureBottomNav("progress");
  app.innerHTML = `
    <div class="screen">
      <h1>Прогресс</h1>
      <div class="card motivation-preview" id="motivationPreview">
        <div class="hint">Собираю достижения...</div>
      </div>

      <div class="hub-grid">
        <button class="action-tile progress" id="motivation">
          <i class="tile-ic ic-progress">🏆</i>
          <b>Достижения</b>
          <small>серии, бейджи, следующий шаг</small>
        </button>
        <button class="action-tile leaderboard-tile" id="leaderboard">
          <i class="tile-ic ic-game">🏅</i>
          <b>Рейтинг</b>
          <small>место среди учеников</small>
        </button>
      </div>
    </div>`;

  document.getElementById("motivation").onclick = () => { haptic(); renderMotivation(); };
  document.getElementById("leaderboard").onclick = () => { haptic(); renderLeaderboard(); };
  loadMotivationPreview();
}

// Кабинет родителя: отчёт, история занятий и аккаунт ребёнка в одном месте.
// Открывается сразу, без пароля (по решению пользователя).

function renderParentZone() {
  setBack(renderMenu);
  tg.MainButton.hide();
  ensureBottomNav("parent");
  const u = state.me.user;
  app.innerHTML = `
    <div class="screen">
      <h1>Профиль</h1>
      <div class="card">
        <b>${esc(u.child_name)}</b>
        <p class="hint mt-8">${esc(ageYearsLabel(u.child_age))} · Уровень - ${esc(u.level_label || "Beginner / A1")}</p>
        <div class="stat-row"><span>Баллы</span><b>${u.points}</b></div>
      </div>

      <div class="action-list">
        <button class="action-row" id="pzChild">
          <i class="tile-ic">🧒</i>
          <div class="action-row-text"><b>Профиль ребёнка</b><small>имя, возраст, уровень</small></div>
        </button>
        <button class="action-row" id="pzCabinet">
          <i class="tile-ic">📊</i>
          <div class="action-row-text"><b>Родительский кабинет</b><small>отчёт и история занятий</small></div>
        </button>
        <button class="action-row" id="pzSub">
          <i class="tile-ic">⭐</i>
          <div class="action-row-text"><b>Подписка</b><small>тариф и доступ</small></div>
        </button>
        <button class="action-row" id="pzSettings">
          <i class="tile-ic">⚙️</i>
          <div class="action-row-text"><b>Настройки</b><small>сброс, выход, удаление</small></div>
        </button>
        <button class="action-row" id="pzHelp">
          <i class="tile-ic">❓</i>
          <div class="action-row-text"><b>Помощь</b><small>как пользоваться, поддержка</small></div>
        </button>
      </div>

      <p class="hint mt-12">Занятия безопасны и подобраны по возрасту. Личные данные ребёнка приложение не запрашивает.</p>
    </div>`;
  document.getElementById("pzChild").onclick = () => { haptic(); renderProfile(); };
  document.getElementById("pzCabinet").onclick = () => { haptic(); renderParentCabinet(); };
  document.getElementById("pzSub").onclick = () => { haptic(); renderSubscription(); };
  document.getElementById("pzSettings").onclick = () => { haptic(); renderSettings(); };
  document.getElementById("pzHelp").onclick = () => { haptic(); renderHelp(); };
}

// Подразделы «Профиля».

function renderParentCabinet() {
  setBack(renderParentZone);
  tg.MainButton.hide();
  ensureBottomNav("parent");
  app.innerHTML = `
    <div class="screen">
      <h1>Родительский кабинет</h1>
      <p class="hint">Прогресс ребёнка: что получается и где нужна поддержка.</p>
      <div class="hub-grid">
        <button class="action-tile report" id="pcReport">
          <i class="tile-ic ic-review">📋</i>
          <b>Отчёт</b>
          <small>что получается и что повторить</small>
        </button>
        <button class="action-tile history" id="pcHistory">
          <i class="tile-ic ic-dict">📅</i>
          <b>История занятий</b>
          <small>уроки, слова, тесты</small>
        </button>
      </div>
    </div>`;
  document.getElementById("pcReport").onclick = () => { haptic(); renderParentReport(); };
  document.getElementById("pcHistory").onclick = () => { haptic(); renderActivityHistory(); };
}

function renderSubscription() {
  setBack(renderParentZone);
  tg.MainButton.hide();
  ensureBottomNav("parent");
  app.innerHTML = `
    <div class="screen">
      <h1>Подписка</h1>
      <div class="card">
        <h2>Тариф: Бесплатный</h2>
        <p class="hint">Доступны слова, тренировки, игры, тесты и общение с ИИ-репетитором.</p>
      </div>
      <div class="card">
        <b>Расширенный доступ — скоро</b>
        <p class="hint mt-8">Больше занятий с голосовым репетитором, генерация картинок к словам и подробные отчёты для родителей. Мы сообщим, когда подписку можно будет подключить.</p>
      </div>
    </div>`;
}

function renderHelp() {
  setBack(renderParentZone);
  tg.MainButton.hide();
  ensureBottomNav("parent");
  app.innerHTML = `
    <div class="screen">
      <h1>Помощь</h1>
      <div class="card">
        <b>Как пользоваться</b>
        <p class="hint mt-8">«Учёба» — слова, тренировки и игры. «Репетитор» — разговор и голос. «Прогресс» — баллы, серии и достижения. «Профиль» — данные ребёнка, отчёт родителю, подписка и настройки.</p>
      </div>
      <div class="card">
        <b>Поддержка</b>
        <p class="hint mt-8">Напишите боту @my_eng_tutor777_bot. Команды: /start — открыть приложение, /help — справка.</p>
      </div>
      <p class="hint mt-12">Занятия безопасны и подобраны по возрасту. Личные данные ребёнка приложение не запрашивает.</p>
    </div>`;
}

async function renderLevelTestIntro({ afterRegistration = false } = {}) {
  setBack(afterRegistration ? null : renderLearningHub);
  loading();
  try {
    const data = await api("/api/level/test", "GET");
    state.levelTest = { data, answers: [], afterRegistration };
    app.innerHTML = `
      <div class="screen">
        <h1>Тест уровня</h1>
        <div class="card">
          <div class="daily-badge">${esc(data.age_label)} · ${data.questions.length} вопросов</div>
          <p class="hint mt-12">Это короткая проверка без оценок и стресса. По результату репетитор будет давать задания не слишком легкие и не слишком сложные.</p>
          <div class="stat-row"><span>Сейчас</span><b>${esc(data.level_label)}</b></div>
        </div>
        <button class="btn" id="levelStart">Начать тест</button>
        ${afterRegistration ? `<button class="btn btn-secondary" id="levelSkip">Позже</button>` : `<button class="btn btn-secondary" id="levelBack">К учебе</button>`}
      </div>`;
    document.getElementById("levelStart").onclick = () => {
      haptic();
      renderLevelQuestion(0);
    };
    const backButton = document.getElementById(afterRegistration ? "levelSkip" : "levelBack");
    if (backButton) {
      backButton.onclick = () => {
        haptic();
        if (afterRegistration) renderMenu();
        else renderLearningHub();
      };
    }
  } catch (e) {
    renderError(e.message);
  }
}

function renderLevelQuestion(index) {
  const test = state.levelTest?.data;
  const q = test?.questions?.[index];
  if (!q) return finishLevelTest();
  setBack(index > 0 ? () => renderLevelQuestion(index - 1) : () => renderLevelTestIntro({ afterRegistration: state.levelTest?.afterRegistration }));
  app.innerHTML = `
    <div class="screen">
      <h1>Тест уровня</h1>
      <div class="card center">
        <div class="daily-badge">Вопрос ${index + 1}/${test.questions.length}</div>
        <div class="big-sub mt-12">${esc(q.prompt)}</div>
      </div>
      ${q.options.map(option => `
        <button class="btn btn-secondary level-answer" data-id="${esc(option.id)}">${esc(option.text)}</button>
      `).join("")}
    </div>`;

  document.querySelectorAll(".level-answer").forEach(btn => {
    btn.onclick = () => {
      haptic();
      state.levelTest.answers[index] = {
        question_id: q.id,
        selected_id: btn.dataset.id,
      };
      document.querySelectorAll(".level-answer").forEach(item => item.disabled = true);
      btn.classList.remove("btn-secondary");
      setTimeout(() => renderLevelQuestion(index + 1), 350);
    };
  });
}

async function finishLevelTest() {
  setBack(state.levelTest?.afterRegistration ? null : renderLearningHub);
  loading();
  try {
    const result = await api("/api/level/submit", "POST", {
      answers: (state.levelTest?.answers || []).filter(Boolean),
    });
    state.me = await api("/api/me", "GET");
    app.innerHTML = `
      <div class="screen">
        <h1>Уровень готов</h1>
        <div class="card center">
          <div class="big" style="color: var(--button)">${esc(result.level_label)}</div>
          <p class="hint">${result.correct_count}/${result.total} правильно · ${result.score}%</p>
          <p>${esc(result.message)}</p>
        </div>
        <button class="btn" id="levelDone">${state.levelTest?.afterRegistration ? "Начать обучение" : "К учебе"}</button>
        <button class="btn btn-secondary" id="levelRetry">Пройти еще раз</button>
      </div>`;
    document.getElementById("levelDone").onclick = () => {
      haptic("success");
      if (state.levelTest?.afterRegistration) renderMenu();
      else renderLearningHub();
    };
    document.getElementById("levelRetry").onclick = () => {
      haptic();
      renderLevelTestIntro({ afterRegistration: Boolean(state.levelTest?.afterRegistration) });
    };
  } catch (e) {
    renderError(e.message);
  }
}

// Правильное склонение: 1 слово, 2-4 слова, 5-20 слов.
function wordsLabel(value) {
  const n = Math.max(0, Number(value) || 0);
  const lastTwo = n % 100;
  const last = n % 10;
  const suffix = lastTwo >= 11 && lastTwo <= 14
    ? "слов"
    : last === 1 ? "слово" : last >= 2 && last <= 4 ? "слова" : "слов";
  return `${n} ${suffix}`;
}

// Шаг 1: выбор темы (колоды). Показываем только темы, где для возраста ребёнка
// достаточно слов (сервер фильтрует), плюс «Любые слова» — случайный набор.
async function renderVocabStart() {
  setBack(renderLearningHub);
  loading();
  try {
    const data = await api("/api/vocab/topics", "GET");
    const topics = data.topics || [];
    app.innerHTML = `
      <div class="screen">
        <h1>Выбери тему</h1>
        <p class="hint">С чего начнём сегодня?</p>
        <div class="hub-grid">
          ${topics.map(t => `
            <button class="action-tile vocab-topic" data-topic="${esc(t.topic)}">
              <i class="tile-ic">${esc(t.emoji)}</i>
              <b>${esc(t.label)}</b>
              <small>${wordsLabel(t.count)}</small>
            </button>`).join("")}
          <button class="action-tile vocab-topic" data-topic="">
            <i class="tile-ic">🎲</i>
            <b>Любые слова</b>
            <small>случайный набор</small>
          </button>
        </div>
      </div>`;
    document.querySelectorAll(".vocab-topic").forEach(btn => {
      btn.onclick = () => { haptic(); renderVocabWords(btn.dataset.topic || null); };
    });
  } catch (e) {
    renderError(e.message);
  }
}

// Шаг 2: карточки слов выбранной темы, затем тест.
async function renderVocabWords(topic) {
  setBack(renderVocabStart);
  loading();
  try {
    const data = await api("/api/vocab/start", "POST", topic ? { topic } : {});
    state.vocab = data;
    app.innerHTML = `
      <div class="screen">
        <h1>Новые слова</h1>
        <p class="hint">Сначала посмотри карточки, потом пройди короткий тест.</p>
        ${data.words.map((w, index) => `
          ${wordStudyCard(w, { badge: `Слово ${index + 1}`, showImage: true })}
        `).join("")}
        <button class="btn" id="startQuiz">Начать тест</button>
      </div>`;
    document.getElementById("startQuiz").onclick = () => { haptic(); renderVocabQuiz(); };
    bindPronunciationButtons();
    queueWordAudioPreload(data.words.map(w => w.word));
  } catch (e) {
    renderError(e.message);
  }
}

async function renderVocabQuiz() {
  setBack(renderVocabStart);
  loading();
  try {
    state.quiz = await api("/api/vocab/quiz", "POST", { session_id: state.vocab.session_id });
    state.answers = [];
    state.quizSession = {
      round: 1,
      target: trainingTarget(),
      totalCorrect: 0,
      totalWrong: 0,
      roundCorrect: 0,
      roundWrong: 0,
      mistakes: [],
      reviewStarted: false,
    };
    renderQuizQuestion(0);
  } catch (e) {
    renderError(e.message);
  }
}

function quizProgressHtml(index) {
  const session = state.quizSession || {};
  const total = state.quiz?.questions?.length || 0;
  const remaining = Math.max(total - index - 1, 0);
  const label = session.reviewStarted ? `Повтор ошибок · раунд ${session.round}` : "Основной набор";
  return `
    <div class="training-progress">
      <div><b>Слово ${Math.min(index + 1, total)} из ${total}</b><span>${esc(label)}</span></div>
      <div class="training-stats">
        <span>Правильно: <b>${session.totalCorrect || 0}</b></span>
        <span>Ошибок: <b>${session.totalWrong || 0}</b></span>
        <span>Осталось: <b>${remaining}</b></span>
      </div>
    </div>`;
}

function quizPromptCard(q, badge = "") {
  const badgeHtml = badge ? `<div class="daily-badge">${esc(badge)}</div>` : "<span></span>";
  if (q.type === "listen") {
    // Аудирование: проигрываем озвучку слова, само слово скрыто -> выбрать перевод.
    return `
      <div class="card word-card compact">
        <div class="word-card-top">${badgeHtml}<span></span></div>
        <div class="quiz-listen">
          ${pronunciationButtonHtml(q.audio_word)}
          <span class="quiz-listen-hint">Нажми и послушай</span>
        </div>
        <p class="hint mt-12">${esc(q.prompt)}</p>
      </div>`;
  }
  if (q.type === "image") {
    // Картинка (эмодзи) -> выбрать перевод.
    return `
      <div class="card word-card compact">
        <div class="word-card-top">${badgeHtml}<span></span></div>
        <div class="quiz-emoji" role="img" aria-label="картинка">${esc(q.emoji)}</div>
        <p class="hint mt-12">${esc(q.prompt)}</p>
      </div>`;
  }
  if (q.type === "word") {
    // Показываем перевод -> ребёнок выбирает английское слово.
    return `
      <div class="card word-card compact">
        <div class="word-card-top">${badgeHtml}<span></span></div>
        <div class="quiz-ask-word">${esc(q.translation)}</div>
        <p class="hint mt-12">${esc(q.prompt)}</p>
      </div>`;
  }
  if (q.type === "gap") {
    // Показываем пример с пропуском -> ребёнок выбирает пропущенное слово.
    return `
      <div class="card word-card compact">
        <div class="word-card-top">${badgeHtml}<span></span></div>
        <div class="quiz-ask-gap">${esc(q.gap_text || q.example)}</div>
        ${q.translation ? `<div class="word-hint">${esc(q.translation)}</div>` : ""}
        <p class="hint mt-12">${esc(q.prompt)}</p>
      </div>`;
  }
  // translation (по умолчанию): показываем слово + транскрипцию -> выбрать перевод.
  return wordStudyCard(q, { badge, prompt: q.prompt, compact: true, showTranslation: false, showLearningDetails: false });
}

function renderQuizQuestion(index) {
  const q = state.quiz.questions[index];
  if (!q) return finishVocabRound();
  const progress = `${index + 1}/${state.quiz.questions.length}`;
  app.innerHTML = `
    <div class="screen">
      <h1>Тест по словам</h1>
      ${quizProgressHtml(index)}
      ${quizPromptCard(q, progress)}
      ${q.options.map(o => `
        <button class="btn btn-secondary answer" data-id="${o.id}">${esc(o.label)}</button>
      `).join("")}
    </div>`;

  document.querySelectorAll(".answer").forEach(btn => {
    btn.onclick = () => {
      const selectedId = Number(btn.dataset.id);
      const correct = selectedId === q.word_id;
      state.answers.push({ word_id: q.word_id, selected_id: selectedId });
      if (state.quizSession) {
        if (correct) {
          state.quizSession.totalCorrect += 1;
          state.quizSession.roundCorrect += 1;
        } else {
          state.quizSession.totalWrong += 1;
          state.quizSession.roundWrong += 1;
          state.quizSession.mistakes.push(q);
        }
      }
      document.querySelectorAll(".answer").forEach(item => item.disabled = true);
      btn.classList.remove("btn-secondary");
      btn.classList.add(correct ? "btn-correct" : "btn-wrong");
      if (!correct) {
        const correctButton = document.querySelector(`.answer[data-id="${q.word_id}"]`);
        correctButton?.classList.remove("btn-secondary");
        correctButton?.classList.add("btn-correct");
      }
      haptic(correct ? "success" : "error");
      setTimeout(() => renderQuizQuestion(index + 1), 650);
    };
  });
  bindPronunciationButtons();
  if (q.word) queueWordAudioPreload([q.word]);
}

function finishVocabRound() {
  const session = state.quizSession;
  if (!session) return finishVocabQuiz();
  const roundTotal = session.roundCorrect + session.roundWrong;
  const roundScore = roundTotal ? Math.round(session.roundCorrect / roundTotal * 100) : 0;
  const uniqueMistakes = [];
  const seen = new Set();
  session.mistakes.forEach(question => {
    if (!question.word_id || seen.has(question.word_id)) return;
    seen.add(question.word_id);
    uniqueMistakes.push(question);
  });
  if (uniqueMistakes.length && (!session.reviewStarted || roundScore < session.target) && session.round < 6) {
    session.reviewStarted = true;
    session.round += 1;
    session.roundCorrect = 0;
    session.roundWrong = 0;
    session.mistakes = [];
    state.quiz.questions = uniqueMistakes;
    app.innerHTML = `
      <div class="screen">
        <h1>Повторим ошибки</h1>
        <div class="card center">
          <div class="big" style="color: var(--button)">${uniqueMistakes.length}</div>
          <p class="hint">Сейчас закрепим только слова, где была ошибка. Цель: ${session.target}% правильных ответов.</p>
        </div>
      </div>`;
    queueWordAudioPreload(uniqueMistakes.map(item => item.word));
    setTimeout(() => renderQuizQuestion(0), 850);
    return;
  }
  finishVocabQuiz();
}

async function finishVocabQuiz() {
  loading();
  try {
    const result = await api("/api/vocab/finish", "POST", {
      session_id: state.vocab.session_id,
      answers: state.answers,
    });
    state.me.user.points = result.points;
    const mistakes = result.results.filter(r => !r.correct);
    app.innerHTML = `
      <div class="screen">
        <h1>Результат теста</h1>
        <div class="card center">
          <div class="big" style="color: var(--button)">${result.score}%</div>
          <p>${result.correct_count} правильно из ${result.total}</p>
          <p><b>${result.delta >= 0 ? "+" : ""}${result.delta} 💎</b> · всего: ${result.points}</p>
        </div>
        ${mistakes.length ? `
          <div class="card">
            <h2>Повторить</h2>
            ${mistakes.map(m => `
              ${reviewWordRow(m)}
            `).join("")}
          </div>
        ` : `<div class="card center"><b>Отлично!</b><p class="hint">Все слова запомнились.</p></div>`}
        <button class="btn" id="again">Еще набор слов</button>
        <button class="btn btn-secondary" id="home">К учебе</button>
      </div>`;
    document.getElementById("again").onclick = () => { haptic(); renderVocabStart(); };
    document.getElementById("home").onclick = () => { haptic(); renderLearningHub(); };
    bindPronunciationButtons();
  } catch (e) {
    renderError(e.message);
  }
}

function renderGamesMenu() {
  setBack(renderLearningHub);
  app.innerHTML = `
    <div class="screen">
      <h1>Игры со словами</h1>
      <div class="card">
        <h2>Словесная охота</h2>
        <p class="hint">Короткая игра: смотри перевод и лови правильное английское слово. За правильные ответы начисляются баллы, штрафов нет.</p>
      </div>
      <button class="btn" id="wordHuntStart">Играть</button>
      <button class="btn btn-secondary" id="wordHuntHome">К учебе</button>
    </div>`;
  document.getElementById("wordHuntStart").onclick = () => { haptic(); startWordHunt(); };
  document.getElementById("wordHuntHome").onclick = () => { haptic(); renderLearningHub(); };
}

async function startWordHunt() {
  setBack(renderGamesMenu);
  loading();
  try {
    const data = await api("/api/game/word-hunt/start", "POST", {});
    state.game = {
      data,
      answers: [],
      score: 0,
    };
    renderWordHuntRound(0);
  } catch (e) {
    renderError(e.message);
  }
}

function renderWordHuntRound(index) {
  const game = state.game?.data;
  const round = game?.rounds?.[index];
  if (!round) return finishWordHunt();
  const progress = `${index + 1}/${game.rounds.length}`;
  setBack(renderGamesMenu);
  app.innerHTML = `
    <div class="screen">
      <h1>${esc(game.title || "Словесная охота")}</h1>
      <div class="game-score">
        <span>${progress}</span>
        <b>${state.game.score} поймано</b>
      </div>
      <div class="card center word-hunt-card">
        <div class="daily-badge">Найди слово</div>
        <div class="big-sub mt-12">${esc(round.translation)}</div>
        <p class="hint mt-12">${esc(round.prompt)}</p>
      </div>
      <div class="game-options">
        ${round.options.map(option => `
          <button class="btn btn-secondary game-option" data-id="${option.id}">${esc(option.word)}</button>
        `).join("")}
      </div>
    </div>`;

  document.querySelectorAll(".game-option").forEach(btn => {
    btn.onclick = () => {
      const selectedId = Number(btn.dataset.id);
      const correct = selectedId === round.word_id;
      state.game.answers[index] = { word_id: round.word_id, selected_id: selectedId };
      if (correct) state.game.score += 1;
      document.querySelectorAll(".game-option").forEach(item => item.disabled = true);
      btn.classList.remove("btn-secondary");
      btn.classList.add(correct ? "btn-correct" : "btn-wrong");
      haptic(correct ? "success" : "error");
      setTimeout(() => renderWordHuntRound(index + 1), 550);
    };
  });
}

async function finishWordHunt() {
  setBack(renderGamesMenu);
  loading();
  try {
    const result = await api("/api/game/word-hunt/finish", "POST", {
      session_id: state.game.data.session_id,
      answers: state.game.answers.filter(Boolean),
    });
    if (state.me?.user) state.me.user.points = result.points;
    const mistakes = result.results.filter(item => !item.correct);
    app.innerHTML = `
      <div class="screen">
        <h1>Охота завершена</h1>
        <div class="card center">
          <div class="big" style="color: var(--button)">${result.score}%</div>
          <p>${result.correct_count} поймано из ${result.total}</p>
          <p><b>+${result.delta} 💎</b> · всего: ${result.points}</p>
          ${result.perfect_bonus ? `<p class="hint">Бонус за идеальную игру: +${result.perfect_bonus} 💎</p>` : ""}
        </div>
        ${mistakes.length ? `
          <div class="card">
            <h2>Потренировать еще</h2>
            ${mistakes.map(item => `
              ${reviewWordRow(item)}
            `).join("")}
          </div>
        ` : `<div class="card center"><b>Отличная охота!</b><p class="hint">Все слова пойманы правильно.</p></div>`}
        <button class="btn" id="gameAgain">Играть еще</button>
        <button class="btn btn-secondary" id="gameHome">К учебе</button>
      </div>`;
    document.getElementById("gameAgain").onclick = () => { haptic(); startWordHunt(); };
    document.getElementById("gameHome").onclick = () => { haptic(); renderLearningHub(); };
    bindPronunciationButtons();
  } catch (e) {
    renderError(e.message);
  }
}

async function renderDictionary() {
  setBack(renderLearningHub);
  loading();
  try {
    state.dictionaryFilter = "all";
    const data = await api("/api/dictionary?filter=all&limit=5000", "GET");
    const words = data.words || [];
    app.innerHTML = `
      <div class="screen">
        <h1>Словарь</h1>
        <div class="card dictionary-search-card">
          <input id="dictionarySearch" type="text" placeholder="Найти слово..." autocomplete="off">
        </div>
        ${words.length ? `
          <div class="card dictionary-list">
            ${words.map(word => `
              <div class="dictionary-row" data-word="${esc(word.word)}" data-search="${esc(normalizeDictionarySearch(`${word.word} ${word.translation} ${word.transcription || ""}`))}">
                <div class="dictionary-main">
                  <b>${esc(word.word)}</b>
                  ${word.transcription ? `<small class="transcription">${esc(word.transcription)}</small>` : ""}
                  <span>${esc(word.translation)}</span>
                </div>
                <div class="dictionary-side">
                  <button type="button" class="pronounce-btn small" data-word="${esc(word.word)}">🔊</button>
                </div>
              </div>
            `).join("")}
          </div>
          <div class="card center" id="dictionaryNoResults" style="display:none">
            <b>Ничего не найдено</b>
            <p class="hint">Попробуй другое слово или перевод.</p>
          </div>
        ` : `
          <div class="card center">
            <b>Словарь пока пуст</b>
            <p class="hint">Пройди набор новых слов или ежедневный урок, и слова появятся здесь.</p>
          </div>
        `}
      </div>`;
    const search = document.getElementById("dictionarySearch");
    const rows = Array.from(document.querySelectorAll(".dictionary-row"));
    const empty = document.getElementById("dictionaryNoResults");
    const applySearch = () => {
      const query = normalizeDictionarySearch(search.value);
      let visible = 0;
      const preloadWords = [];
      rows.forEach(row => {
        const matches = !query || row.dataset.search.includes(query);
        row.hidden = !matches;
        if (matches) visible += 1;
        if (matches && preloadWords.length < 12) preloadWords.push(row.dataset.word);
      });
      if (empty) empty.style.display = visible ? "none" : "block";
      queueWordAudioPreload(preloadWords);
    };
    let searchFrame = null;
    search.addEventListener("input", () => {
      if (searchFrame !== null) cancelAnimationFrame(searchFrame);
      searchFrame = requestAnimationFrame(() => {
        searchFrame = null;
        applySearch();
      });
    });
    bindPronunciationButtons();
    queueWordAudioPreload(words.slice(0, 16).map(word => word.word));
  } catch (e) {
    renderError(e.message);
  }
}

async function renderTrainingMenu(focus = "all") {
  setBack(renderLearningHub);
  const reviewMode = focus === "review";
  app.innerHTML = `
    <div class="screen">
      <h1>${reviewMode ? "Повторение ошибок" : "Тренировка слов"}</h1>
      <div class="card">
        <p class="hint">${reviewMode
          ? "Сейчас будут слова, в которых были ошибки или которые пора освежить."
          : "Короткая практика без длинного теста: выбери перевод или напиши слово по-английски."}</p>
        ${reviewMode ? `<p class="hint review-due-line" id="reviewDueLine" hidden>Готово к повторению: <b id="reviewDueCount">0</b></p>` : ""}
        ${trainingTargetControlHtml()}
      </div>
      <button class="btn" id="choiceTraining">Выбрать перевод</button>
      <button class="btn" id="inputTraining">Написать слово</button>
      <button class="btn btn-secondary" id="trainingHome">К учебе</button>
    </div>`;
  document.getElementById("choiceTraining").onclick = () => { haptic(); renderChoiceTraining(focus); };
  document.getElementById("inputTraining").onclick = () => { haptic(); renderInputTraining(focus); };
  document.getElementById("trainingHome").onclick = () => { haptic(); renderLearningHub(); };
  bindTrainingTargetButtons();
  if (reviewMode) {
    updateReviewNudges();
    ensureLearningPath().then(updateReviewNudges);
  }
}

async function renderChoiceTraining(focus = "all") {
  return startTrainingSession("choice", focus);
}

async function renderInputTraining(focus = "all") {
  return startTrainingSession("input", focus);
}

const TRAINING_SESSION_SIZE = 10;
const TRAINING_REVIEW_SESSION_SIZE = 8;
const TRAINING_TARGET_KEY = "englishTutorKidsTrainingTarget";

function trainingTarget() {
  const value = Number(localStorage.getItem(TRAINING_TARGET_KEY) || 90);
  return [80, 90, 100].includes(value) ? value : 90;
}

function setTrainingTarget(value) {
  const target = [80, 90, 100].includes(Number(value)) ? Number(value) : 90;
  localStorage.setItem(TRAINING_TARGET_KEY, String(target));
  return target;
}

function trainingTargetControlHtml() {
  const target = trainingTarget();
  return `
    <div class="training-target">
      <span>Повторять ошибки до</span>
      <div>
        ${[80, 90, 100].map(value => `
          <button type="button" class="target-btn ${target === value ? "active" : ""}" data-target="${value}">${value}%</button>
        `).join("")}
      </div>
    </div>`;
}

function bindTrainingTargetButtons(root = document) {
  root.querySelectorAll(".target-btn").forEach(button => {
    button.onclick = () => {
      haptic();
      const target = setTrainingTarget(button.dataset.target);
      root.querySelectorAll(".target-btn").forEach(item => {
        item.classList.toggle("active", Number(item.dataset.target) === target);
      });
      if (state.training) state.training.target = target;
    };
  });
}

function startTrainingSession(mode, focus = "all") {
  const reviewMode = focus === "review";
  state.training = {
    mode,
    focus,
    target: trainingTarget(),
    total: reviewMode ? TRAINING_REVIEW_SESSION_SIZE : TRAINING_SESSION_SIZE,
    round: 1,
    currentIndex: 0,
    roundCorrect: 0,
    roundWrong: 0,
    totalCorrect: 0,
    totalWrong: 0,
    mistakes: [],
    reviewQueue: [],
    reviewStarted: false,
    excludeIds: [],
  };
  return renderTrainingSessionNext();
}

function trainingRoundTotal(session) {
  return session.reviewQueue.length || session.total;
}

function trainingRoundLabel(session) {
  if (session.reviewQueue.length) return `Повтор ошибок · раунд ${session.round}`;
  return session.focus === "review" ? "Работа над ошибками" : "Тренировка";
}

function trainingProgressHtml(session) {
  const total = trainingRoundTotal(session);
  const current = Math.min(session.currentIndex + 1, total);
  const remaining = Math.max(total - session.currentIndex - 1, 0);
  return `
    <div class="training-progress">
      <div><b>Слово ${current} из ${total}</b><span>${esc(trainingRoundLabel(session))}</span></div>
      <div class="training-stats">
        <span>Правильно: <b>${session.totalCorrect}</b></span>
        <span>Ошибок: <b>${session.totalWrong}</b></span>
        <span>Осталось: <b>${remaining}</b></span>
      </div>
    </div>`;
}

async function loadTrainingTask(session) {
  const endpoint = session.mode === "choice"
    ? "/api/training/choice/next"
    : "/api/training/input/next";
  const body = { focus: session.focus };
  if (session.reviewQueue.length) {
    body.word_id = session.reviewQueue[session.currentIndex];
  } else {
    body.exclude_ids = session.excludeIds.slice(-60);
  }
  const task = await api(endpoint, "POST", body);
  if (!session.reviewQueue.length && task.word_id) {
    session.excludeIds.push(task.word_id);
  }
  return task;
}

async function renderTrainingSessionNext() {
  const session = state.training;
  if (!session) return renderTrainingMenu("all");
  setBack(() => renderTrainingMenu(session.focus));
  if (session.currentIndex >= trainingRoundTotal(session)) {
    return finishTrainingRound();
  }
  loading();
  try {
    const task = await loadTrainingTask(session);
    session.currentTask = task;
    if (session.mode === "choice") renderChoiceTrainingTask(task, session);
    else renderInputTrainingTask(task, session);
  } catch (e) {
    renderError(e.message);
  }
}

function renderChoiceTrainingTask(task, session) {
  app.innerHTML = `
    <div class="screen">
      <h1>Выбери перевод</h1>
      ${trainingProgressHtml(session)}
      ${task.review_empty ? `<div class="card"><p class="hint">Ошибок для повторения пока нет, поэтому даю обычное слово.</p></div>` : ""}
      ${wordStudyCard(task, { compact: true, showTranslation: false, showLearningDetails: false })}
      <div class="training-options">
        ${task.options.map(option => `
          <button class="btn btn-secondary choice-answer" data-id="${option.id}">${esc(option.translation)}</button>
        `).join("")}
      </div>
      <div id="trainingFeedback"></div>
    </div>`;

  document.querySelectorAll(".choice-answer").forEach(button => {
    button.onclick = async () => {
      const selectedId = Number(button.dataset.id);
      document.querySelectorAll(".choice-answer").forEach(item => item.disabled = true);
      try {
        const result = await api("/api/training/choice/answer", "POST", {
          word_id: task.word_id,
          selected_id: selectedId,
          focus: session.focus,
          attempt_id: task.attempt_id,
        });
        if (state.me?.user) state.me.user.points = result.points;
        button.classList.remove("btn-secondary");
        button.classList.add(result.correct ? "btn-correct" : "btn-wrong");
        if (!result.correct) {
          const correctButton = document.querySelector(`.choice-answer[data-id="${result.word_id}"]`);
          correctButton?.classList.remove("btn-secondary");
          correctButton?.classList.add("btn-correct");
        }
        showTrainingAnswerFeedback(result, session);
      } catch (e) {
        renderError(e.message);
      }
    };
  });
  bindPronunciationButtons();
  queueWordAudioPreload([task.word]);
}

function renderInputTrainingTask(task, session) {
  app.innerHTML = `
    <div class="screen">
      <h1>Напиши слово</h1>
      ${trainingProgressHtml(session)}
      ${task.review_empty ? `<div class="card"><p class="hint">Ошибок для повторения пока нет, поэтому даю обычное слово.</p></div>` : ""}
      <div class="card center">
        <p class="hint">Напиши по-английски:</p>
        <div class="big-sub">${esc(task.translation)}</div>
      </div>
      <input id="inputAnswer" type="text" placeholder="English word" autocomplete="off">
      <button class="btn" id="checkInputAnswer">Проверить</button>
      <div id="trainingFeedback"></div>
    </div>`;

  const input = document.getElementById("inputAnswer");
  const button = document.getElementById("checkInputAnswer");
  const submit = async () => {
    const answer = input.value.trim();
    if (!answer) return tg.showAlert("Напиши слово");
    input.disabled = true;
    button.disabled = true;
    try {
      const result = await api("/api/training/input/answer", "POST", {
        word_id: task.word_id,
        answer,
        focus: session.focus,
        attempt_id: task.attempt_id,
      });
      if (state.me?.user) state.me.user.points = result.points;
      showTrainingAnswerFeedback(result, session);
    } catch (e) {
      renderError(e.message);
    }
  };
  button.onclick = submit;
  input.addEventListener("keypress", e => { if (e.key === "Enter") submit(); });
  input.focus();
}

function showTrainingAnswerFeedback(result, session) {
  const correct = Boolean(result.correct);
  haptic(correct ? "success" : "error");
  if (correct) {
    session.totalCorrect += 1;
    session.roundCorrect += 1;
  } else {
    session.totalWrong += 1;
    session.roundWrong += 1;
    session.mistakes.push({
      word_id: result.word_id,
      word: result.word,
      translation: result.translation,
      transcription: result.transcription || "",
    });
  }
  const feedback = document.getElementById("trainingFeedback");
  if (feedback) {
    feedback.innerHTML = `
      <div class="training-feedback ${correct ? "correct" : "wrong"}">
        <b>${correct ? "Верно!" : "Запомни правильный вариант"}</b>
        <span>${esc(result.word)} — ${esc(result.translation)}</span>
        ${result.transcription ? `<small>${esc(result.transcription)}</small>` : ""}
      </div>`;
  }
  queueWordAudioPreload([result.word], 1);
  session.currentIndex += 1;
  setTimeout(() => renderTrainingSessionNext(), correct ? 620 : 1050);
}

function finishTrainingRound() {
  const session = state.training;
  if (!session) return renderTrainingMenu("all");
  const roundTotal = session.roundCorrect + session.roundWrong;
  const roundScore = roundTotal ? Math.round(session.roundCorrect / roundTotal * 100) : 0;
  const uniqueMistakes = [];
  const seen = new Set();
  session.mistakes.forEach(item => {
    if (!item.word_id || seen.has(item.word_id)) return;
    seen.add(item.word_id);
    uniqueMistakes.push(item);
  });

  if (uniqueMistakes.length && (!session.reviewStarted || roundScore < session.target) && session.round < 6) {
    session.reviewStarted = true;
    session.reviewQueue = uniqueMistakes.map(item => item.word_id);
    session.mistakes = [];
    session.currentIndex = 0;
    session.roundCorrect = 0;
    session.roundWrong = 0;
    session.round += 1;
    app.innerHTML = `
      <div class="screen">
        <h1>Повторим ошибки</h1>
        <div class="card center">
          <div class="big" style="color: var(--button)">${uniqueMistakes.length}</div>
          <p class="hint">Сейчас быстро закрепим только слова, где была ошибка. Цель: ${session.target}% правильных ответов.</p>
        </div>
      </div>`;
    queueWordAudioPreload(uniqueMistakes.map(item => item.word));
    setTimeout(() => renderTrainingSessionNext(), 850);
    return;
  }

  renderTrainingSessionComplete(session);
}

function renderTrainingSessionComplete(session) {
  const total = session.totalCorrect + session.totalWrong;
  const score = total ? Math.round(session.totalCorrect / total * 100) : 0;
  app.innerHTML = `
    <div class="screen">
      <h1>Тренировка завершена</h1>
      <div class="card center">
        <div class="big" style="color: var(--button)">${score}%</div>
        <p>${session.totalCorrect} правильно из ${total}</p>
        <p class="hint">Ошибок: ${session.totalWrong} · цель повторения: ${session.target}%</p>
      </div>
      <button class="btn" id="trainingAgain">Еще тренировка</button>
      <button class="btn btn-secondary" id="trainingModes">Другой режим</button>
      <button class="btn btn-secondary" id="trainingMenu">К учебе</button>
    </div>`;
  document.getElementById("trainingAgain").onclick = () => { haptic(); startTrainingSession(session.mode, session.focus); };
  document.getElementById("trainingModes").onclick = () => { haptic(); renderTrainingMenu(session.focus); };
  document.getElementById("trainingMenu").onclick = () => { haptic(); renderLearningHub(); };
}

function renderTrainingResult({ correct, title, text, pronounceWord = "", transcription = "", delta, points, next, focus = "all" }) {
  setBack(() => renderTrainingMenu(focus));
  const reviewMode = focus === "review";
  haptic(correct ? "success" : "error");
  app.innerHTML = `
    <div class="screen">
      <div class="result-card ${correct ? "correct" : "wrong"}">
        <h1>${esc(title)}</h1>
        <p>${esc(text)}</p>
        ${pronounceWord ? `
          <div class="word-pronunciation result">
            <span>${esc(transcription || "")}</span>
            ${pronunciationButtonHtml(pronounceWord)}
          </div>
        ` : ""}
        <p><b>${delta >= 0 ? "+" : ""}${delta} 💎</b> · всего: ${points}</p>
      </div>
      <button class="btn" id="trainingNext">${reviewMode ? "Еще на повторение" : "Еще слово"}</button>
      <button class="btn btn-secondary" id="trainingModes">Другой режим</button>
      <button class="btn btn-secondary" id="trainingMenu">К учебе</button>
    </div>`;
  document.getElementById("trainingNext").onclick = () => { haptic(); next(); };
  document.getElementById("trainingModes").onclick = () => { haptic(); renderTrainingMenu(focus); };
  document.getElementById("trainingMenu").onclick = () => { haptic(); renderLearningHub(); };
  bindPronunciationButtons();
}

async function updateDailyProgress(completedSteps) {
  const status = await api("/api/daily/progress", "POST", { completed_steps: completedSteps });
  if (state.me?.user && typeof status.points === "number") {
    state.me.user.points = status.points;
  }
  return status;
}

async function renderDailyLesson() {
  setBack(renderLearningHub);
  loading();
  try {
    const status = await api("/api/daily/status", "GET");
    app.innerHTML = `
      <div class="screen">
        <h1>Ежедневный урок</h1>
        <div class="card">
          <div class="daily-badge">${status.completed ? "На сегодня готово" : "5 минут"}</div>
          <p class="hint mt-12">Мини-урок состоит из слов, теста и маленькой практики. Уровень: ${esc(state.me?.user?.level_label || "Beginner / A1")}.</p>
          <div class="daily-steps">
            ${["Слово", "Тест", "Фраза", "Готово"].map((title, i) => `
              <div class="daily-step ${status.completed_steps > i ? "done" : ""}">
                <span>${status.completed_steps > i ? "✓" : i + 1}</span><b>${title}</b>
              </div>
            `).join("")}
          </div>
        </div>
        <button class="btn" id="dailyStart">${status.completed ? "Потренироваться еще" : "Начать с новых слов"}</button>
      </div>`;
    document.getElementById("dailyStart").onclick = () => { haptic(); renderDailyWords(); };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderDailyWords() {
  setBack(renderDailyLesson);
  loading();
  try {
    const data = await api("/api/vocab/start", "POST", {});
    state.dailyVocab = data;
    state.dailyQuiz = null;
    state.dailyAnswers = [];
    const words = data.words.slice(0, Math.min(4, data.words.length));
    app.innerHTML = `
      <div class="screen">
        <h1>Урок: новые слова</h1>
        <div class="card">
          <div class="daily-badge">Шаг 1 из 4</div>
          <p class="hint mt-12">Посмотри слова. Потом будет короткий тест и одна фраза для практики.</p>
        </div>
        ${words.map((w, index) => `
          ${wordStudyCard(w, { badge: `Слово ${index + 1}`, showImage: true })}
        `).join("")}
        <button class="btn" id="dailyWordsDone">Я запомнил слова</button>
      </div>`;
    document.getElementById("dailyWordsDone").onclick = async () => {
      haptic("success");
      loading();
      try {
        await updateDailyProgress(1);
        renderDailyQuiz();
      } catch (e) {
        renderError(e.message);
      }
    };
    bindPronunciationButtons();
  } catch (e) {
    renderError(e.message);
  }
}

async function renderDailyQuiz() {
  setBack(renderDailyWords);
  loading();
  try {
    state.dailyQuiz = await api("/api/vocab/quiz", "POST", { session_id: state.dailyVocab.session_id });
    state.dailyQuiz.questions = state.dailyQuiz.questions.slice(0, Math.min(3, state.dailyQuiz.questions.length));
    state.dailyAnswers = [];
    renderDailyQuizQuestion(0);
  } catch (e) {
    renderError(e.message);
  }
}

function renderDailyQuizQuestion(index) {
  const q = state.dailyQuiz.questions[index];
  if (!q) return finishDailyQuiz();
  app.innerHTML = `
    <div class="screen">
      <h1>Урок: мини-тест</h1>
      ${quizPromptCard(q, `Шаг 2 из 4 · ${index + 1}/${state.dailyQuiz.questions.length}`)}
      ${q.options.map(o => `
        <button class="btn btn-secondary daily-answer" data-id="${o.id}">${esc(o.label)}</button>
      `).join("")}
    </div>`;

  document.querySelectorAll(".daily-answer").forEach(btn => {
    btn.onclick = () => {
      const selectedId = Number(btn.dataset.id);
      state.dailyAnswers.push({ word_id: q.word_id, selected_id: selectedId });
      document.querySelectorAll(".daily-answer").forEach(item => item.disabled = true);
      btn.classList.remove("btn-secondary");
      btn.classList.add(selectedId === q.word_id ? "btn-correct" : "btn-wrong");
      haptic(selectedId === q.word_id ? "success" : "error");
      setTimeout(() => renderDailyQuizQuestion(index + 1), 650);
    };
  });
  bindPronunciationButtons();
}

async function finishDailyQuiz() {
  loading();
  try {
    state.dailyResult = await api("/api/vocab/finish", "POST", {
      session_id: state.dailyVocab.session_id,
      answers: state.dailyAnswers,
    });
    if (state.me?.user) state.me.user.points = state.dailyResult.points;
    await updateDailyProgress(2);
    renderDailyPhrase();
  } catch (e) {
    renderError(e.message);
  }
}

function normalizePhrase(value) {
  return String(value || "").trim().toLowerCase().replace(/[.!?]+$/g, "");
}

function renderDailyPhrase() {
  setBack(renderDailyLesson);
  const firstWord = state.dailyVocab?.words?.[0]?.word || "English";
  const phrase = `I like ${firstWord}.`;
  app.innerHTML = `
    <div class="screen">
      <h1>Урок: фраза</h1>
      <div class="card">
        <div class="daily-badge">Шаг 3 из 4</div>
        <p class="hint mt-12">Напиши эту фразу по-английски. Можно без точки.</p>
        <div class="big-sub mt-12">${esc(phrase)}</div>
      </div>
      <input id="dailyPhraseInput" type="text" placeholder="${esc(phrase)}" autocomplete="off">
      <button class="btn" id="dailyPhraseDone">Проверить</button>
    </div>`;
  document.getElementById("dailyPhraseDone").onclick = async () => {
    const answer = document.getElementById("dailyPhraseInput").value;
    if (!answer.trim()) return tg.showAlert("Напиши фразу");
    loading();
    try {
      const isClose = normalizePhrase(answer) === normalizePhrase(phrase);
      haptic(isClose ? "success" : "warning");
      await updateDailyProgress(3);
      renderDailyFinish(isClose, phrase);
    } catch (e) {
      renderError(e.message);
    }
  };
}

async function renderDailyFinish(phraseWasCorrect = true, phrase = "") {
  setBack(renderDailyLesson);
  loading();
  try {
    const status = await updateDailyProgress(4);
    const result = state.dailyResult || {};
    const reward = status.reward_points || 0;
    app.innerHTML = `
      <div class="screen">
        <h1>Урок завершен</h1>
        <div class="card center">
          <div class="daily-badge">Шаг 4 из 4</div>
          <div class="big mt-12">${result.score ?? 0}%</div>
          <p class="hint">Мини-тест: ${result.correct_count ?? 0} правильно из ${result.total ?? 0}</p>
          ${phraseWasCorrect ? `<p>Фраза написана правильно.</p>` : `<p>Фраза для повторения: <b>${esc(phrase)}</b></p>`}
          <p><b>${reward ? `+${reward} баллов за урок` : "Урок уже был засчитан сегодня"}</b></p>
          <p class="hint">Всего баллов: ${status.points ?? state.me?.user?.points ?? 0}</p>
        </div>
        <button class="btn" id="dailyHome">К учебе</button>
      </div>`;
    document.getElementById("dailyHome").onclick = () => { haptic(); renderLearningHub(); };
  } catch (e) {
    renderError(e.message);
  }
}

// Младшим (5-10) — нарисованный анимированный персонаж с настоящей мимикой
// (черты в SVG, поэтому всё совпадает). Старшим (11-18) — спокойное фото + свечение.
const CHARACTER_AGE_GROUPS = ["5_7", "8_10"];

function tutorCharacterSvg() {
  return `
    <svg class="char-avatar" viewBox="0 0 200 200" aria-hidden="true">
      <defs><clipPath id="charClip"><circle cx="100" cy="100" r="94"/></clipPath></defs>
      <circle class="char-bg" cx="100" cy="100" r="94"/>
      <g clip-path="url(#charClip)">
        <ellipse class="char-body" cx="100" cy="214" rx="78" ry="48"/>
        <path class="char-collar" d="M74 170 Q100 190 126 170 L126 202 L74 202 Z"/>
        <ellipse class="char-hair char-hair-back" cx="100" cy="90" rx="60" ry="56"/>
        <ellipse class="char-skin char-faceshape" cx="100" cy="100" rx="55" ry="53"/>
        <circle class="char-skin char-ear" cx="46" cy="102" r="9"/>
        <circle class="char-skin char-ear" cx="154" cy="102" r="9"/>
        <path class="char-hair" d="M45 82 Q42 44 100 42 Q158 44 155 82 Q146 64 124 62 Q132 76 110 74 Q104 60 100 60 Q96 60 90 74 Q68 76 76 62 Q54 64 45 82 Z"/>
        <circle class="char-cheek" cx="58" cy="118" r="11"/>
        <circle class="char-cheek" cx="142" cy="118" r="11"/>
        <path class="char-brow brow-left" d="M58 84 Q73 77 88 84"/>
        <path class="char-brow brow-right" d="M112 84 Q127 77 142 84"/>
        <g class="char-eye eye-left">
          <ellipse class="eye-white" cx="74" cy="104" rx="14.5" ry="17.5"/>
          <circle class="eye-pupil" cx="75" cy="106" r="9.5"/>
          <circle class="eye-shine" cx="79" cy="101" r="4"/>
          <circle class="eye-shine2" cx="70" cy="110" r="2.2"/>
          <rect class="eye-lid" x="58" y="86" width="30" height="38" rx="15"/>
        </g>
        <g class="char-eye eye-right">
          <ellipse class="eye-white" cx="126" cy="104" rx="14.5" ry="17.5"/>
          <circle class="eye-pupil" cx="125" cy="106" r="9.5"/>
          <circle class="eye-shine" cx="129" cy="101" r="4"/>
          <circle class="eye-shine2" cx="120" cy="110" r="2.2"/>
          <rect class="eye-lid" x="112" y="86" width="30" height="38" rx="15"/>
        </g>
        <path class="char-mouth" d="M83 130 Q100 151 117 130 Q100 140 83 130 Z"/>
      </g>
      <g class="char-spark"><path d="M162 48 l3.5 8 8 3.5 -8 3.5 -3.5 8 -3.5 -8 -8 -3.5 8 -3.5 z"/></g>
    </svg>`;
}

function tutorAvatarHtml() {
  // Возрастное разделение аватара репетитора:
  //  • 5-10 (CHARACTER_AGE_GROUPS) — милый 3D-мультяшный персонаж;
  //  • 11-18 и остальные — реалистичная молодая учительница.
  // Обе картинки: статичное фото + свечение по состоянию + мягкое «дыхание» (CSS).
  const ageGroup = state.me?.user?.age_group || "";
  const isKids = CHARACTER_AGE_GROUPS.includes(ageGroup);
  const v = window.APP_VERSION || "";
  const src = isKids
    ? `/static/assets/tutor-kids-5_10.jpg?v=${v}`
    : `/static/assets/tutor-teen-11_18.jpg?v=${v}`;
  return `
    <div class="tutor-face idle is-photo" id="tutorFace" data-state="idle" aria-hidden="true">
      <img class="tutor-avatar-img" src="${src}" alt="">
      <span class="avatar-glow"></span>
    </div>`;
}

async function renderChat() {
  loading();
  ensureBottomNav("tutor");
  try {
    const data = await api("/api/chat/history", "GET");
    app.innerHTML = `
      <div class="screen chat-wrap">
        <div class="chat-topbar">
          <h2 style="margin:0">Репетитор</h2>
          <button class="chat-reset" id="reset">Очистить</button>
        </div>
        <div class="chat-meta">${(() => {
          const u = data.usage || {};
          if (u.unlimited || u.daily_limit == null) return `Сообщений сегодня: ${u.used_today ?? 0}`;
          if (u.limit_reached) return `Бесплатные занятия на сегодня закончились (${u.daily_limit}/день)`;
          return `Осталось бесплатных сегодня: ${u.remaining_today} из ${u.daily_limit}`;
        })()}</div>
        <div class="tutor-stage">
          ${tutorAvatarHtml()}
          <div class="voice-status-card" id="voiceStatusCard" data-state="idle">
            <span id="voiceStatusLabel">Готова слушать</span>
            <b id="voiceStatusTitle">Нажми «Начать», и я помогу говорить по-английски.</b>
            <small id="voiceStatusHint">Можно начать по-русски или по-английски.</small>
          </div>
          <div class="voice-mode-panel">
            <button class="voice-mode-toggle" id="voiceMode" type="button">
              <span class="voice-mode-dot"></span>
              <span id="voiceModeText">Начать</span>
            </button>
            <div class="voice-mode-status" id="voiceStatus">Готова слушать</div>
          </div>
          <div class="voice-lesson-strip" id="voiceLessonStrip">
            <div class="voice-lesson-copy">
              <span id="voiceLessonPhase">Начало урока</span>
              <b id="voiceLessonTopic">Выбираем тему</b>
            </div>
            <div class="voice-lesson-progress" aria-hidden="true"><span id="voiceLessonProgress"></span></div>
          </div>
        </div>
        <div class="chat-messages" id="messages"></div>
        <div class="chat-input-row">
          <button class="chat-mic" id="mic" type="button" aria-label="Голосовое сообщение" title="Голосовое сообщение"><span class="mic-icon"></span></button>
          <input id="msg" type="text" placeholder="Напиши или скажи..." autocomplete="off">
          <button class="chat-send" id="send" type="button">➤</button>
        </div>
      </div>`;
    const box = document.getElementById("messages");
    const input = document.getElementById("msg");
    const tutorStage = document.querySelector(".tutor-stage");
    const face = document.getElementById("tutorFace");
    const mic = document.getElementById("mic");
    const sendButton = document.getElementById("send");
    const voiceModeButton = document.getElementById("voiceMode");
    const voiceModeText = document.getElementById("voiceModeText");
    const voiceStatus = document.getElementById("voiceStatus");
    const voiceStatusCard = document.getElementById("voiceStatusCard");
    const voiceStatusLabel = document.getElementById("voiceStatusLabel");
    const voiceStatusTitle = document.getElementById("voiceStatusTitle");
    const voiceStatusHint = document.getElementById("voiceStatusHint");
    const voiceLessonPhase = document.getElementById("voiceLessonPhase");
    const voiceLessonTopic = document.getElementById("voiceLessonTopic");
    const voiceLessonProgress = document.getElementById("voiceLessonProgress");
    let lessonState = data.lesson_state || {};
    let recorder = null;
    let audioChunks = [];
    let recordingStream = null;
    let sending = false;
    let discardRecording = false;
    let tutorAudio = null;
    let tutorAudioUrl = "";
    let tutorSpeechBusy = false;
    let tutorSpeechPlaying = false;
    let tutorSpeechId = 0;
    let voiceModeActive = false;
    let autoRecording = false;
    let skipUploadOnStop = false;
    let voiceModeTimer = null;
    let silenceFrame = 0;
    let silenceTimeout = null;
    let audioContext = null;
    let analyser = null;
    let heardVoice = false;
    let recordingStartedAt = 0;
    let lastVoiceAt = 0;
    let missedAutoRecordings = 0;
    let voiceIntroPlayed = false;
    let realtimeActive = false;
    let realtimePc = null;
    let realtimeDataChannel = null;
    let realtimeStream = null;
    let realtimeAudio = null;
    let realtimeAssistantSpeaking = false;
    let realtimeMicResumeTimer = null;
    let realtimeMicResumeAt = 0;
    let realtimeResponseTimer = null;
    let realtimeResponseNudgeTimer = null;
    let realtimeAwaitingResponse = false;
    let realtimeLastUserText = "";
    let realtimeAudioStarted = false;
    let realtimeFallbackShown = false;
    let shortVoiceHintShown = false;
    let voiceUiState = "idle";
    let lastTutorReply = "";
    let lastVoiceUserText = "";
    let voicePlaybackSpeed = 0.94;
    const realtimeLogged = new Set();
    const realtimeResponseText = new Map();

    const VOICE_VOLUME_THRESHOLD = 0.005;
    const VOICE_SILENCE_MS = 1200;
    const VOICE_MIN_RECORDING_MS = 650;
    const VOICE_NO_SPEECH_MS = 6000;
    const VOICE_MAX_RECORDING_MS = 18000;
    const VOICE_RESTART_DELAY_MS = 450;
    const VOICE_TTS_TIMEOUT_MS = 25000;
    const CHAT_TTS_TIMEOUT_MS = 7000;
    const REALTIME_FIRST_AUDIO_TIMEOUT_MS = 7000;
    const STABLE_VOICE_COOLDOWN_MS = 10 * 60 * 1000;
    const VOICE_STATE_LABELS = {
      idle: "Готова слушать",
      requesting_microphone: "Запрашиваю микрофон...",
      microphone_denied: "Микрофон отключён",
      ready: "Твой ход",
      listening: "Слушаю...",
      processing: "Распознаю...",
      thinking: "Думаю...",
      speaking: "Отвечаю...",
      reconnecting: "Переподключаюсь...",
      error: "Не удалось подключиться",
      repeat: "Повтори, пожалуйста",
      ended: "Урок завершён",
    };
    const VOICE_STATUS_UI = {
      idle: {
        label: "Готова слушать",
        title: "Нажми «Начать», и я помогу говорить по-английски.",
        hint: "Можно начать по-русски или по-английски.",
        action: "Начать",
      },
      ready: {
        label: "Твой ход",
        title: "Скажи короткую фразу.",
        hint: "Одного предложения достаточно. Например: I like pizza.",
        action: "Говорить",
      },
      waiting: {
        label: "Твой ход",
        title: "Я жду твой ответ.",
        hint: "Можно сказать одно слово, а я помогу сделать фразу.",
        action: "Говорить",
      },
      listening: {
        label: "Слушаю...",
        title: "Говори сейчас.",
        hint: "Скажи коротко. Я сама подстроюсь под язык.",
        action: "Слушаю",
      },
      processing: {
        label: "Думаю...",
        title: "Понимаю, что ты сказал.",
        hint: "Сейчас отвечу коротко и по делу.",
        action: "Думаю",
      },
      thinking: {
        label: "Думаю...",
        title: "Подбираю полезную подсказку.",
        hint: "Будет одна короткая реакция и одно задание.",
        action: "Думаю",
      },
      speaking: {
        label: "Отвечаю...",
        title: "Слушай и повторяй за мной.",
        hint: "Когда я закончу, снова будет твой ход.",
        action: "Остановить",
      },
      praising: {
        label: "Отлично!",
        title: "Хорошая попытка.",
        hint: "Повтори лучшую фразу ещё раз.",
        action: "Говорить",
      },
      correcting: {
        label: "Мягкая подсказка",
        title: "Почти правильно. Улучшим одну деталь.",
        hint: "Ошибки здесь нужны, чтобы учиться.",
        action: "Говорить",
      },
      repeat: {
        label: "Повтори, пожалуйста",
        title: "Я не очень хорошо услышала.",
        hint: "Скажи ещё раз чуть длиннее и громче.",
        action: "Ещё раз",
      },
      requesting_microphone: {
        label: "Проверяю микрофон",
        title: "Запрашиваю доступ к голосу.",
        hint: "Если появится окно Telegram, разреши микрофон.",
        action: "Ждём",
      },
      microphone_denied: {
        label: "Микрофон отключён",
        title: "Разреши доступ к микрофону, чтобы начать разговор.",
        hint: "Открой настройки Telegram или браузера и попробуй снова.",
        action: "Повторить",
      },
      reconnecting: {
        label: "Соединение потеряно",
        title: "Восстанавливаю голосовой режим.",
        hint: "Если не получится, включу запасной режим.",
        action: "Ждём",
      },
      error: {
        label: "Не удалось подключиться",
        title: "Спокойно, попробуем ещё раз.",
        hint: "Проверь интернет или нажми «Повторить».",
        action: "Повторить",
      },
      ended: {
        label: "Урок завершён",
        title: "Хорошая работа. Можно продолжить позже.",
        hint: "Нажми «Начать», когда будешь готов.",
        action: "Начать",
      },
    };
    const VOICE_STARTERS = [
      "Привет! Расскажи одним словом, что тебе сегодня интересно, а я превращу это в английскую фразу.",
      "Я слушаю. Можно говорить по-русски или по-английски. Начнем с маленькой сценки?",
      "Давай легко: скажи любое слово, например школа, игра или еда, и я начну практику.",
      "Привет! Я буду отвечать коротко и помогать. Что сегодня было интересного?",
      "Начнем с твоего слова. Скажи то, о чем хочется поговорить, и я подстроюсь.",
      "Я рядом. Если не знаешь, что сказать, просто скажи: помоги мне начать.",
    ];
    const VOICE_STARTERS_BY_AGE = {
      "5_7": [
        "Привет! Давай очень легко: cat — кошка или dog — собака?",
        "Я слушаю. Скажи одно слово: еда, игра или школа.",
        "Начнем с игры. Выбери: red — красный или blue — синий?",
      ],
      "8_10": [
        "Привет! Скажи одно слово, и я сделаю из него маленькую английскую фразу.",
        "Давай легко: game, food или school? Выбери одно.",
        "Я слушаю. Можно по-русски. Начнем с короткой игры?",
      ],
      "11_13": [
        "Привет! Можем сделать мини-диалог, сцену в кафе или тему про твой день.",
        "Скажи тему одним словом, а я начну живой английский диалог.",
        "Можно по-русски или по-английски. Что потренируем: school, hobbies или games?",
      ],
      "14_18": [
        "Привет! Можем потренировать speaking, экзаменационный ответ или обычную практику.",
        "Скажи тему, а я помогу сделать английский ответ естественнее.",
        "Можно начать по-русски. Что нужно: grammar, speaking или exam answer?",
      ],
    };
    const VOICE_HELP_HINTS = [
      "Я рядом. Скажи одно слово по-русски, и я помогу сделать английскую фразу.",
      "Можно совсем просто: помоги мне начать.",
      "Давай с одного слова: school, game или food.",
      "Если устал, скажи: проще. Я дам очень легкий вопрос.",
    ];
    const VOICE_HELP_HINTS_BY_AGE = {
      "5_7": [
        "Скажи одно слово: кот, собака или еда.",
        "Можно просто сказать: помоги.",
        "Если устал, скажи: проще.",
      ],
      "8_10": [
        "Скажи одно слово по-русски, и я помогу.",
        "Можно выбрать: game, food или school.",
        "Если сложно, скажи: проще.",
      ],
      "11_13": [
        "Скажи тему одним словом: school, hobby или movie.",
        "Можно попросить: объясни по-русски.",
        "Если хочешь легче, скажи: проще.",
      ],
      "14_18": [
        "Скажи, что нужно: speaking, grammar или exam.",
        "Можно попросить готовую фразу для ответа.",
        "Если темп быстрый, скажи: проще и медленнее.",
      ],
    };

    function bubble(role, text) {
      const div = document.createElement("div");
      div.className = `bubble ${role === "user" ? "user" : "bot"}`;
      div.textContent = text;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
      if (role !== "user" && !isAssistantError(text)) {
        lastTutorReply = String(text || "").trim();
        updateVoiceActionButtons();
      }
    }

    function hasLessonHistory() {
      return Boolean(box.querySelector(".bubble"));
    }

    function firstEnglishPhrase(text) {
      const clean = String(text || "").replace(/[“”]/g, "\"").replace(/[‘’]/g, "'");
      const quoted = clean.match(/"([^"]{2,80})"/);
      if (quoted?.[1] && /[a-z]/i.test(quoted[1])) return quoted[1].trim();
      const englishSentence = clean.match(/\b[A-Z]?[a-z][a-z' ]{1,80}[.!?]/);
      return englishSentence ? englishSentence[0].trim() : "";
    }

    function compactFeedbackText(text, fallback) {
      const clean = String(text || "").replace(/\s+/g, " ").trim();
      if (!clean) return fallback;
      return clean.length > 86 ? `${clean.slice(0, 83).trim()}...` : clean;
    }

    function showVoiceFeedback(userText, reply) {
      // Карточка-подсказка убрана как лишняя; оставляем только живую реакцию
      // аватара: похвала, мягкое исправление или поддержка по тону ответа.
      const isPraise = /great|excellent|well done|perfect|отлично|молодец|здорово|хорош/i.test(reply);
      const isCorrection = /say:|better|correct|исправ|лучше|правильно|ошиб/i.test(reply);
      setFace(isPraise ? "praising" : isCorrection ? "correcting" : "encouraging");
    }

    function faceModeForVoiceState(mode) {
      if (["listening", "speaking", "thinking", "praising", "correcting", "encouraging", "waiting", "error"].includes(mode)) return mode;
      if (["ready"].includes(mode)) return "waiting";
      if (["processing", "requesting_microphone", "reconnecting"].includes(mode)) return "thinking";
      if (["microphone_denied"].includes(mode)) return "error";
      if (["repeat"].includes(mode)) return "correcting";
      return "idle";
    }

    function setFace(mode) {
      const faceMode = faceModeForVoiceState(mode);
      // Сохраняем вариант аватара (is-photo / is-character), иначе теряется
      // баннер-раскладка и «дыхание» после первой же смены состояния.
      const variant = (face.className.match(/\bis-photo\b|\bis-character\b/) || [""])[0];
      face.className = ["tutor-face", faceMode, variant].filter(Boolean).join(" ");
      face.dataset.state = faceMode;
    }

    function typingBubble() {
      const div = document.createElement("div");
      div.className = "typing";
      div.textContent = "...";
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
      return div;
    }

    function inferVoiceState(status = "") {
      const text = String(status || "").toLowerCase();
      if (!voiceModeActive) return "idle";
      if (text.includes("микрофон") && (text.includes("отключ") || text.includes("запрещ"))) return "microphone_denied";
      if (text.includes("микрофон")) return "requesting_microphone";
      if (text.includes("распозна")) return "processing";
      if (text.includes("дума") || text.includes("готовлю")) return "thinking";
      if (text.includes("говор") || text.includes("отвеч") || text.includes("озвуч")) return "speaking";
      if (text.includes("ошиб") || text.includes("не удалось")) return "error";
      if (text.includes("перепод") || text.includes("запас")) return "reconnecting";
      if (text.includes("повтори")) return "repeat";
      if (text.includes("слуш") || text.includes("твой ход")) return "listening";
      return voiceModeActive ? "ready" : "idle";
    }

    function voiceButtonLabel(nextState) {
      const stateKey = nextState === "waiting" ? "ready" : nextState;
      return VOICE_STATUS_UI[stateKey]?.action || (voiceModeActive ? "Остановить" : "Начать");
    }

    function updateVoiceStatusCard(nextState, status = "") {
      const stateKey = nextState === "waiting" ? "ready" : nextState;
      const config = VOICE_STATUS_UI[stateKey] || VOICE_STATUS_UI.idle;
      voiceStatusCard.dataset.state = stateKey;
      voiceStatusLabel.textContent = status || config.label;
      voiceStatusTitle.textContent = config.title;
      voiceStatusHint.textContent = config.hint;
    }

    function updateVoiceActionButtons() {
      // Кнопки быстрых действий убраны из UI — заглушка, чтобы не трогать места вызова.
    }

    function updateVoiceModeUi(status = "", nextState = "") {
      voiceUiState = nextState || inferVoiceState(status);
      if (
        realtimeActive &&
        (voiceUiState === "listening" || voiceUiState === "ready") &&
        typeof realtimeMicIsLive === "function" &&
        !realtimeMicIsLive()
      ) {
        voiceUiState = "thinking";
        status = VOICE_STATE_LABELS.thinking;
      }
      voiceModeButton.classList.toggle("active", voiceModeActive);
      voiceModeButton.dataset.state = voiceUiState;
      voiceModeButton.disabled = ["listening", "processing", "thinking", "requesting_microphone", "reconnecting"].includes(voiceUiState);
      tutorStage.dataset.state = voiceUiState;
      voiceStatus.dataset.state = voiceUiState;
      voiceModeText.textContent = voiceButtonLabel(voiceUiState);
      voiceStatus.textContent = status || VOICE_STATE_LABELS[voiceUiState] || (voiceModeActive ? "Слушаю..." : "Готова слушать");
      updateVoiceStatusCard(voiceUiState, voiceStatus.textContent);
      if (!sending) mic.disabled = voiceModeActive;
      setFace(faceModeForVoiceState(voiceUiState));
      updateVoiceActionButtons();
    }

    function isMicrophonePermissionError(error) {
      return ["NotAllowedError", "PermissionDeniedError", "SecurityError"].includes(error?.name);
    }

    function friendlyVoiceError(error, fallback = "Голос сейчас не сработал. Попробуй ещё раз.") {
      const message = String(error?.message || error || "");
      if (isMicrophonePermissionError(error)) {
        return "Микрофон отключён. Разреши доступ к микрофону в Telegram или браузере и попробуй снова.";
      }
      if (/network|fetch|connect|timeout|timed out|failed/i.test(message)) {
        return "Связь с голосом прервалась. Проверь интернет и попробуй снова.";
      }
      if (/empty|пуст|не расслыш|short|корот/i.test(message)) {
        return "Я не очень хорошо услышал. Повтори, пожалуйста.";
      }
      if (/quota|limit|429/i.test(message)) {
        return "Голосовой репетитор временно перегружен. Попробуй чуть позже.";
      }
      return fallback;
    }

    function renderLessonState(nextState) {
      if (nextState && Object.keys(nextState).length) lessonState = nextState;
      const progress = Math.max(5, Math.min(100, Number(lessonState?.progress_percent) || 5));
      voiceLessonPhase.textContent = lessonState?.phase_label || "Начало урока";
      voiceLessonTopic.textContent = lessonState?.topic_label || "Выбираем тему";
      voiceLessonProgress.style.width = `${progress}%`;
      if (!voiceModeActive && lessonState?.avatar_state && lessonState.avatar_state !== "idle") {
        setFace(lessonState.avatar_state);
      }
    }

    function nextRotatingItem(storageKey, items) {
      if (!items.length) return "";
      try {
        const current = Number(localStorage.getItem(storageKey) || "0");
        localStorage.setItem(storageKey, String(current + 1));
        return items[current % items.length];
      } catch (_) {
        return items[Math.floor(Math.random() * items.length)];
      }
    }

    function voiceAgeGroup() {
      return state.me?.user?.age_group || "default";
    }

    function ageItems(map, fallback) {
      const ageGroup = voiceAgeGroup();
      return map[ageGroup] || fallback;
    }

    function clearVoiceModeTimer() {
      if (voiceModeTimer) {
        clearTimeout(voiceModeTimer);
        voiceModeTimer = null;
      }
    }

    function realtimeSupported() {
      return Boolean(window.RTCPeerConnection && navigator.mediaDevices?.getUserMedia);
    }

    function stableVoiceUntil() {
      try {
        return Number(localStorage.getItem("stableVoiceUntil") || "0");
      } catch (_) {
        return 0;
      }
    }

    function preferStableVoice(reason = "") {
      try {
        localStorage.setItem("stableVoiceUntil", String(Date.now() + STABLE_VOICE_COOLDOWN_MS));
        if (reason) localStorage.setItem("stableVoiceReason", reason);
      } catch (_) {}
    }

    function shouldUseStableVoice() {
      return Date.now() < stableVoiceUntil();
    }

    function clearRealtimeResponseTimer() {
      if (realtimeResponseTimer) {
        clearTimeout(realtimeResponseTimer);
        realtimeResponseTimer = null;
      }
    }

    function clearRealtimeResponseNudgeTimer() {
      if (realtimeResponseNudgeTimer) {
        clearTimeout(realtimeResponseNudgeTimer);
        realtimeResponseNudgeTimer = null;
      }
    }

    function armRealtimeResponseTimer() {
      clearRealtimeResponseTimer();
      realtimeAudioStarted = false;
      realtimeResponseTimer = setTimeout(() => {
        realtimeResponseTimer = null;
        if (!voiceModeActive || !realtimeActive || realtimeAudioStarted) return;
        switchToStableVoice("realtime_first_audio_timeout", realtimeLastUserText).catch(console.error);
      }, REALTIME_FIRST_AUDIO_TIMEOUT_MS);
    }

    function armRealtimeResponseNudge(delayMs = 1200) {
      clearRealtimeResponseNudgeTimer();
      realtimeResponseNudgeTimer = setTimeout(() => {
        realtimeResponseNudgeTimer = null;
        if (!voiceModeActive || !realtimeActive || !realtimeAwaitingResponse || realtimeAssistantSpeaking) return;
        setRealtimeMicEnabled(false);
        updateVoiceModeUi(VOICE_STATE_LABELS.thinking, "thinking");
        setFace("thinking");
        sendRealtimeEvent({
          type: "response.create",
          response: {
            instructions: "Ответь на последнюю реплику ребенка сразу. Сначала по смыслу, затем маленький учебный шаг: одно английское слово, короткая фраза или мягкое исправление. Один вопрос максимум.",
          },
        });
      }, delayMs);
    }

    function waitForIceGatheringComplete(pc, timeoutMs = 1500) {
      if (pc.iceGatheringState === "complete") return Promise.resolve();
      return new Promise(resolve => {
        const timeoutId = setTimeout(done, timeoutMs);
        function done() {
          clearTimeout(timeoutId);
          pc.removeEventListener("icegatheringstatechange", onChange);
          resolve();
        }
        function onChange() {
          if (pc.iceGatheringState === "complete") done();
        }
        pc.addEventListener("icegatheringstatechange", onChange);
      });
    }

    function sendRealtimeEvent(event) {
      if (realtimeDataChannel?.readyState === "open") {
        realtimeDataChannel.send(JSON.stringify(event));
      }
    }

    function setRealtimeMicEnabled(enabled) {
      const shouldEnable = Boolean(enabled && voiceModeActive && realtimeActive && !realtimeAssistantSpeaking && !realtimeAwaitingResponse);
      let micLive = false;
      realtimeStream?.getAudioTracks().forEach(track => {
        if (track.readyState === "live") {
          track.enabled = shouldEnable;
          if (track.enabled) micLive = true;
        }
      });
      return micLive;
    }

    function realtimeMicIsLive() {
      return Boolean(
        realtimeStream?.getAudioTracks().some(track => track.readyState === "live" && track.enabled)
      );
    }

    function setRealtimeAssistantSpeaking(active) {
      if (!voiceModeActive || !realtimeActive) return;
      if (active && realtimeMicResumeTimer) {
        clearTimeout(realtimeMicResumeTimer);
        realtimeMicResumeTimer = null;
        realtimeMicResumeAt = 0;
      }
      if (active) {
        realtimeAudioStarted = true;
        clearRealtimeResponseTimer();
      }
      realtimeAssistantSpeaking = active;
      const micLive = setRealtimeMicEnabled(!active);
      if (active) {
        updateVoiceModeUi(VOICE_STATE_LABELS.speaking, "speaking");
        setFace("speaking");
      } else if (micLive) {
        updateVoiceModeUi(VOICE_STATE_LABELS.ready, "ready");
        setFace("listening");
      } else {
        updateVoiceModeUi(VOICE_STATE_LABELS.thinking, "thinking");
        setFace("thinking");
      }
    }

    function setRealtimeAssistantSpeakingSafe(active) {
      setRealtimeAssistantSpeaking(active);
    }

    function scheduleRealtimeMicResume(delayMs = 800, forceEarlier = false) {
      const resumeAt = Date.now() + delayMs;
      if (!forceEarlier && realtimeMicResumeTimer && realtimeMicResumeAt >= resumeAt) return;
      realtimeMicResumeAt = resumeAt;
      if (realtimeMicResumeTimer) clearTimeout(realtimeMicResumeTimer);
      realtimeMicResumeTimer = setTimeout(() => {
        realtimeMicResumeTimer = null;
        realtimeMicResumeAt = 0;
        setRealtimeAssistantSpeakingSafe(false);
      }, delayMs);
    }

    async function getRealtimeEphemeralKey() {
      const data = await api("/api/realtime/token", "POST", {});
      const key = data?.value || data?.client_secret?.value || "";
      if (!key) throw new Error("Realtime token is empty");
      return key;
    }

    async function logRealtimeMessage(role, text, key) {
      const clean = String(text || "").trim();
      const textKey = `${role}:text:${clean}`;
      if (!clean || realtimeLogged.has(key) || realtimeLogged.has(textKey)) return;
      realtimeLogged.add(key);
      realtimeLogged.add(textKey);
      try {
        const result = await api("/api/realtime/log", "POST", { role, content: clean });
        renderLessonState(result.lesson_state);
      } catch (_) {}
    }

    function extractRealtimeTextFromResponse(response) {
      const parts = [];
      for (const item of response?.output || []) {
        for (const content of item.content || []) {
          if (content.transcript) parts.push(content.transcript);
          else if (content.text) parts.push(content.text);
        }
      }
      return parts.join(" ").trim();
    }

    function handleRealtimeEvent(rawEvent) {
      let event = null;
      try {
        event = JSON.parse(rawEvent.data);
      } catch (_) {
        return;
      }
      const type = event.type || "";
      if (type === "session.created") {
        setRealtimeMicEnabled(false);
        updateVoiceModeUi(VOICE_STATE_LABELS.thinking, "thinking");
        setFace("thinking");
        return;
      }
      if (type === "input_audio_buffer.speech_started") {
        if (realtimeAssistantSpeaking) return;
        if (!realtimeMicIsLive()) return;
        updateVoiceModeUi("Слушаю...", "listening");
        setFace("listening");
        return;
      }
      if (type === "input_audio_buffer.speech_stopped") {
        realtimeAwaitingResponse = true;
        setRealtimeMicEnabled(false);
        updateVoiceModeUi("Думаю...", "thinking");
        setFace("thinking");
        armRealtimeResponseTimer();
        armRealtimeResponseNudge(1400);
        return;
      }
      if (type === "conversation.item.input_audio_transcription.completed") {
        const text = String(event.transcript || event.text || "").trim();
        realtimeLastUserText = text;
        if (text) lastVoiceUserText = text;
        const key = `user:${event.item_id || event.event_id || text}`;
        if (text && !realtimeLogged.has(key) && !realtimeLogged.has(`user:text:${text}`)) {
          bubble("user", text);
          logRealtimeMessage("user", text, key);
        }
        if (realtimeAwaitingResponse) armRealtimeResponseNudge(350);
        return;
      }
      if (type === "response.output_audio_transcript.delta" || type === "response.audio_transcript.delta") {
        const id = event.response_id || event.item_id || "latest";
        realtimeResponseText.set(id, (realtimeResponseText.get(id) || "") + (event.delta || ""));
        return;
      }
      if (type === "response.output_audio_transcript.done" || type === "response.audio_transcript.done") {
        const id = event.response_id || event.item_id || "latest";
        const text = String(event.transcript || realtimeResponseText.get(id) || "").trim();
        realtimeResponseText.delete(id);
        const key = `assistant:${id}:${text}`;
        if (text && !realtimeLogged.has(key) && !realtimeLogged.has(`assistant:text:${text}`)) {
          bubble("assistant", text);
          showVoiceFeedback(lastVoiceUserText || realtimeLastUserText, text);
          logRealtimeMessage("assistant", text, key);
        }
        // Микрофон возвращаем по реальному окончанию аудио (audio.done), а не по
        // завершению транскрипта — иначе оценка длины речи (до 26с) надолго глушила ребёнка.
        return;
      }
      if (type === "response.created") {
        realtimeAwaitingResponse = false;
        setRealtimeMicEnabled(false);
        clearRealtimeResponseNudgeTimer();
        updateVoiceModeUi("Думаю...", "thinking");
        setFace("thinking");
        return;
      }
      if (
        type === "response.output_audio.delta" ||
        type === "response.audio.delta" ||
        type === "response.content_part.added"
      ) {
        setRealtimeAssistantSpeakingSafe(true);
        return;
      }
      if (type === "response.output_audio.done" || type === "response.audio.done") {
        scheduleRealtimeMicResume(400, true);
        return;
      }
      if (type === "response.done") {
        realtimeAwaitingResponse = false;
        clearRealtimeResponseNudgeTimer();
        clearRealtimeResponseTimer();
        const text = extractRealtimeTextFromResponse(event.response);
        const id = event.response?.id || event.event_id || "done";
        const key = `assistant:${id}:${text}`;
        if (text && !realtimeLogged.has(key) && !realtimeLogged.has(`assistant:text:${text}`)) {
          bubble("assistant", text);
          showVoiceFeedback(lastVoiceUserText || realtimeLastUserText, text);
          logRealtimeMessage("assistant", text, key);
        }
        // Страховка: если audio.done не пришёл — вернуть микрофон быстро и предсказуемо
        // (а не через оценку длины речи до 26с).
        scheduleRealtimeMicResume(500, true);
        return;
      }
      if (type === "error") {
        const message = event.error?.message || "Ошибка живого голоса";
        console.error("Realtime voice error:", message);
        updateVoiceModeUi("Переключаюсь на запасной голос...", "reconnecting");
        switchToStableVoice("realtime_error", realtimeLastUserText).catch(console.error);
      }
    }

    function stopRealtimeSession() {
      realtimeActive = false;
      realtimeAssistantSpeaking = false;
      clearRealtimeResponseTimer();
      clearRealtimeResponseNudgeTimer();
      realtimeLastUserText = "";
      realtimeAudioStarted = false;
      realtimeAwaitingResponse = false;
      if (realtimeMicResumeTimer) {
        clearTimeout(realtimeMicResumeTimer);
        realtimeMicResumeTimer = null;
      }
      realtimeMicResumeAt = 0;
      if (realtimeDataChannel) {
        try { realtimeDataChannel.close(); } catch (_) {}
        realtimeDataChannel = null;
      }
      if (realtimePc) {
        try {
          realtimePc.getSenders().forEach(sender => sender.track?.stop());
          realtimePc.close();
        } catch (_) {}
        realtimePc = null;
      }
      realtimeStream?.getTracks().forEach(track => track.stop());
      realtimeStream = null;
      if (realtimeAudio) {
        realtimeAudio.pause();
        realtimeAudio.srcObject = null;
        realtimeAudio = null;
      }
      realtimeResponseText.clear();
    }

    function releaseTutorAudio() {
      if (tutorAudio) {
        tutorAudio.onplaying = null;
        tutorAudio.onended = null;
        tutorAudio.onerror = null;
        tutorAudio.pause();
        tutorAudio.removeAttribute("src");
        tutorAudio.load();
        tutorAudio = null;
      }
      if (tutorAudioUrl) {
        URL.revokeObjectURL(tutorAudioUrl);
        tutorAudioUrl = "";
      }
    }

    function stopTutorSpeech() {
      tutorSpeechId += 1;
      tutorSpeechBusy = false;
      tutorSpeechPlaying = false;
      window.speechSynthesis?.cancel?.();
      releaseTutorAudio();
      updateVoiceActionButtons();
    }

    function finishTutorSpeech(onDone, speechId = tutorSpeechId) {
      if (speechId !== tutorSpeechId) return;
      tutorSpeechBusy = false;
      tutorSpeechPlaying = false;
      releaseTutorAudio();
      setFace("idle");
      updateVoiceActionButtons();
      if (typeof onDone === "function") onDone();
    }

    function isAssistantError(text) {
      return !text || text.startsWith("Ошибка:") || text.startsWith("⚠️");
    }

    function speechLang(char) {
      if (/[a-z]/i.test(char)) return "en-US";
      if (/[а-яё]/i.test(char)) return "ru-RU";
      return "";
    }

    function speechSegments(text) {
      const segments = [];
      let current = "";
      let currentLang = "";
      for (const char of text) {
        const lang = speechLang(char);
        if (!lang || !currentLang || lang === currentLang) {
          current += char;
          if (lang && !currentLang) currentLang = lang;
          continue;
        }
        if (current.trim()) segments.push({ text: current, lang: currentLang });
        current = char;
        currentLang = lang;
      }
      if (current.trim()) segments.push({ text: current, lang: currentLang || "ru-RU" });
      return segments.length ? segments : [{ text, lang: /[а-яё]/i.test(text) ? "ru-RU" : "en-US" }];
    }

    function speakTutorFallback(text, onDone = null) {
      if (isAssistantError(text)) {
        finishTutorSpeech(onDone);
        return;
      }
      stopTutorSpeech();
      const speechId = tutorSpeechId;
      tutorSpeechBusy = true;
      tutorSpeechPlaying = false;
      updateVoiceActionButtons();
      if (!("speechSynthesis" in window)) {
        tutorSpeechPlaying = true;
        setFace("speaking");
        if (voiceModeActive) updateVoiceModeUi(VOICE_STATE_LABELS.speaking, "speaking");
        setTimeout(() => finishTutorSpeech(onDone, speechId), 1400);
        return;
      }
      try {
        const segments = speechSegments(text);
        let index = 0;
        const speakNext = () => {
          if (speechId !== tutorSpeechId) return;
          const segment = segments[index];
          if (!segment) {
            finishTutorSpeech(onDone, speechId);
            return;
          }
          const utterance = new SpeechSynthesisUtterance(segment.text);
          utterance.lang = segment.lang;
          utterance.rate = segment.lang === "en-US" ? 0.88 : 0.95;
          utterance.pitch = 1.05;
          utterance.onstart = () => {
            if (speechId !== tutorSpeechId) return;
            tutorSpeechPlaying = true;
            setFace("speaking");
            if (voiceModeActive) updateVoiceModeUi(VOICE_STATE_LABELS.speaking, "speaking");
          };
          utterance.onend = () => {
            if (speechId !== tutorSpeechId) return;
            index += 1;
            speakNext();
          };
          utterance.onerror = () => finishTutorSpeech(onDone, speechId);
          window.speechSynthesis.speak(utterance);
        };
        speakNext();
      } catch (_) {
        finishTutorSpeech(onDone, speechId);
      }
    }

    async function speakTutor(text, onDone = null, voice = false, speed = null) {
      if (isAssistantError(text)) {
        finishTutorSpeech(onDone);
        return;
      }
      stopTutorSpeech();
      const speechId = tutorSpeechId;
      tutorSpeechBusy = true;
      tutorSpeechPlaying = false;
      updateVoiceActionButtons();
      setFace("thinking");
      if (voice) updateVoiceModeUi("Готовлю голос...", "thinking");
      const payload = { text, mode: voice ? "voice" : "chat" };
      if (voice && speed) payload.speed = speed;
      const timeoutMs = voice ? VOICE_TTS_TIMEOUT_MS : CHAT_TTS_TIMEOUT_MS;
      // Прогрессивное воспроизведение через MediaSource там, где поддерживается
      // (Chrome/Android Telegram). При неудаче/неподдержке — буферный путь ниже.
      if (canStreamSpeech()) {
        try {
          await streamTutorSpeech(payload, text, onDone, speechId, timeoutMs);
          return;
        } catch (_) {
          if (speechId !== tutorSpeechId) return;
          // тихо падаем на буферный путь
        }
      }
      try {
        const audioBlob = await apiBlob("/api/audio/speech", payload, timeoutMs);
        if (speechId !== tutorSpeechId) return;
        await playTutorAudioBlob(audioBlob, text, onDone, speechId);
      } catch (_) {
        if (speechId !== tutorSpeechId) return;
        speakTutorFallback(text, onDone);
      }
    }

    function canStreamSpeech() {
      try {
        return typeof window.MediaSource !== "undefined"
          && typeof window.MediaSource.isTypeSupported === "function"
          && window.MediaSource.isTypeSupported("audio/mpeg")
          && typeof ReadableStream !== "undefined";
      } catch (_) {
        return false;
      }
    }

    // Прогрессивная озвучка: тянем аудио из /api/audio/speech потоком и скармливаем
    // его в MediaSource, чтобы репетитор начинал говорить, не дожидаясь всего MP3.
    // Возвращается, как только воспроизведение СТАРТОВАЛО (как playTutorAudioBlob);
    // докачка идёт в фоне, onended -> finishTutorSpeech(onDone).
    async function streamTutorSpeech(payload, text, onDone, speechId, timeoutMs) {
      const controller = new AbortController();
      const timeoutId = timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null;
      const res = await fetch("/api/audio/speech", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        if (timeoutId) clearTimeout(timeoutId);
        throw new Error("speech stream http " + res.status);
      }
      if (speechId !== tutorSpeechId) {
        if (timeoutId) clearTimeout(timeoutId);
        try { controller.abort(); } catch (_) {}
        throw new Error("stale");
      }

      releaseTutorAudio();
      window.speechSynthesis?.cancel?.();
      tutorSpeechBusy = true;
      tutorSpeechPlaying = false;
      updateVoiceActionButtons();

      const mediaSource = new MediaSource();
      tutorAudioUrl = URL.createObjectURL(mediaSource);
      const audio = new Audio();
      tutorAudio = audio;
      audio.src = tutorAudioUrl;
      audio.preload = "auto";

      let started = false;
      const clearTimer = () => { if (timeoutId) clearTimeout(timeoutId); };

      return await new Promise((resolve, reject) => {
        let settled = false;
        let finished = false;
        const finishOnce = () => {
          if (finished) return;
          finished = true;
          finishTutorSpeech(onDone, speechId);
        };
        const fail = (err) => {
          if (settled) return;
          settled = true;
          clearTimer();
          try { controller.abort(); } catch (_) {}
          if (started) {
            // Звук уже шёл — не роняем диалог, просто завершаем ход.
            finishOnce();
            resolve();
          } else {
            reject(err || new Error("mse error"));
          }
        };
        const markStarted = () => {
          if (started || settled) return;
          started = true;
          clearTimer();
          if (speechId !== tutorSpeechId) return fail(new Error("stale"));
          tutorSpeechBusy = true;
          tutorSpeechPlaying = true;
          setFace("speaking");
          if (voiceModeActive) updateVoiceModeUi("Отвечаю...", "speaking");
          resolve();
        };

        audio.onplaying = markStarted;
        audio.onended = () => { settled = true; finishOnce(); };
        audio.onerror = () => fail(new Error("audio element error"));
        mediaSource.addEventListener("error", () => fail(new Error("mediasource error")), { once: true });

        mediaSource.addEventListener("sourceopen", () => {
          let sb;
          try {
            sb = mediaSource.addSourceBuffer("audio/mpeg");
          } catch (e) {
            return fail(e);
          }
          const reader = res.body.getReader();
          const queue = [];
          let reading = true;
          const pump = () => {
            if (settled && !started) return;
            if (sb.updating) return;
            if (queue.length) {
              try { sb.appendBuffer(queue.shift()); } catch (e) { return fail(e); }
              return;
            }
            if (!reading) {
              try { if (mediaSource.readyState === "open") mediaSource.endOfStream(); } catch (_) {}
            }
          };
          sb.addEventListener("updateend", pump);
          (async () => {
            try {
              while (true) {
                const { done, value } = await reader.read();
                if (speechId !== tutorSpeechId) { reading = false; return fail(new Error("stale")); }
                if (done) { reading = false; pump(); break; }
                if (value && value.length) { queue.push(value); pump(); }
              }
            } catch (e) {
              reading = false;
              fail(e);
            }
          })();
        }, { once: true });

        audio.play().catch((e) => fail(e));
      });
    }

    async function playTutorAudioBlob(audioBlob, text, onDone = null, speechId = null) {
      if (speechId === null) {
        stopTutorSpeech();
        speechId = tutorSpeechId;
      } else if (speechId !== tutorSpeechId) {
        return;
      } else {
        releaseTutorAudio();
        window.speechSynthesis?.cancel?.();
      }
      tutorSpeechBusy = true;
      tutorSpeechPlaying = false;
      updateVoiceActionButtons();
      tutorAudioUrl = URL.createObjectURL(audioBlob);
      tutorAudio = new Audio(tutorAudioUrl);
      tutorAudio.preload = "auto";
      tutorAudio.onplaying = () => {
        if (speechId !== tutorSpeechId) return;
        tutorSpeechBusy = true;
        tutorSpeechPlaying = true;
        setFace("speaking");
        if (voiceModeActive) updateVoiceModeUi("Отвечаю...", "speaking");
      };
      tutorAudio.onended = () => {
        finishTutorSpeech(onDone, speechId);
      };
      tutorAudio.onerror = () => {
        if (speechId !== tutorSpeechId) return;
        speakTutorFallback(text, onDone);
      };
      try {
        await tutorAudio.play();
      } catch (_) {
        if (speechId !== tutorSpeechId) return;
        speakTutorFallback(text, onDone);
      }
    }

    function base64ToBlob(base64, contentType = "audio/mpeg") {
      const binary = atob(base64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i += 1) {
        bytes[i] = binary.charCodeAt(i);
      }
      return new Blob([bytes], { type: contentType });
    }

    function preferredMimeType() {
      if (!window.MediaRecorder?.isTypeSupported) return "";
      return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type)) || "";
    }

    function stopSilenceMonitor() {
      if (silenceFrame) {
        cancelAnimationFrame(silenceFrame);
        silenceFrame = 0;
      }
      if (silenceTimeout) {
        clearTimeout(silenceTimeout);
        silenceTimeout = null;
      }
      if (audioContext) {
        audioContext.close().catch(() => {});
        audioContext = null;
      }
      analyser = null;
    }

    function startSilenceMonitor(stream) {
      stopSilenceMonitor();
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) {
        recordingStartedAt = Date.now();
        silenceTimeout = setTimeout(() => stopRecording(), 7000);
        return;
      }
      audioContext = new AudioContextClass();
      if (audioContext.state === "suspended") {
        audioContext.resume().catch(() => {});
      }
      const source = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 1024;
      source.connect(analyser);
      const samples = new Uint8Array(analyser.fftSize);
      heardVoice = false;
      recordingStartedAt = Date.now();
      lastVoiceAt = 0;

      function tick() {
        if (!autoRecording || !recorder || recorder.state !== "recording" || !analyser) return;
        analyser.getByteTimeDomainData(samples);
        let sum = 0;
        for (const sample of samples) {
          const value = (sample - 128) / 128;
          sum += value * value;
        }
        const volume = Math.sqrt(sum / samples.length);
        const now = Date.now();
        if (volume > VOICE_VOLUME_THRESHOLD) {
          heardVoice = true;
          lastVoiceAt = now;
          missedAutoRecordings = 0;
          updateVoiceModeUi("Слушаю...", "listening");
        }
        if (heardVoice && now - lastVoiceAt > VOICE_SILENCE_MS && now - recordingStartedAt > VOICE_MIN_RECORDING_MS) {
          stopRecording();
          return;
        }
        if (!heardVoice && now - recordingStartedAt > 2800) {
          updateVoiceModeUi("Я слушаю. Можно по-русски...", "listening");
        }
        if (!heardVoice && now - recordingStartedAt > VOICE_NO_SPEECH_MS) {
          missedAutoRecordings += 1;
          skipUploadOnStop = true;
          stopRecording();
          if (missedAutoRecordings <= 2) {
            const ageGroup = voiceAgeGroup();
            const hint = hasLessonHistory()
              ? "Продолжаем эту же тему. Скажи: дальше, проще или повтори."
              : nextRotatingItem(`voiceHelpHintIndex:${ageGroup}`, ageItems(VOICE_HELP_HINTS_BY_AGE, VOICE_HELP_HINTS));
            bubble("assistant", hint);
            speakTutor(hint, () => scheduleVoiceListen(VOICE_RESTART_DELAY_MS), true);
            return;
          }
          scheduleVoiceListen(VOICE_RESTART_DELAY_MS);
          return;
        }
        if (now - recordingStartedAt > VOICE_MAX_RECORDING_MS) {
          stopRecording();
          return;
        }
        silenceFrame = requestAnimationFrame(tick);
      }

      silenceFrame = requestAnimationFrame(tick);
    }

    function stopTracks() {
      recordingStream?.getTracks().forEach(track => track.stop());
      recordingStream = null;
    }

    function cleanupChat() {
      clearVoiceModeTimer();
      voiceModeActive = false;
      autoRecording = false;
      stopRealtimeSession();
      stopTutorSpeech();
      stopSilenceMonitor();
      discardRecording = true;
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = null;
        recorder.stop();
      }
      audioChunks = [];
      stopTracks();
      mic.classList.remove("recording");
      voiceModeButton.classList.remove("active");
      setFace("idle");
    }

    if (!data.messages?.length) {
      box.innerHTML = `<div class="chat-empty">Репетитор начнет практику и предложит тему.</div>`;
    } else {
      data.messages.forEach(m => bubble(m.role, m.content));
    }
    renderLessonState(data.lesson_state);

    async function send(textOverride, options = {}) {
      const text = typeof textOverride === "string" ? textOverride.trim() : input.value.trim();
      if (!text) return;
      if (sending) return;
      sending = true;
      sendButton.disabled = true;
      mic.disabled = true;
      if (box.querySelector(".chat-empty")) box.innerHTML = "";
      input.value = "";
      if (options.showUser !== false) bubble("user", text);
      const typing = typingBubble();
      setFace("thinking");
      try {
        const reply = await api("/api/chat/send", "POST", {
          message: text,
          mode: options.voice ? "voice" : "chat",
        });
        typing.remove();
        bubble("assistant", reply.reply);
        renderLessonState(reply.lesson_state);
        if (options.voice) {
          lastVoiceUserText = text;
          showVoiceFeedback(text, reply.reply);
        }
        speakTutor(
          reply.reply,
          options.autoContinue ? () => scheduleVoiceListen(650) : null,
          Boolean(options.voice),
          options.voice ? voicePlaybackSpeed : null,
        );
      } catch (e) {
        typing.remove();
        bubble("assistant", `Ошибка: ${e.message}`);
        setFace("idle");
        if (options.autoContinue) scheduleVoiceListen(1500);
      } finally {
        sending = false;
        sendButton.disabled = false;
        mic.disabled = voiceModeActive;
        input.focus();
      }
    }

    async function voiceTurn(blob) {
      const form = new FormData();
      const extension = blob.type.includes("mp4") ? "mp4" : "webm";
      form.append("audio", blob, `voice.${extension}`);
      return apiForm("/api/voice/turn", form);
    }

    async function voiceTextTurn(text) {
      return api("/api/voice/text-turn", "POST", { message: text });
    }

    async function renderVoiceTurnResult(result, wasAuto = false, showUser = true) {
      const text = String(result.text || "").trim();
      const reply = String(result.reply || "").trim();
      if (box.querySelector(".chat-empty")) box.innerHTML = "";
      if (showUser && text) {
        lastVoiceUserText = text;
        bubble("user", text);
      } else if (text) {
        lastVoiceUserText = text;
      }
      if (reply) {
        bubble("assistant", reply);
        showVoiceFeedback(lastVoiceUserText || text, reply);
      }
      renderLessonState(result.lesson_state);
      const onDone = wasAuto ? () => scheduleVoiceListen(VOICE_RESTART_DELAY_MS) : null;
      if (result.audio_base64) {
        const audioBlob = base64ToBlob(result.audio_base64, result.audio_content_type || "audio/mpeg");
        updateVoiceModeUi("Отвечаю...", "speaking");
        await playTutorAudioBlob(audioBlob, reply, onDone);
      } else if (reply) {
        if (result.audio_error) {
          speakTutorFallback(reply, onDone);
        } else {
          await speakTutor(reply, onDone, true, voicePlaybackSpeed);
        }
      } else if (wasAuto) {
        scheduleVoiceListen(900);
      }
    }

    function scheduleVoiceListen(delay = 500) {
      clearVoiceModeTimer();
      if (!voiceModeActive) return;
      if (tutorSpeechBusy || realtimeAssistantSpeaking) {
        voiceModeTimer = setTimeout(() => scheduleVoiceListen(VOICE_RESTART_DELAY_MS), 250);
        return;
      }
      updateVoiceModeUi("Твой ход", "ready");
      voiceModeTimer = setTimeout(() => {
        if (!voiceModeActive || sending) return;
        if (tutorSpeechBusy || realtimeAssistantSpeaking) {
          scheduleVoiceListen(VOICE_RESTART_DELAY_MS);
          return;
        }
        if (recorder && recorder.state === "recording") return;
        startRecording(true).catch(error => {
          bubble("assistant", friendlyVoiceError(error, "Не удалось начать запись. Попробуй ещё раз."));
          voiceModeActive = false;
          updateVoiceModeUi("", isMicrophonePermissionError(error) ? "microphone_denied" : "error");
          setFace("error");
        });
      }, delay);
    }

    async function sendStableVoiceTurn(blob, wasAuto = false) {
      sending = true;
      updateVoiceModeUi("Думаю...");
      setFace("thinking");
      const result = await voiceTurn(blob);
      await renderVoiceTurnResult(result, wasAuto, true);
    }

    async function handleRecordingStop(mimeType, wasAuto = false) {
      stopSilenceMonitor();
      autoRecording = false;
      stopTracks();
      mic.classList.remove("recording");
      mic.disabled = true;
      sendButton.disabled = true;
      updateVoiceModeUi(wasAuto ? "Распознаю..." : "");
      setFace("thinking");
      try {
        const blob = new Blob(audioChunks, { type: mimeType || "audio/webm" });
        audioChunks = [];
        if (blob.size < 300) {
          updateVoiceModeUi("Повтори, пожалуйста", "repeat");
          if (!wasAuto && !shortVoiceHintShown) {
            shortVoiceHintShown = true;
            bubble("assistant", "Я не успел расслышать. Нажми микрофон и скажи фразу чуть дольше.");
          }
          setFace("correcting");
          if (wasAuto) scheduleVoiceListen(700);
          return;
        }
        missedAutoRecordings = 0;
        await sendStableVoiceTurn(blob, wasAuto);
      } catch (e) {
        const message = friendlyVoiceError(e);
        if (!wasAuto) tg.showAlert(message);
        else {
          updateVoiceModeUi("Повтори, пожалуйста", "error");
          bubble("assistant", message);
        }
        setFace("error");
        if (wasAuto) scheduleVoiceListen(1500);
      } finally {
        sending = false;
        mic.disabled = voiceModeActive;
        if (!sending) sendButton.disabled = false;
      }
    }

    async function startRecording(auto = false) {
      if (sending || tutorSpeechBusy || realtimeAssistantSpeaking) return;
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        const message = "Голосовой ввод не поддерживается на этом устройстве";
        if (auto) bubble("assistant", message);
        else tg.showAlert(message);
        if (auto) {
          voiceModeActive = false;
          updateVoiceModeUi(message, "error");
        }
        return;
      }
      if (recorder && recorder.state === "recording") return;
      try {
        audioChunks = [];
        skipUploadOnStop = false;
        autoRecording = auto;
        updateVoiceModeUi("Запрашиваю микрофон...", "requesting_microphone");
        recordingStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
          },
        });
        const mimeType = preferredMimeType();
        recorder = mimeType
          ? new MediaRecorder(recordingStream, { mimeType })
          : new MediaRecorder(recordingStream);
        recorder.ondataavailable = event => {
          if (event.data?.size) audioChunks.push(event.data);
        };
        recorder.onstop = () => {
          if (discardRecording) {
            discardRecording = false;
            audioChunks = [];
            stopTracks();
            return;
          }
          if (skipUploadOnStop) {
            skipUploadOnStop = false;
            autoRecording = false;
            audioChunks = [];
            stopSilenceMonitor();
            stopTracks();
            mic.classList.remove("recording");
            setFace("idle");
            return;
          }
          handleRecordingStop(recorder?.mimeType || mimeType, auto);
        };
        recorder.start(250);
        mic.classList.add("recording");
        sendButton.disabled = true;
        setFace("listening");
        if (auto) {
          updateVoiceModeUi("Слушаю...", "listening");
          startSilenceMonitor(recordingStream);
        } else {
          updateVoiceModeUi("Слушаю...", "listening");
        }
        haptic();
      } catch (e) {
        stopTracks();
        const message = friendlyVoiceError(e, "Не удалось включить микрофон. Проверь разрешение и попробуй снова.");
        if (auto) bubble("assistant", message);
        else tg.showAlert(message);
        if (auto) {
          voiceModeActive = false;
          updateVoiceModeUi(message, isMicrophonePermissionError(e) ? "microphone_denied" : "error");
        }
        setFace("error");
      }
    }

    function stopRecording() {
      if (!recorder || recorder.state === "inactive") return;
      stopSilenceMonitor();
      recorder.stop();
      sendButton.disabled = false;
      haptic("success");
    }

    function toggleRecording() {
      if (sending || voiceModeActive || tutorSpeechBusy) return;
      if (recorder && recorder.state === "recording") stopRecording();
      else startRecording();
    }

    async function startLegacyVoiceMode() {
      if (voiceModeActive || sending) return;
      stopTutorSpeech();
      clearVoiceModeTimer();
      voiceModeActive = true;
      missedAutoRecordings = 0;
      updateVoiceModeUi("Готовлюсь...", "thinking");
      haptic();
      if (!voiceIntroPlayed && box.querySelector(".chat-empty")) {
        voiceIntroPlayed = true;
        box.innerHTML = "";
        const ageGroup = voiceAgeGroup();
        const intro = nextRotatingItem(`voiceStarterIndex:${ageGroup}`, ageItems(VOICE_STARTERS_BY_AGE, VOICE_STARTERS));
        bubble("assistant", intro);
        speakTutor(intro, () => scheduleVoiceListen(VOICE_RESTART_DELAY_MS), true);
        return;
      }
      await startRecording(true);
    }

    async function switchToStableVoice(reason = "", text = "") {
      if (!voiceModeActive) return;
      preferStableVoice(reason);
      stopRealtimeSession();
      updateVoiceModeUi("Думаю...");
      setFace("thinking");
      const spokenText = String(text || "").trim();
      if (spokenText) {
        sending = true;
        sendButton.disabled = true;
        mic.disabled = true;
        try {
          const result = await voiceTextTurn(spokenText);
          await renderVoiceTurnResult(result, true, false);
        } catch (e) {
          bubble("assistant", `Ошибка голоса: ${e.message}`);
          scheduleVoiceListen(1500);
        } finally {
          sending = false;
          sendButton.disabled = false;
          mic.disabled = voiceModeActive;
        }
        return;
      }
      voiceModeActive = false;
      await startLegacyVoiceMode();
    }

    async function startRealtimeVoiceMode() {
      if (!realtimeSupported()) {
        throw new Error("WebRTC не поддерживается на этом устройстве");
      }
      stopTutorSpeech();
      stopRealtimeSession();
      clearVoiceModeTimer();
      voiceModeActive = true;
      realtimeActive = true;
      missedAutoRecordings = 0;
      if (box.querySelector(".chat-empty")) box.innerHTML = "";
      updateVoiceModeUi("Подключаю живой голос...", "reconnecting");
      setFace("thinking");
      haptic();

      realtimePc = new RTCPeerConnection();
      realtimeAudio = document.createElement("audio");
      realtimeAudio.autoplay = true;
      realtimeAudio.playsInline = true;
      realtimeAudio.onplaying = () => {
        setRealtimeAssistantSpeakingSafe(true);
      };
      realtimeAudio.onpause = () => {
        if (voiceModeActive && realtimeActive && !realtimeAssistantSpeaking) {
          updateVoiceModeUi("Слушаю...");
          setFace("listening");
        }
      };
      realtimePc.ontrack = event => {
        realtimeAudio.srcObject = event.streams[0];
      };
      realtimePc.onconnectionstatechange = () => {
        if (!voiceModeActive || !realtimeActive) return;
        if (["failed", "disconnected", "closed"].includes(realtimePc.connectionState)) {
          switchToStableVoice(`realtime_${realtimePc.connectionState}`, realtimeLastUserText).catch(console.error);
        }
      };

      updateVoiceModeUi("Запрашиваю микрофон...", "requesting_microphone");
      realtimeStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: { ideal: true },
          noiseSuppression: { ideal: true },
          autoGainControl: { ideal: true },
          sampleRate: { ideal: 16000 },
          channelCount: { ideal: 1 },
          latency: { ideal: 0.02 },
        },
      });
      realtimeStream.getAudioTracks().forEach(track => realtimePc.addTrack(track, realtimeStream));
      setRealtimeMicEnabled(false);

      realtimeDataChannel = realtimePc.createDataChannel("oai-events");
      realtimeDataChannel.onmessage = handleRealtimeEvent;
      realtimeDataChannel.onopen = () => {
        setRealtimeMicEnabled(false);
        updateVoiceModeUi(VOICE_STATE_LABELS.thinking, "thinking");
        setFace("thinking");
        updateVoiceModeUi("Твой ход", "ready");
        setFace("listening");
        const ageGroup = state.me?.user?.age_group || "default";
        const childName = state.me?.user?.child_name || "друг";
        const continueCurrentLesson = Boolean(lessonState?.current_topic || hasLessonHistory());
        const ageGreetings = {
          "5_7": `Поздоровайся с ${childName} по-русски, очень медленно и тепло. Сразу начни суперлегкий английский мини-урок: дай один выбор с двумя словами, например cat — кошка или dog — собака. Один вопрос.`,
          "8_10": `Поздоровайся с ${childName} по-русски, дружелюбно и не быстро. Сразу начни мини-урок английского: дай одну короткую фразу или выбор из двух тем, например game или food. Один вопрос.`,
          "11_13": `Поздоровайся с ${childName} естественно и по-дружески. Сразу начни короткую английскую практику: одна полезная фраза и один вопрос про день, хобби или школу.`,
          "14_18": `Поздоровайся с ${childName} естественно и тепло. Сразу начни устную практику английского: дай один короткий English starter и один интересный вопрос про день, учебу или интересы.`,
          "under_12": `Поздоровайся с ${childName} по-русски, дружелюбно и не быстро. Сразу начни мини-урок английского: дай одну короткую фразу или выбор из двух тем. Один вопрос.`,
          "default": `Начни по-русски: поздоровайся с ${childName} тепло, затем сразу дай маленький английский шаг и один легкий вопрос.`,
        };
        const greeting = lessonState?.current_topic
          ? `Не здоровайся заново и не начинай новую тему. Продолжи урок с ${childName}. Текущая тема: ${lessonState.topic_label}. Этап: ${lessonState.phase_label}. Дай только один подходящий учебный шаг и один вопрос.`
          : continueCurrentLesson
            ? `Не здоровайся заново. Продолжи текущий урок с ${childName}, предложи выбрать одну из уже заданных тем и задай один вопрос.`
            : (ageGreetings[ageGroup] || ageGreetings["default"]);
        sendRealtimeEvent({
          type: "response.create",
          response: {
            instructions: greeting,
          },
        });
      };
      realtimeDataChannel.onclose = () => {
        if (voiceModeActive && realtimeActive) {
          switchToStableVoice("realtime_data_channel_closed", realtimeLastUserText).catch(console.error);
        }
      };

      const offer = await realtimePc.createOffer();
      await realtimePc.setLocalDescription(offer);
      await waitForIceGatheringComplete(realtimePc);
      const localSdp = realtimePc.localDescription?.sdp || offer.sdp;
      let answerSdp = "";
      try {
        const ephemeralKey = await getRealtimeEphemeralKey();
        answerSdp = await openaiRealtimeSdp(ephemeralKey, localSdp);
      } catch (directError) {
        console.error("Direct Realtime call failed, trying server bridge:", directError);
        answerSdp = await apiSdp("/api/realtime/call", localSdp);
      }
      await realtimePc.setRemoteDescription({ type: "answer", sdp: answerSdp });
    }

    async function startVoiceMode() {
      if (voiceModeActive || sending) return;
      if (!shouldUseStableVoice() && realtimeSupported()) {
        try {
          await startRealtimeVoiceMode();
          return;
        } catch (e) {
          console.error("Realtime voice failed:", e);
          preferStableVoice("realtime_start_failed");
          stopRealtimeSession();
          voiceModeActive = false;
          if (isMicrophonePermissionError(e)) {
            const message = friendlyVoiceError(e);
            updateVoiceModeUi(message, "microphone_denied");
            bubble("assistant", message);
            setFace("idle");
            return;
          }
          updateVoiceModeUi("Включаю запасной режим...", "reconnecting");
          if (!realtimeFallbackShown) {
            realtimeFallbackShown = true;
            bubble("assistant", "Живой голос сейчас не включился, попробую запасной режим.");
          }
          setFace("idle");
        }
      }
      await startLegacyVoiceMode();
    }

    function stopVoiceMode() {
      clearVoiceModeTimer();
      voiceModeActive = false;
      autoRecording = false;
      skipUploadOnStop = true;
      stopTutorSpeech();
      updateVoiceModeUi("Обычный режим", "ended");
      stopRealtimeSession();
      if (recorder && recorder.state === "recording") {
        stopRecording();
      } else {
        stopSilenceMonitor();
        stopTracks();
        setFace("idle");
      }
      haptic("success");
    }

    function toggleVoiceMode() {
      if (voiceModeActive) stopVoiceMode();
      else startVoiceMode();
    }

    async function handleVoiceModeButton() {
      if (voiceModeButton.disabled || sending) return;
      if (!voiceModeActive) {
        await startVoiceMode();
        return;
      }
      if (voiceUiState === "speaking") {
        stopTutorSpeech();
        scheduleVoiceListen(220);
        return;
      }
      if (["error", "microphone_denied", "ended"].includes(voiceUiState)) {
        voiceModeActive = false;
        await startVoiceMode();
        return;
      }
      if (["ready", "waiting", "repeat"].includes(voiceUiState)) {
        if (realtimeActive) {
          setRealtimeMicEnabled(true);
          updateVoiceModeUi("Слушаю...", "listening");
          setFace("listening");
        } else {
          await startRecording(true);
        }
        return;
      }
      stopVoiceMode();
    }

    mic.onclick = toggleRecording;
    voiceModeButton.onclick = handleVoiceModeButton;
    sendButton.onclick = send;
    input.addEventListener("keypress", e => { if (e.key === "Enter") send(); });
    setBack(() => {
      cleanupChat();
      renderMenu();
    });
    document.getElementById("reset").onclick = async () => {
      cleanupChat();
      await api("/api/chat/reset", "POST");
      renderChat();
    };
  } catch (e) {
    renderError(e.message);
  }
}

function motivationBadgeHtml(badge, isNew = false) {
  const progress = Math.max(0, Math.min(100, Number(badge.progress_percent) || 0));
  return `
    <div class="badge-card ${badge.unlocked ? "unlocked" : ""} ${isNew ? "badge-unlock" : ""}">
      <div class="badge-mark">${badge.unlocked ? "✓" : progress + "%"}</div>
      <div class="badge-main">
        <b>${esc(badge.title)}${isNew ? ` <span class="badge-new">Новое!</span>` : ""}</b>
        <p>${esc(badge.text)}</p>
        <div class="mini-progress"><span style="width:${progress}%"></span></div>
        <small>${Number(badge.value) || 0}/${Number(badge.target) || 0}</small>
      </div>
    </div>`;
}

// Какие бейджи разблокированы ВПЕРВЫЕ с прошлого просмотра (для анимации).
// Первый заход «сидит» молча — не празднуем задним числом уже открытые.
function diffNewlyUnlocked(badges) {
  const unlockedIds = (badges || []).filter(b => b.unlocked).map(b => b.id);
  let seen = null;
  try { seen = JSON.parse(localStorage.getItem("seenBadges") || "null"); } catch (_) { seen = null; }
  if (!Array.isArray(seen)) {
    try { localStorage.setItem("seenBadges", JSON.stringify(unlockedIds)); } catch (_) {}
    return new Set();
  }
  const seenSet = new Set(seen);
  const fresh = new Set(unlockedIds.filter(id => !seenSet.has(id)));
  if (fresh.size) {
    try { localStorage.setItem("seenBadges", JSON.stringify(unlockedIds)); } catch (_) {}
  }
  return fresh;
}

async function renderMotivation() {
  setBack(renderProgressHub);
  loading();
  try {
    const data = await api("/api/motivation/status", "GET");
    state.motivation = data;
    const summary = data.summary || {};
    const streak = data.streak || {};
    const badges = data.badges || [];
    const freshBadges = diffNewlyUnlocked(badges);
    app.innerHTML = `
      <div class="screen">
        <h1>${esc(data.title || "Достижения")}</h1>
        <div class="card motivation-hero">
          <div>
            <span class="daily-badge">Серия занятий</span>
            <h2>${daysLabel(streak.current)} подряд</h2>
            <p class="hint">${esc(data.coach_message || "Каждый короткий урок двигает вперед.")}</p>
          </div>
          <strong>${summary.unlocked_badges || 0}/${summary.total_badges || 0}</strong>
        </div>
        <div class="card">
          <div class="stat-row"><span>Лучшая серия</span><b>${streak.longest || 0}</b></div>
          <div class="stat-row"><span>Всего учебных дней</span><b>${streak.completed_days || 0}</b></div>
          <div class="stat-row"><span>Слов в обучении</span><b>${summary.words_learned || 0}</b></div>
          <div class="stat-row"><span>Точность ответов</span><b>${summary.accuracy || 0}%</b></div>
        </div>
        <div class="card">
          <h2>${esc(data.next_title || "Следующий шаг")}</h2>
          <p class="hint">${esc(data.next_text || "Сделай короткое задание.")}</p>
          <button class="btn mt-12" id="motivationAction">${esc(suggestedActionLabel(data.next_action))}</button>
        </div>
        <div class="badge-grid">
          ${badges.map(b => motivationBadgeHtml(b, freshBadges.has(b.id))).join("")}
        </div>
        <button class="btn btn-secondary mt-12" id="motivationHome">К прогрессу</button>
      </div>`;
    if (freshBadges.size) haptic("success");
    bindSuggestedActionButton("motivationAction", data.next_action);
    document.getElementById("motivationHome").onclick = () => { haptic(); renderProgressHub(); };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderParentReport() {
  setBack(renderParentCabinet);
  loading();
  try {
    const data = await api("/api/parent/report", "GET");
    const r = data.report;
    const w = data.week || {};
    const d = data.dictionary || {};
    const recommendations = data.recommendations || [];
    const problemWords = data.problem_words || [];
    app.innerHTML = `
      <div class="screen">
        <h1>Отчет для родителя</h1>
        <div class="card">
          <h2>${esc(data.child.name)}</h2>
          <p class="hint">${esc(ageYearsLabel(data.child.child_age))} · Уровень - ${esc(data.child.level_label || "Beginner / A1")}</p>
        </div>
        <div class="card">
          <h2>За 7 дней</h2>
          <div class="stat-row"><span>Занимался дней</span><b>${w.active_days || 0} из ${w.days || 7}</b></div>
          <div class="stat-row"><span>Уроков пройдено</span><b>${w.completed_lessons || 0}</b></div>
          <div class="stat-row"><span>Тестов по словам</span><b>${w.completed_word_tests || 0}</b></div>
          <div class="stat-row"><span>Средний результат</span><b>${w.avg_word_test_score || 0}%</b></div>
          <div class="stat-row"><span>Игр пройдено</span><b>${w.completed_games || 0}</b></div>
          <div class="stat-row"><span>Слов отработано</span><b>${w.words_practiced || 0}</b></div>
        </div>
        <div class="card">
          <h2>За всё время</h2>
          <div class="stat-row"><span>Уроков пройдено</span><b>${r.completed_lessons}</b></div>
          <div class="stat-row"><span>Слов в обучении</span><b>${r.words_learned}</b></div>
          <div class="stat-row"><span>Тестов по словам</span><b>${r.completed_word_tests}</b></div>
          <div class="stat-row"><span>Игр пройдено</span><b>${r.completed_games || 0}</b></div>
          <div class="stat-row"><span>Средний результат</span><b>${r.avg_word_test_score}%</b></div>
          <div class="stat-row"><span>Средний результат игр</span><b>${r.avg_game_score || 0}%</b></div>
          <div class="stat-row"><span>Правильных ответов</span><b>${r.total_correct}</b></div>
          <div class="stat-row"><span>Ошибок</span><b>${r.total_wrong}</b></div>
        </div>
        <div class="card">
          <h2>Статистика слов</h2>
          <div class="stat-row"><span>Всего слов</span><b>${d.total_words || 0}</b></div>
          <div class="stat-row"><span>Нужно повторить</span><b>${d.review_words || 0}</b></div>
          <div class="stat-row"><span>Выучено</span><b>${d.mastered_words || 0}</b></div>
        </div>
        ${recommendations.length ? `
          <div class="card report-recommendations">
            <h2>Что делать дальше</h2>
            ${recommendations.map(item => `
              <div class="recommendation-row">
                <b>${esc(item.title)}</b>
                <p>${esc(item.text)}</p>
              </div>
            `).join("")}
          </div>
        ` : ""}
        ${problemWords.length ? `
          <div class="card">
            <h2>Слова для внимания</h2>
            ${problemWords.map(word => `
              <div class="stat-row">
                <span>${esc(word.word)} · ${esc(word.translation)}</span>
                <b>${word.correct_count}✓ / ${word.wrong_count}×</b>
              </div>
            `).join("")}
          </div>
        ` : ""}
        <button class="btn btn-secondary" id="reportHome">К прогрессу</button>
      </div>`;
    document.getElementById("reportHome").onclick = () => { haptic(); renderProgressHub(); };
  } catch (e) {
    renderError(e.message);
  }
}

function historyDayLabel(value) {
  if (!value) return "";
  try {
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) return value;
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.getTime() === today.getTime()) return "Сегодня";
    if (date.getTime() === yesterday.getTime()) return "Вчера";
    return date.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
  } catch (_) {
    return value;
  }
}

function formatEventTime(value) {
  if (!value) return "";
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return "";
  }
}

function groupHistoryEvents(events) {
  const groups = [];
  events.forEach(event => {
    const date = event.date || "";
    let group = groups.find(item => item.date === date);
    if (!group) {
      group = { date, events: [] };
      groups.push(group);
    }
    group.events.push(event);
  });
  return groups;
}

async function renderActivityHistory() {
  setBack(renderParentCabinet);
  loading();
  try {
    const data = await api("/api/activity/history", "GET");
    const events = data.events || [];
    const groups = groupHistoryEvents(events);
    app.innerHTML = `
      <div class="screen">
        <h1>История занятий</h1>
        ${groups.length ? groups.map(group => `
          <section class="history-day">
            <div class="history-day-label">${esc(historyDayLabel(group.date))}</div>
            <div class="activity-list">
              ${group.events.map(event => `
                <div class="card activity-card">
                  <div class="activity-head">
                    <b>${esc(event.title)}</b>
                    <span>${esc(formatEventTime(event.event_at))}</span>
                  </div>
                  <p>${esc(event.description)}</p>
                </div>
              `).join("")}
            </div>
          </section>
        `).join("") : `
          <div class="card center">
            <b>История пока пустая</b>
            <p class="hint">Заверши урок, тренировку, тест или игру — результат появится здесь.</p>
          </div>
        `}
        <button class="btn btn-secondary" id="historyHome">К прогрессу</button>
      </div>`;
    document.getElementById("historyHome").onclick = () => { haptic(); renderProgressHub(); };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderLeaderboard() {
  setBack(renderProgressHub);
  loading();
  try {
    const data = await api("/api/leaderboard", "GET");
    const rowsHtml = (list) => (list || []).length
      ? list.map(leader => `
          <div class="leader-row ${leader.is_me ? "me" : ""}">
            <div class="leader-rank">${leader.rank}</div>
            <div class="leader-main">
              <b>${esc(leader.name)}</b>
              <span>${esc(leader.age_label)}</span>
            </div>
            <div class="leader-points">${leader.points} 💎</div>
          </div>`).join("")
      : `<p class="hint center">Рейтинг появится после первых тренировок.</p>`;
    const lists = { all: data.leaders, age: data.age_leaders };
    const ageLabel = data.age_label || "Мой возраст";
    app.innerHTML = `
      <div class="screen">
        <h1>Рейтинг</h1>
        <div class="seg-toggle">
          <button class="seg-btn active" data-scope="all">Все</button>
          <button class="seg-btn" data-scope="age">${esc(ageLabel)}</button>
        </div>
        <div class="card leaderboard" id="lbList">${rowsHtml(lists.all)}</div>
        <button class="btn btn-secondary" id="leaderboardHome">К прогрессу</button>
      </div>`;
    const listBox = document.getElementById("lbList");
    document.querySelectorAll(".seg-btn").forEach(btn => {
      btn.onclick = () => {
        haptic();
        document.querySelectorAll(".seg-btn").forEach(b => b.classList.toggle("active", b === btn));
        listBox.innerHTML = rowsHtml(lists[btn.dataset.scope]);
      };
    });
    document.getElementById("leaderboardHome").onclick = () => { haptic(); renderProgressHub(); };
  } catch (e) {
    renderError(e.message);
  }
}

function formatAdminNumber(value) {
  return Number(value || 0).toLocaleString("ru-RU");
}

function formatAdminMoney(value) {
  return `$${Number(value || 0).toFixed(4)}`;
}

function formatAdminDateTime(value) {
  if (!value) return "";
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch (_) {
    return "";
  }
}

function adminStatHtml(label, value, hint = "") {
  return `
    <div class="admin-stat">
      <span>${esc(label)}</span>
      <b>${esc(value)}</b>
      ${hint ? `<small>${esc(hint)}</small>` : ""}
    </div>`;
}

function clampAdminPercent(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, Math.round(number)));
}

function adminRatioPercent(part, total) {
  const totalNumber = Number(total || 0);
  if (!Number.isFinite(totalNumber) || totalNumber <= 0) return 0;
  return Number(part || 0) / totalNumber * 100;
}

function adminChartTone(tone) {
  return ["blue", "green", "yellow", "red", "violet"].includes(tone) ? tone : "blue";
}

function adminCircleChartHtml(label, percent, value, hint = "", tone = "blue") {
  const safePercent = clampAdminPercent(percent);
  return `
    <div class="admin-chart ${adminChartTone(tone)}" style="--value:${safePercent}">
      <div class="admin-chart-ring" aria-label="${esc(label)} ${safePercent}%">
        <span>${safePercent}%</span>
      </div>
      <div class="admin-chart-copy">
        <span>${esc(label)}</span>
        <b>${esc(value)}</b>
        ${hint ? `<small>${esc(hint)}</small>` : ""}
      </div>
    </div>`;
}

function adminFailedImageHtml(word) {
  return `
    <div class="admin-word-row">
      <div>
        <b>${esc(word.word)}</b>
        <span>${esc(word.translation)} · ${esc(word.topic || "basic")}</span>
        ${word.reason ? `<small>${esc(word.reason)}</small>` : ""}
      </div>
      <em>${esc(formatAdminDateTime(word.checked_at) || "нет даты")}</em>
    </div>`;
}

function adminHealthHtml(item) {
  const level = item.level || "info";
  return `
    <div class="admin-health ${esc(level)}">
      <b>${esc(item.title || "Состояние")}</b>
      <span>${esc(item.text || "")}</span>
    </div>`;
}

async function renderAdminPanel() {
  setBack(renderMenu);
  loading();
  try {
    const data = await api("/api/admin/overview", "GET");
    state.admin = data;
    const users = data.users || {};
    const learning = data.learning || {};
    const words = data.words || {};
    const ai = data.ai_today || {};
    const aiWeek = data.ai_week || {};
    const cache = data.cache || {};
    const config = data.config || {};
    const openai = config.openai || {};
    const failedWords = data.failed_image_words || [];
    const health = data.health || [];
    const wordsTotal = Number(words.total || 0);
    const readyImages = Number(words.generated_images || 0) + Number(words.images_needing_review || 0);
    const audioFiles = Number(cache.word_audio?.files || 0);
    const usersTotal = Number(users.total || 0);
    app.innerHTML = `
      <div class="screen admin-screen">
        <h1>Админпанель</h1>
        <div class="card admin-hero">
          <div>
            <div class="daily-badge">Управление</div>
            <h2>Состояние приложения</h2>
            <p class="hint">Безопасная панель: секреты и ключи здесь не показываются.</p>
          </div>
          <strong>${esc(config.app_version || "")}</strong>
        </div>

        <div class="admin-health-list">
          ${health.map(adminHealthHtml).join("")}
        </div>

        <div class="admin-grid">
          ${adminStatHtml("Пользователи", formatAdminNumber(users.total), `сегодня активны: ${formatAdminNumber(users.active_today)}`)}
          ${adminStatHtml("Новые сегодня", formatAdminNumber(users.new_today), `баллов всего: ${formatAdminNumber(users.total_points)}`)}
          ${adminStatHtml("Словарь", formatAdminNumber(words.total), `AI-картинок: ${formatAdminNumber(words.generated_images)}`)}
          ${adminStatHtml("Ошибки картинок", formatAdminNumber(words.failed_images), `ожидают: ${formatAdminNumber(words.missing_images)}`)}
          ${adminStatHtml("AI-запросы сегодня", formatAdminNumber(ai.requests), `${formatAdminNumber(ai.total_tokens)} токенов`)}
          ${adminStatHtml("Расход сегодня", formatAdminMoney(ai.cost_usd), "оценка по сохраненным usage")}
          ${adminStatHtml("Расход за 7 дней", formatAdminMoney(aiWeek.cost_usd), `${formatAdminNumber(aiWeek.requests)} запросов`)}
        </div>

        <div class="admin-chart-grid">
          ${adminCircleChartHtml("Картинки", adminRatioPercent(readyImages, wordsTotal), `${formatAdminNumber(readyImages)} / ${formatAdminNumber(wordsTotal)}`, "готовы или ждут проверки", readyImages >= wordsTotal && wordsTotal ? "green" : "blue")}
          ${adminCircleChartHtml("Активность", adminRatioPercent(users.active_today, usersTotal), `${formatAdminNumber(users.active_today)} / ${formatAdminNumber(usersTotal)}`, "учеников сегодня", users.active_today ? "green" : "blue")}
          ${adminCircleChartHtml("Озвучка", adminRatioPercent(audioFiles, wordsTotal), `${formatAdminNumber(audioFiles)} / ${formatAdminNumber(wordsTotal)}`, "аудио в кэше", audioFiles >= wordsTotal && wordsTotal ? "green" : "violet")}
          ${adminCircleChartHtml("Проблемы", adminRatioPercent(words.failed_images, wordsTotal), formatAdminNumber(words.failed_images), "ошибки генерации картинок", words.failed_images ? "red" : "green")}
        </div>

        <div class="card">
          <h2>Учебная активность</h2>
          <div class="stat-row"><span>Уроков дня завершено</span><b>${formatAdminNumber(learning.completed_daily_lessons)}</b></div>
          <div class="stat-row"><span>Тестов по словам</span><b>${formatAdminNumber(learning.completed_word_tests)}</b></div>
          <div class="stat-row"><span>Игр завершено</span><b>${formatAdminNumber(learning.completed_games)}</b></div>
          <div class="stat-row"><span>Попыток тренировок</span><b>${formatAdminNumber(learning.training_attempts)}</b></div>
        </div>

        <div class="card">
          <h2>OpenAI и медиа</h2>
          <div class="stat-row"><span>Модель чата</span><b>${esc(openai.model || "-")}</b></div>
          <div class="stat-row"><span>Realtime</span><b>${esc(openai.realtime_model || "-")}</b></div>
          <div class="stat-row"><span>Голос</span><b>${esc(openai.realtime_voice || openai.voice_tts_voice || "-")}</b></div>
          <div class="stat-row"><span>Картинки</span><b>${esc(openai.image_model || "-")}</b></div>
          <div class="stat-row"><span>Кэш картинок</span><b>${formatAdminNumber(cache.generated_images?.files)} · ${cache.generated_images?.size_mb || 0} MB</b></div>
          <div class="stat-row"><span>Кэш озвучки</span><b>${formatAdminNumber(cache.word_audio?.files)} · ${cache.word_audio?.size_mb || 0} MB</b></div>
        </div>

        <div class="card">
          <h2>Картинки слов</h2>
          <p class="hint">Если в OpenAI был лимит billing, сбрось ошибки после увеличения лимита. Тогда карточки смогут снова запросить AI-картинки.</p>
          ${failedWords.length ? `
            <div class="admin-list">
              ${failedWords.map(adminFailedImageHtml).join("")}
            </div>
          ` : `<p class="hint">Ошибок генерации картинок сейчас нет.</p>`}
          <button class="btn mt-12" id="adminResetImages">Сбросить ошибки картинок</button>
        </div>

        <button class="btn" id="adminUsers">Пользователи</button>
        <button class="btn btn-secondary" id="adminRefresh">Обновить</button>
        <button class="btn btn-secondary" id="adminHome">В меню</button>
      </div>`;
    document.getElementById("adminUsers").onclick = () => { haptic(); renderAdminUsers(); };
    document.getElementById("adminRefresh").onclick = () => { haptic(); renderAdminPanel(); };
    document.getElementById("adminHome").onclick = () => { haptic(); renderMenu(); };
    document.getElementById("adminResetImages").onclick = async () => {
      haptic("warning");
      const ok = await confirmAction("Сбросить статусы неудачной генерации картинок? После этого карточки смогут запросить картинки снова.");
      if (!ok) return;
      try {
        const result = await api("/api/admin/images/reset-failed", "POST", { confirm: "reset_image_failures" });
        tg.showAlert(`Сброшено статусов: ${result.updated || 0}`);
        renderAdminPanel();
      } catch (e) {
        tg.showAlert(e.message);
      }
    };
  } catch (e) {
    renderError(e.message);
  }
}

function adminUserRowHtml(user) {
  return `
    <div class="admin-user-row">
      <div class="admin-user-main">
        <b>${esc(user.child_name)}</b>
        <span>ID ${esc(user.id)} · ${esc(user.age_label || "возраст не указан")} · ${esc(user.level_label || "")}</span>
        <small>${esc(user.parent_name || "родитель не указан")} · ${formatAdminNumber(user.points)} баллов · ${formatAdminNumber(user.words_learned)} слов · точность ${user.accuracy || 0}%</small>
      </div>
      <div class="admin-user-actions">
        <button type="button" class="admin-mini-btn" data-open-user="${esc(user.id)}">Открыть</button>
        <button type="button" class="admin-mini-btn danger" data-reset-user="${esc(user.id)}">Сброс</button>
      </div>
    </div>`;
}

function bindAdminUserActions(query = "") {
  document.querySelectorAll("[data-open-user]").forEach(button => {
    button.onclick = () => {
      haptic();
      renderAdminUserDetail(Number(button.dataset.openUser));
    };
  });
  document.querySelectorAll("[data-reset-user]").forEach(button => {
    button.onclick = async () => {
      haptic("warning");
      const userId = Number(button.dataset.resetUser);
      const ok = await confirmAction(`Обнулить учебные результаты пользователя ${userId}? Профиль останется.`);
      if (!ok) return;
      button.disabled = true;
      try {
        await api("/api/admin/users/reset-results", "POST", {
          user_id: userId,
          confirm: "reset_user_results",
        });
        tg.showAlert("Результаты пользователя обнулены.");
        renderAdminUsers(query);
      } catch (e) {
        button.disabled = false;
        tg.showAlert(e.message);
      }
    };
  });
}

function adminUsersListHtml(users, query = "") {
  if (users.length) {
    return users.map(adminUserRowHtml).join("");
  }
  return `
    <div class="card center">
      <b>Ничего не найдено</b>
      <p class="hint">${query ? "Попробуй другой запрос." : "Пользователи появятся после регистраций."}</p>
    </div>`;
}

async function loadAdminUsers(query = "") {
  const list = document.getElementById("adminUsersList");
  if (!list) return;
  const requestId = ++adminUsersRequestId;
  state.adminUsersQuery = query;
  list.innerHTML = `<div class="card center"><p class="hint">Загружаю пользователей...</p></div>`;
  try {
    const data = await api(`/api/admin/users?q=${encodeURIComponent(query)}&limit=60`, "GET");
    if (requestId !== adminUsersRequestId) return;
    const users = data.users || [];
    list.innerHTML = adminUsersListHtml(users, query);
    bindAdminUserActions(query);
  } catch (e) {
    if (requestId !== adminUsersRequestId) return;
    list.innerHTML = `
      <div class="error-box">
        ${esc(e.message)}
      </div>`;
  }
}

async function renderAdminUsers(query = "") {
  setBack(renderAdminPanel);
  state.adminUsersQuery = query;
  app.innerHTML = `
    <div class="screen admin-screen">
      <h1>Пользователи</h1>
      <div class="card dictionary-search-card">
        <input id="adminUserSearch" type="text" placeholder="Найти ученика, родителя или ID..." value="${esc(query)}" autocomplete="off">
      </div>
      <div class="admin-list" id="adminUsersList">
        <div class="card center"><p class="hint">Загружаю пользователей...</p></div>
      </div>
      <button class="btn btn-secondary" id="adminUsersBack">К админке</button>
    </div>`;
  const search = document.getElementById("adminUserSearch");
  let searchTimer = null;
  search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => loadAdminUsers(search.value.trim()), 350);
  });
  document.getElementById("adminUsersBack").onclick = () => { haptic(); renderAdminPanel(); };
  loadAdminUsers(query);
}

function adminProblemWordHtml(word) {
  return `
    <div class="admin-word-row">
      <div>
        <b>${esc(word.word)} · ${esc(word.translation)}</b>
        <span>${esc(word.transcription || "")}</span>
      </div>
      <em>${formatAdminNumber(word.correct_count)}✓ / ${formatAdminNumber(word.wrong_count)}×</em>
    </div>`;
}

function adminHistoryHtml(event) {
  return `
    <div class="activity-card card">
      <div class="activity-head">
        <b>${esc(event.title)}</b>
        <span>${esc(formatEventTime(event.event_at))}</span>
      </div>
      <p>${esc(event.description)}</p>
    </div>`;
}

async function renderAdminUserDetail(userId) {
  setBack(() => renderAdminUsers(state.adminUsersQuery || ""));
  loading();
  try {
    const data = await api(`/api/admin/users/detail?user_id=${encodeURIComponent(userId)}`, "GET");
    const u = data.user || {};
    const stats = data.stats || {};
    const report = data.report || {};
    const dictionary = data.dictionary || {};
    const streak = data.streak || {};
    const ai = data.ai_today || {};
    const problemWords = data.problem_words || [];
    const history = data.history || [];
    const totalWords = Number(dictionary.total_words || 0);
    const wordsForReview = Number(dictionary.review_words || 0);
    const masteredWords = Number(dictionary.mastered_words || 0);
    const streakDays = Number(streak.current || 0);
    app.innerHTML = `
      <div class="screen admin-screen">
        <h1>Карточка ученика</h1>
        <div class="card admin-hero">
          <div>
            <div class="daily-badge">ID ${esc(u.id || userId)}</div>
            <h2>${esc(u.child_name || "Ученик")}</h2>
            <p class="hint">${esc(u.age_label || "возраст не указан")} · ${esc(u.goal_label || "")} · ${esc(u.level_label || "")}</p>
          </div>
          <strong>${formatAdminNumber(u.points)} 💎</strong>
        </div>

        <div class="admin-grid">
          ${adminStatHtml("Слов в обучении", formatAdminNumber(stats.words_learned), `повторить: ${formatAdminNumber(dictionary.review_words)}`)}
          ${adminStatHtml("Точность", `${stats.accuracy || 0}%`, `${formatAdminNumber(stats.total_correct)}✓ / ${formatAdminNumber(stats.total_wrong)}×`)}
          ${adminStatHtml("Уроки", formatAdminNumber(report.completed_lessons), `серия: ${formatAdminNumber(streak.current)} дн.`)}
          ${adminStatHtml("AI сегодня", formatAdminNumber(ai.used_today), `${formatAdminMoney(ai.cost_usd_today)} · ${formatAdminNumber(ai.total_tokens_today)} токенов`)}
        </div>

        <div class="admin-chart-grid">
          ${adminCircleChartHtml("Точность", stats.accuracy || 0, `${stats.accuracy || 0}%`, `${formatAdminNumber(stats.total_correct)}✓ / ${formatAdminNumber(stats.total_wrong)}×`, Number(stats.accuracy || 0) >= 80 ? "green" : "yellow")}
          ${adminCircleChartHtml("Выучено", adminRatioPercent(masteredWords, totalWords), `${formatAdminNumber(masteredWords)} / ${formatAdminNumber(totalWords)}`, "словарь ученика", "blue")}
          ${adminCircleChartHtml("Повторить", adminRatioPercent(wordsForReview, totalWords), formatAdminNumber(wordsForReview), "слов требуют внимания", wordsForReview ? "yellow" : "green")}
          ${adminCircleChartHtml("Серия", Math.min(100, streakDays / 7 * 100), `${formatAdminNumber(streakDays)} дн.`, "цель: 7 дней подряд", streakDays >= 7 ? "green" : "violet")}
        </div>

        <div class="card">
          <h2>Профиль</h2>
          <div class="stat-row"><span>Родитель</span><b>${esc(u.parent_name || "-")}</b></div>
          <div class="stat-row"><span>Возраст</span><b>${esc(u.child_age || "-")}</b></div>
          <div class="stat-row"><span>Тест уровня</span><b>${u.level_test_completed ? `${u.level_test_score}%` : "не пройден"}</b></div>
          <div class="stat-row"><span>Регистрация</span><b>${esc(formatAdminDateTime(u.registered_at) || "-")}</b></div>
        </div>

        <div class="card">
          <h2>Учебные результаты</h2>
          <div class="stat-row"><span>Тестов по словам</span><b>${formatAdminNumber(report.completed_word_tests)}</b></div>
          <div class="stat-row"><span>Средний тест</span><b>${formatAdminNumber(report.avg_word_test_score)}%</b></div>
          <div class="stat-row"><span>Игр завершено</span><b>${formatAdminNumber(report.completed_games)}</b></div>
          <div class="stat-row"><span>Выучено слов</span><b>${formatAdminNumber(dictionary.mastered_words)}</b></div>
        </div>

        <div class="card">
          <h2>Слова для внимания</h2>
          ${problemWords.length ? `<div class="admin-list">${problemWords.map(adminProblemWordHtml).join("")}</div>` : `<p class="hint">Пока нет слов с ошибками.</p>`}
        </div>

        <div class="card">
          <h2>Последняя активность</h2>
          ${history.length ? `<div class="activity-list">${history.map(adminHistoryHtml).join("")}</div>` : `<p class="hint">Активности пока нет.</p>`}
        </div>

        <button class="btn btn-danger" id="adminDetailReset">Обнулить результаты ученика</button>
        <button class="btn btn-secondary" id="adminDetailBack">К пользователям</button>
      </div>`;
    document.getElementById("adminDetailBack").onclick = () => { haptic(); renderAdminUsers(state.adminUsersQuery || ""); };
    document.getElementById("adminDetailReset").onclick = async () => {
      haptic("warning");
      const ok = await confirmAction(`Обнулить учебные результаты ученика ${u.child_name || userId}?`);
      if (!ok) return;
      try {
        await api("/api/admin/users/reset-results", "POST", {
          user_id: Number(u.id || userId),
          confirm: "reset_user_results",
        });
        tg.showAlert("Результаты ученика обнулены.");
        renderAdminUserDetail(userId);
      } catch (e) {
        tg.showAlert(e.message);
      }
    };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderProfile() {
  setBack(renderParentZone);
  loading();
  try {
    state.me = await api("/api/me", "GET");
    const u = state.me.user;
    app.innerHTML = `
      <div class="screen">
        <h1>Профиль ребёнка</h1>
        <div class="card center">
          <h2>${esc(u.child_name)}</h2>
          <p class="hint">Возраст — ${esc(ageYearsLabel(u.child_age))}</p>
          <div class="big" style="color: var(--button)">${u.points} 💎</div>
        </div>
        <div class="card">
          <div class="stat-row"><span>Родитель</span><b>${esc(u.parent_name || "-")}</b></div>
          <div class="stat-row"><span>Возраст</span><b>${u.child_age || "-"}</b></div>
          <div class="stat-row"><span>Уровень</span><b>${esc(u.level_label || "Beginner / A1")}</b></div>
          <div class="stat-row"><span>Тест уровня</span><b>${u.level_test_completed ? `${u.level_test_score}%` : "не пройден"}</b></div>
        </div>
      </div>`;
  } catch (e) {
    renderError(e.message);
  }
}

async function renderSettings() {
  setBack(renderParentZone);
  tg.MainButton.hide();
  ensureBottomNav("parent");
  if (!state.me || !state.me.user) { renderMenu(); return; }
  app.innerHTML = `
    <div class="screen">
      <h1>Настройки</h1>
      <div class="card">
        <h2>Уведомления</h2>
        <p class="hint">Напоминание в Telegram, если за день не было занятий. Не чаще одного раза в день.</p>
        <button class="btn" id="remToggle">Напоминания</button>
      </div>
      <div class="card">
        <h2>Аккаунт и данные</h2>
        <p class="hint">Сброс результатов обнулит баллы, уровень, выученные слова, тесты и ежедневные уроки. Профиль и чат с репетитором останутся.</p>
        <button class="btn btn-danger" id="resetResults">Обнулить результаты</button>
        <button class="btn btn-secondary" id="logout">Выйти из аккаунта</button>
        <p class="hint mt-12">Удаление навсегда стирает профиль, прогресс, историю и все диалоги с репетитором. Отменить нельзя.</p>
        <button class="btn btn-danger" id="deleteAccount">Удалить профиль и все данные</button>
      </div>
    </div>`;
  const remBtn = document.getElementById("remToggle");
  const paintRem = (on) => {
    remBtn.textContent = on ? "🔔 Напоминания: включены" : "🔕 Напоминания: выключены";
    remBtn.className = on ? "btn" : "btn btn-secondary";
  };
  paintRem(!!(state.me.user && state.me.user.reminders_enabled));
  remBtn.onclick = async () => {
    haptic();
    const next = !(state.me.user && state.me.user.reminders_enabled);
    remBtn.disabled = true;
    try {
      const r = await api("/api/settings", "POST", { reminders_enabled: next });
      state.me.user.reminders_enabled = r.reminders_enabled;
      paintRem(r.reminders_enabled);
    } catch (e) {
      tg.showAlert(e.message || "Не удалось сохранить настройку");
    } finally {
      remBtn.disabled = false;
    }
  };
  document.getElementById("resetResults").onclick = async () => {
    haptic("warning");
    const ok = await confirmAction("Обнулить все учебные результаты? Баллы, уровень, тесты и прогресс слов начнутся заново.");
    if (!ok) return;
    try {
      const result = await api("/api/results/reset", "POST", { confirm: "reset_results" });
      state.me.user.points = result.user.points;
      state.me.stats = result.stats;
      tg.showAlert("Результаты обнулены. Можно начать обучение заново.");
      renderSettings();
    } catch (e) {
      renderError(e.message);
    }
  };
  document.getElementById("logout").onclick = async () => {
    haptic("warning");
    const ok = await confirmAction("Выйти из аккаунта на этом устройстве? Для другого аккаунта переключитесь в Telegram и откройте приложение снова.");
    if (ok) logoutFromApp();
  };
  document.getElementById("deleteAccount").onclick = async () => {
    haptic("warning");
    const ok = await confirmAction("Удалить профиль и ВСЕ данные ребёнка навсегда? Прогресс, история и диалоги будут стёрты без возможности восстановления.");
    if (!ok) return;
    try {
      await api("/api/account/delete", "POST", { confirm: "delete_account" });
      tg.showAlert("Профиль и все данные удалены.");
      logoutFromApp();
    } catch (e) {
      renderError(e.message);
    }
  };
}

function renderLoggedOut() {
  setBack(null);
  tg.MainButton.hide();
  const telegramHint = tg.initData
    ? "Чтобы войти в другой аккаунт, переключите аккаунт в Telegram и откройте приложение снова."
    : "Чтобы войти снова, отправьте боту /start и откройте новую кнопку приложения.";
  app.innerHTML = `
    <div class="screen">
      <h1>Вы вышли</h1>
      <div class="card">
        <p class="hint">${telegramHint}</p>
      </div>
      <button class="btn" id="loginAgain">Войти снова</button>
    </div>`;
  document.getElementById("loginAgain").onclick = () => {
    haptic();
    loginAgain();
  };
}

async function start() {
  if (isLoggedOut()) {
    renderLoggedOut();
    return;
  }
  const hasFallbackAuth = /[?&]fa_hash=/.test(fallbackAuth);
  if (!tg.initData && !hasFallbackAuth) {
    app.innerHTML = `
      <div class="screen">
        <h1>AI English Tutor Kids</h1>
        <div class="card">
          <p class="hint">Откройте приложение через новую кнопку в Telegram-боте. Если эта страница открылась из старой кнопки, отправьте боту /start и нажмите новую кнопку.</p>
        </div>
      </div>`;
    return;
  }
  try {
    state.me = await api("/api/me", "GET");
    applyAppearance();
    if (state.me.registered) renderMenu();
    else renderRegistration();
  } catch (e) {
    renderError(e.message);
  }
}

start();
