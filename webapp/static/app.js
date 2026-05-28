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
const state = { me: null, back: null, vocab: null, quiz: null, answers: [] };

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

async function apiForm(path, formData) {
  const res = await fetch(path, {
    method: "POST",
    headers: {
      "X-Telegram-Init-Data": tg.initData || "",
    },
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `HTTP ${res.status}`);
  }
  return res.json();
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function haptic(type = "light") {
  try {
    if (["success", "error", "warning"].includes(type)) tg.HapticFeedback?.notificationOccurred(type);
    else tg.HapticFeedback?.impactOccurred(type);
  } catch (_) {}
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

  document.querySelectorAll(".age").forEach(btn => {
    btn.onclick = () => choose(".age", btn, value => { ageGroup = value; });
  });
  document.querySelectorAll(".goal").forEach(btn => {
    btn.onclick = () => choose(".goal", btn, value => { goal = value; });
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
      renderMenu();
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
    <div class="screen">
      <h1>Привет, ${esc(u.child_name)}!</h1>
      <div class="card">
        <div><b>${esc(u.age_label)}</b> · ${esc(u.goal_label || "английский")}</div>
        <div class="mt-12">Баллы: <span class="points-pill">${u.points} 💎</span></div>
      </div>

      <button class="btn" id="vocab">Новые слова + тест</button>
      <button class="btn" id="daily">Ежедневный урок</button>
      <button class="btn" id="chat">Поговорить с репетитором</button>
      <button class="btn btn-secondary" id="report">Отчет для родителя</button>
      <button class="btn btn-secondary" id="profile">Профиль</button>
    </div>`;

  document.getElementById("vocab").onclick = () => { haptic(); renderVocabStart(); };
  document.getElementById("daily").onclick = () => { haptic(); renderDailyLesson(); };
  document.getElementById("chat").onclick = () => { haptic(); renderChat(); };
  document.getElementById("report").onclick = () => { haptic(); renderParentReport(); };
  document.getElementById("profile").onclick = () => { haptic(); renderProfile(); };
}

async function renderVocabStart() {
  setBack(renderMenu);
  loading();
  try {
    const data = await api("/api/vocab/start", "POST", {});
    state.vocab = data;
    app.innerHTML = `
      <div class="screen">
        <h1>Новые слова</h1>
        <p class="hint">Сначала посмотри карточки, потом пройди короткий тест.</p>
        ${data.words.map((w, index) => `
          <div class="card word-card">
            <div class="daily-badge">Слово ${index + 1}</div>
            <div class="big mt-12">${esc(w.word)}</div>
            <div class="big-sub">${esc(w.translation)}</div>
            <p class="hint mt-12">${esc(w.example)}</p>
          </div>
        `).join("")}
        <button class="btn" id="startQuiz">Начать тест</button>
      </div>`;
    document.getElementById("startQuiz").onclick = () => { haptic(); renderVocabQuiz(); };
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
      <div class="card center">
        <div class="daily-badge">${progress}</div>
        <div class="big mt-12">${esc(q.word)}</div>
        <p class="hint mt-12">${esc(q.prompt)}</p>
      </div>
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
            ${mistakes.map(m => `<div class="stat-row"><span>${esc(m.word)}</span><b>${esc(m.translation)}</b></div>`).join("")}
          </div>
        ` : `<div class="card center"><b>Отлично!</b><p class="hint">Все слова запомнились.</p></div>`}
        <button class="btn" id="again">Еще набор слов</button>
        <button class="btn btn-secondary" id="home">В меню</button>
      </div>`;
    document.getElementById("again").onclick = () => { haptic(); renderVocabStart(); };
    document.getElementById("home").onclick = () => { haptic(); renderMenu(); };
  } catch (e) {
    renderError(e.message);
  }
}

async function renderDailyLesson() {
  setBack(renderMenu);
  loading();
  try {
    const status = await api("/api/daily/status", "GET");
    app.innerHTML = `
      <div class="screen">
        <h1>Ежедневный урок</h1>
        <div class="card">
          <div class="daily-badge">${status.completed ? "На сегодня готово" : "5 минут"}</div>
          <p class="hint mt-12">Мини-урок состоит из слов, теста и маленькой практики.</p>
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
    document.getElementById("dailyStart").onclick = () => renderVocabStart();
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
          <h2 style="margin:0">AI-репетитор</h2>
          <button class="chat-reset" id="reset">Очистить</button>
        </div>
        <div class="chat-meta">Осталось сообщений сегодня: ${data.usage?.remaining_today ?? "∞"}</div>
        <div class="tutor-stage">
          <div class="tutor-face idle" id="tutorFace" aria-hidden="true">
            <div class="face-hair"></div>
            <div class="face-eye left"></div>
            <div class="face-eye right"></div>
            <div class="face-cheek left"></div>
            <div class="face-cheek right"></div>
            <div class="face-mouth"></div>
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
    let recorder = null;
    let audioChunks = [];
    let recordingStream = null;
    let sending = false;
    let discardRecording = false;

    function bubble(role, text) {
      const div = document.createElement("div");
      div.className = `bubble ${role === "user" ? "user" : "bot"}`;
      div.textContent = text;
      box.appendChild(div);
      box.scrollTop = box.scrollHeight;
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

    function speakTutor(text) {
      if (!text || text.startsWith("Ошибка:")) {
        setFace("idle");
        return;
      }
      if (!("speechSynthesis" in window)) {
        setFace("speaking");
        setTimeout(() => setFace("idle"), 1400);
        return;
      }
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        const isRussian = /[а-яё]/i.test(text);
        utterance.lang = isRussian ? "ru-RU" : "en-US";
        utterance.rate = isRussian ? 0.95 : 0.86;
        utterance.pitch = 1.08;
        utterance.onstart = () => setFace("speaking");
        utterance.onend = () => setFace("idle");
        utterance.onerror = () => setFace("idle");
        window.speechSynthesis.speak(utterance);
      } catch (_) {
        setFace("idle");
      }
    }

    function preferredMimeType() {
      if (!window.MediaRecorder?.isTypeSupported) return "";
      return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(type => MediaRecorder.isTypeSupported(type)) || "";
    }

    function stopTracks() {
      recordingStream?.getTracks().forEach(track => track.stop());
      recordingStream = null;
    }

    function cleanupChat() {
      window.speechSynthesis?.cancel?.();
      discardRecording = true;
      if (recorder && recorder.state !== "inactive") {
        recorder.onstop = null;
        recorder.stop();
      }
      audioChunks = [];
      stopTracks();
      mic.classList.remove("recording");
      setFace("idle");
    }

    if (!data.messages?.length) {
      box.innerHTML = `<div class="chat-empty">Hello! или Я не понимаю.</div>`;
    } else {
      data.messages.forEach(m => bubble(m.role, m.content));
    }

    async function send(textOverride) {
      const text = typeof textOverride === "string" ? textOverride.trim() : input.value.trim();
      if (!text) return;
      if (sending) return;
      sending = true;
      sendButton.disabled = true;
      mic.disabled = true;
      if (box.querySelector(".chat-empty")) box.innerHTML = "";
      input.value = "";
      bubble("user", text);
      const typing = typingBubble();
      setFace("thinking");
      try {
        const reply = await api("/api/chat/send", "POST", { message: text });
        typing.remove();
        bubble("assistant", reply.reply);
        speakTutor(reply.reply);
      } catch (e) {
        typing.remove();
        bubble("assistant", `Ошибка: ${e.message}`);
        setFace("idle");
      } finally {
        sending = false;
        sendButton.disabled = false;
        mic.disabled = false;
        input.focus();
      }
    }

    async function uploadVoice(blob) {
      const form = new FormData();
      const extension = blob.type.includes("mp4") ? "mp4" : "webm";
      form.append("audio", blob, `voice.${extension}`);
      const result = await apiForm("/api/audio/transcribe", form);
      return (result.text || "").trim();
    }

    async function handleRecordingStop(mimeType) {
      stopTracks();
      mic.classList.remove("recording");
      mic.disabled = true;
      sendButton.disabled = true;
      setFace("thinking");
      try {
        const blob = new Blob(audioChunks, { type: mimeType || "audio/webm" });
        audioChunks = [];
        if (blob.size < 600) {
          tg.showAlert("Голосовое сообщение слишком короткое");
          setFace("idle");
          return;
        }
        const text = await uploadVoice(blob);
        if (!text) {
          tg.showAlert("Не удалось разобрать речь. Попробуй еще раз.");
          setFace("idle");
          return;
        }
        await send(text);
      } catch (e) {
        tg.showAlert(e.message);
        setFace("idle");
      } finally {
        mic.disabled = false;
        if (!sending) sendButton.disabled = false;
      }
    }

    async function startRecording() {
      if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
        tg.showAlert("Голосовой ввод не поддерживается на этом устройстве");
        return;
      }
      try {
        audioChunks = [];
        recordingStream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
          handleRecordingStop(recorder?.mimeType || mimeType);
        };
        recorder.start();
        mic.classList.add("recording");
        sendButton.disabled = true;
        setFace("listening");
        haptic();
      } catch (e) {
        stopTracks();
        tg.showAlert(`Не удалось включить микрофон: ${e.message}`);
        setFace("idle");
      }
    }

    function stopRecording() {
      if (!recorder || recorder.state === "inactive") return;
      recorder.stop();
      sendButton.disabled = false;
      haptic("success");
    }

    function toggleRecording() {
      if (sending) return;
      if (recorder && recorder.state === "recording") stopRecording();
      else startRecording();
    }

    mic.onclick = toggleRecording;
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

async function renderParentReport() {
  setBack(renderMenu);
  loading();
  try {
    const data = await api("/api/parent/report", "GET");
    const r = data.report;
    app.innerHTML = `
      <div class="screen">
        <h1>Отчет для родителя</h1>
        <div class="card">
          <h2>${esc(data.child.name)}</h2>
          <p class="hint">${esc(data.child.age_label)} · ${esc(data.child.goal_label)}</p>
        </div>
        <div class="card">
          <div class="stat-row"><span>Уроков пройдено</span><b>${r.completed_lessons}</b></div>
          <div class="stat-row"><span>Слов в обучении</span><b>${r.words_learned}</b></div>
          <div class="stat-row"><span>Тестов по словам</span><b>${r.completed_word_tests}</b></div>
          <div class="stat-row"><span>Средний результат</span><b>${r.avg_word_test_score}%</b></div>
          <div class="stat-row"><span>Правильных ответов</span><b>${r.total_correct}</b></div>
          <div class="stat-row"><span>Ошибок</span><b>${r.total_wrong}</b></div>
        </div>
      </div>`;
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
    const s = state.me.stats;
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
          <div class="stat-row"><span>Слов в обучении</span><b>${s.words_learned}</b></div>
          <div class="stat-row"><span>Правильных ответов</span><b>${s.total_correct}</b></div>
          <div class="stat-row"><span>Ошибок</span><b>${s.total_wrong}</b></div>
        </div>
      </div>`;
  } catch (e) {
    renderError(e.message);
  }
}

async function start() {
  if (!tg.initData) {
    app.innerHTML = `
      <div class="screen">
        <h1>AI English Tutor Kids</h1>
        <div class="card">
          <p class="hint">Откройте Mini App через Telegram-бота. В браузере доступен только просмотр интерфейса.</p>
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
