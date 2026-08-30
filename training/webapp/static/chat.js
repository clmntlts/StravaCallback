"use strict";

const chatState = { messages: [], busy: false, mode: "qa", modeChosen: false,
  abortController: null, elapsed: 0, timer: null, notice: null };

function chatDefaultMode() {
  return (state.plan && state.plan.meta && state.plan.meta.onboarded === false)
    ? "onboarding" : "qa";
}

function chatBubbles() {
  return chatState.messages.map((m) => `
    <div class="chat-msg ${m.role}">
      <div class="chat-bubble${m.error ? " error" : ""}">${esc(m.content).replace(/\n/g, "<br>")}</div>
    </div>`).join("");
}

function chatRender() {
  const el = document.getElementById("view-chat");
  if (!el) return;
  if (!chatState.modeChosen) chatState.mode = chatDefaultMode();
  const onboarding = chatState.mode === "onboarding";

  const empty = !chatState.messages.length
    ? `<p class="tip">${onboarding
        ? "Dis-moi ton objectif (ex. 24 tours), ta date de course, tes jours de dispo… on configure ton profil ensemble."
        : "Pose une question sur la semaine en cours, une allure, un ajustement…"}</p>`
    : "";
  const spinner = chatState.busy
    ? `<div class="chat-msg assistant"><div class="chat-bubble loading">… <span class="chat-elapsed" id="chat-elapsed">${chatState.elapsed} s</span></div></div>` : "";
  const notice = chatState.notice
    ? `<p class="tip">${esc(chatState.notice)}</p>` : "";
  const banner = onboarding
    ? '<div class="banner muted">Mode configuration du profil — l\'agent écrit ton profil lui-même une fois tes réponses réunies.</div>'
    : "";

  el.innerHTML = `
    <div class="card chat-card">
      <div class="card-header-row">
        <h2>Coach — ${onboarding ? "configuration du profil" : "questions sur ton plan"}</h2>
        <button type="button" id="chat-mode-toggle" class="btn btn-ghost">
          ${onboarding ? "Revenir aux questions" : "Configurer mon profil"}
        </button>
      </div>
      ${banner}
      <div class="chat-log" id="chat-log">${empty}${chatBubbles()}${spinner}${notice}</div>
      <form id="chat-form" class="chat-form">
        <input type="text" id="chat-input" placeholder="Écris ta réponse…"
          aria-label="Message au coach" autocomplete="off" ${chatState.busy ? "disabled" : ""}>
        <button type="submit" class="btn btn-primary" ${chatState.busy ? "disabled" : ""}>Envoyer</button>
        ${chatState.busy ? '<button type="button" id="chat-cancel" class="btn btn-secondary">Annuler</button>' : ""}
      </form>
    </div>`;
  const log = document.getElementById("chat-log");
  log.scrollTop = log.scrollHeight;
  document.getElementById("chat-form").addEventListener("submit", chatSubmit);
  document.getElementById("chat-mode-toggle").addEventListener("click", () => {
    if (chatState.messages.length &&
        !confirm("Changer de mode effacera la conversation en cours. Continuer ?")) {
      return;
    }
    chatState.mode = onboarding ? "qa" : "onboarding";
    chatState.modeChosen = true;
    chatState.messages = [];
    chatState.notice = null;
    chatRender();
  });
  document.getElementById("chat-cancel")?.addEventListener("click", () => {
    if (chatState.abortController) chatState.abortController.abort();
  });
  if (!chatState.busy) document.getElementById("chat-input")?.focus();
}

async function chatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text || chatState.busy) return;
  chatState.messages.push({ role: "user", content: text });
  chatState.busy = true;
  chatState.notice = null;
  chatState.elapsed = 0;
  const controller = new AbortController();
  chatState.abortController = controller;
  chatRender();
  chatState.timer = setInterval(() => {
    chatState.elapsed += 1;
    const eSpan = document.getElementById("chat-elapsed");
    if (eSpan) eSpan.textContent = chatState.elapsed + " s";
  }, 1000);
  try {
    const body = { messages: chatState.messages, mode: chatState.mode };
    if (chatState.mode !== "onboarding") body.week_idx = state.weekIdx;
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
    chatState.messages.push({ role: "assistant", content: data.reply });
    if (data.onboarded) {
      chatState.mode = "qa";
      chatState.modeChosen = true;
      await loadPlan();
      await loadWeek(state.weekIdx, false);
    }
  } catch (err) {
    if (err.name === "AbortError") {
      chatState.notice = "Annulé";
    } else {
      chatState.messages.push({ role: "assistant", content: `Erreur : ${err.message}`, error: true });
    }
  } finally {
    if (chatState.timer) { clearInterval(chatState.timer); chatState.timer = null; }
    chatState.abortController = null;
    chatState.busy = false;
    chatRender();
  }
}

chatRender();
