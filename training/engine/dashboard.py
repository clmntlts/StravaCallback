"""Dashboard hebdomadaire visuel (HTML autonome, sans dépendance externe).

Sert aussi de CORPS d'email (cf. deliver.email_body_html) : tout est inline et
email-safe (styles dans <head>, valeurs littérales — pas de variables CSS que
Gmail retire). Thème clair unique.

Contenu : où tu en es dans le plan · prévu vs réalisé (avec la courbe d'ambition
du template) · adhérence / ACWR · séances ajustées + consignes spécifiques ·
cap de sécurité (garde-fous rendus visibles) · debrief de la semaine passée.

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

# Séances "longues/spécifiques" dont le volume est piloté par le plafond de sécurité.
_LONG_TEMPLATES = {"long", "runwalk", "backyard", "night", "b2b"}


def _esc(s) -> str:
    return html.escape(str(s))


# --------------------------------------------------------------------------- #
# Courbes de charge : ambition template (ligne) · prévu (barre neutre) ·
# réalisé (barre accent). Un seul axe.
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


def _nominal_hours() -> List[float]:
    """Heures/semaine du template à l'échelle 1.0 (l'ambition brute, avant mise
    à l'échelle sur le volume de l'athlète). Sert de plafond de référence."""
    return [program.planned_hours(program.build_week_scaled(i, 1.0))
            for i in range(1, program.N_WEEKS + 1)]


def _load_curve_svg(planned: List[float], actual: List[Optional[float]],
                    current: int, nominal: Optional[List[float]] = None) -> str:
    n = len(planned)
    actual = (list(actual) + [None] * n)[:n]
    nominal = (list(nominal) + [None] * n)[:n] if nominal else [None] * n
    W, H = 760, 236
    L, R, T, B = 30, 8, 26, 26
    plotW, plotH = W - L - R, H - T - B
    bw = plotW / n
    tops = planned + [a for a in actual if a] + [x for x in nominal if x] + [1]
    top = max(tops)
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
        parts.append(f'<text x="{(x0+x1)/2:.1f}" y="{T-9:.1f}" class="ph">{_esc(name)}</text>')

    # grille horizontale + libellés d'axe
    for v in range(0, top + 1, 4):
        yy = y(v)
        parts.append(f'<line x1="{L}" y1="{yy:.1f}" x2="{W-R}" y2="{yy:.1f}" class="grid"/>')
        parts.append(f'<text x="{L-6}" y="{yy+3:.1f}" class="yl">{v}h</text>')

    # surlignage de la semaine en cours (sous les barres)
    if 1 <= current <= n:
        i = current - 1
        parts.append(f'<rect x="{x(i)+1:.1f}" y="{T:.1f}" width="{bw-2:.1f}" '
                     f'height="{plotH:.1f}" rx="3" class="cur"/>')

    # barres : prévu (référence large, neutre) + réalisé (accent, plus étroit)
    for i in range(n):
        cx = x(i) + bw / 2
        pw = bw * 0.62
        ph_y = y(planned[i])
        parts.append(f'<rect x="{cx-pw/2:.1f}" y="{ph_y:.1f}" width="{pw:.1f}" '
                     f'height="{max(0,y(0)-ph_y):.1f}" rx="2" class="plan">'
                     f'<title>S{i+1} prévu {planned[i]:.1f} h</title></rect>')
        a = actual[i]
        if a is not None and a > 0:
            aw = bw * 0.36
            ay = y(a)
            parts.append(f'<rect x="{cx-aw/2:.1f}" y="{ay:.1f}" width="{aw:.1f}" '
                         f'height="{max(0,y(0)-ay):.1f}" rx="2" class="act">'
                         f'<title>S{i+1} réalisé {a:.1f} h</title></rect>')

    # courbe d'ambition (template, échelle 1.0) — ligne pointillée par-dessus
    pts = " ".join(f"{x(i)+bw/2:.1f},{y(nominal[i]):.1f}"
                   for i in range(n) if nominal[i] is not None)
    if pts:
        parts.append(f'<polyline class="ceil" points="{pts}"/>')

    # axe des semaines
    parts.append(f'<line x1="{L}" y1="{y(0):.1f}" x2="{W-R}" y2="{y(0):.1f}" class="axis"/>')
    for i in range(n):
        if i == 0 or (i + 1) % 4 == 0:
            parts.append(f'<text x="{x(i)+bw/2:.1f}" y="{H-9:.1f}" class="xl">{i+1}</text>')

    return (f'<svg viewBox="0 0 {W} {H}" class="chart" '
            f'preserveAspectRatio="xMidYMid meet" role="img" '
            f'aria-label="Charge hebdomadaire : ambition, prévu et réalisé sur {n} semaines">'
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


# --------------------------------------------------------------------------- #
# Consignes spécifiques (ravito, durabilité, discipline Z2) + marge cross-training
# --------------------------------------------------------------------------- #
def _tips_html(w) -> str:
    rows = ""
    for role in ordered_roles(w.sessions):
        t = workouts.tip(w.sessions[role])
        if t:
            rows += (f'<li><span class="tg">{_esc(role)}</span> {_esc(t)}</li>')
    if not rows:
        return ""
    cross = ""
    if not w.deload and w.phase not in ("Affûtage",):
        cross = (
            '<div class="xnote"><b>Marge des 4 jours — le cross-training.</b> '
            'Ton volume plafonne à 4 jours de course : ajoute 2–4 h/sem de '
            'vélo/elliptique (aérobie, sans impact) sur tes jours off. Ça compte '
            'dans ta charge de base, sans le risque d’un 5ᵉ jour de course. '
            'Priorité aux jambes fraîches pour le week-end longue/B2B.</div>')
    return ('<section class="card">'
            '<div class="h2">Consignes spécifiques</div>'
            f'<ul class="tips">{rows}</ul>{cross}</section>')


# --------------------------------------------------------------------------- #
# Cap de sécurité : rend VISIBLE l'écart entre l'ambition du plan et ce qui est
# réellement prescrit après garde-fous (échelle de bande + plafond de la longue).
# --------------------------------------------------------------------------- #
def _cap_html(res, last, idx) -> str:
    presc_w = res.week
    if presc_w.deload:
        return ""
    plan_w = program.PROGRAM[idx - 1]
    plan_h = program.planned_hours(plan_w)
    presc_h = program.planned_hours(presc_w)

    # sortie longue / sim : plan vs prescrit (minutes)
    def _long_min(week):
        vals = [workouts.minutes(s) for s in week.sessions.values()
                if s.template in _LONG_TEMPLATES]
        return max(vals) if vals else 0.0
    plan_long = _long_min(plan_w)
    presc_long = _long_min(presc_w)

    cap_adj = next((a for a in res.adjustments if "plafon" in a.reason.lower()), None)
    throttled = presc_h < plan_h * 0.95 or cap_adj is not None
    if not throttled:
        return ""

    max_loops = max((int(s.params.get("loops", 0))
                     for w in program.PROGRAM for s in w.sessions.values()
                     if s.template == "backyard"), default=0)

    lines = [
        f'<div class="capk"><span>{presc_h:.1f} h</span> prescrit '
        f'<span class="vs">vs {plan_h:.1f} h au plan</span></div>'
    ]
    if plan_long > 0:
        lines.append(
            f'<div class="capk"><span>{_hm_min(presc_long)}</span> sortie longue '
            f'<span class="vs">vs {_hm_min(plan_long)} visés</span></div>')
    body = "".join(lines)

    why = _esc(cap_adj.reason) if cap_adj else (
        "réduction de bande selon ton réalisé (adhérence / ACWR)")
    ref = ""
    if last is not None and last.longest_run_s:
        ref = f" Ta plus longue récente : {last.longest_run_s/60:.0f}′."
    forward = (
        f"Le plafond de sécurité **monte avec ta plus longue réelle** : "
        f"allonge-la régulièrement pour débloquer les gros sims "
        f"(le plan vise jusqu’à {max_loops} boucles).{ref}"
        if max_loops else "")

    return (
        '<section class="card cap">'
        '<div class="h2">Cap de sécurité <span class="tagline">garde-fous actifs</span></div>'
        f'<div class="capgrid">{body}</div>'
        f'<p class="capwhy"><b>Pourquoi&nbsp;:</b> {why}.</p>'
        + (f'<p class="capfwd">{_md_bold(forward)}</p>' if forward else "")
        + '</section>')


def _hm_min(minutes: float) -> str:
    """Durée en minutes → "1h45" / "45′"."""
    m = int(round(minutes))
    h, mm = divmod(m, 60)
    if h and mm:
        return f"{h}h{mm:02d}"
    if h:
        return f"{h}h"
    return f"{m}′"


def _md_bold(s: str) -> str:
    """Rend **gras** minimal sûr (le texte est déjà de source interne)."""
    out, bold = [], False
    for chunk in _esc(s).split("**"):
        out.append(f"<b>{chunk}</b>" if bold else chunk)
        bold = not bold
    return "".join(out)


def _analysis_html(analysis) -> str:
    if analysis is None:
        return ""
    obs = "".join(f"<li>{_esc(o)}</li>" for o in analysis.observations)
    rec = "".join(f"<li>{_esc(r)}</li>" for r in analysis.recommendations)
    trends = ""
    if getattr(analysis, "trends", None):
        tr = "".join(f"<li>{_esc(t)}</li>" for t in analysis.trends)
        trends = f'<div class="h3">Tendances (4 sem.)</div><ul class="trd">{tr}</ul>'
    return (
        '<section class="card">'
        '<div class="h2">Debrief de la semaine passée</div>'
        f'<p class="verdict">{_esc(analysis.headline)}</p>'
        f'<div class="h3">Constats</div><ul class="obs">{obs}</ul>'
        f'{trends}'
        f'<div class="h3">À travailler</div><ul class="rec">{rec}</ul>'
        '</section>')


def build(res: AdaptResult, last: WeekSummary,
          actual_hours: List[Optional[float]], analysis=None,
          today: Optional[date] = None) -> str:
    today = today or date.today()
    w = res.week
    idx = w.index
    planned = [program.planned_hours(pw) for pw in program.PROGRAM]
    nominal = _nominal_hours()
    jrs = program.days_to_race(today)
    ws, we = program.week_start(idx), program.week_end(idx)
    pct = round(100 * idx / program.N_WEEKS)

    # séances (+ consigne courte sous chaque libellé)
    rows = ""
    for role in ordered_roles(w.sessions):
        spec = w.sessions[role]
        rows += (f'<tr><td class="d">{_esc(ROLE_DAY[role])}</td>'
                 f'<td class="s">{_esc(workouts.label(spec))}</td>'
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
        cap=_cap_html(res, last, idx),
        tips=_tips_html(w),
        analysis=_analysis_html(analysis),
        chart=_load_curve_svg(planned, actual_hours, idx, nominal),
    )


_PAGE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Semaine {idx} — Backyard Ultra</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
*{{box-sizing:border-box}}
body{{margin:0; background:#eef1ee; color:#16211d;
  font-family:"Barlow",-apple-system,Segoe UI,Roboto,sans-serif; line-height:1.5;
  -webkit-font-smoothing:antialiased;}}
.wrap{{max-width:800px; margin:0 auto; padding:clamp(16px,4vw,40px)}}

/* Hero */
.hero{{background:#ffffff; border:1px solid #e0e5e0; border-radius:18px;
  padding:clamp(18px,3.4vw,26px); position:relative; overflow:hidden;
  box-shadow:0 1px 2px rgba(22,33,29,.05), 0 18px 40px -26px rgba(22,33,29,.30)}}
.hero:before{{content:""; position:absolute; left:0; top:0; bottom:0; width:5px;
  background:#157a6e}}
.eyebrow{{font-family:"Barlow Condensed",sans-serif; text-transform:uppercase;
  letter-spacing:.16em; color:#0e5c53; font-weight:700; font-size:.76rem}}
h1{{font-family:"Barlow Condensed",sans-serif; font-weight:700;
  font-size:clamp(2.1rem,5.6vw,3.1rem); margin:.04em 0 .08em; line-height:1; letter-spacing:-.01em}}
h1 .of{{color:#9aa39c; font-weight:600}}
.sub{{color:#41504a; margin:0; font-weight:500}}
.sub .ph{{display:inline-block; font-family:"Barlow Condensed",sans-serif;
  font-weight:700; text-transform:uppercase; letter-spacing:.05em; font-size:.82rem;
  color:#0e5c53; background:#e7f1ee; border:1px solid #cfe5df; border-radius:999px;
  padding:2px 10px; margin-right:8px}}

.progress{{margin:16px 0 8px}}
.progress .ptrow{{display:flex; justify-content:space-between; align-items:baseline;
  margin-bottom:6px}}
.progress .track{{width:100%; height:9px; border-radius:999px; background:#e4e8e4;
  overflow:hidden}}
.progress .fill{{display:block; height:9px; background:#157a6e; border-radius:999px;
  min-width:7px}}
.progress .pt{{font-family:"IBM Plex Mono",monospace; font-size:.8rem; color:#5c6660;
  white-space:nowrap; font-variant-numeric:tabular-nums}}
.meta{{display:flex; flex-wrap:wrap; gap:8px; margin-top:4px}}
.pill{{font-family:"Barlow Condensed",sans-serif; font-weight:600; font-size:.86rem;
  padding:4px 12px; border-radius:999px; background:#f6f8f6;
  border:1px solid #e0e5e0; color:#41504a}}
.pill b{{color:#0e5c53}}

.kpis{{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px;
  margin:16px 0}}
.kpi{{background:#ffffff; border:1px solid #e0e5e0; border-radius:14px;
  padding:14px 15px; box-shadow:0 1px 2px rgba(22,33,29,.05), 0 12px 28px -18px rgba(22,33,29,.24); border-top:3px solid #dfe4df}}
.kpi.good{{border-top-color:#2e7d46; background:#eaf4ed}}
.kpi.warn{{border-top-color:#b67514; background:#f8f0e1}}
.kpi.bad{{border-top-color:#c0392b; background:#f9eae7}}
.kv{{font-family:"IBM Plex Mono",monospace; font-weight:600; font-size:1.72rem;
  line-height:1; font-variant-numeric:tabular-nums}}
.kl{{font-size:.82rem; color:#41504a; margin-top:5px; font-weight:600}}
.ks{{font-size:.72rem; color:#8a938c; margin-top:2px}}

.card{{background:#ffffff; border:1px solid #e0e5e0; border-radius:16px;
  padding:clamp(16px,3vw,24px); margin-top:14px; box-shadow:0 1px 2px rgba(22,33,29,.05), 0 12px 28px -18px rgba(22,33,29,.24)}}
.h2{{font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:1.4rem;
  margin:0 0 12px; display:flex; align-items:baseline; gap:10px}}
.h2 .tagline{{font-family:"Barlow Condensed",sans-serif; font-size:.72rem;
  text-transform:uppercase; letter-spacing:.08em; font-weight:700; color:#b67514;
  background:#f8f0e1; border:1px solid #ecdcbd; border-radius:999px; padding:2px 9px}}
.h3{{font-family:"Barlow Condensed",sans-serif; font-weight:700; font-size:1rem;
  margin:14px 0 6px; text-transform:uppercase; letter-spacing:.04em; color:#5c6660}}
.coach{{border-left:3px solid #157a6e; background:#f6faf9;
  padding:11px 14px; border-radius:0 10px 10px 0; margin:0 0 14px; font-weight:500}}

table{{width:100%; border-collapse:collapse; font-size:.98rem}}
td{{padding:10px 6px; border-bottom:1px solid #eef1ee; vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
td.d{{font-family:"Barlow Condensed",sans-serif; text-transform:uppercase;
  font-size:.74rem; letter-spacing:.05em; color:#8a938c; width:74px}}
td.s{{font-weight:500}}
td.n{{text-align:right; font-family:"IBM Plex Mono",monospace; color:#0e5c53;
  white-space:nowrap; font-variant-numeric:tabular-nums; font-weight:600}}
.adj{{margin-top:8px}} .adj ul{{margin:0; padding-left:1.05em}}
.adj li{{margin:.34em 0; font-size:.9rem}} .muted{{color:#5c6660}}

/* Consignes */
ul.tips{{list-style:none; margin:0; padding:0}}
ul.tips li{{position:relative; padding:9px 0 9px 0; border-bottom:1px solid #eef1ee;
  font-size:.92rem; color:#2c3630}}
ul.tips li:last-child{{border-bottom:none}}
.tg{{display:inline-block; font-family:"Barlow Condensed",sans-serif; font-weight:700;
  text-transform:uppercase; letter-spacing:.05em; font-size:.68rem; color:#0e5c53;
  background:#e7f1ee; border-radius:5px; padding:1px 7px; margin-right:8px; vertical-align:1px}}
.xnote{{margin-top:12px; background:#f6faf9; border:1px solid #dcebe7;
  border-radius:10px; padding:12px 14px; font-size:.9rem; color:#2c3630}}
.xnote b{{color:#0e5c53}}

/* Cap de sécurité */
.card.cap{{background:#fdfaf4; border-color:#ecdcbd}}
.capgrid{{display:flex; flex-wrap:wrap; gap:10px 22px; margin:2px 0 10px}}
.capk{{font-size:.9rem; color:#5c6660}}
.capk span:first-child{{font-family:"IBM Plex Mono",monospace; font-weight:600;
  font-size:1.15rem; color:#8a5a12; margin-right:6px; font-variant-numeric:tabular-nums}}
.capk .vs{{color:#8a938c}}
.capwhy{{margin:6px 0 4px; font-size:.92rem}}
.capfwd{{margin:6px 0 0; font-size:.92rem; color:#2c3630; background:#fff; border:1px solid #ecdcbd;
  border-radius:10px; padding:10px 13px}}

.verdict{{font-family:"Barlow Condensed",sans-serif; font-weight:600; font-size:1.18rem;
  color:#0e5c53; margin:0 0 6px}}
ul.obs,ul.rec{{margin:2px 0 0; padding-left:1.05em}}
ul.obs li{{margin:.32em 0; font-size:.94rem}}
ul.trd{{margin:2px 0 0; padding-left:1.05em}}
ul.trd li{{margin:.3em 0; font-size:.92rem; color:#5c6660}}
ul.rec li{{margin:.36em 0; font-size:.94rem; font-weight:500}}
ul.rec li::marker{{color:#157a6e}}

.chart{{width:100%; height:auto; display:block; margin-top:2px}}
.chart .band{{fill:#f1f4f1}}
.chart .grid{{stroke:#eef1ee; stroke-width:1}}
.chart .axis{{stroke:#dfe4df; stroke-width:1.5}}
.chart .plan{{fill:#cfd6d0}}
.chart .act{{fill:#157a6e}}
.chart .ceil{{fill:none; stroke:#b67514; stroke-width:1.6; stroke-dasharray:4 3;
  stroke-linejoin:round; stroke-linecap:round; opacity:.8}}
.chart .cur{{fill:#fff5ed; stroke:#e0a35a; stroke-width:1; stroke-dasharray:3 2}}
.chart .yl{{fill:#8a938c; font-size:9px; text-anchor:end; font-family:"IBM Plex Mono",monospace}}
.chart .xl{{fill:#8a938c; font-size:9px; text-anchor:middle; font-family:"IBM Plex Mono",monospace}}
.chart .ph{{fill:#5c6660; font-size:9px; text-anchor:middle; font-family:"Barlow Condensed",sans-serif; letter-spacing:.03em}}
.legend{{display:flex; flex-wrap:wrap; gap:14px; margin-top:10px; font-size:.84rem; color:#5c6660}}
.legend i{{display:inline-block; width:12px; height:12px; border-radius:3px; margin-right:6px; vertical-align:-1px}}
.legend i.line{{height:0; border-radius:0; border-top:2px dashed #b67514; width:16px; vertical-align:3px}}

footer{{margin-top:20px; text-align:center; color:#8a938c; font-size:.8rem; line-height:1.6}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div class="eyebrow">Backyard Ultra · coaching adaptatif</div>
    <h1>Semaine {idx} <span class="of">/ {n}</span></h1>
    <p class="sub"><span class="ph">{phase}</span>{note}</p>

    <div class="progress">
      <div class="ptrow"><span class="pt">Progression du plan</span><span class="pt">{pct}%</span></div>
      <div class="track"><div class="fill" style="width:{pct}%"></div></div>
    </div>
    <div class="meta">
      <span class="pill">{dates}</span>
      <span class="pill">Course dans <b>J-{jrs}</b></span>
    </div>
  </div>

  <div class="kpis">{kpis}</div>

  <section class="card">
    <div class="h2">Ta semaine</div>
    <p class="coach">{msg}</p>
    <table>{rows}</table>
    {adj}
  </section>

  {cap}

  {tips}

  {analysis}

  <section class="card">
    <div class="h2">Progression — ambition, prévu &amp; réalisé</div>
    {chart}
    <div class="legend">
      <span><i class="line"></i>Ambition (template)</span>
      <span><i style="background:#cfd6d0"></i>Prévu (ton volume)</span>
      <span><i style="background:#157a6e"></i>Réalisé (Strava)</span>
      <span><i style="background:#fff5ed;border:1px dashed #e0a35a"></i>Semaine en cours</span>
    </div>
  </section>

  <footer>Généré automatiquement chaque dimanche · plan indicatif, adapte selon ta forme.</footer>
</div>
</body>
</html>
"""
