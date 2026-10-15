"""G1b human spot-check page: 30 rendered SATB strips with their labels (PIYA-106 Phase 1, ml-cv-lead 6b).

Why: the automatic SVG check compares glyph counts and staff positions, but it cannot tell whether a rule is
musically right (e.g. whether a courtesy signature belongs after the barline, or whether a treble-8vb tenor
should be labelled clef.G-L2). A person reads 30 strips against their token chips. Pass rule (plan): 0
systematic errors; any fix means a fresh sample of 30.

Strips are cut straight from the rendered page PNG with the SVG staff geometry and a generous vertical margin,
across the full page width (so first-system staff names are visible). This checks labels, not Stage 1/2 cutting.
Only renders that passed the SVG check are sampled. Selection is stratified: 6 strips per font, and every G1b
case in the plan is covered where the corpus has it (cases with no candidate are listed on the page).

Usage: python training/phase1/g1b_page.py --out D:/PiyaNota-training/data/phase1_renders [--seed 1]
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import random
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

FONTS: tuple[str, ...] = ("Leipzig", "Bravura", "Gootville", "Leland", "Petaluma")
N_STRIPS = 30
MARGIN_STAFF_HEIGHTS = 1.6       # above and below the staff: room for ledger notes, fermatas and lyrics
TOKEN_RE = re.compile(r"^(.*)-([LS]-?\d+)$")

CASES: dict[str, str] = {
    "tie_across_break": "Tie across a system break (slur.end after the clef+key of the new system)",
    "tied_accidental_after_break": "Accidental on a tied note continued after the break",
    "key_change_at_break": "Key change at a system break, courtesy signature at the end of this system",
    "key_change_header": "Key change at a system break, new key in this system's header",
    "meter_change_at_break": "Meter change at a system break (courtesy at system end)",
    "meter_change_mid": "Constructed meter change inside a system",
    "key_change_mid": "Key change inside a system (incl. cancelling naturals to no key)",
    "multirest": "Multirest (full-choir rest, digits above the staff)",
    "carried_accidental": "Accidental carried within a bar (later note, no glyph)",
    "cancelling_natural": "Cancelling natural inside a bar",
    "cautionary_accidental": "Cautionary accidental (restates the key after an altered bar)",
    "tenor_8vb": "Treble-8vb tenor: labelled clef.G-L2 with positions as drawn",
    "first_system_label": "First system: staff name drawn, not labelled",
    "breve": "Breve (double whole) note or rest",
    "clef_normalised": "Source clef normalised (alto to treble, tenor to treble-8vb; no C clefs)",
}
# Divisi arm G1b (freeze doc section 5): only these cases, only strips with a chordnote (--divisi).
CHORD_CASES: dict[str, str] = {
    "chord_dyad": "Two-note chord: lowest head as note.*, the other as chordnote-<pos>",
    "chord_triad": "Three-note chord: two chordnote tokens, bottom to top",
    "chord_dotted": "Dotted chord: one dot per head, after the chordnote tokens",
    "chord_accidental": "Accidental on a chord member (accidentals bottom to top, before the note)",
    "chord_ledger": "Chord member on a ledger line, above or below the staff",
}
CASES.update(CHORD_CASES)
# Cases that only arise from Palestrina's source handling; the Bach page never lists them as missing.
PALESTRINA_ONLY: frozenset[str] = frozenset({"breve", "clef_normalised"})


@dataclass
class Strip:
    font: str
    piece: str
    page: int
    system: int
    voice: str
    tokens: list[str]
    case: str
    render_dir: Path


def _split(tok: str) -> tuple[str, str]:
    m = TOKEN_RE.match(tok)
    return (m.group(1), m.group(2)) if m else (tok, "")


def _bars(tokens: list[str]) -> list[list[str]]:
    bars: list[list[str]] = [[]]
    for t in tokens:
        bars[-1].append(t)
        if t.startswith("barline"):
            bars.append([])
    return bars


def _is_note(name: str) -> bool:
    return name.startswith(("note.", "gracenote."))


def _body_start(tokens: list[str]) -> int:
    """Index of the first token after the clef/key/meter header."""
    i = 0
    while i < len(tokens) and tokens[i].startswith(("clef.", "accidental.", "digit.", "metersign.")):
        i += 1
    return i


def _accidental_cases(tokens: list[str]) -> set[str]:
    found: set[str] = set()
    body = tokens[_body_start(tokens):]
    prev_bar: dict[str, str] = {}
    for bar in _bars(body):
        shown: dict[str, str] = {}
        pending: str | None = None
        for t in bar:
            name, pos = _split(t)
            if name.startswith("accidental."):
                pending = name.split(".", 1)[1]
            elif _is_note(name):
                if pending is not None:
                    if pending == "natural":
                        found.add("cancelling_natural")
                    if pos in prev_bar and prev_bar[pos] != pending and pos not in shown:
                        found.add("cautionary_accidental")
                    shown[pos] = pending
                elif pos in shown:
                    found.add("carried_accidental")
                pending = None
            elif name.startswith(("slur.", "dot", "fermata")):
                continue
            else:
                pending = None
        prev_bar = shown
    return found


def strip_cases(tokens: list[str], prev_tokens: list[str] | None, system: int, voice: str,
                plan: dict[str, object], systems: list[list[int]]) -> set[str]:
    cases = _accidental_cases(tokens)
    names = [_split(t)[0] for t in tokens]
    if any(n.endswith(".double_whole") or n.startswith("rest.double_whole") for n in names):
        cases.add("breve")
    if str(plan.get("composer")) == "palestrina" and voice in ("Alto", "Tenor"):
        cases.add("clef_normalised")
    body = names[_body_start(tokens):]
    first_note = next((i for i, n in enumerate(body) if _is_note(n)), None)
    if first_note is not None and "slur.end" in body[:first_note]:
        cases.add("tie_across_break")
        if prev_tokens is not None:
            last_start = max((i for i, t in enumerate(prev_tokens) if t.startswith("slur.start")), default=None)
            if last_start is not None and last_start >= 2 and prev_tokens[last_start - 2].startswith("accidental."):
                cases.add("tied_accidental_after_break")
    if "multirest" in names:
        cases.add("multirest")
    if voice == "Tenor":
        cases.add("tenor_8vb")
    if system == 0:
        cases.add("first_system_label")
    measures = systems[system]
    nxt = systems[system + 1][0] if system + 1 < len(systems) else None
    for key, kind in (("key_change", "key"), ("meter_change", "meter")):
        event = plan.get(key)
        if not isinstance(event, dict) or "measure_index" not in event:
            continue
        idx = event["measure_index"]
        if event.get("at_break"):
            if idx == nxt:
                cases.add(f"{kind}_change_at_break")
            if kind == "key" and idx == measures[0]:
                cases.add("key_change_header")
        elif idx in measures[1:]:
            cases.add(f"{kind}_change_mid")
    return cases


def _ledger(pos: str) -> bool:
    """Positions needing a ledger line: L0 and below, L6 and above, S-1 and below, S6 and above."""
    n = int(pos[1:])
    return n <= (0 if pos[0] == "L" else -1) or n >= 6


def chord_cases(tokens: list[str]) -> set[str]:
    found: set[str] = set()
    for i, t in enumerate(tokens):
        if not t.startswith("chordnote-"):
            continue
        pos = _split(t)[1]
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        prev = tokens[i - 1]
        if not (prev.startswith("chordnote-") or nxt.startswith("chordnote-")):
            found.add("chord_dyad")
        if nxt.startswith("chordnote-"):
            found.add("chord_triad")
        if nxt.startswith("dot"):
            found.add("chord_dotted")
        if _ledger(pos):
            found.add("chord_ledger")
        j = i - 1
        while j >= 0 and tokens[j].startswith(("chordnote-", "note.")):
            j -= 1
        while j >= 0 and tokens[j].startswith("accidental."):
            if _split(tokens[j])[1] == pos:
                found.add("chord_accidental")
            j -= 1
    return found


def collect(out: Path, composer: str, divisi: bool = False) -> list[Strip]:
    strips: list[Strip] = []
    for font in FONTS:
        for render_dir in sorted((out / "renders" / font).glob(f"{composer}_*")):
            labels_path, plan_path = render_dir / "labels.json", out / "corpus" / f"{render_dir.name}.plan.json"
            if not labels_path.exists() or not plan_path.exists():
                continue
            rows = json.loads(labels_path.read_text(encoding="utf-8"))
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            by_key = {(r["voice"], r["system"]): r for r in rows}
            for r in rows:
                if r.get("quarantine"):
                    continue   # OOV strip (vocab_guard): never used for training, so not worth a hand check
                prev = by_key.get((r["voice"], r["system"] - 1))
                found = (chord_cases(r["tokens"]) if divisi else
                         strip_cases(r["tokens"], prev["tokens"] if prev else None, r["system"], r["voice"], plan,
                                     plan["systems"]))
                for case in found:
                    strips.append(Strip(font, render_dir.name, r["page"], r["system"], r["voice"], r["tokens"],
                                        case, render_dir))
    return strips


def select(strips: list[Strip], rng: random.Random, n_strips: int,
           cases: list[str]) -> tuple[list[Strip], list[str]]:
    """Equal share per font; cases filled round-robin so each available case appears at least once, rarest first."""
    per_case: dict[str, list[Strip]] = {c: [] for c in cases}
    for s in strips:
        if s.case in per_case:
            per_case[s.case].append(s)
    missing = [c for c, v in per_case.items() if not v]
    # The Palestrina-only cases (breve, normalised clef) are what a Palestrina page exists to check, and they are
    # common there, so rarest-first alone would drop them from a 10-strip page. Bach has none, so its order is unchanged.
    order = sorted((c for c in cases if per_case[c]), key=lambda c: (c not in PALESTRINA_ONLY, len(per_case[c])))
    per_font_quota = -(-n_strips // len(FONTS))
    chosen: list[Strip] = []
    used: set[tuple[str, str, int, str]] = set()
    font_count = {f: 0 for f in FONTS}
    rounds = 0
    while len(chosen) < n_strips and rounds < 50:
        rounds += 1
        for case in order:
            if len(chosen) >= n_strips:
                break
            options = [s for s in per_case[case] if font_count[s.font] < per_font_quota
                       and (s.font, s.piece, s.system, s.voice) not in used]
            if not options:
                continue
            least = min(font_count[s.font] for s in options)
            s = rng.choice([o for o in options if font_count[o.font] == least])
            chosen.append(s)
            used.add((s.font, s.piece, s.system, s.voice))
            font_count[s.font] += 1
    return chosen, missing


def crop(strip: Strip) -> str:
    meta = json.loads((strip.render_dir / "meta.json").read_text(encoding="utf-8"))
    box = next(b for b in meta["staff_boxes_px"] if b["system"] == strip.system
               and b["staff_n"] == str(("Soprano", "Alto", "Tenor", "Bass").index(strip.voice) + 1))
    img = Image.open(strip.render_dir / f"page_{strip.page}.png").convert("L")
    height = box["bottom"] - box["top"]
    top = max(0, int(box["top"] - MARGIN_STAFF_HEIGHTS * height))
    bottom = min(img.height, int(box["bottom"] + MARGIN_STAFF_HEIGHTS * height))
    buf = io.BytesIO()
    img.crop((0, top, img.width, bottom)).save(buf, format="PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def chip_kind(tok: str) -> str:
    name = _split(tok)[0]
    for prefix, kind in (("clef", "clef"), ("accidental", "acc"), ("digit", "num"), ("metersign", "num"),
                         ("multirest", "num"), ("note", "note"), ("gracenote", "note"), ("rest", "rest"),
                         ("barline", "bar"), ("slur", "tie"), ("dot", "dot"), ("fermata", "tie")):
        if name.startswith(prefix):
            return kind
    return "other"


PAGE_CSS = """
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--muted:#666;--line:#ddd;--clef:#e8e0ff;--acc:#ffe3e3;--num:#fff0c8;
--note:#e1f0ff;--rest:#e9e9e9;--bar:#d9d9d9;--tie:#dff5e3;--dot:#f3e8ff;--other:#eee;--ok:#1a7f37}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#161616;--card:#222;--ink:#eee;--muted:#aaa;
--line:#3a3a3a;--clef:#3b3260;--acc:#5a2a2a;--num:#57481c;--note:#1f3b5a;--rest:#3a3a3a;--bar:#444;--tie:#1f4a2a;
--dot:#44305a;--other:#333;--ok:#4ac26b}}
:root[data-theme="dark"]{--bg:#161616;--card:#222;--ink:#eee;--muted:#aaa;--line:#3a3a3a;--clef:#3b3260;--acc:#5a2a2a;
--num:#57481c;--note:#1f3b5a;--rest:#3a3a3a;--bar:#444;--tie:#1f4a2a;--dot:#44305a;--other:#333;--ok:#4ac26b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
main{max-width:1100px;margin:0 auto;padding:16px}h1{font-size:1.3rem;margin:.2em 0}.muted{color:var(--muted)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px;margin:14px 0}
.imgwrap{overflow-x:auto;background:#fff;border-radius:6px;border:1px solid var(--line)}
.imgwrap img{display:block;width:100%;height:auto;cursor:zoom-in}.imgwrap.full img{width:auto;max-width:none;cursor:zoom-out}
.chips{display:flex;flex-wrap:wrap;gap:4px;margin:10px 0}.chip{font:12px/1.2 ui-monospace,monospace;padding:3px 6px;
border-radius:5px;border:1px solid var(--line)}.clef{background:var(--clef)}.acc{background:var(--acc)}
.num{background:var(--num)}.note{background:var(--note)}.rest{background:var(--rest)}.bar{background:var(--bar)}
.tie{background:var(--tie)}.dot{background:var(--dot)}.other{background:var(--other)}
.meta{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:.9rem}.case{font-weight:600}
.row{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-top:8px}textarea{width:100%;min-height:44px;
background:var(--bg);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:6px;font:inherit}
button{font:inherit;padding:8px 14px;border-radius:8px;border:1px solid var(--line);background:var(--card);color:var(--ink);cursor:pointer}
.bar-top{position:sticky;top:0;background:var(--bg);padding:8px 0;display:flex;flex-wrap:wrap;gap:10px;align-items:center;z-index:2}
label.ok{color:var(--ok);font-weight:600}
"""

PAGE_JS = """
const KEY='g1b-phase1-v1';
function load(){try{return JSON.parse(localStorage.getItem(KEY)||'{}')}catch(e){console.warn('storage read failed',e);return {}}}
function save(s){try{localStorage.setItem(KEY,JSON.stringify(s))}catch(e){console.warn('storage write failed',e)}}
const state=load();
function progress(){const n=document.querySelectorAll('.card[data-id]').length;
 const d=Object.values(state).filter(v=>v&&v.ok).length;document.getElementById('prog').textContent=d+' / '+n+' marked correct';}
document.querySelectorAll('.card[data-id]').forEach(card=>{const id=card.dataset.id;const cb=card.querySelector('input');
 const ta=card.querySelector('textarea');const st=state[id]||{};cb.checked=!!st.ok;ta.value=st.note||'';
 const upd=()=>{state[id]={ok:cb.checked,note:ta.value};save(state);progress();};cb.addEventListener('change',upd);
 ta.addEventListener('input',upd);card.querySelector('.imgwrap').addEventListener('click',e=>e.currentTarget.classList.toggle('full'));});
progress();
document.getElementById('export').addEventListener('click',()=>{const out=[...document.querySelectorAll('.card[data-id]')].map(c=>({
 id:c.dataset.id,...JSON.parse(c.dataset.info),ok:!!(state[c.dataset.id]||{}).ok,note:(state[c.dataset.id]||{}).note||''}));
 const blob=new Blob([JSON.stringify({exported:new Date().toISOString(),results:out},null,1)],{type:'application/json'});
 const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='g1b_results.json';a.click();URL.revokeObjectURL(a.href);});
"""


def build_html(chosen: list[Strip], missing: list[str], seed: int, title: str) -> str:
    cards: list[str] = []
    for i, s in enumerate(chosen, 1):
        sid = f"{s.font}|{s.piece}|{s.system}|{s.voice}"
        info = {"font": s.font, "piece": s.piece, "page": s.page, "system": s.system, "voice": s.voice,
                "case": s.case, "tokens": s.tokens}
        chips = "".join(f'<span class="chip {chip_kind(t)}">{html.escape(t)}</span>' for t in s.tokens)
        cards.append(
            f'<section class="card" data-id="{html.escape(sid)}" data-info="{html.escape(json.dumps(info))}">'
            f'<div class="imgwrap"><img alt="strip {i}" src="data:image/png;base64,{crop(s)}"></div>'
            f'<div class="meta"><span class="case">#{i} {html.escape(CASES[s.case])}</span></div>'
            f'<div class="meta muted"><span>font {s.font}</span><span>piece {html.escape(s.piece)}</span>'
            f'<span>page {s.page}</span><span>system {s.system + 1}</span><span>voice {s.voice}</span>'
            f'<span>{len(s.tokens)} tokens</span></div>'
            f'<div class="chips">{chips}</div>'
            f'<div class="row"><label class="ok"><input type="checkbox"> labels match the strip</label></div>'
            f'<textarea placeholder="Note (what is wrong, token index...)"></textarea></section>')
    missing_html = ("<p><b>Cases with no candidate in the passed renders:</b> "
                    + ", ".join(html.escape(CASES[c]) for c in missing) + "</p>") if missing else ""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>G1b Label Check</title>'
            f'<style>{PAGE_CSS}</style></head><body><main><h1>{html.escape(title)}</h1>'
            f'<p class="muted">{len(chosen)} strips, spread evenly over the 5 fonts, sampled with seed {seed} from '
            'renders that passed '
            'the automatic SVG check. Read each strip left to right against its chips (one per token). Tick when '
            'every token matches what is drawn; otherwise write the token and what is wrong. Staff names, lyrics '
            'and titles are drawn but never labelled. The tenor is labelled from the drawn treble clef '
            '(clef.G-L2), not the sounding octave. Tap an image to toggle 1:1 zoom. Pass rule: 0 systematic '
            'errors.</p><p class="muted">Known gaps, not tested here: repeat signs are stripped from the renders '
            '(BUG-040) and beams across a system break cannot be built (BUG-041).</p>'
            f'{missing_html}<div class="bar-top"><button id="export">Export results (JSON)</button>'
            f'<span id="prog" class="muted"></span></div>{"".join(cards)}</main><script>{PAGE_JS}</script>'
            '</body></html>')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--composer", default="bach", help="piece-id prefix to sample from (bach or palestrina)")
    parser.add_argument("--n", type=int, default=N_STRIPS)
    parser.add_argument("--name", default="g1b", help="output folder under --out")
    parser.add_argument("--divisi", action="store_true", help="divisi arm: sample only chord strips, chord cases")
    args = parser.parse_args()
    rng = random.Random(args.seed)
    if args.divisi:
        cases = list(CHORD_CASES)
    else:
        cases = [c for c in CASES if c not in CHORD_CASES
                 and (args.composer == "palestrina" or c not in PALESTRINA_ONLY)]
    chosen, missing = select(collect(args.out, args.composer, args.divisi), rng, args.n, cases)
    page_dir = args.out / args.name
    page_dir.mkdir(parents=True, exist_ok=True)
    title = (f"G1b label spot-check ({args.composer.capitalize()} "
             f"{'divisi-arm injected chords' if args.divisi else 'Phase 1 renders'})")
    (page_dir / "index.html").write_text(build_html(chosen, missing, args.seed, title), encoding="utf-8")
    manifest = [{"font": s.font, "piece": s.piece, "page": s.page, "system": s.system, "voice": s.voice,
                 "case": s.case, "tokens": s.tokens} for s in chosen]
    (page_dir / "selection.json").write_text(json.dumps({"seed": args.seed, "missing_cases": missing,
                                                         "strips": manifest}, indent=1), encoding="utf-8")
    counts: dict[str, int] = {}
    for s in chosen:
        counts[s.case] = counts.get(s.case, 0) + 1
    print(f"{len(chosen)} strips; per case {counts}; missing {missing}")


if __name__ == "__main__":
    main()
