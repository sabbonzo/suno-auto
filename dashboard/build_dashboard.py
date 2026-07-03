# © Sabino Gervasio
"""
build_dashboard.py — Genera il cruscotto HTML dello stato pubblicazioni.

Legge dashboard/status.json (fonte di verità, aggiornabile a mano o da script)
e, se esiste MUSIC_DIR/suno_queue_master.json, aggiorna in automatico i
contatori della coda Suno. Output: dashboard/index.html (autonomo, zero
dipendenze, doppio tema chiaro/scuro).

Uso:
    python dashboard/build_dashboard.py                  # genera index.html
    python dashboard/build_dashboard.py --fragment f.html  # solo <body> interno
"""
import json
import os
import sys
from datetime import datetime
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATUS_FILE = HERE / "status.json"
OUT_FILE = HERE / "index.html"
MUSIC_DIR = Path(os.getenv("MUSIC_DIR", str(Path.home() / "MusicaBusiness")))

STATUS_META = {
    "live":        ("good",      "✓", "Live"),
    "in_progress": ("accent",    "▸", "In corso"),
    "in_review":   ("warning",   "⏳", "In review"),
    "pending":     ("warning",   "○", "Pendente"),
    "attention":   ("serious",   "!",      "Attenzione"),
    "blocked":     ("critical",  "×", "Bloccato"),
    "up":          ("good",      "✓", "UP"),
    "scheduled":   ("accent",    "▸", "Schedulato"),
}

CSS = """
:root {
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --hairline: #e1e0d9; --ring: rgba(11,11,11,0.10);
  --accent: #2a78d6; --track: #e1e0d9;
  --good: #0ca30c; --warning: #fab219; --serious: #ec835a; --critical: #d03b3b;
}
@media (prefers-color-scheme: dark) {
  :root {
    --page: #0d0d0d; --surface: #1a1a19;
    --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --hairline: #2c2c2a; --ring: rgba(255,255,255,0.10);
    --accent: #3987e5; --track: #2c2c2a;
  }
}
:root[data-theme="light"] {
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --hairline: #e1e0d9; --ring: rgba(11,11,11,0.10);
  --accent: #2a78d6; --track: #e1e0d9;
}
:root[data-theme="dark"] {
  --page: #0d0d0d; --surface: #1a1a19;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --hairline: #2c2c2a; --ring: rgba(255,255,255,0.10);
  --accent: #3987e5; --track: #2c2c2a;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  font-size: 15px; line-height: 1.5;
}
.wrap { max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }
header.top { display: flex; flex-wrap: wrap; align-items: baseline; gap: 8px 16px; margin-bottom: 28px; }
header.top h1 { font-size: 22px; font-weight: 650; margin: 0; letter-spacing: -0.01em; }
header.top .updated { color: var(--muted); font-size: 13px; }
.eyebrow {
  font-size: 11px; font-weight: 600; letter-spacing: 0.08em; text-transform: uppercase;
  color: var(--muted); margin: 36px 0 12px;
}
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; }
.kpi {
  background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
  padding: 14px 16px;
}
.kpi .v { font-size: 28px; font-weight: 650; letter-spacing: -0.01em; }
.kpi .l { font-size: 12px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--ink-2); }
.kpi .n { font-size: 12px; color: var(--muted); margin-top: 2px; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.card {
  background: var(--surface); border: 1px solid var(--ring); border-radius: 8px;
  padding: 16px; display: flex; flex-direction: column; gap: 10px;
}
.card .head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.card h3 { margin: 0; font-size: 15px; font-weight: 650; }
.card .platform { font-size: 12px; color: var(--muted); }
.chip {
  display: inline-flex; align-items: center; gap: 5px; flex: none;
  font-size: 12px; font-weight: 600; padding: 2px 9px; border-radius: 999px;
  border: 1px solid var(--ring); color: var(--ink);
}
.chip .dot { font-weight: 700; }
.chip.good     { background: color-mix(in srgb, var(--good) 14%, var(--surface)); }
.chip.good .dot { color: var(--good); }
.chip.accent   { background: color-mix(in srgb, var(--accent) 14%, var(--surface)); }
.chip.accent .dot { color: var(--accent); }
.chip.warning  { background: color-mix(in srgb, var(--warning) 18%, var(--surface)); }
.chip.warning .dot { color: color-mix(in srgb, var(--warning) 70%, var(--ink)); }
.chip.serious  { background: color-mix(in srgb, var(--serious) 18%, var(--surface)); }
.chip.serious .dot { color: color-mix(in srgb, var(--serious) 75%, var(--ink)); }
.chip.critical { background: color-mix(in srgb, var(--critical) 14%, var(--surface)); }
.chip.critical .dot { color: var(--critical); }
.meter { display: flex; align-items: center; gap: 10px; }
.meter .track { flex: 1; height: 8px; border-radius: 4px; background: var(--track); overflow: hidden; }
.meter .fill { height: 100%; border-radius: 4px; background: var(--accent); min-width: 2px; }
.meter .val { font-size: 13px; color: var(--ink-2); font-variant-numeric: tabular-nums; white-space: nowrap; }
.blockers { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 6px; }
.blockers li {
  font-size: 13px; color: var(--ink-2); padding-left: 18px; position: relative;
}
.blockers li::before {
  content: "\\00D7"; position: absolute; left: 2px; top: 0;
  color: var(--critical); font-weight: 700;
}
.next { font-size: 13px; color: var(--ink-2); border-top: 1px solid var(--hairline); padding-top: 10px; margin-top: auto; }
.next b { color: var(--ink); font-weight: 600; }
table.agents { width: 100%; border-collapse: collapse; background: var(--surface); border: 1px solid var(--ring); border-radius: 8px; overflow: hidden; }
table.agents th, table.agents td { text-align: left; padding: 10px 14px; font-size: 13px; border-top: 1px solid var(--hairline); }
table.agents th { border-top: none; font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); font-weight: 600; }
table.agents td.name { font-weight: 600; }
table.agents td.note { color: var(--muted); }
.tablewrap { overflow-x: auto; }
footer.note { margin-top: 40px; font-size: 12px; color: var(--muted); }
"""


def chip(status: str) -> str:
    cls, glyph, label = STATUS_META.get(status, ("warning", "?", status))
    return (f'<span class="chip {cls}"><span class="dot" aria-hidden="true">{glyph}</span>'
            f'{escape(label)}</span>')


def meter(done: int, total: int, unit: str) -> str:
    pct = 0 if total == 0 else round(done / total * 100)
    return (
        '<div class="meter" role="progressbar" '
        f'aria-valuenow="{done}" aria-valuemin="0" aria-valuemax="{total}">'
        f'<div class="track"><div class="fill" style="width:{pct}%"></div></div>'
        f'<span class="val">{done}/{total} {escape(unit)} · {pct}%</span></div>'
    )


def refresh_from_queue(data: dict) -> None:
    """Se la queue master locale esiste, aggiorna i contatori Suno live."""
    qf = MUSIC_DIR / "suno_queue_master.json"
    if not qf.exists():
        return
    try:
        queue = json.loads(qf.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    done = sum(1 for i in queue if i.get("done"))
    for p in data["projects"]:
        if p["id"] == "suno-pipeline":
            p["done"], p["total"] = done, len(queue)
    for k in data["kpi"]:
        if k["label"] == "Coda Suno":
            k["value"] = f"{done} / {len(queue)}"


def render(data: dict) -> tuple[str, str]:
    """Ritorna (head_inner, body_inner)."""
    blockers_count = sum(len(p.get("blockers", [])) for p in data["projects"])
    for k in data["kpi"]:
        if k["value"] == "auto":
            k["value"] = str(blockers_count)

    kpis = "".join(
        f'<div class="kpi"><div class="l">{escape(k["label"])}</div>'
        f'<div class="v">{escape(k["value"])}</div>'
        f'<div class="n">{escape(k.get("note", ""))}</div></div>'
        for k in data["kpi"]
    )

    cards = []
    for p in data["projects"]:
        blockers = "".join(f"<li>{escape(b)}</li>" for b in p.get("blockers", []))
        blockers_html = f'<ul class="blockers">{blockers}</ul>' if blockers else ""
        next_html = f'<div class="next"><b>Prossimo:</b> {escape(p["next"])}</div>' if p.get("next") else ""
        cards.append(
            '<article class="card">'
            f'<div class="head"><div><h3>{escape(p["name"])}</h3>'
            f'<div class="platform">{escape(p["platform"])}</div></div>{chip(p["status"])}</div>'
            f'{meter(p.get("done", 0), p.get("total", 1), p.get("unit", ""))}'
            f"{blockers_html}{next_html}</article>"
        )

    rows = "".join(
        f'<tr><td class="name">{escape(a["name"])}</td><td>{escape(a["role"])}</td>'
        f'<td>{chip(a["state"])}</td><td class="note">{escape(a.get("note", ""))}</td></tr>'
        for a in data["agents"]
    )

    body = f"""
<div class="wrap">
  <header class="top">
    <h1>Cruscotto Monetizzazione — Sabino</h1>
    <span class="updated">aggiornato al {escape(data["updated"])}</span>
  </header>

  <div class="eyebrow" style="margin-top:0">Sintesi</div>
  <section class="kpis">{kpis}</section>

  <div class="eyebrow">Progetti e pubblicazioni</div>
  <section class="grid">{"".join(cards)}</section>

  <div class="eyebrow">Agenti e infrastruttura</div>
  <div class="tablewrap"><table class="agents">
    <thead><tr><th>Agente</th><th>Ruolo</th><th>Stato</th><th>Note</th></tr></thead>
    <tbody>{rows}</tbody>
  </table></div>

  <footer class="note">Fonte: dashboard/status.json · rigenerato con
  build_dashboard.py · {escape(datetime.now().strftime("%Y-%m-%d %H:%M"))}</footer>
</div>
"""
    head = f'<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">' \
           f"<title>Cruscotto Monetizzazione</title><style>{CSS}</style>"
    return head, body


def main() -> None:
    data = json.loads(STATUS_FILE.read_text("utf-8"))
    refresh_from_queue(data)
    head, body = render(data)

    if len(sys.argv) >= 3 and sys.argv[1] == "--fragment":
        Path(sys.argv[2]).write_text(f"<style>{CSS}</style>\n{body}", "utf-8")
        print(f"Fragment scritto: {sys.argv[2]}")
        return

    OUT_FILE.write_text(
        f"<!doctype html>\n<html lang=\"it\">\n<head>{head}</head>\n<body>{body}</body>\n</html>\n",
        "utf-8",
    )
    print(f"Dashboard generata: {OUT_FILE}")


if __name__ == "__main__":
    main()
