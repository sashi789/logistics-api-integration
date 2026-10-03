"""Build a single self-contained HTML dashboard from the reporting views.

    python -m etl.dashboard            # writes exports/dashboard.html

No JS libraries, no CDN, no BI tool: charts are inline SVG generated here, so the file
opens offline, diffs cleanly and can be attached to an email or uploaded as a CI artifact.
"""
import html
import json
import math
import pathlib
from datetime import datetime, timezone

from etl.db import connect

OUT = pathlib.Path("exports/dashboard.html")
SLA_MINUTES = 30
STALE_AFTER_MINUTES = 35  # SLA plus a little slack for delayed scheduler runs

# outcome groups for the stacked bar; each maps canonical statuses -> one reader-friendly bucket
GROUPS = [
    ("Delivered", ("DELIVERED",), "var(--good)"),
    ("In motion", ("CREATED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"), "var(--series-1)"),
    ("Delayed", ("DELAYED",), "var(--warning)"),
    ("Exception", ("EXCEPTION",), "var(--critical)"),
    ("Unknown", ("UNKNOWN",), "var(--muted)"),
]
SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"]  # fixed order, one per partner


def esc(value):
    return html.escape(str(value), quote=True)


def tip(title, rows):
    """tooltip payload; rows = [(label, value, color_or_None)]. Rendered client-side with textContent."""
    return esc(json.dumps({"t": title, "r": [list(r) for r in rows]}))


def fetch(cur, sql):
    cur.execute(sql)
    cols = [c[0] for c in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def load_data():
    with connect() as conn, conn.cursor() as cur:
        return {
            "status": fetch(cur, "SELECT * FROM v_status_by_partner"),
            "delivery": fetch(cur, "SELECT * FROM v_delivery_time ORDER BY partner"),
            "freshness": fetch(cur, "SELECT * FROM v_feed_freshness ORDER BY partner"),
            "delayed": fetch(cur, "SELECT * FROM v_delayed_shipments ORDER BY hours_past_eta DESC NULLS LAST"),
            "daily": fetch(cur, """
                SELECT p.name AS partner, date_trunc('day', e.event_ts)::date AS day, COUNT(*) AS events
                FROM shipment_events e JOIN shipments s USING (shipment_id) JOIN partners p USING (partner_id)
                GROUP BY 1, 2 ORDER BY 2"""),
            "runs": fetch(cur, """
                SELECT p.name AS partner, r.started_at, r.status, r.rows_fetched, r.events_loaded
                FROM etl_run_log r JOIN partners p USING (partner_id)
                ORDER BY r.started_at DESC LIMIT 8"""),
        }


def nice_max(v):
    """Round up to 1/2/3/4/6/8/10 x 10^n so quarter gridlines land on readable ticks."""
    if v <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(v))
    return next(m * mag for m in (1, 2, 3, 4, 6, 8, 10) if m * mag >= v)


# ------------------------------------------------------------------ chart pieces
def bar_path(x, y, w, h, r=4, round_left=False, round_right=True):
    """Horizontal bar: square at the baseline (left), 4px rounded data end (right)."""
    r = min(r, w / 2, h / 2)
    rl, rr = (r if round_left else 0), (r if round_right else 0)
    return (f"M{x + rl:.1f},{y:.1f}H{x + w - rr:.1f}"
            f"{'a%g,%g 0 0 1 %g,%g' % (rr, rr, rr, rr) if rr else ''}V{y + h - rr:.1f}"
            f"{'a%g,%g 0 0 1 %g,%g' % (rr, rr, -rr, rr) if rr else ''}H{x + rl:.1f}"
            f"{'a%g,%g 0 0 1 %g,%g' % (rl, rl, -rl, -rl) if rl else ''}V{y + rl:.1f}"
            f"{'a%g,%g 0 0 1 %g,%g' % (rl, rl, rl, -rl) if rl else ''}Z")


def stacked_outcomes(data):
    partners = sorted({r["partner"] for r in data["status"]})
    counts = {p: {g[0]: 0 for g in GROUPS} for p in partners}
    for r in data["status"]:
        for name, statuses, _ in GROUPS:
            if r["status"] in statuses:
                counts[r["partner"]][name] += r["shipments"]
    used = [g for g in GROUPS if any(counts[p][g[0]] for p in partners)]

    left, right, row_h, bar_h, gap = 150, 24, 44, 24, 2
    width, height = 720, 16 + row_h * len(partners)
    inner = width - left - right
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Shipment outcomes by partner, share of shipments">']
    for i, p in enumerate(partners):
        total = sum(counts[p].values()) or 1
        y = 8 + i * row_h + (row_h - bar_h) / 2
        out.append(f'<text x="0" y="{y + 16:.0f}" class="lbl">{esc(p)}</text>')
        x = left
        segs = [g for g in used if counts[p][g[0]]]
        for j, (name, _, color) in enumerate(segs):
            n = counts[p][name]
            w = inner * n / total
            seg_w = max(w - (gap if j < len(segs) - 1 else 0), 1)
            t = tip(p, [(name, f"{n} shipments ({n / total:.0%})", color)])
            out.append(f'<path class="mark" d="{bar_path(x, y, seg_w, bar_h, round_left=False, round_right=(j == len(segs) - 1))}" '
                       f'fill="{color}" data-tip="{t}" tabindex="0"/>')
            label = f"{n / total:.0%}"
            if seg_w > 46 and name in ("Delivered", "In motion"):  # only label what fits with padding
                out.append(f'<text x="{x + seg_w / 2:.1f}" y="{y + 16:.1f}" text-anchor="middle" class="inlbl" pointer-events="none">{label}</text>')
            x += w
    out.append("</svg>")
    legend = "".join(f'<span class="key"><i style="background:{c}"></i>{esc(n)}</span>' for n, _, c in used)
    table = rows_table(["Partner"] + [g[0] for g in used],
                       [[p] + [counts[p][g[0]] for g in used] for p in partners])
    return "".join(out), legend, table, counts


def hbar_chart(items, unit, label, width=720):
    """items = [(name, value)]; single hue, value at the bar tip."""
    left, row_h, bar_h = 130, 44, 24
    height = 30 + row_h * len(items)  # extra room under the bars for axis labels
    vmax = nice_max(max(v for _, v in items) if items else 1)
    inner = width - left - 80
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{esc(label)}">']
    for frac in (0.25, 0.5, 0.75, 1):
        gx = left + inner * frac
        out.append(f'<line x1="{gx:.1f}" x2="{gx:.1f}" y1="4" y2="{height - 18}" class="grid"/>'
                   f'<text x="{gx:.1f}" y="{height - 4}" text-anchor="middle" class="axis">{vmax * frac:g}</text>')
    out.append(f'<line x1="{left}" x2="{left}" y1="4" y2="{height - 18}" class="base"/>')
    for i, (name, v) in enumerate(items):
        y = 8 + i * row_h + (row_h - bar_h) / 2
        w = max(inner * v / vmax, 2)
        out.append(f'<text x="0" y="{y + 16:.0f}" class="lbl">{esc(name)}</text>'
                   f'<path class="mark" d="{bar_path(left, y, w, bar_h)}" fill="var(--series-1)" '
                   f'data-tip="{tip(name, [(label, f"{v:g} {unit}", "var(--series-1)")])}" tabindex="0"/>'
                   f'<text x="{left + w + 8:.1f}" y="{y + 16:.0f}" class="val">{v:g} {unit}</text>')
    out.append("</svg>")
    return "".join(out)


def daily_lines(data):
    days = sorted({r["day"] for r in data["daily"]})
    partners = sorted({r["partner"] for r in data["daily"]})
    if len(days) < 2:
        return None, "", ""
    vals = {(r["partner"], r["day"]): r["events"] for r in data["daily"]}
    vmax = nice_max(max(vals.values()))
    left, top, width, height, bottom = 40, 12, 720, 240, 28
    iw, ih = width - left - 24, height - top - bottom
    xs = {d: left + iw * i / (len(days) - 1) for i, d in enumerate(days)}
    y_of = lambda v: top + ih - ih * v / vmax
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Tracking events per day by partner">']
    for k in range(5):
        v = vmax * k / 4
        out.append(f'<line x1="{left}" x2="{width - 24}" y1="{y_of(v):.1f}" y2="{y_of(v):.1f}" class="{"base" if k == 0 else "grid"}"/>'
                   f'<text x="{left - 8}" y="{y_of(v) + 4:.1f}" text-anchor="end" class="axis">{v:g}</text>')
    step = max(len(days) // 6, 1)
    for i, d in enumerate(days):
        if i % step == 0 or i == len(days) - 1:
            out.append(f'<text x="{xs[d]:.1f}" y="{height - 8}" text-anchor="middle" class="axis">{d:%b %d}</text>')
    for color, p in zip(SERIES, partners):
        pts = " ".join(f"{xs[d]:.1f},{y_of(vals.get((p, d), 0)):.1f}" for d in days)
        out.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>')
        d = days[-1]
        out.append(f'<circle cx="{xs[d]:.1f}" cy="{y_of(vals.get((p, d), 0)):.1f}" r="4" fill="{color}" stroke="var(--surface)" stroke-width="2"/>')
    out.append(f'<line id="xh" class="xh" y1="{top}" y2="{top + ih}" x1="0" x2="0" visibility="hidden"/>')
    colw = iw / (len(days) - 1)
    for d in days:  # one wide hit column per day so the pointer finds the X, not the line
        rows = [(p, f"{vals.get((p, d), 0)} events", c) for c, p in zip(SERIES, partners)]
        out.append(f'<rect class="hit" x="{xs[d] - colw / 2:.1f}" y="{top}" width="{colw:.1f}" height="{ih}" fill="transparent" '
                   f'data-x="{xs[d]:.1f}" data-tip="{tip(f"{d:%a %b %d}", rows)}" tabindex="0"/>')
    out.append("</svg>")
    legend = "".join(f'<span class="key"><i style="background:{c}"></i>{esc(p)}</span>' for c, p in zip(SERIES, partners))
    table = rows_table(["Day"] + partners, [[f"{d:%Y-%m-%d}"] + [vals.get((p, d), 0) for p in partners] for d in days])
    return "".join(out), legend, table


def rows_table(head, rows, cls=""):
    th = "".join(f"<th>{esc(h)}</th>" for h in head)
    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f'<table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


# ------------------------------------------------------------------ status chips (icon + label, never color alone)
CHIP = {"good": ("✓", "Fresh"), "warning": ("▲", "Stale"), "critical": ("✕", "Failing")}


def chip(kind, text):
    return f'<span class="chip {kind}"><b aria-hidden="true">{CHIP[kind][0]}</b>{esc(text)}</span>'


def freshness_table(data):
    rows = []
    for r in data["freshness"]:
        m, f = r["minutes_since_success"], r["failures_last_24h"]
        if m is None:
            state = chip("critical", "Never succeeded")
        elif m > STALE_AFTER_MINUTES:
            state = chip("warning", "Stale")
        else:
            state = chip("good", "Fresh")
        rows.append(f"<tr><td>{esc(r['partner'])}</td><td>{state}</td>"
                    f"<td class='num'>{'–' if m is None else f'{m:g} min ago'}</td><td class='num'>{f}</td></tr>")
    return ("<table><thead><tr><th>Partner</th><th>State</th><th class='num'>Last success</th>"
            f"<th class='num'>Failures (24h)</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")


def delayed_table(data, limit=10):
    rows = []
    for r in data["delayed"][:limit]:
        h = r["hours_past_eta"]
        kind = "critical" if r["status"] == "EXCEPTION" else "warning"
        icon, word = ("✕", "Exception") if kind == "critical" else ("▲", "Delayed")
        if r["status"] not in ("EXCEPTION", "DELAYED"):
            word = "Past ETA"
        rows.append(f"<tr><td>{esc(r['partner'])}</td><td>{esc(r['tracking_no'])}</td>"
                    f"<td><span class='chip {kind}'><b aria-hidden='true'>{icon}</b>{esc(word)}</span></td>"
                    f"<td>{esc(r['origin'])} → {esc(r['destination'])}</td>"
                    f"<td class='num'>{'–' if h is None else f'{h:g} h'}</td></tr>")
    return ("<table><thead><tr><th>Partner</th><th>Tracking</th><th>State</th><th>Route</th>"
            f"<th class='num'>Hours past ETA</th></tr></thead><tbody>{''.join(rows)}</tbody></table>")


def kpi(label, value, note=""):
    return f'<div class="tile"><div class="tl">{esc(label)}</div><div class="tv">{esc(value)}</div><div class="tn">{esc(note)}</div></div>'


# ------------------------------------------------------------------ page
CSS = """
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;
--grid:#e1e0d9;--base:#c3c2b7;--ring:rgba(11,11,11,.10);--series-1:#2a78d6;--series-2:#eb6834;--series-3:#1baf7a;
--good:#0ca30c;--warning:#fab219;--critical:#d03b3b;--good-ink:#006300;--warn-ink:#8a5a00;--crit-ink:#a82a2a}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;
--ink2:#c3c2b7;--grid:#2c2c2a;--base:#383835;--ring:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;
--good-ink:#0ca30c;--warn-ink:#fab219;--crit-ink:#ec6b6b}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#2c2c2a;--base:#383835;
--ring:rgba(255,255,255,.10);--series-1:#3987e5;--series-2:#d95926;--series-3:#199e70;--good-ink:#0ca30c;--warn-ink:#fab219;--crit-ink:#ec6b6b}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1040px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:22px;margin:0 0 2px}h2{font-size:15px;margin:0 0 2px}.sub{color:var(--ink2);margin:0 0 16px;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin-bottom:16px}
.tile,.card{background:var(--surface);border:1px solid var(--ring);border-radius:12px;padding:16px}
.tl{color:var(--ink2);font-size:13px}.tv{font-size:34px;font-weight:600;line-height:1.15;margin-top:2px}.tn{color:var(--muted);font-size:12px;margin-top:2px}
.card{margin-bottom:16px}.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:16px}.grid2 .card{margin:0}
svg{width:100%;height:auto;display:block;margin-top:8px;overflow:visible}
.lbl{fill:var(--ink);font-size:13px}.val{fill:var(--ink);font-size:13px;font-weight:600}.axis{fill:var(--muted);font-size:11px}
.inlbl{fill:#fff;font-size:12px;font-weight:600}.grid{stroke:var(--grid);stroke-width:1}.base{stroke:var(--base);stroke-width:1}
.xh{stroke:var(--muted);stroke-width:1}.mark{transition:opacity .1s}.mark:hover,.mark:focus{opacity:.8;outline:none}
.legend{display:flex;flex-wrap:wrap;gap:4px 16px;margin-top:8px;color:var(--ink2);font-size:12px}
.key{display:inline-flex;align-items:center;gap:6px}.key i{width:10px;height:10px;border-radius:2px;display:inline-block}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:8px}th{color:var(--ink2);font-weight:500;text-align:left}
th,td{padding:8px 10px;border-bottom:1px solid var(--grid)}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}details{margin-top:8px;color:var(--ink2);font-size:12px}summary{cursor:pointer}
.chip{display:inline-flex;align-items:center;gap:6px;font-weight:500}.chip b{font-size:11px}
.chip.good{color:var(--good-ink)}.chip.warning{color:var(--warn-ink)}.chip.critical{color:var(--crit-ink)}
#tt{position:fixed;pointer-events:none;background:var(--surface);color:var(--ink);border:1px solid var(--ring);border-radius:8px;
padding:8px 10px;font-size:12px;box-shadow:0 4px 16px rgba(0,0,0,.15);display:none;z-index:9;max-width:260px}
#tt .tt{color:var(--ink2);margin-bottom:4px}#tt .row{display:flex;align-items:center;gap:8px}
#tt .row i{width:12px;height:2px;display:inline-block}#tt .row b{font-weight:600}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]) .inlbl{fill:#0b0b0b}}
:root[data-theme="dark"] .inlbl{fill:#0b0b0b}
"""

JS = """
const tt=document.getElementById('tt'),xh=document.getElementById('xh');
function show(el,ev){const d=JSON.parse(el.dataset.tip);tt.replaceChildren();
 const t=document.createElement('div');t.className='tt';t.textContent=d.t;tt.append(t);
 for(const [l,v,c] of d.r){const r=document.createElement('div');r.className='row';
  if(c){const i=document.createElement('i');i.style.background=c;r.append(i)}
  const b=document.createElement('b');b.textContent=v;const s=document.createElement('span');s.textContent=l;r.append(b,s);tt.append(r)}
 tt.style.display='block';const p=ev.clientX?ev:{clientX:el.getBoundingClientRect().x+8,clientY:el.getBoundingClientRect().y};
 tt.style.left=Math.min(p.clientX+14,innerWidth-tt.offsetWidth-8)+'px';tt.style.top=(p.clientY+14)+'px';
 if(el.dataset.x&&xh){xh.setAttribute('x1',el.dataset.x);xh.setAttribute('x2',el.dataset.x);xh.setAttribute('visibility','visible')}}
function hide(){tt.style.display='none';if(xh)xh.setAttribute('visibility','hidden')}
document.querySelectorAll('[data-tip]').forEach(el=>{el.addEventListener('pointermove',e=>show(el,e));
 el.addEventListener('pointerleave',hide);el.addEventListener('focus',e=>show(el,e));el.addEventListener('blur',hide)});
"""


def card(title, subtitle, body, legend="", table=""):
    det = f'<details><summary>View as table</summary><div class="scroll">{table}</div></details>' if table else ""
    leg = f'<div class="legend">{legend}</div>' if legend else ""
    return f'<section class="card"><h2>{esc(title)}</h2><p class="sub">{esc(subtitle)}</p>{body}{leg}{det}</section>'


def build(data):
    stacked, stacked_legend, stacked_table, counts = stacked_outcomes(data)
    total = sum(sum(c.values()) for c in counts.values())
    delivered = sum(c["Delivered"] for c in counts.values())
    at_risk = len(data["delayed"])
    fresh = sum(1 for r in data["freshness"] if r["minutes_since_success"] is not None and r["minutes_since_success"] <= STALE_AFTER_MINUTES)
    n_feeds = len(data["freshness"])
    failures = sum(r["failures_last_24h"] for r in data["freshness"])

    delivery_items = [(r["partner"], float(r["avg_hours_to_deliver"])) for r in data["delivery"]]
    delivery_chart = hbar_chart(delivery_items, "h", "Average hours to deliver", width=460)
    delivery_table = rows_table(["Partner", "Delivered", "Avg hours"],
                                [[r["partner"], r["delivered_shipments"], r["avg_hours_to_deliver"]] for r in data["delivery"]])
    line, line_legend, line_table = daily_lines(data)
    runs = rows_table(["Partner", "Started (UTC)", "Status", "Fetched", "New events"],
                      [[r["partner"], f"{r['started_at']:%Y-%m-%d %H:%M}", r["status"], r["rows_fetched"], r["events_loaded"]]
                       for r in data["runs"]])
    now = datetime.now(timezone.utc)
    parts = [
        '<h1>Logistics tracking – pipeline &amp; shipment health</h1>',
        f'<p class="sub">Generated {now:%Y-%m-%d %H:%M} UTC from the reporting views · mock carrier data</p>',
        '<div class="tiles">',
        kpi("Shipments tracked", f"{total:,}", f"across {len(counts)} partners"),
        kpi("Delivered", f"{delivered / total:.0%}" if total else "–", f"{delivered:,} of {total:,}"),
        kpi("Needing attention", f"{at_risk}", "delayed, exception or past ETA"),
        kpi("Feeds within SLA", f"{fresh}/{n_feeds}", f"{failures} failed runs in last 24h · SLA {SLA_MINUTES} min"),
        '</div>',
        card("Shipment outcomes by partner", "Share of each partner's shipments by current state", stacked, stacked_legend, stacked_table),
        '<div class="grid2">',
        card("Average time to deliver", "Hours from first event to delivery, delivered shipments only", delivery_chart, "", delivery_table),
        card("Feed health", f"Is each partner's data fresh? Stale after {STALE_AFTER_MINUTES} min without a successful run",
             freshness_table(data)),
        '</div>',
    ]
    if line:
        parts.append(card("Tracking events per day", "New tracking events received, by partner", line, line_legend, line_table))
    parts += [
        card("Shipments needing attention", f"Top {min(10, at_risk)} of {at_risk}, most overdue first", f'<div class="scroll">{delayed_table(data)}</div>'),
        card("Recent pipeline runs", "Last 8 runs from etl_run_log", f'<div class="scroll">{runs}</div>'),
    ]
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>Logistics pipeline dashboard</title><style>{CSS}</style></head><body><main>{"".join(parts)}</main>'
            f'<div id="tt" role="status"></div><script>{JS}</script></body></html>')


if __name__ == "__main__":
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(build(load_data()), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")
