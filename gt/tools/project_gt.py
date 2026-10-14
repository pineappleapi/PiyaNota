"""Builds both scored GT versions of a Phase 4 piece from its one gt_source.txt (PIYA-106, SER-15 plan Amendment 8.5).

v1 ("without divisi") is what the dev build_gt.py builds: every <OOV:...> region is one <OOV> wildcard.
v2 ("with divisi") expands <OOV:chord ...> and <OOV:splitstem ...> into the arm's chord tokens; triplet and twovoice
regions stay <OOV> (tuplets and different-rhythm split stems are cut from arm v1, divisi freeze section 1).
The spec of the source format is gt/tools/PHASE4_GT_FORMAT.md. Nobody hand-edits the outputs.

Firewall (Amendment 8.4): this prints validity results only, never divisi/interval/voice counts.

Usage (repo root):
  python gt/tools/project_gt.py gt/<piece>        writes gt/<piece>/{v1,v2}/gt.json (+ a copy of gt_source.txt,
                                                  which score_eval.load_gt reads for clef/key)
  python gt/tools/project_gt.py --parity          self-check: v1 equals the committed dev gt.json on the dev pieces
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SHARP_ORDER, FLAT_ORDER = "FCGDAEB", "BEADGCF"
# key-signature glyph positions (PrIMuS agnostic), per clef, in printed order
KEY_POS = {"G": {"#": ["L5", "S3", "S5", "L4", "S2", "S4", "L3"], "b": ["L3", "S4", "S2", "L4", "S1", "S3", "L2"]},
           "F": {"#": ["L4", "S2", "S4", "L3", "S1", "S3", "L2"], "b": ["L2", "S3", "S1", "L3", "L1", "S2", "S0"]}}
DUR = {"w": 1920, "h": 960, "q": 480, "e": 240, "s": 120}
DOTMUL = {0: 1.0, 1: 1.5, 2: 1.75}  # a second dot adds a quarter of the base value, not another half
DURNAME = {"w": "whole", "h": "half", "q": "quarter", "e": "eighth", "s": "sixteenth"}
LET = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
SEMI = [0, 2, 4, 5, 7, 9, 11]
BASE_STEP = {"G": 30, "F": 18}  # diatonic index (oct*7+letter) at the bottom line
ACCNAME = {"^": "sharp", "_": "flat", "=": "natural"}
OOV_KINDS = ("chord", "splitstem", "triplet", "twovoice")  # seconds are derived from member steps, not tagged
EXPANDED = ("chord", "splitstem")
FERMATA_TOKEN = "fermata.above-S6"  # music_to_agnostic.FERMATA_ABOVE_POSITION: S6 whatever the note height
# Dev pieces whose gt.json was built by the build_gt.py this file was copied from (DSMN uses another builder).
# piece -> whether its committed gt.json was built with --common-time (read off its meter tokens)
PARITY_PIECES = {"non_nobis_domine": True, "honneur_a_toi": True, "gaano_ko_ikaw_kamahal": False, "handog": False}


def step_of(p: str, clef: str) -> int:
    return int(p[1:]) * 7 + LET[p[0]] - BASE_STEP[clef]


def pos(step: int) -> str:  # agnostic staff position suffix
    return f"L{step // 2 + 1}" if step % 2 == 0 else f"S{(step + 1) // 2}"


def dot_pos(step: int) -> str:  # a line note's dot sits in the space above (CPM)
    return f"S{step // 2 + 1}"


def parse_key(tok: str) -> tuple[int, str]:
    m = re.fullmatch(r"key:(\d)([#b])", tok)  # sign always written (key:0# = no key): score_eval.load_gt needs it
    assert m, tok
    return int(m[1]), m[2]


def key_tokens(clef: str, n: int, sign: str) -> list[str]:
    return [f"accidental.{'sharp' if sign == '#' else 'flat'}-{p}" for p in KEY_POS[clef][sign][:n]]


def meter_tokens(tok: str, common_time: bool) -> tuple[list[str], int]:
    """time:N/D, time:C or time:C/ -> (tokens, bar ticks). --common-time keeps the dev 4/4-as-C convention."""
    v = tok.split(":", 1)[1]
    if v == "C" or (v == "4/4" and common_time):
        return ["metersign.C-L3"], 1920
    if v == "C/":
        return ["metersign.C/-L3"], 1920
    m = re.fullmatch(r"(\d+)/(\d+)", v)
    assert m, tok
    return [f"digit.{m[1]}-L4", f"digit.{m[2]}-L2"], int(m[1]) * 1920 // int(m[2])


def parse_line(line: str) -> dict[str, Any]:
    head, body = line.split(": ", 1)
    m = re.match(r"p(\d+)s(\d+) (\w+)", head)
    page, sysi, voice = int(m[1]), int(m[2]), m[3]
    if body.startswith("<EXCLUDED"):
        return dict(page=page, sys=sysi, voice=voice, excluded=body)
    n_slurs = int(re.search(r"#slurs (\d+)", line)[1]) if "#slurs" in line else 0
    body = re.sub(r"#(slurs|omitted) (\d+)", "", body)  # #omitted n: cue notes / small optional heads left out
    toks = re.findall(r"<OOV:[^>]*>|\[|\]\??|\||[^\s\[\]|<]+(?:<~)?", body)
    return dict(page=page, sys=sysi, voice=voice, toks=toks, n_phrase_slurs=n_slurs)


class Strip:
    """One strip's walk. Pitch state (key, bar accidentals, tie-carried accidentals) is the same for v1 and v2; only
    the tokens and events emitted for an expanded region differ, which is what makes the v1/v2 identity hold."""

    def __init__(self, rec: dict[str, Any], divisi: bool, common_time: bool) -> None:
        self.rec, self.divisi, self.common_time = rec, divisi, common_time
        self.voice = rec["voice"]
        self.clef = "F" if self.voice == "Bass" else "G"
        self.key = (1, "b")
        self.bar_acc: dict[str, str] = {}  # accidentals carry to the end of the bar per letter+octave
        self.prev_ties: dict[str, str | None] = {}  # tied pitch -> its accidental, carried across the barline
        self.bar_ticks = 1920
        self.ag: list[str] = []
        self.ev: list[dict[str, Any]] = []
        self.measure = 0
        self.unc = 0
        self.n_chord = 0
        self.fermata = False

    def midi_of(self, p: str, acc: str | None) -> int:
        m = 12 * (int(p[1:]) + 1) + SEMI[LET[p[0]]]
        if acc is not None:  # ^ sharp, _ flat, = natural, relative to the natural letter
            return m + {"^": 1, "_": -1, "=": 0}[acc]
        n, sign = self.key
        if p[0] in (SHARP_ORDER if sign == "#" else FLAT_ORDER)[:n]:
            return m + (1 if sign == "#" else -1)
        return m

    def resolve_acc(self, p: str, acc_sym: str | None) -> str | None:
        if acc_sym:
            self.bar_acc[p] = acc_sym
        elif self.prev_ties.get(p):
            self.bar_acc.setdefault(p, self.prev_ties[p])  # tied continuation keeps the accidental across the barline
        return self.bar_acc.get(p)

    def pitch_event(self, p: str, acc: str | None, ticks: int, tie: str | None, **extra: Any) -> dict[str, Any]:
        written = self.midi_of(p, acc)
        octave_down = 12 if self.voice == "Tenor" and self.clef == "G" else 0  # Tenor in F clef sounds as written
        return dict(kind="note", pitch_written=written, pitch=written - octave_down,
                    dur=ticks, measure=self.measure, tie=tie, **extra)

    def emit_fermata(self) -> None:
        if self.fermata:
            self.ag.append(FERMATA_TOKEN)
            self.fermata = False

    def header(self) -> list[str]:
        toks = self.rec["toks"]
        written_clef = toks[0].split(":", 1)[1]
        allowed = {"Soprano": ("G",), "Alto": ("G",), "Tenor": ("G8", "G", "F"), "Bass": ("F",)}[self.voice]
        assert written_clef in allowed, (self.rec, toks[0])  # Tenor may be treble-8vb, treble or bass (clef scope)
        self.clef = "F" if written_clef == "F" else "G"
        self.key = parse_key(toks[1])
        # G8 has no own token: same G-L2 glyph; Stage 3 lowers Tenor by voice
        self.ag = [f"clef.{self.clef}-L{2 if self.clef == 'G' else 4}"] + key_tokens(self.clef, *self.key)
        i = 2
        if i < len(toks) and toks[i].startswith("time:"):
            mt, self.bar_ticks = meter_tokens(toks[i], self.common_time)
            self.ag += mt
            i += 1
        if i < len(toks) and toks[i] == "|":
            i += 1  # header separator only, not a barline (system starts right after the key signature)
        return toks[i:]

    def items(self, body: list[str]) -> list[dict[str, Any]]:
        group, items = None, []
        for t in body:
            if t == "[":
                group = []
                continue
            if t.startswith("]"):
                self.unc += t.endswith("?")
                for k, it in enumerate(group):
                    it["beam"] = "Right" if k == 0 else ("Left" if k == len(group) - 1 else "Both")
                group = None
                continue
            it = dict(raw=t)
            items.append(it)
            if group is not None:
                group.append(it)
        return items

    def oov(self, it: dict[str, Any]) -> None:
        t = it["raw"]
        self.unc += t.count("?")
        m = re.fullmatch(r"<OOV:(\w+)[ >].*", t, re.S)
        kind = m[1] if m else ""
        if self.divisi:  # v2 runs only on Phase 4 sources, so the kind list is enforced there
            assert kind in OOV_KINDS, (self.rec["page"], self.rec["sys"], self.voice, t)
        members = re.fullmatch(r"<OOV:\w+ ([whqes])(\.{0,2}) ([^>]+)>", t) if kind in EXPANDED else None
        heads = self.heads(members[3].split("+")) if members else None
        if kind in EXPANDED and self.divisi:  # dev sources carry free-form chord text; v1 must still build them
            assert heads, (self.rec["page"], self.rec["sys"], self.voice, t)
        if heads and self.divisi:
            self.chord(it, members[1], len(members[2]), heads)
            return
        if heads:  # v1: same pitch and tie state as v2, tokens/events stay one wildcard
            self.resolve_heads(heads)
        self.emit_fermata()
        d = re.search(r"\b([whqes])(\.{0,2})(?=[ >])", t)
        dur = DUR[d[1]] * DOTMUL[len(d[2])] if d else 0
        self.ag.append("<OOV>")
        self.ev.append(dict(kind="oov", dur=int(dur), measure=self.measure, desc=t))

    def heads(self, members: list[str]) -> list[dict[str, Any]] | None:
        """Parses strict members, sorted bottom to top; None if any member is free text (dev sources)."""
        heads = []
        for mem in members:
            m0 = mem.replace("?", "")
            arrive = m0.endswith("<~")
            m0 = m0.replace("<~", "")
            tie_next = m0.endswith("~>")
            m0 = m0.replace("~>", "")
            tie_in = m0.endswith("~")
            mm = re.fullmatch(r"([\^_=]?)([A-G]\d)", m0.rstrip("~"))
            if not mm:
                return None
            heads.append(dict(acc=mm[1] or None, p=mm[2], st=step_of(mm[2], self.clef), arrive=arrive,
                              tie_next=tie_next, tie_in=tie_in))
        heads.sort(key=lambda h: h["st"])
        steps = [h["st"] for h in heads]
        # two same-pitch heads are never one stem's chord (twovoice); a single head is a plain note
        assert len(heads) >= 2 and len(set(steps)) == len(steps), ("chord needs 2+ distinct heads", members)
        return heads

    def resolve_heads(self, heads: list[dict[str, Any]]) -> None:
        for h in heads:
            h["acc_now"] = self.resolve_acc(h["p"], h["acc"])
        self.prev_ties = {h["p"]: h["acc_now"] for h in heads if h["tie_in"]}

    def chord(self, it: dict[str, Any], d: str, ndots: int, heads: list[dict[str, Any]]) -> None:
        """v2 chord tokens, x order: fermata, tie arrivals, slur.end per tied-in member, accidentals, base note,
        chordnotes, one dot per head, slur.start per tied member; all member lists bottom to top."""
        self.emit_fermata()  # before the span, as v1 emits it before its <OOV>
        span = ["<SPAN>"]
        if any(h["arrive"] for h in heads):
            span.append("<TIEX>")
        span.append("<CHORD>")  # the re-walk puts pending slur.end tokens here
        span += [f"accidental.{ACCNAME[h['acc']]}-{pos(h['st'])}" for h in heads if h["acc"]]
        shape = f"beamed{it['beam']}{1 if d == 'e' else 2}" if "beam" in it and d in "es" else DURNAME[d]
        span.append(f"note.{shape}-{pos(heads[0]['st'])}")
        span += [f"chordnote-{pos(h['st'])}" for h in heads[1:]]
        used: set[int] = set()
        for h in reversed(heads):  # top down: a line note whose space above already holds a dot takes the space below
            ds = h["st"] + 1 if h["st"] % 2 == 0 else h["st"]
            h["dot"] = h["st"] - 1 if ds in used else ds
            used.add(h["dot"])
        for h in heads:
            span += [f"dot-{pos(h['dot'])}"] * ndots
        span += [f"slur.start-{pos(h['st'])}" for h in heads if h["tie_in"]]
        if any(h["tie_next"] for h in heads):
            span.append("<TIEX>")
        span.append("</SPAN>")
        self.ag += span
        ticks = int(DUR[d] * DOTMUL[ndots])
        cid = self.n_chord
        self.n_chord += 1
        self.resolve_heads(heads)
        for h in heads:
            tie = "in" if h["tie_in"] else "out" if h["tie_next"] else ("arr" if h["arrive"] else None)
            self.ev.append(self.pitch_event(h["p"], h["acc_now"], ticks, tie, chord=cid, name=h["p"],
                                            d=d + "." * ndots, arrive=h["arrive"]))

    def note_or_rest(self, it: dict[str, Any]) -> None:
        t = it["raw"]
        self.unc += t.count("?")
        t0 = t.replace("?", "")
        arrive = t0.endswith("<~")
        t0 = t0.replace("<~", "")
        tie_next = t0.endswith("~>")
        t0 = t0.replace("~>", "")
        tie_in = t0.endswith("~")
        t0 = t0.rstrip("~") if not tie_next else t0
        rm = re.fullmatch(r"r([whqes])(\.{0,2})", t0)
        if rm:
            d, rdots = rm[1], len(rm[2])
            self.emit_fermata()
            self.ag.append(f"rest.{DURNAME[d]}-L{4 if d == 'w' else 3}")
            self.ag += ["dot-S3"] * rdots  # dotted rest: dot in the third space, as PrIMuS writes it
            self.prev_ties = {}
            # a whole rest fills the bar whatever the meter (dev pieces are all 4/4, so 1920 there)
            ticks = self.bar_ticks if d == "w" and not rdots else int(DUR[d] * DOTMUL[rdots])
            self.ev.append(dict(kind="rest", dur=ticks, measure=self.measure))
            return
        gm = re.fullmatch(r"g([qes]):([\^_=]?)([A-G]\d)", t0)
        if gm:  # grace note: drawn, never timed
            st = step_of(gm[3], self.clef)
            if gm[2]:
                self.ag.append(f"accidental.{ACCNAME[gm[2]]}-{pos(st)}")
            self.ag.append(f"gracenote.{DURNAME[gm[1]]}-{pos(st)}")
            return
        m = re.fullmatch(r"([whqes])(\.{0,2}):([\^_=]?)([A-G]\d)", t0)
        assert m, (self.rec["page"], self.rec["sys"], self.voice, t)
        d, dot, acc_sym, p = m[1], m[2], m[3] or None, m[4]
        st = step_of(p, self.clef)
        self.emit_fermata()
        if acc_sym:
            self.ag.append(f"accidental.{ACCNAME[acc_sym]}-{pos(st)}")  # PrIMuS order: accidental before its note
        acc = self.resolve_acc(p, acc_sym)
        name = f"note.beamed{it['beam']}{1 if d == 'e' else 2}" if "beam" in it and d in "es" else f"note.{DURNAME[d]}"
        if arrive:
            self.ag.append("<TIEX>")
        self.ag.append(f"{name}-{pos(st)}")
        self.ag += [f"dot-{dot_pos(st)}"] * len(dot)
        if tie_in:
            self.ag.append(f"slur.start-{pos(st)}")
        if tie_next:
            self.ag.append("<TIEX>")
        self.prev_ties = {p: acc} if tie_in else {}
        tie = "in" if tie_in else "out" if tie_next else ("arr" if arrive else None)
        self.ev.append(self.pitch_event(p, acc, int(DUR[d] * DOTMUL[len(dot)]), tie, name=p, d=d + dot,
                                        arrive=arrive))

    def build(self) -> dict[str, Any]:
        for it in self.items(self.header()):
            t = it["raw"]
            if t == "|":
                self.ag.append("barline-L1")
                self.measure += 1
                self.bar_acc = {}
            elif t == "fermata":
                self.fermata = True
            elif t.startswith("time:"):
                mt, self.bar_ticks = meter_tokens(t, self.common_time)
                self.ag += mt
            elif t.startswith("key:"):  # mid-strip key change; key:0# prints naturals, a trailing ! prints cancel naturals
                old, self.key = self.key, parse_key(t.rstrip("!"))
                keep = self.key[0] if self.key[1] == old[1] else 0
                cancel = t.endswith("!") or not self.key[0]
                self.ag += [f"accidental.natural-{p}" for p in KEY_POS[self.clef][old[1]][keep:old[0]] if cancel]
                self.ag += key_tokens(self.clef, *self.key)
            elif re.fullmatch(r"mr:\d+", t):  # multi-bar rest: count digits above the staff, then the bar
                n = int(t[3:])
                self.ag += [f"digit.{ch}-S5" for ch in str(n)] + ["multirest-L3"]
                self.ev.append(dict(kind="rest", dur=n * self.bar_ticks, measure=self.measure))
                self.measure += n - 1
                self.prev_ties = {}
            elif t.startswith("<OOV"):
                self.oov(it)
            else:
                self.note_or_rest(it)
        assert not self.fermata, ("fermata with no note after it", self.rec["page"], self.rec["sys"], self.voice)
        rec = self.rec
        return dict(strip_id=f"page{rec['page']:03d}_sys{rec['sys']:02d}_{self.voice}", page=rec["page"],
                    sys=rec["sys"], voice=self.voice, agnostic=rewalk_ties(self.ag), events=self.ev,
                    n_bars=self.measure, n_uncertain=self.unc, n_oov=sum(1 for e in self.ev if e["kind"] == "oov"),
                    n_phrase_slurs=rec.get("n_phrase_slurs", 0))


def rewalk_ties(ag: list[str]) -> list[str]:
    """Puts each slur.end right before the next note token (PrIMuS order), or at a chord's <CHORD> slot. Pending ends
    accumulate, so a chord whose members are all tied closes every one of them."""
    res: list[str] = []
    pend: list[str] = []
    for tok in ag:
        if tok.startswith("slur.start-"):
            res.append(tok)
            pend.append(tok.split("-", 1)[1])
            continue
        if tok == "<CHORD>":
            res += [f"slur.end-{p}" for p in pend]
            pend = []
            continue
        if pend and tok.startswith("note."):
            res += [f"slur.end-{p}" for p in pend]
            pend = []
        res.append(tok)
    return res


def scored_tokens(ag: list[str]) -> list[str]:
    """What score_eval.score_strip compares: no <TIEX>, no slur.* (and here, the v2 span sentinels collapsed)."""
    out: list[str] = []
    inside = False
    for t in ag:
        if t == "<SPAN>":
            out.append("<OOV>")
            inside = True
        elif t == "</SPAN>":
            inside = False
        elif not inside and t != "<TIEX>" and not t.startswith("slur"):
            out.append(t)
    return out


def scored_events(ev: list[dict[str, Any]]) -> list[tuple]:
    out: list[tuple] = []
    last_chord = None
    for e in ev:
        if "chord" in e:
            if e["chord"] != last_chord:
                out.append(("oov",))
            last_chord = e["chord"]
            continue
        last_chord = None
        out.append(("oov",) if e["kind"] == "oov" else (e["kind"], e.get("pitch"), e["dur"], e["measure"]))
    return out


def build_piece(src: Path, divisi: bool, common_time: bool) -> list[dict[str, Any]]:
    out = []
    for line in src.read_text(encoding="utf-8").splitlines():
        if not (line.startswith("p") and " " in line and line[1].isdigit()):
            continue
        r = parse_line(line)
        if "excluded" in r:
            out.append(dict(strip_id=f"page{r['page']:03d}_sys{r['sys']:02d}_{r['voice']}", page=r["page"],
                            sys=r["sys"], voice=r["voice"], excluded=r["excluded"]))
        else:
            out.append(Strip(r, divisi, common_time).build())
    return out


def project(gt_dir: Path, common_time: bool) -> None:
    src = gt_dir / "gt_source.txt"
    v1, v2 = build_piece(src, False, common_time), build_piece(src, True, common_time)
    errs = []
    for a, b in zip(v1, v2):
        assert a["strip_id"] == b["strip_id"]
        if "excluded" in a:
            continue
        if scored_tokens(a["agnostic"]) != scored_tokens(b["agnostic"]):
            errs.append(f"{a['strip_id']}: v1/v2 tokens differ outside expanded spans")
        if scored_events(a["events"]) != scored_events(b["events"]):
            errs.append(f"{a['strip_id']}: v1/v2 events differ outside expanded spans")
    for e in errs:
        print("IDENTITY FAIL:", e)
    if errs:
        raise SystemExit(1)
    for ver, strips in (("v1", v1), ("v2", v2)):
        for s in strips:
            if "agnostic" in s:
                s["agnostic"] = [t for t in s["agnostic"] if t not in ("<SPAN>", "</SPAN>")]
        (gt_dir / ver).mkdir(exist_ok=True)
        (gt_dir / ver / "gt.json").write_text(json.dumps(strips, indent=1), encoding="utf-8")
        shutil.copyfile(src, gt_dir / ver / "gt_source.txt")
    n = sum(1 for s in v1 if "excluded" not in s)
    print(f"{gt_dir.name}: v1 and v2 written, {n} scored strips, {len(v1) - n} excluded; identity OK")


def parity() -> int:
    """v1 must reproduce the committed dev gt.json (agnostic tokens and events) built by the dev build_gt.py."""
    bad = 0
    for piece, common_time in PARITY_PIECES.items():
        ref = json.loads((ROOT / "gt" / piece / "gt.json").read_text(encoding="utf-8"))
        mine = build_piece(ROOT / "gt" / piece / "gt_source.txt", False, common_time)
        for r, m in zip(ref, mine, strict=True):
            if "excluded" in r:
                continue
            ag = [t for t in m["agnostic"] if t not in ("<SPAN>", "</SPAN>")]
            if ag != r["agnostic"]:
                bad += 1
                print(f"PARITY FAIL {piece} {r['strip_id']}: tokens")
            if [{k: v for k, v in e.items()} for e in m["events"]] != r["events"]:
                bad += 1
                print(f"PARITY FAIL {piece} {r['strip_id']}: events")
    print("parity OK" if not bad else f"parity: {bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    if "--parity" in sys.argv:
        sys.exit(parity())
    project(Path(sys.argv[1]), "--common-time" in sys.argv)
