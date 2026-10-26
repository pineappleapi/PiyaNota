"""Agnostic labels for real-engraving divisi strips: score parts merged onto the staves the PDF prints (PIYA-106 A7).

Why: the `data/chords_dataset` scores keep each divisi part on its own staff (SSAATTBB) while the PDFs print two or
three parts on one staff. The images come from the PDF, so the labels must describe the PDF staff: the parts that
share it are merged bar by bar, then the existing converter labels the merged staff and the strips are cut at the PDF
system breaks recorded by hand in `divisi_score_maps.json`.

Merge rule per bar, over the parts that have a note in it (a part resting the whole bar is left out):
- one part: its bar as written;
- 2+ parts with the same rhythm: one note or chord per slot, beams from the first of those parts; the same pitch in
  two parts is one head (its tie / fermata ids are remapped to the kept head);
- anything else (different rhythms, a rest against a note, a unison with two spellings, more than MAX_CHORD_NOTES
  heads) is a layered or unlabelable bar. It gets a placeholder and its system's strip is dropped with the reason,
  because the converter has no 2-layer labels yet (A7-CL).
A bar the converter cannot read (tuplet, two layers in one part, an unknown element) is dropped the same way, and so is
a bar whose tie partner was dropped, since the drawn curve would lose one end.

Known label risks (verification by notehead count, or the user's spot check on raster PDFs, must catch them):
- Verovio's @accid is per source part, so a merged bar can show an accidental twice where the PDF shows it once.
- A part resting part of a bar inside a merge drops the bar, but a part resting a whole bar is ignored, while some
  engravers still draw its rest as a second layer.
- Same-rhythm split stems (A7 counts these as layers) are labelled as chords: the score cannot say how the PDF drew
  them.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from music_to_agnostic import (BARLINES_WRITTEN, MEI_NS, XML_ID, ConversionError, MeasureTokens,  # noqa: E402
                               convert_staff, split_systems)

ET.register_namespace("", MEI_NS)
ET.register_namespace("xml", "http://www.w3.org/XML/1998/namespace")

MAPS = Path(__file__).with_name("divisi_score_maps.json")
MAX_CHORD_NOTES = 3            # build_corpus.MAX_CHORD_NOTES (A7 3.1: no 4-note same-stem chords); not imported, it needs music21
EVENT_TAGS = frozenset({"note", "chord", "rest", "mRest", "space", "mSpace"})
CONTAINER_TAGS = frozenset({"beam"})
UNREADABLE_TAGS = frozenset({"tuplet", "bTrem", "fTrem"})
ID_REF_ATTRS = ("startid", "endid")
HEAD_PREFIXES = ("note.", "gracenote.", "chordnote-")


def q(tag: str) -> str:
    return f"{{{MEI_NS}}}{tag}"


def local(tag: str) -> str:
    return tag.split("}", 1)[-1]


class BadBar(Exception):
    """A bar whose merged staff the converter cannot label."""


def events(layer: ET.Element) -> list[tuple[ET.Element, ET.Element]]:
    """(parent, event) pairs in drawn order, beams entered, other non-events skipped."""
    out: list[tuple[ET.Element, ET.Element]] = []
    for el in layer:
        tag = local(el.tag)
        if tag in EVENT_TAGS:
            out.append((layer, el))
        elif tag in CONTAINER_TAGS:
            out += events(el)
        elif tag in UNREADABLE_TAGS:
            raise BadBar(f"<{tag}>")
    return out


def slot_key(el: ET.Element) -> tuple[str, str, str, bool]:
    tag = local(el.tag)
    kind = "n" if tag in ("note", "chord") else "r"
    return kind, el.attrib.get("dur", "M" if tag in ("mRest", "mSpace") else ""), el.attrib.get("dots", "0"), \
        "grace" in el.attrib


def heads(el: ET.Element) -> list[ET.Element]:
    return [el] if local(el.tag) == "note" else el.findall(q("note"))


def sounding_alter(n: ET.Element) -> str:
    accid = n.find(q("accid"))
    src = accid.attrib if accid is not None else n.attrib
    return src.get("accid.ges", src.get("accid", ""))


def merge_bar(layers: list[ET.Element], remap: dict[str, str]) -> tuple[ET.Element, int]:
    """Merged layer for one bar and the number of parts that sing in it. Raises BadBar."""
    seqs = [events(layer) for layer in layers]
    active = [i for i, seq in enumerate(seqs) if any(slot_key(e)[0] == "n" for _, e in seq)]
    if len(active) <= 1:
        return copy.deepcopy(layers[active[0] if active else 0]), len(active)
    keys = [[slot_key(e) for _, e in seqs[i]] for i in active]
    if any(k != keys[0] for k in keys[1:]):
        raise BadBar("different rhythms (layered)")
    template = copy.deepcopy(layers[active[0]])
    for slot, (parent, el) in enumerate(events(template)):
        key = keys[0][slot]
        if key[0] != "n":
            continue
        kept: dict[tuple[str, str], ET.Element] = {}
        for i in active:
            for n in heads(seqs[i][slot][1]):
                pitch = (n.attrib["pname"], n.attrib["oct"])
                if pitch not in kept:
                    kept[pitch] = n
                elif sounding_alter(kept[pitch]) != sounding_alter(n):
                    raise BadBar("unison with two spellings")
                elif n.attrib.get(XML_ID) != kept[pitch].attrib.get(XML_ID):
                    remap[n.attrib[XML_ID]] = kept[pitch].attrib[XML_ID]
        if len(kept) > MAX_CHORD_NOTES:
            raise BadBar(f"{len(kept)}-note chord")
        if len(kept) > 1 and key[3]:
            raise BadBar("grace chord")
        members = [copy.deepcopy(n) for n in kept.values()]
        if len(members) == 1:
            new = members[0]
            new.attrib.update({a: el.attrib[a] for a in ("dur", "dots") if a in el.attrib})
        else:
            new = ET.Element(q("chord"), {a: el.attrib[a] for a in ("dur", "dots", "stem.dir") if a in el.attrib})
            new.set(XML_ID, f"merged_{members[0].attrib.get(XML_ID, slot)}")
            new.extend(members)
        idx = list(parent).index(el)
        parent.remove(el)
        parent.insert(idx, new)
    return template, len(active)


def placeholder() -> ET.Element:
    layer = ET.Element(q("layer"), {"n": "1"})
    ET.SubElement(layer, q("mRest"))
    return layer


def build_group(mei: Path, group: list[str], out: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Write an MEI copy whose staff `group[0]` holds the merged group; return bad bars and per-bar flags by @n."""
    tree = ET.parse(mei)
    score = tree.getroot().find(f".//{q('score')}")
    assert score is not None, mei
    bad: dict[str, str] = {}
    flags: dict[str, list[str]] = {}
    remap: dict[str, str] = {}
    bar_of: dict[str, str] = {}
    targets: dict[str, ET.Element] = {}
    for measure in score.iter(q("measure")):
        n = measure.attrib["n"]
        staves = {s.attrib["n"]: s for s in measure.findall(q("staff"))}
        for s in group:
            for note in staves[s].iter(q("note")):
                bar_of[note.attrib.get(XML_ID, "")] = n
        target = staves[group[0]]
        targets[n] = target
        try:
            layer_sets = [staves[s].findall(q("layer")) for s in group]
            if any(len(ls) != 1 for ls in layer_sets):
                raise BadBar("2+ layers in a source part")
            merged, singing = merge_bar([ls[0] for ls in layer_sets], remap)
            if singing >= 3:
                flags.setdefault(n, []).append("3+ parts on one staff")
        except BadBar as exc:
            bad[n] = str(exc)
            merged = placeholder()
        if measure.attrib.get("right", "single") not in BARLINES_WRITTEN | {"invis"}:
            bad.setdefault(n, f"barline {measure.attrib['right']!r}")
            measure.set("right", "single")
        if measure.attrib.get("right", "").startswith("rpt"):
            flags.setdefault(n, []).append("repeat dots unlabelled")
        for old in target.findall(q("layer")):
            target.remove(old)
        merged.set("n", "1")
        target.append(merged)
    for el in score.iter():
        for attr in ID_REF_ATTRS:
            ref = el.attrib.get(attr, "").lstrip("#")
            if ref in remap:
                el.set(attr, f"#{remap[ref]}")
    # A tie half in a dropped bar leaves a curve end with no label in the kept neighbour.
    for tie in score.iter(q("tie")):
        ends = [bar_of.get(tie.attrib.get(a, "").lstrip("#")) for a in ID_REF_ATTRS]
        for here, there in (ends, ends[::-1]):
            if here is not None and there in bad and here not in bad:
                bad[here] = f"tie partner in dropped bar {there}"
                for old in targets[here].findall(q("layer")):
                    targets[here].remove(old)
                targets[here].append(placeholder())
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return bad, flags


def convert_robust(path: Path, staff: str, bad: dict[str, str]) -> list[MeasureTokens]:
    """convert_staff, turning each bar it rejects into a dropped placeholder bar (found by prefix bisection)."""
    while True:
        try:
            return convert_staff(path, staff, dialect="verovio")
        except ConversionError as exc:
            tree = ET.parse(path)
            measures = list(tree.getroot().iter(q("measure")))
            lo, hi = 0, len(measures) - 1
            while lo < hi:   # smallest prefix that fails ends at the bad bar
                mid = (lo + hi) // 2
                trial = copy.deepcopy(tree)
                trial_measures = list(trial.getroot().iter(q("measure")))
                section_of = {c: p for p in trial.getroot().iter() for c in p}
                for m in trial_measures[mid + 1:]:
                    section_of[m].remove(m)
                trial_path = path.with_suffix(".trial.mei")
                trial.write(trial_path, encoding="utf-8", xml_declaration=True)
                try:
                    convert_staff(trial_path, staff, dialect="verovio")
                    lo = mid + 1
                except ConversionError:
                    hi = mid
            bar = measures[lo]
            if bar.attrib["n"] in bad:
                raise RuntimeError(f"{path.name}: placeholder bar {bar.attrib['n']} still fails: {exc}") from exc
            bad[bar.attrib["n"]] = f"converter: {exc}"
            target = next(s for s in bar.findall(q("staff")) if s.attrib["n"] == staff)
            for old in target.findall(q("layer")):
                target.remove(old)
            target.append(placeholder())
            tree.write(path, encoding="utf-8", xml_declaration=True)


def map_systems(spec: dict) -> list[dict]:
    systems: list[dict] = []
    for page, entries in spec["pages"]:
        for k, entry in enumerate(entries):
            e = {"first": entry} if isinstance(entry, str) else dict(entry)
            e.setdefault("staves", spec["staves"])
            e["page"], e["sys"] = page, e.get("sys", k + 1)
            systems.append(e)
    return systems


def has_note(score: ET.Element, staff: str, bars: set[str]) -> bool:
    return any(s.attrib["n"] == staff and s.find(f".//{q('note')}") is not None
               for m in score.iter(q("measure")) if m.attrib["n"] in bars for s in m.findall(q("staff")))


def label_piece(piece: str, spec: dict, mei: Path, work: Path) -> list[dict]:
    score = ET.parse(mei).getroot().find(f".//{q('score')}")
    assert score is not None, mei
    order = [m.attrib["n"] for m in score.iter(q("measure"))]
    systems = map_systems(spec)
    starts = [order.index(s["first"]) for s in systems]
    assert starts[0] == 0 and starts == sorted(starts), f"{piece}: map must start at bar {order[0]} and ascend"
    cache: dict[tuple[str, ...], tuple[list[list[str]], dict[str, str], dict[str, list[str]]]] = {}
    records: list[dict] = []
    for si, s in enumerate(systems):
        end = starts[si + 1] if si + 1 < len(systems) else len(order)
        bars = order[starts[si]:end]
        groups = s["staves"]
        if groups is None:
            continue
        if isinstance(groups, dict):
            groups = [[n] for n in groups["auto"] if has_note(score, n, set(bars))]
        for staff_i, group in enumerate(groups):
            key = tuple(group)
            if key not in cache:
                path = work / f"{piece}__{'-'.join(group)}.mei"
                bad, flags = build_group(mei, group, path)
                measures = convert_robust(path, group[0], bad)
                start_set = set(starts)
                for i, m in enumerate(measures):
                    m.system_start = i in start_set
                cache[key] = (split_systems(measures), bad, flags)
            cut, bad, flags = cache[key]
            drop = sorted({f"bar {b}: {bad[b]}" for b in bars if b in bad})
            tokens = cut[si]
            records.append({
                "piece": piece, "page": s["page"], "sys": s["sys"], "staff": staff_i, "parts": group,
                "bars": [bars[0], bars[-1]], "tokens": None if drop else tokens,
                "heads": sum(t.startswith(HEAD_PREFIXES) for t in tokens), "drop": drop,
                "flags": sorted({f for b in bars for f in flags.get(b, [])} | ({"merged"} if len(group) > 1 else set())),
            })
    return records


def self_check() -> None:
    """Two same-rhythm parts become one chord, a shared pitch one head; different rhythms are rejected."""
    def layer(*notes: tuple[str, str, str, str]) -> ET.Element:
        el = ET.Element(q("layer"))
        for i, (pname, octave, dur, nid) in enumerate(notes):
            ET.SubElement(el, q("note"), {"pname": pname, "oct": octave, "dur": dur, XML_ID: nid})
        return el
    remap: dict[str, str] = {}
    merged, singing = merge_bar([layer(("e", "5", "2", "a1"), ("c", "5", "2", "a2")),
                                 layer(("c", "5", "2", "b1"), ("c", "5", "2", "b2"))], remap)
    first, second = list(merged)
    assert singing == 2 and local(first.tag) == "chord" and len(first) == 2, ET.tostring(merged)
    assert local(second.tag) == "note" and remap == {"b2": "a2"}, (ET.tostring(merged), remap)
    try:
        merge_bar([layer(("c", "5", "1", "x")), layer(("c", "4", "2", "y"), ("d", "4", "2", "z"))], {})
    except BadBar:
        pass
    else:
        raise AssertionError("different rhythms must be rejected")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mei-dir", type=Path, required=True, help="<piece>.mei per piece (Verovio from MusicXML)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--piece", action="append", help="only these pieces (default: all in the map)")
    args = parser.parse_args()
    self_check()
    maps = {k: v for k, v in json.loads(MAPS.read_text(encoding="utf-8")).items() if not k.startswith("_")}
    work = args.out / "merged_mei"
    work.mkdir(parents=True, exist_ok=True)
    with (args.out / "labels.jsonl").open("w", encoding="utf-8") as fh:
        for piece in args.piece or sorted(maps):
            records = label_piece(piece, maps[piece], args.mei_dir / f"{piece}.mei", work)
            for r in records:
                fh.write(json.dumps(r) + "\n")
            reasons = Counter(d.split(": ", 1)[1].split(" (")[0] for r in records for d in r["drop"][:1])
            kept = [r for r in records if r["tokens"] is not None]
            chords = sum(t.startswith("chordnote-") for r in kept for t in r["tokens"])
            print(f"{piece}: strips {len(records)}, kept {len(kept)}, chordnotes kept {chords}, "
                  f"first drop reason {dict(reasons)}")


if __name__ == "__main__":
    main()
