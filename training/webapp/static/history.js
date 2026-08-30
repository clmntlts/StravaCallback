"use strict";

const historyState = { data: null, loading: false, error: null, showTable: false };

function historyOnTabShown() {
  if (!historyState.data && !historyState.loading) loadHistory(false);
}

async function loadHistory(refresh) {
  historyState.loading = true;
  historyState.error = null;
  historyRender();
  try {
    const data = await getJSON("/api/history" + (refresh ? "?refresh=1" : ""));
    if (data.error) {
      historyState.error = data.error;
      historyState.data = null;
    } else {
      historyState.data = data;
    }
  } catch (e) {
    historyState.error = e.message;
  } finally {
    historyState.loading = false;
    historyRender();
  }
}

// --------------------------------------------------------------------------
// Rendu
// --------------------------------------------------------------------------
function historyRender() {
  const el = document.getElementById("view-history");
  if (!el) return;

  if (historyState.loading && !historyState.data) {
    el.innerHTML = '<div class="week-body loading">Récupération de l\'historique Strava…</div>';
    return;
  }

  const toolbar = `
    <div class="hist-toolbar">
      <button type="button" id="hist-refresh" class="btn btn-secondary" ${historyState.loading ? "disabled" : ""}>
        ${historyState.loading ? "Actualisation…" : "Actualiser depuis Strava"}
      </button>
      <button type="button" id="hist-table-toggle" class="btn btn-ghost">
        ${historyState.showTable ? "Voir les graphiques" : "Voir en tableau"}
      </button>
    </div>`;

  if (historyState.error) {
    el.innerHTML = toolbar +
      `<div class="banner warn">${esc(historyState.error)}</div>
       <div class="banner muted">Configure Strava une fois (jeton local) :
         <code>python3 generate.py strava-auth-url</code> — voir <code>training/RUNBOOK.md</code>.</div>`;
    wireHistoryToolbar();
    return;
  }

  const d = historyState.data;
  const totals = d && d.totals;
  const weekly = d && d.weekly;
  if (!d || !Array.isArray(weekly) || !weekly.length || !totals || !totals.activities) {
    el.innerHTML = toolbar +
      '<div class="banner muted">Aucune activité Strava sur les 12 derniers mois.</div>';
    wireHistoryToolbar();
    return;
  }

  // Une charge utile partielle/malformée doit dégrader vers un état vide plutôt
  // que de casser le rendu (promesse rejetée non gérée) — d'où num() + try/catch.
  const num = (v, dec) => (typeof v === "number" && isFinite(v) ? v.toFixed(dec) : "—");
  const daily = Array.isArray(d.daily) ? d.daily : [];

  try {
    const kpis = `
      <div class="kpis">
        <div class="kpi"><div class="kn">${num(totals.hours, 0)} h</div><div class="kl">Volume (12 mois)</div></div>
        <div class="kpi"><div class="kn">${num(totals.km, 0)} km</div><div class="kl">Distance</div></div>
        <div class="kpi"><div class="kn">${num(totals.elevation_m, 0)} m</div><div class="kl">Dénivelé cumulé</div></div>
        <div class="kpi"><div class="kn">${esc(totals.activities)}</div><div class="kl">Activités</div></div>
      </div>`;

    const body = historyState.showTable ? historyTable(weekly) : `
      <div class="card">
        <h2>Volume hebdomadaire</h2>
        ${buildBarChart(weekly)}
      </div>
      <div class="card">
        <h2>Régularité — 12 derniers mois</h2>
        ${buildHeatmap(daily)}
      </div>
      <div class="card">
        <h2>Dénivelé cumulé</h2>
        ${buildLineChart(weekly, "elevation_cumulative_m", { unit: "m", color: "var(--accent)", title: "Dénivelé cumulé" })}
      </div>
      ${historyHrCard(weekly)}
    `;

    el.innerHTML = toolbar + kpis + body;
    wireHistoryToolbar();
    wireHistoryInteractions(d);
  } catch (e) {
    el.innerHTML = toolbar +
      '<div class="banner muted">Données d\'historique incomplètes ou invalides.</div>';
    wireHistoryToolbar();
  }
}

function historyHrCard(weekly) {
  if (!weekly.some((w) => w.avg_hr != null)) {
    return `<div class="card"><h2>Fréquence cardiaque moyenne</h2>
      <p class="tip">Pas de FC moyenne dans tes activités Strava sur cette période.</p></div>`;
  }
  return `<div class="card"><h2>Fréquence cardiaque moyenne</h2>
    ${buildLineChart(weekly, "avg_hr", { unit: "bpm", color: "var(--accent-dark)", area: false, title: "Fréquence cardiaque moyenne" })}</div>`;
}

function historyTable(weekly) {
  const rows = weekly.map((w) => `
    <tr>
      <td>${esc(w.week_start)}</td>
      <td class="n">${w.hours.toFixed(1)} h</td>
      <td class="n">${w.km.toFixed(1)} km</td>
      <td class="n">${w.elevation_m.toFixed(0)} m</td>
      <td class="n">${w.avg_hr != null ? w.avg_hr.toFixed(0) + " bpm" : "—"}</td>
    </tr>`).join("");
  return `
    <div class="card">
      <h2>Détail hebdomadaire</h2>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Semaine</th><th class="n">Volume</th>
            <th class="n">Distance</th><th class="n">D+</th>
            <th class="n">FC moy.</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
}

function wireHistoryToolbar() {
  document.getElementById("hist-refresh")?.addEventListener("click", () => loadHistory(true));
  document.getElementById("hist-table-toggle")?.addEventListener("click", () => {
    historyState.showTable = !historyState.showTable;
    historyRender();
  });
}

// --------------------------------------------------------------------------
// Graphiques — barres (volume hebdo)
// --------------------------------------------------------------------------
function niceMax(v) {
  if (v <= 0) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(v)));
  for (const s of [1, 2, 2.5, 5, 10]) {
    if (v <= s * mag) return s * mag;
  }
  return 10 * mag;
}

function buildBarChart(weekly) {
  const maxH = niceMax(Math.max(...weekly.map((w) => w.hours), 1));
  const bars = weekly.map((w, i) => {
    const pct = Math.max(1, (w.hours / maxH) * 100);
    const label = `Semaine du ${w.week_start} : ${w.hours.toFixed(1)} h, ${w.km.toFixed(1)} km`;
    return `<div class="hist-bar" data-idx="${i}" tabindex="0" role="img" aria-label="${esc(label)}" style="height:${pct}%"></div>`;
  }).join("");
  return `
    <div class="hist-bars-wrap">
      <div class="hist-bars-ygrid">
        <span>${maxH.toFixed(0)} h</span>
        <span>${(maxH / 2).toFixed(0)} h</span>
        <span>0 h</span>
      </div>
      <div class="hist-bars" id="hist-bars">${bars}</div>
    </div>`;
}

// --------------------------------------------------------------------------
// Graphiques — calendrier (heatmap)
// --------------------------------------------------------------------------
const _HIST_MONTHS_FR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
  "juil.", "août", "sept.", "oct.", "nov.", "déc."];

function buildHeatmap(daily) {
  const weeks = [];
  for (let i = 0; i < daily.length; i += 7) weeks.push(daily.slice(i, i + 7));

  const nonZero = daily.map((d) => d.hours).filter((h) => h > 0).sort((a, b) => a - b);
  const at = (p) => nonZero.length ? nonZero[Math.min(nonZero.length - 1, Math.floor(p * nonZero.length))] : 0;
  const thresholds = [at(0.33), at(0.66), at(0.9)];
  const levelOf = (h) => {
    if (h <= 0) return 0;
    if (h <= thresholds[0]) return 1;
    if (h <= thresholds[1]) return 2;
    if (h <= thresholds[2]) return 3;
    return 4;
  };

  // Un nouveau mois n'affiche son label que s'il y a assez de colonnes depuis
  // le précédent (sinon "août"/"sept." se chevauchent quand l'historique
  // démarre à cheval sur un changement de mois) — mieux vaut l'omettre que
  // le faire se superposer au suivant.
  const MIN_COLS_BETWEEN_LABELS = 3;
  let lastMonth = -1;
  let lastLabelCol = -MIN_COLS_BETWEEN_LABELS;
  const monthLabels = weeks.map((wk, col) => {
    const m = new Date(wk[0].date).getUTCMonth();
    if (m === lastMonth) return "<span></span>";
    lastMonth = m;
    if (col - lastLabelCol < MIN_COLS_BETWEEN_LABELS) return "<span></span>";
    lastLabelCol = col;
    return `<span>${_HIST_MONTHS_FR[m]}</span>`;
  }).join("");

  const cols = weeks.map((wk) => {
    const cells = wk.map((day) => {
      const label = `${day.date} : ${Number(day.hours).toFixed(1)} h, ${Number(day.km).toFixed(1)} km`;
      return `<div class="hist-cell hl-${levelOf(day.hours)}" tabindex="0" role="img" aria-label="${esc(label)}"
         data-date="${day.date}" data-hours="${day.hours}" data-km="${day.km}"></div>`;
    }).join("");
    return `<div class="hist-col">${cells}</div>`;
  }).join("");

  return `
    <div class="hist-heatmap-wrap">
      <div class="hist-heatmap-months">${monthLabels}</div>
      <div class="hist-heatmap" id="hist-heatmap">${cols}</div>
      <div class="hist-heatmap-legend">
        <span>Moins</span>
        <span class="hist-cell hl-0"></span><span class="hist-cell hl-1"></span>
        <span class="hist-cell hl-2"></span><span class="hist-cell hl-3"></span>
        <span class="hist-cell hl-4"></span>
        <span>Plus</span>
      </div>
    </div>`;
}

// --------------------------------------------------------------------------
// Graphiques — lignes (dénivelé cumulé, FC moyenne)
// --------------------------------------------------------------------------
function buildLineChart(weekly, field, opts) {
  const W = 900, H = 200, PAD_L = 44, PAD_R = 16, PAD_T = 16, PAD_B = 24;
  const n = weekly.length;
  const points = weekly.map((w, i) => ({ i, v: w[field] })).filter((p) => p.v != null);
  if (!points.length) return '<p class="tip">Pas assez de données.</p>';

  const vals = points.map((p) => p.v);
  const minV = field === "avg_hr" ? Math.min(...vals) * 0.95 : 0;
  const maxV = niceMax(Math.max(...vals));
  const bandW = (W - PAD_L - PAD_R) / Math.max(1, n - 1);
  const x = (i) => PAD_L + i * bandW;
  const y = (v) => H - PAD_B - ((v - minV) / (maxV - minV || 1)) * (H - PAD_T - PAD_B);

  // Segmente en runs contigus : les trous (ex. semaines sans FC) ne sont jamais reliés.
  const runs = [];
  let cur = [], lastI = null;
  for (const p of points) {
    if (lastI !== null && p.i !== lastI + 1) { runs.push(cur); cur = []; }
    cur.push(p);
    lastI = p.i;
  }
  if (cur.length) runs.push(cur);

  const linePaths = runs.map((run) => `<path class="hist-line" stroke="${opts.color}" d="${
    run.map((p, k) => `${k === 0 ? "M" : "L"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ")
  }" />`).join("");

  // L'aire n'a de sens que pour une grandeur à zéro réel (dénivelé cumulé) :
  // pour la FC (pas de "zéro" significatif), une aire retomberait à un plancher
  // arbitraire à chaque trou de données et créerait des "tentes" trompeuses.
  const areaPaths = opts.area === false ? "" : runs.map((run) => {
    const d = `M${x(run[0].i).toFixed(1)},${y(minV).toFixed(1)} ` +
      run.map((p) => `L${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ") +
      ` L${x(run[run.length - 1].i).toFixed(1)},${y(minV).toFixed(1)} Z`;
    return `<path class="hist-area" fill="${opts.color}" d="${d}" />`;
  }).join("");

  const last = points[points.length - 1];
  const gridlines = [0, 0.5, 1].map((f) => {
    const yy = PAD_T + f * (H - PAD_T - PAD_B);
    const val = maxV - f * (maxV - minV);
    return `<line class="hist-grid" x1="${PAD_L}" x2="${W - PAD_R}" y1="${yy}" y2="${yy}" />
            <text class="hist-axis-label" x="${PAD_L - 6}" y="${yy + 3}" text-anchor="end">${val.toFixed(0)}</text>`;
  }).join("");

  const hitAreas = weekly.map((w, i) => {
    const aria = w[field] != null
      ? ` aria-label="${esc(`Semaine du ${w.week_start} : ${w[field].toFixed(0)} ${opts.unit}`)}"` : "";
    return `<rect class="hist-hit" tabindex="0" data-idx="${i}"${aria}
      x="${(x(i) - bandW / 2).toFixed(1)}" y="0" width="${bandW.toFixed(1)}" height="${H}" fill="transparent" />`;
  }).join("");

  const svgTitle = opts.title ? `${opts.title}, ${opts.unit}` : opts.unit;

  return `
    <svg class="hist-linechart" viewBox="0 0 ${W} ${H}" data-field="${field}" data-unit="${esc(opts.unit)}" role="img">
      <title>${esc(svgTitle)}</title>
      ${gridlines}
      ${areaPaths}
      ${linePaths}
      <circle class="hist-enddot" cx="${x(last.i)}" cy="${y(last.v)}" r="4" fill="${opts.color}" />
      <text class="hist-endlabel" x="${x(last.i) + 8}" y="${y(last.v) + 4}">${last.v.toFixed(0)} ${esc(opts.unit)}</text>
      <line class="hist-crosshair" x1="0" x2="0" y1="${PAD_T}" y2="${H - PAD_B}" style="display:none" />
      ${hitAreas}
    </svg>`;
}

// --------------------------------------------------------------------------
// Interactions — tooltip partagé + crosshair
// --------------------------------------------------------------------------
function historyTooltipEl() {
  let el = document.getElementById("hist-tooltip");
  if (!el) {
    el = document.createElement("div");
    el.id = "hist-tooltip";
    el.className = "hist-tooltip";
    el.style.display = "none";
    document.body.appendChild(el);
  }
  return el;
}

function showHistTooltip(evt, titleText, rows) {
  const el = historyTooltipEl();
  el.textContent = "";
  const title = document.createElement("div");
  title.className = "hist-tooltip-title";
  title.textContent = titleText;
  el.appendChild(title);
  rows.forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "hist-tooltip-row";
    const val = document.createElement("strong");
    val.textContent = value;
    row.appendChild(val);
    row.appendChild(document.createTextNode(" " + label));
    el.appendChild(row);
  });
  el.style.display = "block";
  // Sur un focus clavier, clientX/clientY valent 0 : on se replie sur le centre
  // du rectangle de l'élément focalisé au lieu de coller le tooltip en haut à gauche.
  let px = evt.clientX;
  let py = evt.clientY;
  if (evt.type === "focus" || (!px && !py)) {
    const target = evt.currentTarget || evt.target;
    if (target && target.getBoundingClientRect) {
      const rect = target.getBoundingClientRect();
      px = rect.left + rect.width / 2;
      py = rect.top + rect.height / 2;
    }
  }
  const x = (px || 0) + 14;
  const y = (py || 0) + 14;
  el.style.left = Math.min(x, window.innerWidth - el.offsetWidth - 10) + "px";
  el.style.top = Math.min(y, window.innerHeight - el.offsetHeight - 10) + "px";
}

function hideHistTooltip() {
  const el = document.getElementById("hist-tooltip");
  if (el) el.style.display = "none";
}

function wireHistoryInteractions(d) {
  document.querySelectorAll("#hist-bars .hist-bar").forEach((bar) => {
    const w = d.weekly[Number(bar.dataset.idx)];
    const show = (evt) => {
      bar.classList.add("is-active");
      showHistTooltip(evt, `Semaine du ${w.week_start}`,
        [["h", w.hours.toFixed(1)], ["km", w.km.toFixed(1)]]);
    };
    const hide = () => { bar.classList.remove("is-active"); hideHistTooltip(); };
    ["pointerenter", "pointermove", "focus"].forEach((ev) => bar.addEventListener(ev, show));
    ["pointerleave", "blur"].forEach((ev) => bar.addEventListener(ev, hide));
  });

  document.querySelectorAll("#hist-heatmap .hist-cell").forEach((cell) => {
    const show = (evt) => {
      cell.classList.add("is-active");
      showHistTooltip(evt, cell.dataset.date,
        [["h", Number(cell.dataset.hours).toFixed(1)], ["km", Number(cell.dataset.km).toFixed(1)]]);
    };
    const hide = () => { cell.classList.remove("is-active"); hideHistTooltip(); };
    ["pointerenter", "pointermove", "focus"].forEach((ev) => cell.addEventListener(ev, show));
    ["pointerleave", "blur"].forEach((ev) => cell.addEventListener(ev, hide));
  });

  document.querySelectorAll(".hist-linechart").forEach((svg) => {
    const field = svg.dataset.field;
    const unit = svg.dataset.unit;
    const crosshair = svg.querySelector(".hist-crosshair");
    svg.querySelectorAll(".hist-hit").forEach((hit) => {
      const w = d.weekly[Number(hit.dataset.idx)];
      const show = (evt) => {
        if (w[field] == null) return hide();
        if (crosshair) {
          const cx = (Number(hit.getAttribute("x")) + Number(hit.getAttribute("width")) / 2).toFixed(1);
          crosshair.setAttribute("x1", cx);
          crosshair.setAttribute("x2", cx);
          crosshair.style.display = "block";
        }
        showHistTooltip(evt, `Semaine du ${w.week_start}`, [[unit, w[field].toFixed(0)]]);
      };
      const hide = () => { hideHistTooltip(); if (crosshair) crosshair.style.display = "none"; };
      ["pointerenter", "pointermove", "focus"].forEach((ev) => hit.addEventListener(ev, show));
      ["pointerleave", "blur"].forEach((ev) => hit.addEventListener(ev, hide));
    });
  });
}
