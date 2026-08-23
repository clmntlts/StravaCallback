"""Dashboard hebdomadaire visuel (HTML autonome, sans dépendance externe).

Thème CLAIR unique, soigné et robuste en email : où tu en es dans le plan, la
progression prévu vs réalisé, l'adhérence, les séances de la semaine (ajustées)
et le bilan de la semaine passée.

Palette (light) — surface #ffffff / fond #f4f6f4 :
  ink #16211d · muted #5c6660 · accent (réalisé) #157a6e · référence (prévu) neutre
  statuts : good #2e7d46 · warn #b67514 · bad #c0392b   (toujours + libellé)
"""

from __future__ import annotations

import html
from datetime import date
from typing import List, Optional

from .adapt import ACWR_BRAKE, ACWR_CAUTION, ACWR_LOW, AdaptResult
from .models import ROLE_DAY, WeekSummary, ordered_roles
from . import program, workouts


def _esc(s) -> str:
    return html.escape(str(s))


# --------------------------------------------------------------------------- #
# Graphe de charge : prévu (référence neutre) vs réalisé (accent), 1 axe
# --------------------------------------------------------------------------- #
def _phase_segments():
    segs = []
    cur = None
    for i, w in enumerate(program.PROGRAM):
        if w.phase != cur:
            segs.append([w.phase, i, i])
            cur = w.phase
        else:
            segs[-1][2] = i
    return segs


def _load_curve_svg(planned: List[float], actual: List[Optional[float]],
                    current: int) -> str:
    n = len(planned)
    actual = (list(actual) + [None] * n)[:n]
    W, H = 760, 232
    L, R, T, B = 30, 8, 24, 26
    plotW, plotH = W - L - R, H - T - B
    bw = plotW / n
    top = max(planned + [a for a in actual if a] + [1])
    top = (int(top // 4) + 1) * 4  # arrondi sup. au multiple de 4 h

    def x(i): return L + i * bw
    def y(v): return T + plotH * (1 - v / top)

    parts = []
    # bandes de phase alternées (contexte, très désaturé) + libellés
    for k, (name, s, e) in enumerate(_phase_segments()):
        x0, x1 = x(s), x(e + 1)
        if k % 2 == 1:
            parts.append(f'<rect x="{x0:.1f}" y="{T}" width="{x1-x0:.1f}" '
                         f'height="{plotH:.1f}" class="band"/>')
        parts.append(f'<text x="{(x0+x1)/2:.1f}" y="{T-8:.1f}" class="ph">{_esc(name)}</text>')

    # grille horizontale + libellés d'axe
    for v in range(0, top + 1, 4):
        yy = y(v)
        parts.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" class="grid"/>')
        parts.append(f'<text x="{L-6}" y="{yy+3:.1f}" class="yl">{v}h</text>')

    # barres : prévu (référence large, neutre) + réalisé (accent, plus étroit)
    for i in range(n):
        cx = x(i) + bw / 2
        if i + 1 == current:
            parts.append(f'<rect x="{x(i)+1:.1f}" y="{T:.1f}" width="{bw-2:.1f}" '
                         f'height="{plotH:.1f}" class="cur"/>')
        pw = bw * 0.66
        ph_y = y(planned[i])
        parts.append(f'<rect x="{cx-pw/2:.1f}" y="{ph_y:.1f}" width="{pw:.1f}" '
                     f'height="{max(0,y(0)-ph_y):.1f}" rx="2" class="plan">'
                     f'<title>S{i+1} prévu {planned[i]:.1f} h</title></rect>')
        a = actual[i]
        if a is not None and a > 0:
            aw = bw * 0.40
            ay = y(a)
            parts.append(f'<rect x="{cx-aw/2:.1f}" y="{ay:.1f}" width="{aw:.1f}" '
                         f'height="{max(0,y(0)-ay):.1f}" rx="2" class="act">'
                         f'<title>S{i+1} réalisé {a:.1f} h</title></rect>')

    # axe des semaines
    parts.append(f'<line x1="{L}" y1="{y(0):.1f}" x2="{W-R}" y2="{y(0):.1f}" class="axis"/>')
    for i in range(n):
        if i == 0 or (i + 1) % 4 == 0:
            parts.append(f'<text x="{x(i)+bw/2:.1f}" y="{H-9:.1f}" class="xl">{i+1}</text>')

    return (f'<svg viewBox="0 0 {W} {H}" class="chart" '
            f'preserveAspectRatio="xMidYMid meet" role="img" '
            f'aria-label="Charge hebdomadaire prévue vs réalisée sur {n} semaines">'
            + "".join(parts) + "</svg>")


# --------------------------------------------------------------------------- #
def _stat(value, label, sub="", cls=""):
    sub = f'<div class="ks">{_esc(sub)}</div>' if sub else ""
    return (f'<div class="kpi {cls}"><div class="kv">{_esc(value)}</div>'
            f'<div class="kl">{_esc(label)}</div>{sub}</div>')


def _adh_cls(a):
    if a < 0.6:
        return "bad"
    if a < 0.85:
        return "warn"
    if a <= 1.15:
        return "good"
    return "warn"


def _acwr_cls(a):
    if a is None:
        return ""
    if a > ACWR_BRAKE or a < ACWR_LOW:
        return "bad"
    if a > ACWR_CAUTION:
        return "warn"
    return "good"


_BAND_LABEL = {
    "deload": "Décharge", "reprise": "Reprise", "consolide": "Consolidation",
    "nominal": "Nominal", "vigilance": "Vigilance", "verifier": "À vérifier",
}


def build(res: AdaptResult, last: WeekSummary,
          actual_hours: List[Optional[float]], today: Optional[date] = None) -> str:
    today = today or date.today()
    w = res.week
    idx = w.index
    planned = [program.planned_hours(pw) for pw in program.PROGRAM]
    jrs = program.days_to_race(today)
    ws, we = program.week_start(idx), program.week_end(idx)
    pct = round(100 * idx / program.N_WEEKS)

    # séances
    rows = ""
    for role in ordered_roles(w.sessions):
        spec = w.sessions[role]
        rows += (f'<tr><td class="d">{_esc(ROLE_DAY[role])}</td>'
                 f'<td>{_esc(workouts.label(spec))}</td>'
                 f'<td class="n">{workouts.minutes(spec)/60:.1f} h</td></tr>')

    if res.adjustments:
        items = "".join(
            f'<li><b>{_esc(a.role)}</b> {_esc(a.before)} → {_esc(a.after)} '
            f'<span class="muted">· {_esc(a.reason)}</span></li>'
            for a in res.adjustments)
        adj = f'<div class="adj"><div class="h3">Ajustements</div><ul>{items}</ul></div>'
    else:
        adj = '<div class="adj muted">Aucun ajustement — semaine telle que prévue.</div>'

    # KPI (this week volume + bilan N-1)
    has_prev = last.n_runs or last.planned_time_s
    kpis = _stat(f"{program.planned_hours(w):.1f} h", "Volume cette semaine",
                 f"statut : {_BAND_LABEL.get(res.band, res.band)}")
    if has_prev:
        kpis += _stat(f"{last.adherence:.0%}", "Adhérence N-1",
                      f"{last.actual_hours:.1f}h / {last.planned_hours:.1f}h",
                      cls=_adh_cls(last.adherence))
        kpis += _stat(f"{last.acwr:.2f}" if last.acwr is not None else "—",
                      "Charge aiguë/chronique",
                      "zone sûre 0,8–1,3", cls=_acwr_cls(last.acwr))
        kpis += _stat(f"{last.longest_run_s/60:.0f}′", "Plus longue N-1",
                      f"{last.n_runs} sorties · {last.total_dist_m/1000:.0f} km")
    else:
        kpis += _stat("—", "Semaine précédente", "pas de données")

    return _PAGE.format(
        idx=idx, n=program.N_WEEKS, phase=_esc(w.phase), pct=pct,
        note=_esc(w.note), dates=f"{ws.strftime('%d/%m')} – {we.strftime('%d/%m/%Y')}",
        jrs=jrs, msg=_esc(res.message), rows=rows, adj=adj, kpis=kpis,
        chart=_load_curve_svg(planned, actual_hours, idx),
    )


_PAGE = """<title>Semaine {idx} — Backyard Ultra</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
:root{{
  --ground:#f4f6f4; --surface:#ffffff; --raise:#fbfcfb;
  --ink:#16211d; --muted:#5c6660; --faint:#8a938c;
  --hair:#e4e8e4; --hair2:#eef1ee;
  --accent:#157a6e; --accent-ink:#0e5c53; --plan:#d3dad4;
  --good:#2e7d46; --warn:#b67514; --bad:#c0392b;
  --good-bg:#e9f3ec; --warn-bg:#f7efe0; --bad-bg:#f8e9e6;
  --shadow:0 1px 2px rgba(22,33,29,.05), 0 10px 26px -16px rgba(22,33,29,.22);
}}
*{{box-sizing:border-box}}
body{{margin:0; background:var(--ground); color:var(--ink);
  font-family:"Barlow",-apple-system,Segoe UI,Roboto,sans-serif; line-height:1.5;
  -webkit-font-smoothing:antialiased;}}
.wrap{{max-width:800px; margin:0 auto; padding:clamp(18px,4vw,40px)}}

.eyebrow{{font-family:"Barlow Condensed",sans-serif; text-transform:uppercase;
  letter-spacing:.16em; color:var(--accent-ink); font-weight:700; font-size:.78rem}}
h1{{font-family:"Barlow Condensed",sans-serif; font-weight:700;
  font-size:clamp(2rem,5.5vw,3rem); margin:.06em 0 .1em; line-height:1; letter-spacing:-.01em}}
.sub{{color:var(--muted); margin:0}}

.progress{{display:flex; align-items:center; gap:12px; margin:16px 0 6px}}
.progress .track{{flex:1; height:8px; border-radius:999px; background:var(--hair);
  overflow:hidden}}
.progress .fill{{height:100%; background:var(--accent); border-radius:999px}}
.progress .pt{{font-family:"IBM Plex Mono",monospace; font-size:.82rem; color:var(--muted);
  white-space:nowrap; font-variant-numeric:tabular-nums}}
.meta{{display:flex; flex-wrap:wrap; gap:8px; margin-top:6px}}
.pill{{font-family:"Barlow Condensed",sans-serif; font-weight:600; font-size:.86rem;
  padding:4px 11px; border-radius:999px; background:var(--surface);
  border:1px solid var(--hair); color:var(--muted)}}
.pill b{{color:var(--accent-ink)}}

.kpis{{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px;
  margin:18px 0}}
.kpi{{background:var(--surface); border:1px solid var(--hair); border-radius:14px;
  padding:14px 15px; box-shadow:var(--shadow); border-top:3px solid var(--hair)}}
.kpi.good{{border-top-color:var(--good); background:var(--good-bg)}}
.kpi.warn{{border-top-color:var(--warn); background:var(--warn-bg)}}
.kpi.bad{{border-top-color:var(--bad); background:var(--bad-bg)}}
.kv{{font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:1.7rem;
  line-height:1; font-variant-numeric:tabular-nums}}
.kl{{font-size:.82rem; color:var(--muted); margin-top:5px; font-weight:500}}
.ks{{font-size:.72rem; color:var(--faint); margin-top:2px}}

.card{{background:var(--surface); border:1px solid var(--hair); border-radius:16px;
  padding:clamp(16px,3vw,24px); margin-top:16px; box-shadow:var(--shadow)}}
.h2{{font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:1.35rem; margin:0 0 12px}}
.h3{{font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:1rem;
  margin:14px 0 6px; text-transform:uppercase; letter-spacing:.04em; color:var(--muted)}}
.coach{{border-left:3px solid var(--accent); background:var(--raise);
  padding:11px 14px; border-radius:0 10px 10px 0; margin:0 0 14px; font-weight:500}}

table{{width:100%; border-collapse:collapse; font-size:.98rem}}
td{{padding:9px 6px; border-bottom:1px solid var(--hair2)}}
tr:last-child td{{border-bottom:none}}
td.d{{font-family:"Barlow Condensed",sans-serif; text-transform:uppercase;
  font-size:.74rem; letter-spacing:.05em; color:var(--faint); width:74px}}
td.n{{text-align:right; font-family:"IBM Plex Mono",monospace; color:var(--accent-ink);
  white-space:nowrap; font-variant-numeric:tabular-nums}}
.adj{{margin-top:4px}} .adj ul{{margin:0; padding-left:1.05em}}
.adj li{{margin:.34em 0; font-size:.9rem}} .muted{{color:var(--muted)}}

.chart{{width:100%; height:auto; display:block; margin-top:4px}}
.chart .band{{fill:#eef1ee}}
.chart .grid{{stroke:var(--hair2); stroke-width:1}}
.chart .axis{{stroke:var(--hair); stroke-width:1.5}}
.chart .plan{{fill:var(--plan)}}
.chart .act{{fill:var(--accent)}}
.chart .cur{{fill:#fff5ed; stroke:#e0a35a; stroke-width:1; stroke-dasharray:3 2}}
.chart .yl{{fill:var(--faint); font-size:9px; text-anchor:end; font-family:"IBM Plex Mono",monospace}}
.chart .xl{{fill:var(--faint); font-size:9px; text-anchor:middle; font-family:"IBM Plex Mono",monospace}}
.chart .ph{{fill:var(--muted); font-size:9px; text-anchor:middle; font-family:"Barlow Condensed",sans-serif; letter-spacing:.03em}}
.legend{{display:flex; flex-wrap:wrap; gap:16px; margin-top:10px; font-size:.85rem; color:var(--muted)}}
.legend i{{display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:-1px}}

footer{{margin-top:22px; text-align:center; color:var(--faint); font-size:.8rem}}
</style>
<div class="wrap">
  <div class="eyebrow">Backyard Ultra · coaching adaptatif</div>
  <h1>Semaine {idx} <span style="color:var(--faint);font-weight:600">/ {n}</span></h1>
  <p class="sub">{phase} — {note}</p>

  <div class="progress">
    <span class="pt">Progression du plan</span>
    <span class="track"><span class="fill" style="width:{pct}%"></span></span>
    <span class="pt">{pct}%</span>
  </div>
  <div class="meta">
    <span class="pill">{dates}</span>
    <span class="pill">Course dans <b>J-{jrs}</b></span>
  </div>

  <div class="kpis">{kpis}</div>

  <section class="card">
    <div class="h2">Ta semaine</div>
    <p class="coach">{msg}</p>
    <table>{rows}</table>
    {adj}
  </section>

  <section class="card">
    <div class="h2">Progression — prévu vs réalisé</div>
    {chart}
    <div class="legend">
      <span><i style="background:var(--plan)"></i>Prévu (objectif)</span>
      <span><i style="background:var(--accent)"></i>Réalisé (Strava)</span>
      <span><i style="background:#fff5ed;border:1px dashed #e0a35a"></i>Semaine en cours</span>
    </div>
  </section>

  <footer>Généré automatiquement chaque dimanche · plan indicatif, adapte selon ta forme.</footer>
</div>
"""
