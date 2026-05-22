// ============================================================
// Mini App: SPA на vanilla JS — слова, тренировка, профиль, ИИ-репетитор
// ============================================================

const tg = window.Telegram.WebApp;
tg.ready();
tg.expand();

const app = document.getElementById("app");
const state = { me: null, _back: null };

// ---------- HTTP ----------

async function api(path, method = "POST", body = null) {
  const res = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Telegram-Init-Data": tg.initData || "",
    },
    body: method === "GET" ? undefined : JSON.stringify(body || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

// ---------- BackButton ----------

function setBack(handler) {
  if (state._back) tg.BackButton.offClick(state._back);
  state._back = handler || null;
  if (handler) {
    tg.BackButton.onClick(handler);
    tg.BackButton.show();
  } else {
    tg.BackButton.hide();
  }
}

// ---------- Утилиты ----------

function esc(s) {
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function haptic(type) {
  try {
    if (["success", "error", "warning"].includes(type)) {
      tg.HapticFeedback?.notificationOccurred(type);
    } else {
      tg.HapticFeedback?.impactOccurred(type || "light");
    }
  } catch (_) {}
}

function showLoading() {
  app.innerHTML = `<div class="screen card center">Загрузка…</div>`;
}

// ============================================================
// Экраны
// ============================================================

function renderError(msg) {
  setBack(null);
  app.innerHTML = `
    <div class="screen">
      <div class="error-box"><b>😕 Что-то пошло не так</b><div class="mt-8">${esc(msg)}</div></div>
      <button class="btn mt-12" onclick="location.reload()">Перезагрузить</button>
    </div>`;
}

// ---------- Регистрация ----------

function renderRegistration() {
  setBack(null);
  tg.MainButton.hide();

  const firstName = state.me.tg_user.first_name || "";
  const ageOpts = state.me.age_groups.map(g => `
    <button class="btn btn-secondary age" data-age="${esc(g.value)}">${esc(g.label)}</button>
  `).join("");

  app.innerHTML = `
    <div class="screen">
      <h1>👋 Привет!</h1>
      <p class="hint">Я помогу учить английский. Давай знакомиться.</p>
      <div class="card mt-24">
        <h2>Как тебя зовут?</h2>
        <input id="name" type="text" placeholder="Имя" value="${esc(firstName)}" maxlength="30" autocomplete="off">
      </div>
      <div class="card">
        <h2>Возрастная группа</h2>
        <div id="ages">${ageOpts}</div>
      </div>
    </div>`;

  let selectedAge = null;

  function refreshMain() {
    const name = document.getElementById("name").value.trim();
    if (name.length >= 2 && selectedAge) {
      tg.MainButton.setText("Завершить регистрацию");
      tg.MainButton.onClick(submit);
      tg.MainButton.show();
    } else {
      tg.MainButton.hide();
      tg.MainButton.offClick(submit);
    }
  }

  document.getElementById("name").addEventListener("input", refreshMain);
  document.querySelectorAll(".age").forEach(btn => {
    btn.addEventListener("click", () => {
      selectedAge = btn.dataset.age;
      document.querySelectorAll(".age").forEach(b => { if (b !== btn) b.classList.add("btn-secondary"); });
      btn.classList.remove("btn-secondary");
      haptic("light");
      refreshMain();
    });
  });

  async function submit() {
    const name = document.getElementById("name").value.trim();
    if (name.length < 2) return tg.showAlert("Имя слишком короткое");
    if (!selectedAge) return tg.showAlert("Выбери возрастную группу");
    tg.MainButton.showProgress();
    try {
      await api("/api/register", "POST", { name, age_group: selectedAge });
      state.me = await api("/api/me", "GET");
      tg.MainButton.offClick(submit);
      tg.MainButton.hide();
      haptic("success");
      renderMenu();
    } catch (e) {
      tg.MainButton.hideProgress();
      tg.showAlert(e.message);
    }
  }
}

// ---------- Главное меню ----------

function renderMenu() {
  setBack(null);
  tg.MainButton.hide();

  const u = state.me.user;
  app.innerHTML = `
    <div class="screen">
      <h1>📚 Главное меню</h1>
      <div class="card">
        <div>Привет, <b>${esc(u.name)}</b>!</div>
        <div class="mt-12">Баллы: <span class="points-pill">${u.points} 💎</span></div>
      </div>
      <button class="btn" id="chat">💬 Поговорить с репетитором</button>
      <button class="btn" id="learn">📖 Учить слова</button>
      <button class="btn" id="train">🎯 Тренировка</button>
      <button class="btn btn-secondary" id="profile">📊 Профиль</button>
    </div>`;

  document.getElementById("chat").onclick    = () => { haptic(); renderChat(); };
  document.getElementById("learn").onclick   = () => { haptic(); renderLearn(); };
  document.getElementById("train").onclick   = () => { haptic(); renderTrainingMenu(); };
  document.getElementById("profile").onclick = () => { haptic(); renderProfile(); };
}

// ---------- ИИ-репетитор (чат) ----------

async function renderChat() {
  setBack(renderMenu);
  tg.MainButton.hide();
  showLoading();

  let history = [];
  try {
    const data = await api("/api/chat/history", "GET");
    history = data.messages || [];
  } catch (e) {
    return renderError(e.message);
  }

  app.innerHTML = `
    <div class="screen chat-wrap">
      <div class="chat-topbar">
        <h2 style="margin:0">💬 Репетитор</h2>
        <button class="chat-reset" id="reset">Очистить</button>
      </div>
      <div class="chat-messages" id="messages"></div>
      <div class="chat-input-row">
        <input id="msg" type="text" placeholder="Напиши на английском…" autocomplete="off">
        <button class="chat-send" id="send">➤</button>
      </div>
    </div>`;

  const box = document.getElementById("messages");
  const input = document.getElementById("msg");
  const sendBtn = document.getElementById("send");

  function addBubble(role, text) {
    const div = document.createElement("div");
    div.className = "bubble " + (role === "user" ? "user" : "bot");
    div.textContent = text;
    box.appendChild(div);
    box.scrollTop = box.scrollHeight;
    return div;
  }

  if (history.length === 0) {
    box.innerHTML = `<div class="chat-empty">Напиши первое сообщение по-английски —<br>репетитор ответит и поможет.</div>`;
  } else {
    history.forEach(m => addBubble(m.role, m.content));
  }

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    input.value = "";
    if (box.querySelector(".chat-empty")) box.innerHTML = "";

    addBubble("user", text);
    sendBtn.disabled = true;
    input.disabled = true;

    const typing = document.createElement("div");
    typing.className = "typing";
    typing.textContent = "репетитор печатает…";
    box.appendChild(typing);
    box.scrollTop = box.scrollHeight;

    try {
      const data = await api("/api/chat/send", "POST", { message: text });
      typing.remove();
      addBubble("assistant", data.reply);
      haptic("light");
    } catch (e) {
      typing.remove();
      addBubble("assistant", "⚠️ " + e.message);
    } finally {
      sendBtn.disabled = false;
      input.disabled = false;
      input.focus();
    }
  }

  sendBtn.onclick = send;
  input.addEventListener("keypress", e => { if (e.key === "Enter") send(); });

  document.getElementById("reset").onclick = async () => {
    tg.showConfirm("Очистить историю разговора?", async (ok) => {
      if (!ok) return;
      try {
        await api("/api/chat/reset", "POST");
        box.innerHTML = `<div class="chat-empty">История очищена. Начни заново!</div>`;
      } catch (e) { tg.showAlert(e.message); }
    });
  };
}

// ---------- Изучение слов ----------

async function renderLearn(currentId = null) {
  setBack(renderMenu);
  tg.MainButton.hide();
  showLoading();
  try {
    const w = await api("/api/learn/next", "POST", { current_id: currentId });
    app.innerHTML = `
      <div class="screen">
        <h1>📖 Учить слова</h1>
        <div class="card center">
          <div class="big">${esc(w.word)}</div>
          <div class="big-sub">${esc(w.translation)}</div>
          ${w.example ? `<p class="hint mt-24"><i>${esc(w.example)}</i></p>` : ""}
        </div>
        <button class="btn" id="next">➡️ Следующее слово</button>
      </div>`;
    document.getElementById("next").onclick = () => { haptic(); renderLearn(w.id); };
  } catch (e) { renderError(e.message); }
}

// ---------- Тренировка ----------

function renderTrainingMenu() {
  setBack(renderMenu);
  tg.MainButton.hide();
  app.innerHTML = `
    <div class="screen">
      <h1>🎯 Тренировка</h1>
      <p class="hint">Выбери режим:</p>
      <button class="btn" id="choice">✅ Выбор перевода</button>
      <button class="btn" id="input">⌨️ Ввод слова</button>
    </div>`;
  document.getElementById("choice").onclick = () => { haptic(); renderChoice(); };
  document.getElementById("input").onclick  = () => { haptic(); renderInput(); };
}

async function renderChoice() {
  setBack(renderTrainingMenu);
  showLoading();
  try {
    const q = await api("/api/training/choice/next", "POST");
    const optsHtml = q.options.map(o => `
      <button class="btn btn-secondary opt" data-id="${o.id}">${esc(o.translation)}</button>
    `).join("");
    app.innerHTML = `
      <div class="screen">
        <h1>Выбери перевод</h1>
        <div class="card center"><div class="big">${esc(q.word)}</div></div>
        <div id="opts">${optsHtml}</div>
      </div>`;
    document.querySelectorAll(".opt").forEach(btn => {
      btn.addEventListener("click", async () => {
        document.querySelectorAll(".opt").forEach(b => b.disabled = true);
        const selectedId = parseInt(btn.dataset.id, 10);
        try {
          const r = await api("/api/training/choice/answer", "POST", { word_id: q.word_id, selected_id: selectedId });
          state.me.user.points = r.points;
          btn.classList.remove("btn-secondary");
          btn.classList.add(r.correct ? "btn-correct" : "btn-wrong");
          if (!r.correct) {
            const cb = document.querySelector(`.opt[data-id="${q.word_id}"]`);
            if (cb) { cb.classList.remove("btn-secondary"); cb.classList.add("btn-correct"); }
          }
          haptic(r.correct ? "success" : "error");
          setTimeout(renderChoice, 1100);
        } catch (e) { renderError(e.message); }
      });
    });
  } catch (e) { renderError(e.message); }
}

async function renderInput() {
  setBack(renderTrainingMenu);
  showLoading();
  try {
    const q = await api("/api/training/input/next", "POST");
    app.innerHTML = `
      <div class="screen">
        <h1>Введи слово</h1>
        <div class="card center">
          <div class="big">${esc(q.translation)}</div>
          <p class="hint mt-8">по-английски</p>
        </div>
        <input id="answer" type="text" placeholder="Ваш ответ…" autocomplete="off" autocapitalize="none" spellcheck="false">
        <button class="btn" id="submit">Проверить</button>
      </div>`;
    const inp = document.getElementById("answer");
    inp.focus();
    const submit = async () => {
      const ans = inp.value.trim();
      if (!ans) return;
      try {
        const r = await api("/api/training/input/answer", "POST", { word_id: q.word_id, answer: ans });
        state.me.user.points = r.points;
        haptic(r.correct ? "success" : "error");
        renderInputResult(r, ans);
      } catch (e) { renderError(e.message); }
    };
    document.getElementById("submit").onclick = submit;
    inp.addEventListener("keypress", e => { if (e.key === "Enter") submit(); });
  } catch (e) { renderError(e.message); }
}

function renderInputResult(r, userAnswer) {
  const html = r.correct
    ? `<div class="result-card correct center">
         <div class="big" style="color:#fff">✅ Правильно!</div>
         <p>${esc(r.word)} — ${esc(r.translation)}</p>
         <p><b>+${r.delta} 💎</b> · всего: ${r.points}</p></div>`
    : `<div class="result-card wrong center">
         <div class="big" style="color:#fff">❌ Неверно</div>
         <p>Твой ответ: <code>${esc(userAnswer)}</code></p>
         <p>Правильно: <b>${esc(r.word)}</b> — ${esc(r.translation)}</p>
         <p><b>${r.delta} 💎</b> · всего: ${r.points}</p></div>`;
  app.innerHTML = `
    <div class="screen">
      <h1>Введи слово</h1>
      ${html}
      <button class="btn" id="next">➡️ Следующее</button>
    </div>`;
  document.getElementById("next").onclick = () => { haptic(); renderInput(); };
}

// ---------- Профиль ----------

async function renderProfile() {
  setBack(renderMenu);
  showLoading();
  try {
    state.me = await api("/api/me", "GET");
    const u = state.me.user, s = state.me.stats;
    app.innerHTML = `
      <div class="screen">
        <h1>📊 Профиль</h1>
        <div class="card center">
          <h2 style="margin:0">${esc(u.name)}</h2>
          <p class="hint" style="margin:4px 0 16px">${esc(u.age_label)}</p>
          <div class="big" style="color: var(--button)">${u.points} 💎</div>
        </div>
        <div class="card">
          <div class="stat-row"><span>📚 Слов в обучении</span><b>${s.words_learned}</b></div>
          <div class="stat-row"><span>✅ Правильных ответов</span><b>${s.total_correct}</b></div>
          <div class="stat-row"><span>❌ Ошибок</span><b>${s.total_wrong}</b></div>
        </div>
      </div>`;
  } catch (e) { renderError(e.message); }
}

// ============================================================
// Старт
// ============================================================

async function start() {
  if (!tg.initData) {
    renderError("Откройте приложение через бота в Telegram.");
    return;
  }
  try {
    state.me = await api("/api/me", "GET");
    if (state.me.registered) renderMenu();
    else renderRegistration();
  } catch (e) { renderError(e.message); }
}

start();
