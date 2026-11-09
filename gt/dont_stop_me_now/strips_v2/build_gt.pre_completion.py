"""HAND-MADE / PROVISIONAL / single annotator (agent) / not verified by a musician.
Compiles gt/gt_source.txt (fixed before any CRNN run) into per-strip agnostic-token and event layers.
Run from data/eval_dsmn:  python gt/build_gt.py"""
import re, json, sys, hashlib
DUR = {"w": 1920, "h": 960, "q": 480, "e": 240, "s": 120}
DURNAME = {"w": "whole", "h": "half", "q": "quarter", "e": "eighth", "s": "sixteenth"}
LET = {"C": 0, "D": 1, "E": 2, "F": 3, "G": 4, "A": 5, "B": 6}
SEMI = [0, 2, 4, 5, 7, 9, 11]
BASE_STEP = {"G": 30, "F": 18}  # diatonic index (oct*7+letter) at the bottom line


def step_of(p, clef):
    return int(p[1:]) * 7 + LET[p[0]] - BASE_STEP[clef]


def midi_of(p):  # key = 1 flat: every B is Bb
    m = 12 * (int(p[1:]) + 1) + SEMI[LET[p[0]]]
    return m - 1 if p[0] == "B" else m


def pos(step):  # agnostic staff position suffix
    return f"L{step // 2 + 1}" if step % 2 == 0 else f"S{(step + 1) // 2}"


def parse_line(line):
    head, body = line.split(": ", 1)
    m = re.match(r"p(\d+)s(\d+) (\w+)", head)
    page, sysi, voice = int(m[1]), int(m[2]), m[3]
    if body.startswith("<EXCLUDED"):
        return dict(page=page, sys=sysi, voice=voice, excluded=body)
    body = re.sub(r"#slurs (\d+)", "", body)
    n_slurs = int(re.search(r"#slurs (\d+)", line)[1]) if "#slurs" in line else 0
    toks = re.findall(r"<OOV:[^>]*>|\[|\]\??|\||[^\s\[\]|<]+(?:<~)?", body)
    return dict(page=page, sys=sysi, voice=voice, toks=toks, n_phrase_slurs=n_slurs)


def build(rec):
    voice, page, sysi = rec["voice"], rec["page"], rec["sys"]
    toks = rec["toks"]
    clef = "F" if voice == "Bass" else "G"
    ag = [f"clef.{clef}-L{2 if clef=='G' else 4}"]
    ag.append("accidental.flat-L3" if clef == "G" else "accidental.flat-L2")  # Bb line
    first_bar_real = (page, sysi) == (1, 1)
    idx = 2 if toks[1].startswith("key:") else 1  # after clef:, key:
    i = 2
    if toks[i].startswith("time:"):
        ag += ["digit.4-L4", "digit.4-L2"]; i += 1
    if toks[i] == "|":
        i += 1  # header separator only, not a barline (system starts right after the key signature)
    body = toks[i:]
    # resolve beams: annotate beam role
    events, out, oov, unc, ties = [], [], 0, 0, []
    tick, measure = 0, 0
    beam = None  # list of indices into out
    seq = []  # (kind, payload)
    j = 0
    group = None
    items = []
    for t in body:
        if t in ("[",):
            group = []; continue
        if t.startswith("]"):
            if t.endswith("?"): unc += 1
            for k, it in enumerate(group):
                it["beam"] = "Right" if k == 0 else ("Left" if k == len(group) - 1 else "Both")
            group = None; continue
        it = dict(raw=t)
        items.append(it)
        if group is not None: group.append(it)
    ag_body, ev = [], []
    for it in items:
        t = it["raw"]
        if t == "|":
            ag_body.append("barline-L1"); measure += 1; ev.append(dict(kind="bar")); continue
        if t.startswith("<OOV"):
            d = re.search(r"\b([whqes]\.?)(?=[ >])", t)
            dur = DUR[d[1][0]] * (1.5 if d and d[1].endswith(".") else 1) if d else 0
            ag_body.append("<OOV>"); ev.append(dict(kind="oov", dur=int(dur), measure=measure, desc=t)); continue
        unc += t.count("?"); t0 = t.replace("?", "")
        arrive = t0.endswith("<~"); t0 = t0.replace("<~", "")
        tie_next = t0.endswith("~>"); t0 = t0.replace("~>", "")
        tie_in = t0.endswith("~"); t0 = t0.rstrip("~") if not tie_next else t0
        if re.fullmatch(r"r[whqes]", t0):
            d = t0[1]
            ag_body.append(f"rest.{DURNAME[d]}-L{4 if d=='w' else 3}")
            ev.append(dict(kind="rest", dur=DUR[d], measure=measure)); continue
        m = re.fullmatch(r"([whqes])(\.?):([A-G]\d)", t0)
        assert m, (rec["page"], rec["sys"], voice, t)
        d, dot, p = m[1], m[2], m[3]
        st = step_of(p, clef)
        if "beam" in it and d in "es":
            nb = 1 if d == "e" else 2
            name = f"note.beamed{it['beam']}{nb}"
        else:
            name = f"note.{DURNAME[d]}"
        if arrive: ag_body.append("<TIEX>")
        ag_body.append(f"{name}-{pos(st)}")
        if dot: ag_body.append(f"dot-S{st // 2 + 1}")
        if tie_in: ag_body.append(f"slur.start-{pos(st)}")
        if tie_next: ag_body.append("<TIEX>")
        ev.append(dict(kind="note", pitch_written=midi_of(p), pitch=midi_of(p) - (12 if voice == "Tenor" else 0),
                       dur=int(DUR[d] * (1.5 if dot else 1)), measure=measure, tie=("in" if tie_in else "out" if tie_next else ("arr" if arrive else None)),
                       name=p, d=d + dot, arrive=arrive))
    # slur.end goes before the note that ends the tie: re-walk to insert
    final, pending_end = [], None
    k = 0
    # find tie starts and insert 'slur.end-P' right before the next note token (PrIMuS order)
    res = []
    pend = None
    for tok in ag_body:
        if tok.startswith("slur.start-"):
            res.append(tok); pend = tok.split("-", 1)[1]; continue
        if pend and (tok.startswith("note.")):
            res.append(f"slur.end-{pend}"); pend = None
        res.append(tok)
    ag = ag + res
    return dict(strip_id=f"page{page:03d}_sys{sysi:02d}_{voice}", page=page, sys=sysi, voice=voice, agnostic=ag,
                events=[e for e in ev if e["kind"] != "bar"], n_bars=measure, n_uncertain=unc, n_oov=sum(1 for e in ev if e["kind"] == "oov"),
                n_phrase_slurs=rec.get("n_phrase_slurs", 0))


def main():
    recs = [parse_line(l) for l in open("gt/gt_source.txt", encoding="utf-8") if l.startswith("p") and " " in l and l[1].isdigit()]
    out = []
    for r in recs:
        if "excluded" in r:
            out.append(dict(strip_id=f"page{r['page']:03d}_sys{r['sys']:02d}_{r['voice']}", page=r["page"], sys=r["sys"], voice=r["voice"], excluded=r["excluded"]))
        else:
            out.append(build(r))
    json.dump(out, open("gt/gt.json", "w"), indent=1)
    for o in out:
        if "excluded" in o: print(o["strip_id"], "EXCLUDED"); continue
        bar_ticks = {}
        for e in o["events"]: bar_ticks[e["measure"]] = bar_ticks.get(e["measure"], 0) + e["dur"]
        print(o["strip_id"], "tokens", len(o["agnostic"]), "events", len(o["events"]), "oov", o["n_oov"], "unc", o["n_uncertain"], "bars", {k: v for k, v in sorted(bar_ticks.items())})
        with open(f"gt/{o['strip_id']}.txt", "w") as f:
            f.write("# HAND-MADE / PROVISIONAL / single annotator (agent) / not verified by a musician\n# agnostic:\n" + " ".join(o["agnostic"]) + "\n# events (kind pitch_sounding dur measure):\n")
            for e in o["events"]: f.write(f"{e['kind']} {e.get('pitch','R')} {e['dur']} {e['measure']} {e.get('tie') or ''}\n")


main()
