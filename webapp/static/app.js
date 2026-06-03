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
  dictionaryFilter: "all",
};
let fallbackAuth = window.location.search || "";
const LOGGED_OUT_KEY = "englishTutorKidsLoggedOut";

function authHeaders(contentType = "application/json") {
  const headers = {
    "X-Telegram-Init-Data": tg.initData || "",
    "X-App-Fallback-Auth": fallbackAuth,
  };
  if (contentType) headers["Content-Type"] = contentType;
  return headers;
}

async function api(path, method = "POST", body = null) {
  const res = await fetch(path, {
    method,
    headers: authHeaders(),
    body: method === "GET" ? undefined : JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
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
    throw new Error(err.error || `HTTP ${res.status}`);
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
      throw new Error(err.error || `HTTP ${res.status}`);
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
  if (await speakWordLocally(word, button)) return;

  const oldText = button?.textContent;
  if (button) {
    button.disabled = true;
    button.textContent = "…";
  }
  try {
    const cacheKey = word.toLowerCase();
    let audioBlob = wordAudioCache.get(cacheKey);
    if (!audioBlob) {
      audioBlob = await apiBlob("/api/audio/speech", { text: word, mode: "word" }, 60000);
      rememberWordAudio(cacheKey, audioBlob);
    }
    wordAudioUrl = URL.createObjectURL(audioBlob);
    wordAudio = new Audio(wordAudioUrl);
    wordAudio.onended = stopWordAudio;
    wordAudio.onerror = stopWordAudio;
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

function pronunciationButtonHtml(word, small = false) {
  return `<button type="button" class="pronounce-btn ${small ? "small" : ""}" data-word="${esc(word)}" aria-label="Озвучить ${esc(word)}">🔊</button>`;
}

function wordImageHtml(wordData, small = false) {
  const src = wordData?.image_url || "";
  if (!src) return "";
  const label = wordData?.word || wordData?.translation || "word";
  return `<img class="word-image ${small ? "small" : ""}" src="${esc(src)}" alt="${esc(label)}" loading="lazy">`;
}

function wordStudyCard(wordData, options = {}) {
  const badge = options.badge || "";
  const prompt = options.prompt || "";
  return `
    <div class="card word-card ${options.compact ? "compact" : ""}">
      <div class="word-card-top">
        ${badge ? `<div class="daily-badge">${esc(badge)}</div>` : "<span></span>"}
        ${pronunciationButtonHtml(wordData.word)}
      </div>
      ${options.showImage ? wordImageHtml(wordData) : ""}
      <div class="word-main">${esc(wordData.word)}</div>
      ${wordData.transcription ? `<div class="word-transcription">${esc(wordData.transcription)}</div>` : ""}
      ${wordData.translation ? `<div class="word-translation">${esc(wordData.translation)}</div>` : ""}
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
  state.dictionaryFilter = "all";
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

function renderError(message) {
  setBack(null);
  app.innerHTML = `
    <div class="screen">
      <div class="error-box"><b>Что-то пошло не так</b><div class="mt-8">${esc(message)}</div></div>
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

function learningPathHtml(data) {
  const levelTestButton = data.next_action === "level"
    ? `<button class="btn btn-secondary mt-12" id="learningPathLevelTest">Пройти тест уровня</button>`
    : "";
  return `
    <div class="learning-path-head">
      <div>
        <div class="daily-badge">${esc(data.title || "Маршрут дня")}</div>
        <h2>${esc(data.next_title || "Продолжить обучение")}</h2>
      </div>
      <strong>${data.progress_percent || 0}%</strong>
    </div>
    <p class="hint">${esc(data.next_text || "Выбери следующий шаг.")}</p>
    <div class="path-progress"><span style="width:${Math.max(0, Math.min(100, Number(data.progress_percent) || 0))}%"></span></div>
    ${levelTestButton}`;
}

async function loadLearningPath() {
  const box = document.getElementById("learningPath");
  if (!box) return;
  box.innerHTML = `<div class="hint">Подбираю следующий шаг...</div>`;
  try {
    const data = await api("/api/learning/path", "GET");
    state.learningPath = data;
    box.innerHTML = learningPathHtml(data);
    const levelTestButton = document.getElementById("learningPathLevelTest");
    if (levelTestButton) {
      levelTestButton.onclick = () => { haptic(); renderLevelTestIntro(); };
    }
  } catch (_) {
    box.innerHTML = `
      <div class="learning-path-head">
        <div>
          <div class="daily-badge">Маршрут дня</div>
          <h2>Начать короткий урок</h2>
        </div>
      </div>
      <p class="hint">Не удалось обновить маршрут. Открой раздел учебы ниже.</p>`;
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
        <h2>${streak.current || 0} дней подряд</h2>
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
      </div>

      <div class="card">
        <h2>Возрастная группа</h2>
        <div id="ageGroups">${optionButtons(state.me.age_groups || [], "age")}</div>
      </div>

      <div class="card">
        <h2>Цель обучения</h2>
        <div id="goals">${optionButtons(state.me.goals || [], "goal")}</div>
      </div>

      <button class="btn" id="register">Создать профиль</button>
    </div>`;

  let ageGroup = "";
  let goal = "";

  function choose(selector, button, setter) {
    document.querySelectorAll(selector).forEach(btn => btn.classList.add("btn-secondary"));
    button.classList.remove("btn-secondary");
    setter(button.dataset.value);
    haptic();
  }

  function chooseByValue(selector, value, setter) {
    const button = document.querySelector(`${selector}[data-value="${value}"]`);
    if (button) choose(selector, button, setter);
  }

  document.querySelectorAll(".age").forEach(btn => {
    btn.onclick = () => choose(".age", btn, value => { ageGroup = value; });
  });
  document.querySelectorAll(".goal").forEach(btn => {
    btn.onclick = () => choose(".goal", btn, value => { goal = value; });
  });
  document.getElementById("childAge").addEventListener("input", event => {
    const suggestedGroup = ageToGroup(Number(event.target.value));
    if (suggestedGroup) chooseByValue(".age", suggestedGroup, value => { ageGroup = value; });
  });

  document.getElementById("register").onclick = async () => {
    const parent_name = document.getElementById("parentName").value.trim();
    const child_name = document.getElementById("childName").value.trim();
    const child_age = document.getElementById("childAge").value.trim();
    if (child_name.length < 2) return tg.showAlert("Введите имя ребенка");
    if (!child_age || Number(child_age) < 5 || Number(child_age) > 18) return tg.showAlert("Возраст должен быть от 5 до 18");
    if (!ageGroup) return tg.showAlert("Выберите возрастную группу");
    if (!goal) return tg.showAlert("Выберите цель обучения");
    try {
      await api("/api/register", "POST", { parent_name, child_name, child_age, age_group: ageGroup, goal });
      state.me = await api("/api/me", "GET");
      haptic("success");
      renderLevelTestIntro({ afterRegistration: true });
    } catch (e) {
      tg.showAlert(e.message);
    }
  };
}

function renderMenu() {
  setBack(null);
  tg.MainButton.hide();
  const u = state.me.user;
  app.innerHTML = `
    <div class="screen dashboard">
      <div class="dashboard-hero">
        <div>
          <div class="daily-badge">Сегодня</div>
          <h1>Привет, ${esc(u.child_name)}!</h1>
          <p>${esc(u.goal_label || "Английский")} · ${esc(u.level_label || "Beginner / A1")}</p>
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
          <span>Репетитор</span>
          <b>Разговорная практика</b>
          <small>говорить, слушать, задавать вопросы</small>
        </button>
        <button class="action-tile learn" id="learnHub">
          <span>Учеба</span>
          <b>Практические занятия</b>
          <small>урок, тренировки, словарь, игры</small>
        </button>
        <button class="action-tile progress" id="progressHub">
          <span>Прогресс</span>
          <b>Достижения и отчет</b>
          <small>история, рейтинг, родительский отчет</small>
        </button>
        <button class="action-tile profile" id="profile">
          <span>Аккаунт</span>
          <b>Профиль</b>
          <small>уровень, данные, выход</small>
        </button>
      </div>

    </div>`;

  document.getElementById("chat").onclick = () => { haptic(); renderChat(); };
  document.getElementById("learnHub").onclick = () => { haptic(); renderLearningHub(); };
  document.getElementById("progressHub").onclick = () => { haptic(); renderProgressHub(); };
  document.getElementById("profile").onclick = () => { haptic(); renderProfile(); };
  loadLearningPath();
}

function renderLearningHub() {
  setBack(renderMenu);
  tg.MainButton.hide();
  const u = state.me.user;
  app.innerHTML = `
    <div class="screen">
      <h1>Учеба</h1>
      <div class="section-label">Сегодня</div>
      <div class="action-list">
        <button class="action-row primary" id="daily">
          <span>Урок дня</span>
          <b>Короткий маршрут</b>
          <small>слова, мини-тест и простая фраза</small>
        </button>
      </div>

      <div class="section-label">Практика</div>
      <div class="hub-grid">
        <button class="action-tile learn" id="vocab">
          <b>Учим слова</b>
          <small>карточки и короткий тест</small>
        </button>
        <button class="action-tile review" id="training">
          <b>Работа над ошибками</b>
          <small>ошибки и закрепление</small>
        </button>
        <button class="action-tile dictionary" id="dictionary">
          <b>Словарь</b>
          <small>транскрипция и озвучка</small>
        </button>
        <button class="action-tile game" id="games">
          <b>Игровая практика</b>
          <small>закрепить слова в игре</small>
        </button>
      </div>

      <div class="section-label">Настройка уровня</div>
      <button class="btn btn-secondary" id="levelTest">${u.level_test_completed ? "Обновить уровень" : "Пройти тест уровня"}</button>
    </div>`;

  document.getElementById("daily").onclick = () => { haptic(); renderDailyLesson(); };
  document.getElementById("vocab").onclick = () => { haptic(); renderVocabStart(); };
  document.getElementById("training").onclick = () => { haptic(); renderTrainingMenu(); };
  document.getElementById("dictionary").onclick = () => { haptic(); renderDictionary(); };
  document.getElementById("games").onclick = () => { haptic(); renderGamesMenu(); };
  document.getElementById("levelTest").onclick = () => { haptic(); renderLevelTestIntro(); };
}

function renderProgressHub() {
  setBack(renderMenu);
  tg.MainButton.hide();
  app.innerHTML = `
    <div class="screen">
      <h1>Прогресс</h1>
      <div class="card motivation-preview" id="motivationPreview">
        <div class="hint">Собираю достижения...</div>
      </div>

      <div class="hub-grid">
        <button class="action-tile progress" id="motivation">
          <b>Достижения</b>
          <small>серии, бейджи, следующий шаг</small>
        </button>
        <button class="action-tile report" id="report">
          <b>Отчет</b>
          <small>что получается и что повторить</small>
        </button>
        <button class="action-tile history" id="history">
          <b>История занятий</b>
          <small>уроки, слова, тесты</small>
        </button>
        <button class="action-tile leaderboard-tile" id="leaderboard">
          <b>Рейтинг</b>
          <small>место среди учеников</small>
        </button>
      </div>
    </div>`;

  document.getElementById("motivation").onclick = () => { haptic(); renderMotivation(); };
  document.getElementById("report").onclick = () => { haptic(); renderParentReport(); };
  document.getElementById("history").onclick = () => { haptic(); renderActivityHistory(); };
  document.getElementById("leaderboard").onclick = () => { haptic(); renderLeaderboard(); };
  loadMotivationPreview();
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

async function renderVocabStart() {
  setBack(renderLearningHub);
  loading();
  try {
    const data = await api("/api/vocab/start", "POST", {});
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
    renderQuizQuestion(0);
  } catch (e) {
    renderError(e.message);
  }
}

function renderQuizQuestion(index) {
  const q = state.quiz.questions[index];
  if (!q) return finishVocabQuiz();
  const progress = `${index + 1}/${state.quiz.questions.length}`;
  app.innerHTML = `
    <div class="screen">
      <h1>Тест по словам</h1>
      ${wordStudyCard(q, { badge: progress, prompt: q.prompt, compact: true })}
      ${q.options.map(o => `
        <button class="btn btn-secondary answer" data-id="${o.id}">${esc(o.translation)}</button>
      `).join("")}
    </div>`;

  document.querySelectorAll(".answer").forEach(btn => {
    btn.onclick = () => {
      const selectedId = Number(btn.dataset.id);
      state.answers.push({ word_id: q.word_id, selected_id: selectedId });
      document.querySelectorAll(".answer").forEach(item => item.disabled = true);
      btn.classList.remove("btn-secondary");
      btn.classList.add(selectedId === q.word_id ? "btn-correct" : "btn-wrong");
      haptic(selectedId === q.word_id ? "success" : "error");
      setTimeout(() => renderQuizQuestion(index + 1), 650);
    };
  });
  bindPronunciationButtons();
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
        <div class="card">
          <input id="dictionarySearch" type="text" placeholder="Найти слово..." autocomplete="off">
        </div>
        ${words.length ? `
          <div class="card dictionary-list">
            ${words.map(word => `
              <div class="dictionary-row" data-search="${esc(`${word.word} ${word.translation} ${word.transcription || ""}`.toLowerCase())}">
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
      const query = search.value.trim().toLowerCase();
      let visible = 0;
      rows.forEach(row => {
        const matches = !query || row.dataset.search.includes(query);
        row.hidden = !matches;
        if (matches) visible += 1;
      });
      if (empty) empty.style.display = visible ? "none" : "block";
    };
    search.addEventListener("input", applySearch);
    bindPronunciationButtons();
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
      </div>
      <button class="btn" id="choiceTraining">Выбрать перевод</button>
      <button class="btn" id="inputTraining">Написать слово</button>
      <button class="btn btn-secondary" id="trainingHome">К учебе</button>
    </div>`;
  document.getElementById("choiceTraining").onclick = () => { haptic(); renderChoiceTraining(focus); };
  document.getElementById("inputTraining").onclick = () => { haptic(); renderInputTraining(focus); };
  document.getElementById("trainingHome").onclick = () => { haptic(); renderLearningHub(); };
}

async function renderChoiceTraining(focus = "all") {
  setBack(() => renderTrainingMenu(focus));
  loading();
  try {
    const task = await api("/api/training/choice/next", "POST", { focus });
    app.innerHTML = `
      <div class="screen">
        <h1>Выбери перевод</h1>
        ${task.review_empty ? `<div class="card"><p class="hint">Ошибок для повторения пока нет, поэтому даю обычное слово.</p></div>` : ""}
        ${wordStudyCard(task, { compact: true })}
        ${task.options.map(option => `
          <button class="btn btn-secondary choice-answer" data-id="${option.id}">${esc(option.translation)}</button>
        `).join("")}
      </div>`;

    document.querySelectorAll(".choice-answer").forEach(button => {
      button.onclick = async () => {
        const selectedId = Number(button.dataset.id);
        document.querySelectorAll(".choice-answer").forEach(item => item.disabled = true);
        loading();
        try {
          const result = await api("/api/training/choice/answer", "POST", {
            word_id: task.word_id,
            selected_id: selectedId,
          });
          if (state.me?.user) state.me.user.points = result.points;
          renderTrainingResult({
            correct: result.correct,
            title: result.correct ? "Верно!" : "Почти",
            text: `${result.word} — ${result.translation}`,
            pronounceWord: result.word,
            transcription: result.transcription,
            delta: result.delta,
            points: result.points,
            next: () => renderChoiceTraining(focus),
            focus,
          });
        } catch (e) {
          renderError(e.message);
        }
      };
    });
    bindPronunciationButtons();
  } catch (e) {
    renderError(e.message);
  }
}

async function renderInputTraining(focus = "all") {
  setBack(() => renderTrainingMenu(focus));
  loading();
  try {
    const task = await api("/api/training/input/next", "POST", { focus });
    app.innerHTML = `
      <div class="screen">
        <h1>Напиши слово</h1>
        ${task.review_empty ? `<div class="card"><p class="hint">Ошибок для повторения пока нет, поэтому даю обычное слово.</p></div>` : ""}
        <div class="card center">
          <p class="hint">Напиши по-английски:</p>
          <div class="big-sub">${esc(task.translation)}</div>
        </div>
        <input id="inputAnswer" type="text" placeholder="English word" autocomplete="off">
        <button class="btn" id="checkInputAnswer">Проверить</button>
      </div>`;

    const input = document.getElementById("inputAnswer");
    const submit = async () => {
      const answer = input.value.trim();
      if (!answer) return tg.showAlert("Напиши слово");
      loading();
      try {
        const result = await api("/api/training/input/answer", "POST", {
          word_id: task.word_id,
          answer,
        });
        if (state.me?.user) state.me.user.points = result.points;
        renderTrainingResult({
          correct: result.correct,
          title: result.correct ? "Верно!" : "Запомни правильный вариант",
          text: `${result.translation} — ${result.word}`,
          pronounceWord: result.word,
          transcription: result.transcription,
          delta: result.delta,
          points: result.points,
          next: () => renderInputTraining(focus),
          focus,
        });
      } catch (e) {
        renderError(e.message);
      }
    };
    document.getElementById("checkInputAnswer").onclick = submit;
    input.addEventListener("keypress", e => { if (e.key === "Enter") submit(); });
    input.focus();
  } catch (e) {
    renderError(e.message);
  }
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
      ${wordStudyCard(q, { badge: `Шаг 2 из 4 · ${index + 1}/${state.dailyQuiz.questions.length}`, prompt: "Выбери перевод", compact: true })}
      ${q.options.map(o => `
        <button class="btn btn-secondary daily-answer" data-id="${o.id}">${esc(o.translation)}</button>
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

async function renderChat() {
  loading();
  try {
    const data = await api("/api/chat/history", "GET");
    app.innerHTML = `
      <div class="screen chat-wrap">
        <div class="chat-topbar">
          <h2 style="margin:0">Репетитор</h2>
          <button class="chat-reset" id="reset">Очистить</button>
        </div>
        <div class="chat-meta">Сообщений сегодня: ${data.usage?.used_today ?? 0} · без лимита</div>
        <div class="tutor-stage">
          <div class="tutor-face idle" id="tutorFace" aria-hidden="true">
            <div class="face-hair"></div>
            <div class="face-eye left"></div>
            <div class="face-eye right"></div>
            <div class="face-cheek left"></div>
            <div class="face-cheek right"></div>
            <div class="face-mouth"></div>
          </div>
          <div class="voice-mode-panel">
            <button class="voice-mode-toggle" id="voiceMode" type="button">
              <span class="voice-mode-dot"></span>
              <span id="voiceModeText">Говорить</span>
            </button>
            <div class="voice-mode-status" id="voiceStatus">Обычный режим</div>
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
    const face = document.getElementById("tutorFace");
    const mic = document.getElementById("mic");
    const sendButton = document.getElementById("send");
    const voiceModeButton = document.getElementById("voiceMode");
    const voiceModeText = document.getElementById("voiceModeText");
    const voiceStatus = document.getElementById("voiceStatus");
    let recorder = null;
    let audioChunks = [];
    let recordingStream = null;
    let sending = false;
    let discardRecording = false;
    let tutorAudio = null;
    let tutorAudioUrl = "";
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
    const realtimeLogged = new Set();
    const realtimeResponseText = new Map();

    const VOICE_VOLUME_THRESHOLD = 0.008;
    const VOICE_SILENCE_MS = 950;
    const VOICE_MIN_RECORDING_MS = 650;
    const VOICE_NO_SPEECH_MS = 5200;
    const VOICE_MAX_RECORDING_MS = 18000;
    const VOICE_RESTART_DELAY_MS = 450;
    const VOICE_TTS_TIMEOUT_MS = 25000;
    const CHAT_TTS_TIMEOUT_MS = 7000;
    const REALTIME_FIRST_AUDIO_TIMEOUT_MS = 7000;
    const STABLE_VOICE_COOLDOWN_MS = 10 * 60 * 1000;
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
    }

    function hasLessonHistory() {
      return Boolean(box.querySelector(".bubble"));
    }

    function setFace(mode) {
      face.className = `tutor-face ${mode}`;
    }

    function typingBubble() {
      const div = document.createElement("div");
      div.className = "typing";
      div.textContent = "...";
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
      return div;
    }

    function updateVoiceModeUi(status = "") {
      voiceModeButton.classList.toggle("active", voiceModeActive);
      voiceModeText.textContent = voiceModeActive ? "Стоп" : "Говорить";
      voiceStatus.textContent = status || (voiceModeActive ? "Слушаю..." : "Обычный режим");
      if (!sending) mic.disabled = voiceModeActive;
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
        sendRealtimeEvent({
          type: "response.create",
          response: {
            instructions: "Ответь на последнюю реплику ребенка сразу. Сначала по смыслу, затем маленький учебный шаг: одно английское слово, короткая фраза или мягкое исправление. Один вопрос максимум.",
          },
        });
      }, delayMs);
    }

    function waitForIceGatheringComplete(pc, timeoutMs = 5000) {
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
      realtimeStream?.getAudioTracks().forEach(track => {
        if (track.readyState === "live") track.enabled = enabled;
      });
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
      setRealtimeMicEnabled(!active);
      updateVoiceModeUi(active ? "Говорю..." : "Слушаю...");
      setFace(active ? "speaking" : "listening");
    }

    function estimateRealtimeSpeechMs(text) {
      const clean = String(text || "").trim();
      if (!clean) return 5000;
      const words = clean.split(/\s+/).filter(Boolean).length;
      const byWords = words * 760;
      const byChars = clean.length * 95;
      return Math.min(26000, Math.max(3500, Math.max(byWords, byChars)));
    }

    function scheduleRealtimeMicResume(delayMs = 800) {
      const resumeAt = Date.now() + delayMs;
      if (realtimeMicResumeTimer && realtimeMicResumeAt >= resumeAt) return;
      realtimeMicResumeAt = resumeAt;
      if (realtimeMicResumeTimer) clearTimeout(realtimeMicResumeTimer);
      realtimeMicResumeTimer = setTimeout(() => {
        realtimeMicResumeTimer = null;
        realtimeMicResumeAt = 0;
        setRealtimeAssistantSpeaking(false);
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
        await api("/api/realtime/log", "POST", { role, content: clean });
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
        updateVoiceModeUi("Слушаю...");
        setFace("listening");
        return;
      }
      if (type === "input_audio_buffer.speech_started") {
        if (realtimeAssistantSpeaking) return;
        updateVoiceModeUi("Слушаю...");
        setFace("listening");
        return;
      }
      if (type === "input_audio_buffer.speech_stopped") {
        realtimeAwaitingResponse = true;
        updateVoiceModeUi("Думаю...");
        setFace("thinking");
        armRealtimeResponseTimer();
        armRealtimeResponseNudge(1400);
        return;
      }
      if (type === "conversation.item.input_audio_transcription.completed") {
        const text = String(event.transcript || event.text || "").trim();
        realtimeLastUserText = text;
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
          logRealtimeMessage("assistant", text, key);
        }
        scheduleRealtimeMicResume(900);
        return;
      }
      if (type === "response.created") {
        realtimeAwaitingResponse = false;
        clearRealtimeResponseNudgeTimer();
        setRealtimeAssistantSpeaking(true);
        updateVoiceModeUi("Отвечаю...");
        setFace("thinking");
        return;
      }
      if (
        type === "response.output_audio.delta" ||
        type === "response.audio.delta" ||
        type === "response.content_part.added"
      ) {
        setRealtimeAssistantSpeaking(true);
        return;
      }
      if (type === "response.output_audio.done" || type === "response.audio.done") {
        scheduleRealtimeMicResume(700);
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
          logRealtimeMessage("assistant", text, key);
        }
        scheduleRealtimeMicResume(900);
        return;
      }
      if (type === "error") {
        const message = event.error?.message || "Ошибка живого голоса";
        console.error("Realtime voice error:", message);
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

    function stopTutorSpeech() {
      window.speechSynthesis?.cancel?.();
      if (tutorAudio) {
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

    function finishTutorSpeech(onDone) {
      setFace("idle");
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
      if (!("speechSynthesis" in window)) {
        setFace("speaking");
        setTimeout(() => finishTutorSpeech(onDone), 1400);
        return;
      }
      try {
        window.speechSynthesis.cancel();
        const segments = speechSegments(text);
        let index = 0;
        const speakNext = () => {
          const segment = segments[index];
          if (!segment) {
            finishTutorSpeech(onDone);
            return;
          }
          const utterance = new SpeechSynthesisUtterance(segment.text);
          utterance.lang = segment.lang;
          utterance.rate = segment.lang === "en-US" ? 0.88 : 0.95;
          utterance.pitch = 1.05;
          utterance.onstart = () => setFace("speaking");
          utterance.onend = () => {
            index += 1;
            speakNext();
          };
          utterance.onerror = () => finishTutorSpeech(onDone);
          window.speechSynthesis.speak(utterance);
        };
        speakNext();
      } catch (_) {
        finishTutorSpeech(onDone);
      }
    }

    async function speakTutor(text, onDone = null, voice = false) {
      if (isAssistantError(text)) {
        finishTutorSpeech(onDone);
        return;
      }
      stopTutorSpeech();
      setFace("thinking");
      if (voice) updateVoiceModeUi("Озвучиваю...");
      try {
        const audioBlob = await apiBlob(
          "/api/audio/speech",
          { text, mode: voice ? "voice" : "chat" },
          voice ? VOICE_TTS_TIMEOUT_MS : CHAT_TTS_TIMEOUT_MS,
        );
        await playTutorAudioBlob(audioBlob, text, onDone);
      } catch (_) {
        stopTutorSpeech();
        speakTutorFallback(text, onDone);
      }
    }

    async function playTutorAudioBlob(audioBlob, text, onDone = null) {
      stopTutorSpeech();
      tutorAudioUrl = URL.createObjectURL(audioBlob);
      tutorAudio = new Audio(tutorAudioUrl);
      tutorAudio.preload = "auto";
      tutorAudio.onplaying = () => setFace("speaking");
      tutorAudio.onended = () => {
        stopTutorSpeech();
        finishTutorSpeech(onDone);
      };
      tutorAudio.onerror = () => {
        stopTutorSpeech();
        speakTutorFallback(text, onDone);
      };
      try {
        await tutorAudio.play();
      } catch (_) {
        stopTutorSpeech();
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
          updateVoiceModeUi("Говори...");
        }
        if (heardVoice && now - lastVoiceAt > VOICE_SILENCE_MS && now - recordingStartedAt > VOICE_MIN_RECORDING_MS) {
          stopRecording();
          return;
        }
        if (!heardVoice && now - recordingStartedAt > 2800) {
          updateVoiceModeUi("Я слушаю. Можно по-русски...");
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
        speakTutor(
          reply.reply,
          options.autoContinue ? () => scheduleVoiceListen(650) : null,
          Boolean(options.voice),
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
      if (showUser && text) bubble("user", text);
      if (reply) bubble("assistant", reply);
      const onDone = wasAuto ? () => scheduleVoiceListen(VOICE_RESTART_DELAY_MS) : null;
      if (result.audio_base64) {
        const audioBlob = base64ToBlob(result.audio_base64, result.audio_content_type || "audio/mpeg");
        updateVoiceModeUi("Говорю...");
        await playTutorAudioBlob(audioBlob, reply, onDone);
      } else if (reply) {
        await speakTutor(reply, onDone, true);
      } else if (wasAuto) {
        scheduleVoiceListen(900);
      }
    }

    function scheduleVoiceListen(delay = 500) {
      clearVoiceModeTimer();
      if (!voiceModeActive) return;
      updateVoiceModeUi("Слушаю...");
      voiceModeTimer = setTimeout(() => {
        if (!voiceModeActive || sending) return;
        if (recorder && recorder.state === "recording") return;
        startRecording(true).catch(error => {
          bubble("assistant", `Не удалось начать запись: ${error.message}`);
          voiceModeActive = false;
          updateVoiceModeUi();
          setFace("idle");
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
          updateVoiceModeUi("Скажи чуть дольше");
          if (!wasAuto && !shortVoiceHintShown) {
            shortVoiceHintShown = true;
            bubble("assistant", "Я не успел расслышать. Нажми микрофон и скажи фразу чуть дольше.");
          }
          setFace("idle");
          if (wasAuto) scheduleVoiceListen(700);
          return;
        }
        missedAutoRecordings = 0;
        await sendStableVoiceTurn(blob, wasAuto);
      } catch (e) {
        if (!wasAuto) tg.showAlert(e.message);
        else {
          updateVoiceModeUi("Ошибка голоса");
          bubble("assistant", `Ошибка голоса: ${e.message}`);
        }
        setFace("idle");
        if (wasAuto) scheduleVoiceListen(1500);
      } finally {
        sending = false;
        mic.disabled = voiceModeActive;
        if (!sending) sendButton.disabled = false;
      }
    }

    async function startRecording(auto = false) {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        const message = "Голосовой ввод не поддерживается на этом устройстве";
        if (auto) bubble("assistant", message);
        else tg.showAlert(message);
        if (auto) {
          voiceModeActive = false;
          updateVoiceModeUi();
        }
        return;
      }
      if (recorder && recorder.state === "recording") return;
      try {
        audioChunks = [];
        skipUploadOnStop = false;
        autoRecording = auto;
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
          updateVoiceModeUi("Слушаю...");
          startSilenceMonitor(recordingStream);
        }
        haptic();
      } catch (e) {
        stopTracks();
        const message = `Не удалось включить микрофон: ${e.message}`;
        if (auto) bubble("assistant", message);
        else tg.showAlert(message);
        if (auto) {
          voiceModeActive = false;
          updateVoiceModeUi();
        }
        setFace("idle");
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
      if (sending || voiceModeActive) return;
      if (recorder && recorder.state === "recording") stopRecording();
      else startRecording();
    }

    async function startLegacyVoiceMode() {
      if (voiceModeActive || sending) return;
      stopTutorSpeech();
      clearVoiceModeTimer();
      voiceModeActive = true;
      missedAutoRecordings = 0;
      updateVoiceModeUi("Готовлюсь...");
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
      updateVoiceModeUi("Подключаю живой голос...");
      setFace("thinking");
      haptic();

      realtimePc = new RTCPeerConnection();
      realtimeAudio = document.createElement("audio");
      realtimeAudio.autoplay = true;
      realtimeAudio.playsInline = true;
      realtimeAudio.onplaying = () => {
        setRealtimeAssistantSpeaking(true);
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

      realtimeDataChannel = realtimePc.createDataChannel("oai-events");
      realtimeDataChannel.onmessage = handleRealtimeEvent;
      realtimeDataChannel.onopen = () => {
        updateVoiceModeUi("Слушаю...");
        setFace("listening");
        const ageGroup = state.me?.user?.age_group || "default";
        const childName = state.me?.user?.child_name || "друг";
        const continueCurrentLesson = hasLessonHistory();
        const ageGreetings = {
          "5_7": `Поздоровайся с ${childName} по-русски, очень медленно и тепло. Сразу начни суперлегкий английский мини-урок: дай один выбор с двумя словами, например cat — кошка или dog — собака. Один вопрос.`,
          "8_10": `Поздоровайся с ${childName} по-русски, дружелюбно и не быстро. Сразу начни мини-урок английского: дай одну короткую фразу или выбор из двух тем, например game или food. Один вопрос.`,
          "11_13": `Поздоровайся с ${childName} естественно и по-дружески. Сразу начни короткую английскую практику: одна полезная фраза и один вопрос про день, хобби или школу.`,
          "14_18": `Поздоровайся с ${childName} естественно и тепло. Сразу начни устную практику английского: дай один короткий English starter и один интересный вопрос про день, учебу или интересы.`,
          "under_12": `Поздоровайся с ${childName} по-русски, дружелюбно и не быстро. Сразу начни мини-урок английского: дай одну короткую фразу или выбор из двух тем. Один вопрос.`,
          "default": `Начни по-русски: поздоровайся с ${childName} тепло, затем сразу дай маленький английский шаг и один легкий вопрос.`,
        };
        const greeting = continueCurrentLesson
          ? `Не здоровайся заново и не начинай новую тему. Коротко продолжи текущий урок с ${childName} по последней теме из истории. Дай один маленький учебный шаг и один вопрос.`
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
          updateVoiceModeUi("Включаю запасной режим...");
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
      updateVoiceModeUi("Обычный режим");
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

    mic.onclick = toggleRecording;
    voiceModeButton.onclick = toggleVoiceMode;
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

function motivationBadgeHtml(badge) {
  const progress = Math.max(0, Math.min(100, Number(badge.progress_percent) || 0));
  return `
    <div class="badge-card ${badge.unlocked ? "unlocked" : ""}">
      <div class="badge-mark">${badge.unlocked ? "✓" : progress + "%"}</div>
      <div class="badge-main">
        <b>${esc(badge.title)}</b>
        <p>${esc(badge.text)}</p>
        <div class="mini-progress"><span style="width:${progress}%"></span></div>
        <small>${Number(badge.value) || 0}/${Number(badge.target) || 0}</small>
      </div>
    </div>`;
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
    app.innerHTML = `
      <div class="screen">
        <h1>${esc(data.title || "Достижения")}</h1>
        <div class="card motivation-hero">
          <div>
            <span class="daily-badge">Серия занятий</span>
            <h2>${streak.current || 0} дней подряд</h2>
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
        </div>
        <div class="badge-grid">
          ${badges.map(motivationBadgeHtml).join("")}
        </div>
        <button class="btn btn-secondary mt-12" id="motivationHome">К прогрессу</button>
      </div>`;
    document.getElementById("motivationHome").onclick = () => { haptic(); renderProgressHub(); };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderParentReport() {
  setBack(renderProgressHub);
  loading();
  try {
    const data = await api("/api/parent/report", "GET");
    const r = data.report;
    const d = data.dictionary || {};
    const recommendations = data.recommendations || [];
    const problemWords = data.problem_words || [];
    app.innerHTML = `
      <div class="screen">
        <h1>Отчет для родителя</h1>
        <div class="card">
          <h2>${esc(data.child.name)}</h2>
          <p class="hint">${esc(data.child.age_label)} · ${esc(data.child.goal_label)} · ${esc(data.child.level_label || "Beginner / A1")}</p>
        </div>
        <div class="card">
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

function formatEventDate(value) {
  if (!value) return "";
  try {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleDateString("ru-RU", { day: "2-digit", month: "short" });
  } catch (_) {
    return value;
  }
}

async function renderActivityHistory() {
  setBack(renderProgressHub);
  loading();
  try {
    const data = await api("/api/activity/history", "GET");
    const events = data.events || [];
    app.innerHTML = `
      <div class="screen">
        <h1>История занятий</h1>
        <div class="card">
          <div class="stat-row"><span>Записей</span><b>${data.summary?.total_events || 0}</b></div>
          <div class="stat-row"><span>Завершено</span><b>${data.summary?.completed_events || 0}</b></div>
        </div>
        ${events.length ? `
          <div class="activity-list">
            ${events.map(event => `
              <div class="card activity-card ${event.completed ? "done" : "open"}">
                <div class="activity-head">
                  <div>
                    <b>${esc(event.title)}</b>
                    <span>${esc(formatEventDate(event.event_at || event.date))}</span>
                  </div>
                  ${event.score === null || event.score === undefined ? "" : `<strong>${event.score}%</strong>`}
                </div>
                <p class="hint mt-8">${esc(event.description)}</p>
                <div class="activity-meta">
                  ${event.word_count ? `<span>${event.word_count} слов</span>` : ""}
                  ${event.points_delta ? `<span>${event.points_delta > 0 ? "+" : ""}${event.points_delta} 💎</span>` : ""}
                  ${event.completed_steps && event.total_steps ? `<span>${event.completed_steps}/${event.total_steps} шагов</span>` : ""}
                </div>
              </div>
            `).join("")}
          </div>
        ` : `
          <div class="card center">
            <b>История пока пустая</b>
            <p class="hint">Пройди ежедневный урок или тест по словам, и здесь появятся первые записи.</p>
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
    app.innerHTML = `
      <div class="screen">
        <h1>Рейтинг</h1>
        <div class="card leaderboard">
          ${(data.leaders || []).length ? data.leaders.map(leader => `
            <div class="leader-row ${leader.is_me ? "me" : ""}">
              <div class="leader-rank">${leader.rank}</div>
              <div class="leader-main">
                <b>${esc(leader.name)}</b>
                <span>${esc(leader.age_label)}</span>
              </div>
              <div class="leader-points">${leader.points} 💎</div>
            </div>
          `).join("") : `<p class="hint center">Рейтинг появится после первых тренировок.</p>`}
        </div>
        <button class="btn btn-secondary" id="leaderboardHome">К прогрессу</button>
      </div>`;
    document.getElementById("leaderboardHome").onclick = () => { haptic(); renderProgressHub(); };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderProfile() {
  setBack(renderMenu);
  loading();
  try {
    state.me = await api("/api/me", "GET");
    const u = state.me.user;
    app.innerHTML = `
      <div class="screen">
        <h1>Профиль</h1>
        <div class="card center">
          <h2>${esc(u.child_name)}</h2>
          <p class="hint">${esc(u.age_label)} · ${esc(u.goal_label)}</p>
          <div class="big" style="color: var(--button)">${u.points} 💎</div>
        </div>
        <div class="card">
          <div class="stat-row"><span>Родитель</span><b>${esc(u.parent_name || "-")}</b></div>
          <div class="stat-row"><span>Возраст</span><b>${u.child_age || "-"}</b></div>
          <div class="stat-row"><span>Уровень</span><b>${esc(u.level_label || "Beginner / A1")}</b></div>
          <div class="stat-row"><span>Тест уровня</span><b>${u.level_test_completed ? `${u.level_test_score}%` : "не пройден"}</b></div>
        </div>
        <div class="card">
          <h2>Аккаунт и данные</h2>
          <p class="hint">Сброс результатов обнулит баллы, уровень, выученные слова, тесты и ежедневные уроки. Профиль и чат с репетитором останутся.</p>
          <button class="btn btn-danger" id="resetResults">Обнулить результаты</button>
          <button class="btn btn-secondary" id="logout">Выйти из аккаунта</button>
        </div>
        <button class="btn btn-secondary" id="profileHome">В меню</button>
      </div>`;
    document.getElementById("resetResults").onclick = async () => {
      haptic("warning");
      const ok = await confirmAction("Обнулить все учебные результаты? Баллы, уровень, тесты и прогресс слов начнутся заново.");
      if (!ok) return;
      try {
        const result = await api("/api/results/reset", "POST", { confirm: "reset_results" });
        state.me.user.points = result.user.points;
        state.me.stats = result.stats;
        tg.showAlert("Результаты обнулены. Можно начать обучение заново.");
        renderProfile();
      } catch (e) {
        renderError(e.message);
      }
    };
    document.getElementById("logout").onclick = async () => {
      haptic("warning");
      const ok = await confirmAction("Выйти из аккаунта на этом устройстве? Для другого аккаунта переключитесь в Telegram и откройте приложение снова.");
      if (ok) logoutFromApp();
    };
    document.getElementById("profileHome").onclick = () => { haptic(); renderMenu(); };
  } catch (e) {
    renderError(e.message);
  }
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
    if (state.me.registered) renderMenu();
    else renderRegistration();
  } catch (e) {
    renderError(e.message);
  }
}

start();
