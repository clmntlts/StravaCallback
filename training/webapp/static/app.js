"use strict";

const state = { plan: null, weekIdx: null, week: null, liveBusy: false,
  pushBusy: false, weekBusy: false, pushResult: null, loadError: null,
  loadingLabel: null };

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
  // Verrou anti-course : ignore les clics tant qu'un chargement est en cours (#44).
  if (state.weekBusy) return;
  state.weekBusy = true;
  state.loadError = null;
  state.loadingLabel = live ? "Récupération Strava…" : "Chargement…";
  renderWeekView();
  try {
    const url = `/api/week/${idx}` + (live ? "?live=1" : "");
    state.week = await getJSON(url);
    state.weekIdx = idx;
    state.pushResult = null;
  } catch (e) {
    // On expose l'erreur via l'état (bannière + « Réessayer »), sans mutation DOM directe (#41).
    state.loadError = { idx, live, message: e.message };
  } finally {
    state.weekBusy = false;
    renderWeekView();
  }
}

// --------------------------------------------------------------------------
// Rendu — semaine
// --------------------------------------------------------------------------
function renderWeekNav() {
  const n = state.plan.meta.weeks;
  const idx = state.weekIdx;
  const busy = state.weekBusy;
  let opts = "";
  for (let i = 1; i <= n; i++) {
    opts += `<option value="${i}" ${i === idx ? "selected" : ""}>Semaine ${i}</option>`;
  }
  return `
    <div class="week-nav">
      <button class="btn btn-icon" id="wk-prev" ${busy || idx <= 1 ? "disabled" : ""} aria-label="Semaine précédente">&larr;</button>
      <select id="wk-select" aria-label="Choisir la semaine" ${busy ? "disabled" : ""}>${opts}</select>
      <button class="btn btn-icon" id="wk-next" ${busy || idx >= n ? "disabled" : ""} aria-label="Semaine suivante">&rarr;</button>
      <button class="btn btn-secondary ml-auto" id="wk-live" ${busy || state.liveBusy ? "disabled" : ""}>
        ${state.liveBusy ? "Récupération…" : "Charger Strava (live)"}
      </button>
    </div>`;
}

function renderWeekView() {
  const el = document.getElementById("view-week");
  // Plan pas encore chargé : c'est main()/loadAll() qui gère cet état.
  if (!state.plan) return;

  // État d'erreur de chargement : nav + bannière + « Réessayer » (#41).
  if (state.loadError) {
    el.innerHTML = `
      ${renderWeekNav()}
      <div class="week-body">
        <div class="banner warn">Erreur : ${esc(state.loadError.message)}</div>
        <div class="actions-row">
          <button class="btn btn-primary" id="wk-retry" type="button">Réessayer</button>
        </div>
      </div>`;
    wireWeekNav();
    document.getElementById("wk-retry")?.addEventListener("click", () => {
      loadWeek(state.loadError.idx, state.loadError.live);
    });
    return;
  }

  // Chargement en cours : nav (contrôles verrouillés) + indicateur.
  if (state.weekBusy) {
    el.innerHTML = `
      ${renderWeekNav()}
      <div class="week-body loading">${esc(state.loadingLabel || "Chargement…")}</div>`;
    wireWeekNav();
    return;
  }

  const w = state.week;
  if (!w) { el.innerHTML = renderWeekNav(); wireWeekNav(); return; }

  // Bannière onboarding : le plan affiché est un modèle par défaut (#42).
  const onboardingBanner = (state.plan.meta && state.plan.meta.onboarded === false)
    ? `<div class="banner onboarding">
        <div>Ce plan est un modèle par défaut. Configure ton profil (objectif, date
          de course, jours de dispo, allures) via l'onglet Coach pour l'adapter à toi.</div>
        <button class="btn btn-primary" id="wk-onboard-cta" type="button">Configurer mon profil</button>
      </div>`
    : "";

  // Bannière Strava : on ajoute la même remédiation que l'Historique (#50).
  const banner = w.strava_error
    ? `<div class="banner warn">Strava : ${esc(w.strava_error)}
        <div class="muted-inline">Configure Strava une fois (jeton local) :
          <code>python3 generate.py strava-auth-url</code> — voir <code>training/RUNBOOK.md</code>.</div></div>`
    : "";

  // Garde-fous : un payload partiel doit dégrader vers « — » plutôt que geler (#49).
  const lastWeek = w.last_week || {};
  const totalHours = typeof w.total_hours === "number" ? `${w.total_hours.toFixed(1)} h` : "—";
  const adherence = typeof lastWeek.adherence === "number"
    ? `${(lastWeek.adherence * 100).toFixed(0)}%` : "—";
  const acwr = typeof lastWeek.acwr === "number" ? lastWeek.acwr.toFixed(2) : "—";
  const phase = w.phase != null ? esc(w.phase) : "—";
  const weekNo = w.week != null ? w.week : state.weekIdx;
  const sessions = Array.isArray(w.sessions) ? w.sessions : [];

  const kpis = `
    <div class="kpis">
      <div class="kpi ${bandClass(w.band)}">
        <div class="kn">${totalHours}</div>
        <div class="kl">Volume prévu</div>
      </div>
      <div class="kpi">
        <div class="kn">${adherence}</div>
        <div class="kl" title="Part des séances de la semaine précédente réellement réalisées">Adhérence S-1</div>
      </div>
      <div class="kpi">
        <div class="kn">${acwr}</div>
        <div class="kl" title="ACWR = ratio charge aiguë/chronique (7j/28j)">ACWR</div>
      </div>
      <div class="kpi">
        <div class="kn">${phase}${w.deload ? ' <span class="dot dot-deload" title="Semaine de décharge"></span>' : ""}</div>
        <div class="kl">Phase</div>
      </div>
    </div>`;

  const rows = sessions.map((s) => `
    <tr>
      <td><span class="role">${esc(s.day)}</span></td>
      <td>
        <div>${esc(s.label)}</div>
        ${s.tip ? `<div class="tip">${esc(s.tip)}</div>` : ""}
      </td>
      <td class="n">${s.minutes} min</td>
      <td>${s.file ? `<a class="dl" href="/api/week/${weekNo}/fit/${esc(s.role)}" download data-filename="${esc(s.role)}.fit">.fit</a>` : ""}</td>
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
      ${onboardingBanner}
      ${banner}
      ${w.message ? `<div class="banner muted">${esc(w.message)}</div>` : ""}
      ${kpis}
      <div class="card">
        <h2>Semaine ${esc(weekNo)} — ${phase} ${w.deload ? '<span class="deload-tag">décharge</span>' : ""}</h2>
        <div class="table-wrap">
          <table>
            <thead><tr><th>Jour</th><th>Séance</th><th class="n">Durée</th><th></th></tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
        <div id="fit-msg" role="alert"></div>
        <div class="actions-row">
          <button class="btn btn-primary" id="wk-push" ${state.pushBusy ? "disabled" : ""}>
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
    <li>${r.ok
        ? '<span class="status-ok" aria-hidden="true"></span><span class="sr-only">réussi</span>'
        : '<span class="status-ko" aria-hidden="true"></span><span class="sr-only">échoué</span>'} <strong>${esc(r.date)}</strong> ${esc(r.label)}
      <span class="muted-inline"> · ${esc(r.detail)}</span></li>`).join("");
  return `<div class="banner ${res.ok ? "muted" : "warn"} mt-3">
    <div>Voie : <strong>${esc(res.via)}</strong></div>
    <ul class="adj mt-2">${rows}</ul>
  </div>`;
}

function wireWeekNav() {
  const n = state.plan.meta.weeks;
  document.getElementById("wk-prev")?.addEventListener("click", () => {
    if (!state.weekBusy && state.weekIdx > 1) loadWeek(state.weekIdx - 1, false);
  });
  document.getElementById("wk-next")?.addEventListener("click", () => {
    if (!state.weekBusy && state.weekIdx < n) loadWeek(state.weekIdx + 1, false);
  });
  document.getElementById("wk-select")?.addEventListener("change", (e) => {
    if (!state.weekBusy) loadWeek(parseInt(e.target.value, 10), false);
  });
  document.getElementById("wk-live")?.addEventListener("click", async () => {
    if (state.weekBusy) return;
    state.liveBusy = true;
    renderWeekView();
    try {
      await loadWeek(state.weekIdx, true);
    } finally {
      // Toujours re-rendre : sinon le bouton reste bloqué sur « Récupération… » (#40).
      state.liveBusy = false;
      renderWeekView();
    }
  });
  document.getElementById("wk-push")?.addEventListener("click", async () => {
    // Confirmation avant d'écrire sur le calendrier Garmin (#43).
    const nb = Array.isArray(state.week?.sessions) ? state.week.sessions.length : 0;
    const wk = state.week?.week != null ? state.week.week : state.weekIdx;
    if (!window.confirm(`Planifier les ${nb} séances de la semaine ${wk} sur Garmin ?`)) return;
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

  // CTA onboarding : bascule sur l'onglet Coach en mode configuration (#42).
  document.getElementById("wk-onboard-cta")?.addEventListener("click", () => {
    if (typeof chatState !== "undefined") {
      chatState.mode = "onboarding";
      chatState.modeChosen = true;
      chatState.messages = [];
    }
    document.getElementById("tab-chat")?.click();
    if (typeof chatRender === "function") chatRender();
  });

  // Téléchargement .fit : on récupère d'abord l'URL ; une 409 JSON (post-redémarrage/
  // onboarding) ne doit pas être enregistrée comme un fichier (#50).
  document.querySelectorAll("#view-week a.dl").forEach((a) => {
    a.addEventListener("click", async (ev) => {
      ev.preventDefault();
      const url = a.getAttribute("href");
      try {
        const r = await fetch(url);
        if (!r.ok) { showFitMsg("Recharge la semaine avant de télécharger."); return; }
        const blob = await r.blob();
        const objUrl = URL.createObjectURL(blob);
        const tmp = document.createElement("a");
        tmp.href = objUrl;
        tmp.download = a.getAttribute("data-filename") || "seance.fit";
        document.body.appendChild(tmp);
        tmp.click();
        tmp.remove();
        URL.revokeObjectURL(objUrl);
      } catch (e) {
        showFitMsg(`Erreur : ${e.message}`);
      }
    });
  });
}

function showFitMsg(msg) {
  const el = document.getElementById("fit-msg");
  if (el) el.innerHTML = `<div class="banner warn mt-2">${esc(msg)}</div>`;
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
      <div class="table-wrap">
        <table class="plan-table">
          <thead><tr><th>Sem.</th><th>Phase</th><th>Séances</th><th class="n">Total</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
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

  // Active un onglet : classe + état ARIA/tabindex + affichage du panneau (#45).
  function activate(target, moveFocus) {
    tabs.forEach(({ tabEl, viewEl }) => {
      const on = tabEl === target;
      tabEl.classList.toggle("active", on);
      tabEl.setAttribute("aria-selected", on ? "true" : "false");
      tabEl.tabIndex = on ? 0 : -1;
      viewEl.style.display = on ? "" : "none";
    });
    if (moveFocus) target.focus();
    if (target.id === "tab-history") historyOnTabShown();
  }

  tabs.forEach(({ tabEl }, i) => {
    tabEl.addEventListener("click", () => activate(tabEl, false));
    // Focus itinérant ArrowLeft/ArrowRight (motif WAI-ARIA tab) (#45).
    tabEl.addEventListener("keydown", (e) => {
      if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
      e.preventDefault();
      const dir = e.key === "ArrowRight" ? 1 : -1;
      activate(tabs[(i + dir + tabs.length) % tabs.length].tabEl, true);
    });
  });

  // État ARIA initial cohérent avec l'onglet actif par défaut (Semaine).
  activate(tabs[0].tabEl, false);
}

// --------------------------------------------------------------------------
// En cas d'échec de loadPlan(), on affiche une action « Réessayer » plutôt
// que de laisser les vues vides (#41).
function renderPlanLoadError(message) {
  const retry = `
    <div class="week-body">
      <div class="banner warn">Erreur de chargement : ${esc(message)}</div>
      <div class="actions-row">
        <button class="btn btn-primary" id="plan-retry" type="button">Réessayer</button>
      </div>
    </div>`;
  const wv = document.getElementById("view-week");
  const pv = document.getElementById("view-plan");
  if (wv) wv.innerHTML = retry;
  if (pv) pv.innerHTML =
    `<div class="week-body"><div class="banner warn">Erreur de chargement : ${esc(message)}</div></div>`;
  document.getElementById("plan-retry")?.addEventListener("click", () => loadAll());
}

async function loadAll() {
  try {
    await loadPlan();
    // Le chat dépend de state.plan.meta.onboarded désormais chargé (#42).
    if (typeof chatRender === "function") chatRender();
  } catch (e) {
    document.getElementById("hero-sub").textContent = `Erreur : ${e.message}`;
    renderPlanLoadError(e.message);
    return;
  }
  await loadWeek(state.weekIdx, false);
}

async function main() {
  wireTabs();
  await loadAll();
}

main();
