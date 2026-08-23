"""Dashboard hebdomadaire visuel (HTML autonome, sans dépendance externe).

Montre : où tu en es dans le plan, la progression prévu vs réalisé, l'adhérence,
les séances de la semaine (ajustées) et le bilan de la semaine passée.

Le HTML est auto-suffisant (CSS + SVG inline) : lisible en pièce jointe email,
ou publiable tel quel en Artifact. Thème clair/sombre.
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


def _load_curve_svg(planned: List[float], actual: List[Optional[float]],
                    current: int) -> str:
    n = len(planned)
    # aligne défensivement les deux séries sur la longueur de `planned`
    actual = (list(actual) + [None] * n)[:n]
    W, H = 720, 200
    pad_b, pad_t = 24, 12
    bw = W / n
    top = max(planned + [a for a in actual if a] + [1])
    def y(v): return pad_t + (H - pad_t - pad_b) * (1 - v / top)
    bars = []
    for i in range(n):
        x = i * bw
        # prévu (barre claire)
        ph = y(planned[i])
        bars.append(
            f'<rect x="{x+bw*0.12:.1f}" y="{ph:.1f}" width="{bw*0.76:.1f}" '
            f'height="{H-pad_b-ph:.1f}" rx="1.5" class="planned"/>')
        # réalisé (barre pleine par-dessus)
        a = actual[i]
        if a is not None and a > 0:
            ah = y(a)
            bars.append(
                f'<rect x="{x+bw*0.12:.1f}" y="{ah:.1f}" width="{bw*0.76:.1f}" '
                f'height="{H-pad_b-ah:.1f}" rx="1.5" class="actual"/>')
        # marqueur semaine courante
        if i + 1 == current:
            bars.append(
                f'<rect x="{x+bw*0.06:.1f}" y="{pad_t-2:.1f}" width="{bw*0.88:.1f}" '
                f'height="{H-pad_b-pad_t+4:.1f}" rx="2" class="cur"/>')
        if (i + 1) % 4 == 0 or i == 0:
            bars.append(
                f'<text x="{x+bw/2:.1f}" y="{H-8:.1f}" class="xl">{i+1}</text>')
    grid = "".join(
        f'<line x1="0" y1="{y(v):.1f}" x2="{W}" y2="{y(v):.1f}" class="grid"/>'
        f'<text x="2" y="{y(v)-2:.1f}" class="yl">{v}h</text>'
        for v in range(0, int(top) + 1, 4) if v > 0)
    return (f'<svg viewBox="0 0 {W} {H}" class="chart" '
            f'preserveAspectRatio="xMidYMid meet" role="img" '
            f'aria-label="Charge prévue vs réalisée par semaine">'
            f'{grid}{"".join(bars)}</svg>')


def build(res: AdaptResult, last: WeekSummary,
          actual_hours: List[Optional[float]], today: Optional[date] = None) -> str:
    today = today or date.today()
    w = res.week
    idx = w.index
    planned = [program.planned_hours(pw) for pw in program.PROGRAM]
    jrs = program.days_to_race(today)
    ws, we = program.week_start(idx), program.week_end(idx)

    # séances de la semaine
    rows = ""
    for role in ordered_roles(w.sessions):
        spec = w.sessions[role]
        rows += (f'<tr><td class="d">{_esc(ROLE_DAY[role])}</td>'
                 f'<td>{_esc(workouts.label(spec))}</td>'
                 f'<td class="n">{workouts.minutes(spec)/60:.1f} h</td></tr>')

    adj = ""
    if res.adjustments:
        items = "".join(
            f'<li><b>{_esc(a.role)}</b> : {_esc(a.before)} → {_esc(a.after)} '
            f'<span class="muted">— {_esc(a.reason)}</span></li>'
            for a in res.adjustments)
        adj = f'<div class="adj"><h3>Ajustements</h3><ul>{items}</ul></div>'
    else:
        adj = '<div class="adj muted">Semaine appliquée telle que prévue.</div>'

    # bilan N-1
    if last.n_runs or last.planned_time_s:
        stats = "".join([
            _stat(f"{last.n_runs}", "sorties"),
            _stat(f"{last.actual_hours:.1f} h", "temps"),
            _stat(f"{last.adherence:.0%}", "adhérence",
                  cls=_adh_cls(last.adherence)),
            _stat(f"{last.total_dist_m/1000:.0f} km", "distance"),
            _stat(f"{last.total_elev_m:.0f} m", "D+"),
            _stat(f"{last.longest_run_s/60:.0f}′", "+ longue"),
            _stat(f"{last.acwr:.2f}" if last.acwr is not None else "—", "ACWR",
                  cls=_acwr_cls(last.acwr)),
        ])
    else:
        stats = '<p class="muted">Pas de données pour la semaine précédente.</p>'

    band_label = {
        "deload": "Décharge", "reprise": "Reprise", "consolide": "Consolidation",
        "nominal": "Nominal", "vigilance": "Vigilance",
    }.get(res.band, res.band)

    return _PAGE.format(
        idx=idx, n=program.N_WEEKS, phase=_esc(w.phase),
        note=_esc(w.note), band=_esc(band_label),
        dates=f"{ws.strftime('%d/%m')} – {we.strftime('%d/%m/%Y')}",
        jrs=jrs, total=f"{program.planned_hours(w):.1f}",
        msg=_esc(res.message), rows=rows, adj=adj, stats=stats,
        chart=_load_curve_svg(planned, actual_hours, idx),
    )


def _stat(value, label, cls=""):
    return (f'<div class="stat {cls}"><div class="sv">{_esc(value)}</div>'
            f'<div class="sl">{_esc(label)}</div></div>')


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


_PAGE = """<title>Semaine {idx} — Backyard Ultra</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700&family=Barlow:wght@400;500;600&family=IBM+Plex+Mono:wght@500;600&display=swap">
<style>
:root{{--ground:#f4f6ef;--surface:#fff;--ink:#1a2316;--muted:#5b6552;--hair:#e0e4d8;
--pine:#356338;--ember:#bf5527;--sage:#e7eede;--sage-ink:#4a6540;
--good:#3f7d3a;--warn:#c58a1e;--bad:#bf3b2b;--planned:#cdd8c0;--actual:#356338;}}
@media(prefers-color-scheme:dark){{:root:not([data-theme="light"]){{
--ground:#0f130c;--surface:#161b11;--ink:#e9eee1;--muted:#98a488;--hair:#2a3222;
--pine:#7cb377;--ember:#e07d43;--sage:#243019;--sage-ink:#a7c295;
--good:#7cb377;--warn:#d9a441;--bad:#e0715c;--planned:#39432c;--actual:#7cb377;}}}}
:root[data-theme="dark"]{{--ground:#0f130c;--surface:#161b11;--ink:#e9eee1;--muted:#98a488;
--hair:#2a3222;--pine:#7cb377;--ember:#e07d43;--sage:#243019;--sage-ink:#a7c295;
--good:#7cb377;--warn:#d9a441;--bad:#e0715c;--planned:#39432c;--actual:#7cb377;}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--ground);color:var(--ink);
font-family:"Barlow",system-ui,sans-serif;line-height:1.5}}
.wrap{{max-width:760px;margin:0 auto;padding:clamp(18px,4vw,40px)}}
.eyebrow{{font-family:"Barlow Condensed",sans-serif;text-transform:uppercase;
letter-spacing:.16em;color:var(--pine);font-weight:600;font-size:.8rem}}
h1{{font-family:"Barlow Condensed",sans-serif;font-weight:700;
font-size:clamp(2rem,6vw,3rem);margin:.1em 0;line-height:1}}
.sub{{color:var(--muted);margin:0 0 6px}}
.badges{{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}}
.badge{{font-family:"Barlow Condensed",sans-serif;font-weight:600;padding:5px 12px;
border-radius:999px;background:var(--surface);border:1px solid var(--hair)}}
.badge b{{color:var(--ember)}}
.card{{background:var(--surface);border:1px solid var(--hair);border-radius:14px;
padding:clamp(16px,3vw,24px);margin-top:18px}}
h2{{font-family:"Barlow Condensed",sans-serif;font-weight:700;font-size:1.35rem;margin:0 0 4px}}
h3{{font-family:"Barlow Condensed",sans-serif;font-size:1.05rem;margin:14px 0 6px}}
.coach{{background:var(--sage);color:var(--sage-ink);border-radius:10px;
padding:12px 14px;font-weight:500;margin:0 0 14px}}
table{{width:100%;border-collapse:collapse;font-size:.98rem}}
td{{padding:8px 6px;border-bottom:1px solid var(--hair)}}
td.d{{font-family:"Barlow Condensed",sans-serif;text-transform:uppercase;
font-size:.78rem;letter-spacing:.05em;color:var(--muted);width:70px}}
td.n{{text-align:right;font-family:"IBM Plex Mono",monospace;color:var(--pine);white-space:nowrap}}
.adj ul{{margin:0;padding-left:1.1em}} .adj li{{margin:.3em 0;font-size:.92rem}}
.muted{{color:var(--muted)}}
.chart{{width:100%;height:auto;margin-top:6px}}
.chart .planned{{fill:var(--planned)}} .chart .actual{{fill:var(--actual)}}
.chart .cur{{fill:none;stroke:var(--ember);stroke-width:1.5;stroke-dasharray:3 2}}
.chart .grid{{stroke:var(--hair);stroke-width:1}}
.chart .xl,.chart .yl{{fill:var(--muted);font-size:9px;font-family:"IBM Plex Mono",monospace}}
.chart .xl{{text-anchor:middle}}
.legend{{display:flex;gap:16px;margin-top:8px;font-size:.85rem;color:var(--muted)}}
.legend i{{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:5px;vertical-align:-1px}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(88px,1fr));gap:10px}}
.stat{{background:var(--ground);border:1px solid var(--hair);border-radius:10px;padding:10px;text-align:center}}
.sv{{font-family:"IBM Plex Mono",monospace;font-weight:600;font-size:1.15rem}}
.sl{{font-size:.72rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
.stat.good .sv{{color:var(--good)}} .stat.warn .sv{{color:var(--warn)}} .stat.bad .sv{{color:var(--bad)}}
footer{{margin-top:20px;text-align:center;color:var(--muted);font-size:.82rem}}
</style>
<div class="wrap">
  <div class="eyebrow">Backyard Ultra · coaching adaptatif</div>
  <h1>Semaine {idx} / {n}</h1>
  <p class="sub">{phase} — {note}</p>
  <div class="badges">
    <span class="badge">{dates}</span>
    <span class="badge">Statut <b>{band}</b></span>
    <span class="badge">Volume <b>{total} h</b></span>
    <span class="badge">Course dans <b>J-{jrs}</b></span>
  </div>

  <section class="card">
    <h2>Ta semaine</h2>
    <p class="coach">{msg}</p>
    <table>{rows}</table>
    {adj}
  </section>

  <section class="card">
    <h2>Progression — prévu vs réalisé</h2>
    {chart}
    <div class="legend">
      <span><i style="background:var(--planned)"></i>Prévu</span>
      <span><i style="background:var(--actual)"></i>Réalisé</span>
      <span><i style="background:transparent;border:1.5px dashed var(--ember)"></i>Semaine en cours</span>
    </div>
  </section>

  <section class="card">
    <h2>Semaine précédente</h2>
    <div class="stats">{stats}</div>
  </section>

  <footer>Généré automatiquement · plan indicatif, adapte selon ta forme.</footer>
</div>
"""
