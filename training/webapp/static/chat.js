"use strict";

const chatState = { messages: [], busy: false };

function chatBubbles() {
  return chatState.messages.map((m) => `
    <div class="chat-msg ${m.role}">
      <div class="chat-bubble">${esc(m.content).replace(/\n/g, "<br>")}</div>
    </div>`).join("");
}

function chatRender() {
  const el = document.getElementById("view-chat");
  if (!el) return;
  const empty = !chatState.messages.length
    ? '<p class="tip">Pose une question sur la semaine en cours, une allure, un ajustement…</p>' : "";
  const spinner = chatState.busy
    ? '<div class="chat-msg assistant"><div class="chat-bubble loading">…</div></div>' : "";
  el.innerHTML = `
    <div class="card chat-card">
      <h2>Coach — questions sur ton plan</h2>
      <div class="chat-log" id="chat-log">${empty}${chatBubbles()}${spinner}</div>
      <form id="chat-form" class="chat-form">
        <input type="text" id="chat-input" placeholder="Écris ta question…"
          autocomplete="off" ${chatState.busy ? "disabled" : ""}>
        <button type="submit" ${chatState.busy ? "disabled" : ""}>Envoyer</button>
      </form>
    </div>`;
  const log = document.getElementById("chat-log");
  log.scrollTop = log.scrollHeight;
  document.getElementById("chat-form").addEventListener("submit", chatSubmit);
  if (!chatState.busy) document.getElementById("chat-input")?.focus();
}

async function chatSubmit(e) {
  e.preventDefault();
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text || chatState.busy) return;
  chatState.messages.push({ role: "user", content: text });
  chatState.busy = true;
  chatRender();
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: chatState.messages, week_idx: state.weekIdx }),
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
    chatState.messages.push({ role: "assistant", content: data.reply });
  } catch (err) {
    chatState.messages.push({ role: "assistant", content: `Erreur : ${err.message}` });
  } finally {
    chatState.busy = false;
    chatRender();
  }
}

chatRender();
