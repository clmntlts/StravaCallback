"use strict";

const state = { plan: null, weekIdx: null, week: null, liveBusy: false,
  pushBusy: false, pushResult: null };

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function bandClass(band) {
  if (band === "brake" || band === "bad") return "bad";
  if (band === "caution" || band === "warn") return "warn";
  return "good";
}

async function getJSON(url) {
  const r = await fetch(url);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

async function postJSON(url) {
  const r = await fetch(url, { method: "POST" });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || `${r.status} ${r.statusText}`);
  return data;
}

// --------------------------------------------------------------------------
// Chargement
// --------------------------------------------------------------------------
async function loadPlan() {
  state.plan = await getJSON("/api/plan");
  document.getElementById("hero-sub").textContent =
    `${state.plan.meta.objective} · ${state.plan.meta.days} j/sem · ${state.plan.meta.season}`;
  document.getElementById("hero-pill").textContent =
    `${state.plan.meta.weeks} semaines`;
  if (state.weekIdx === null) state.weekIdx = state.plan.current_week;
  renderPlanView();
}

async function loadWeek(idx, live) {
  const el = document.getElementById("view-week");
  el.querySelector(".week-body")?.remove();
  const body = document.createElement("div");
  body.className = "week-body loading";
  body.textContent = live ? "Récupération Strava…" : "Chargement…";
  el.appendChild(body);
  try {
    const url = `/api/week/${idx}` + (live ? "?live=1" : "");
    state.week = await getJSON(url);
    state.weekIdx = idx;
    state.pushResult = null;
  } catch (e) {
    body.textContent = `Erreur : ${e.message}`;
    body.classList.remove("loading");
    return;
  }
  renderWeekView();
}

// --------------------------------------------------------------------------
// Rendu — semaine
// --------------------------------------------------------------------------
function renderWeekNav() {
  const n = state.plan.meta.weeks;
  const idx = state.weekIdx;
  let opts = "";
  for (let i = 1; i <= n; i++) {
    opts += `<option value="${i}" ${i === idx ? "selected" : ""}>Semaine ${i}</option>`;
  }
  return `
    <div class="week-nav">
      <button class="btn btn-icon" id="wk-prev" ${idx <= 1 ? "disabled" : ""} aria-label="Semaine précédente">&larr;</button>
      <select id="wk-select">${opts}</select>
      <button class="btn btn-icon" id="wk-next" ${idx >= n ? "disabled" : ""} aria-label="Semaine suivante">&rarr;</button>
      <button class="btn btn-secondary" id="wk-live" ${state.liveBusy ? "disabled" : ""}>
        ${state.liveBusy ? "Récupération…" : "Charger Strava (live)"}
      </button>
    </div>`;
}

function renderWeekView() {
  const el = document.getElementById("view-week");
  const w = state.week;
  if (!w) { el.innerHTML = renderWeekNav(); wireWeekNav(); return; }

  const banner = w.strava_error
    ? `<div class="banner warn">Strava : ${esc(w.strava_error)}</div>`
    : "";

  const kpis = `
    <div class="kpis">
      <div class="kpi ${bandClass(w.band)}">
        <div class="kn">${w.total_hours.toFixed(1)} h</div>
        <div class="kl">Volume prévu</div>
      </div>
      <div class="kpi">
        <div class="kn">${(w.last_week.adherence * 100).toFixed(0)}%</div>
        <div class="kl">Adhérence S-1</div>
      </div>
      <div class="kpi">
        <div class="kn">${w.last_week.acwr ? w.last_week.acwr.toFixed(2) : "—"}</div>
        <div class="kl">ACWR</div>
      </div>
      <div class="kpi">
        <div class="kn">${w.phase}${w.deload ? ' <span class="dot dot-deload" title="Semaine de décharge"></span>' : ""}</div>
        <div class="kl">Phase</div>
      </div>
    </div>`;

  const rows = w.sessions.map((s) => `
    <tr>
      <td><span class="role">${esc(s.day)}</span></td>
      <td>
        <div>${esc(s.label)}</div>
        ${s.tip ? `<div class="tip">${esc(s.tip)}</div>` : ""}
      </td>
      <td class="n">${s.minutes} min</td>
      <td>${s.file ? `<a class="dl" href="/api/week/${w.week}/fit/${esc(s.role)}" download>.fit</a>` : ""}</td>
    </tr>`).join("");

  const adj = (w.adjustments || []).length
    ? `<div class="card"><h2>Ajustements</h2><ul class="adj">
        ${w.adjustments.map((a) => `<li><strong>${esc(a.role)}</strong> ${esc(a.before)} &rarr; ${esc(a.after)}
          <span class="muted-inline"> · ${esc(a.reason)}</span></li>`).join("")}
       </ul></div>`
    : "";

  const analysis = w.analysis ? `
    <div class="card">
      <h2>Debrief coach</h2>
      <p><strong>${esc(w.analysis.headline)}</strong></p>
      ${w.analysis.observations.length ? `<ul class="adj">${w.analysis.observations.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : ""}
      ${(w.analysis.trends || []).length ? `<h2 class="subhead">Tendances</h2><ul class="adj">${w.analysis.trends.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : ""}
      ${w.analysis.recommendations.length ? `<h2 class="subhead">Recommandations</h2><ul class="adj">${w.analysis.recommendations.map((o) => `<li>${esc(o)}</li>`).join("")}</ul>` : ""}
    </div>` : "";

  el.innerHTML = `
    ${renderWeekNav()}
    <div class="week-body">
      ${banner}
      ${w.message ? `<div class="banner muted">${esc(w.message)}</div>` : ""}
      ${kpis}
      <div class="card">
        <h2>Semaine ${w.week} — ${esc(w.phase)} ${w.deload ? '<span class="deload-tag">décharge</span>' : ""}</h2>
        <table>
          <thead><tr><th>Jour</th><th>Séance</th><th style="text-align:right">Durée</th><th></th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="actions-row">
          <button class="btn btn-secondary" id="wk-push" ${state.pushBusy ? "disabled" : ""}>
            ${state.pushBusy ? "Envoi…" : "Planifier sur Garmin"}
          </button>
        </div>
        ${renderPushResult()}
      </div>
      ${adj}
      ${analysis}
    </div>`;
  wireWeekNav();
}

function renderPushResult() {
  const res = state.pushResult;
  if (!res) return "";
  if (res.error) {
    return `<div class="banner warn mt-3">${esc(res.error)}</div>`;
  }
  if (!res.configured) {
    return `<div class="banner muted mt-3">
      Garmin non configuré (ni Training API officielle, ni Garmin Connect) —
      voir <code>training/RUNBOOK.md</code>.</div>`;
  }
  if (res.detail) {
    return `<div class="banner warn mt-3">
      ${esc(res.via)} : ${esc(res.detail)}</div>`;
  }
  const rows = res.results.map((r) => `
    <li>${r.ok ? "✓" : "✗"} <strong>${esc(r.date)}</strong> ${esc(r.label)}
      <span class="muted-inline"> · ${esc(r.detail)}</span></li>`).join("");
  return `<div class="banner ${res.ok ? "muted" : "warn"} mt-3">
    <div>Voie : <strong>${esc(res.via)}</strong></div>
    <ul class="adj mt-2">${rows}</ul>
  </div>`;
}

function wireWeekNav() {
  const n = state.plan.meta.weeks;
  document.getElementById("wk-prev")?.addEventListener("click", () => {
    if (state.weekIdx > 1) loadWeek(state.weekIdx - 1, false);
  });
  document.getElementById("wk-next")?.addEventListener("click", () => {
    if (state.weekIdx < n) loadWeek(state.weekIdx + 1, false);
  });
  document.getElementById("wk-select")?.addEventListener("change", (e) => {
    loadWeek(parseInt(e.target.value, 10), false);
  });
  document.getElementById("wk-live")?.addEventListener("click", async () => {
    state.liveBusy = true;
    renderWeekView();
    try {
      await loadWeek(state.weekIdx, true);
    } finally {
      state.liveBusy = false;
    }
  });
  document.getElementById("wk-push")?.addEventListener("click", async () => {
    state.pushBusy = true;
    renderWeekView();
    try {
      state.pushResult = await postJSON(`/api/week/${state.weekIdx}/push-garmin`);
    } catch (e) {
      state.pushResult = { error: e.message };
    } finally {
      state.pushBusy = false;
      renderWeekView();
    }
  });
}

// --------------------------------------------------------------------------
// Rendu — plan complet
// --------------------------------------------------------------------------
function renderPlanView() {
  const el = document.getElementById("view-plan");
  const rows = state.plan.weeks.map((w) => `
    <tr class="${w.wk === state.plan.current_week ? "current" : ""}">
      <td class="wk">${w.wk}${w.deload ? ' <span class="dot dot-deload" title="Décharge"></span>' : ""}</td>
      <td>${esc(w.phase)}</td>
      <td>${w.s.map(esc).join(" · ")}</td>
      <td class="n">${w.h.toFixed(1)} h</td>
    </tr>`).join("");
  el.innerHTML = `
    <div class="card">
      <h2>Plan — ${state.plan.meta.weeks} semaines (${esc(state.plan.meta.season)})</h2>
      <div class="legend"><span class="dot dot-deload"></span> décharge</div>
      <table class="plan-table">
        <thead><tr><th>Sem.</th><th>Phase</th><th>Séances</th><th style="text-align:right">Total</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
}

// --------------------------------------------------------------------------
// Onglets
// --------------------------------------------------------------------------
function wireTabs() {
  const tabs = [
    { tab: "tab-week", view: "view-week" },
    { tab: "tab-plan", view: "view-plan" },
    { tab: "tab-history", view: "view-history" },
    { tab: "tab-chat", view: "view-chat" },
  ].map((t) => ({ tabEl: document.getElementById(t.tab), viewEl: document.getElementById(t.view) }));
  tabs.forEach(({ tabEl, viewEl }) => {
    tabEl.addEventListener("click", () => {
      tabs.forEach((o) => {
        o.tabEl.classList.toggle("active", o.tabEl === tabEl);
        o.viewEl.style.display = o.tabEl === tabEl ? "" : "none";
      });
      if (tabEl.id === "tab-history") historyOnTabShown();
    });
  });
}

// --------------------------------------------------------------------------
async function main() {
  wireTabs();
  try {
    await loadPlan();
    await loadWeek(state.weekIdx, false);
  } catch (e) {
    document.getElementById("hero-sub").textContent = `Erreur : ${e.message}`;
  }
}

main();
