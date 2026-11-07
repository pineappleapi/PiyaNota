import json, subprocess, time, os, mido
from build_combined import *
bpm = 100
ev, bars = synthetic()
build_combined(ev, bars, bpm, "combined.mid")
print("size", os.path.getsize("combined.mid"))
def load(p):
    m = mido.MidiFile(p); assert m.type == 1 and m.ticks_per_beat == PPQ
    tr = {}
    for i, t in enumerate(m.tracks):
        a = 0; notes = []; meta = []
        for msg in t:
            a += msg.time
            if msg.type == "note_on" and msg.velocity: notes.append((a, msg.channel, msg.note))
            elif msg.type in ("set_tempo", "time_signature"): meta.append((a, msg))
        tr[i] = (notes, meta)
    return m, tr
m, tr = load("combined.mid")
msper = 60000 / bpm / PPQ
# click vs bars
clicks = tr[5][0]; assert all(c == 9 for _, c, _ in clicks)
want = {b["startTick"] for b in bars if not b.get("pickup")}
acc = {t for t, _, n in clicks if n == CLICK_HI}
assert acc == want, (acc, want)
print("downbeat clicks", sorted(acc), "dev ms", max(abs(a - b) for a, b in zip(sorted(acc), sorted(want))) * msper)
# note onsets
mx = 0
for i, v in enumerate(VOICES):
    got = sorted((t, n) for t, c, n in tr[i+1][0]); assert all(c == i for _, c, _ in tr[i+1][0])
    exp = sorted((e["tick_onset"], e["pitch"]) for e in ev[v] if e["type"] == "note")
    assert len(got) == len(exp)
    mx = max(mx, max(abs(g[0]-x[0]) for g, x in zip(got, exp))); assert [g[1] for g in got] == [x[1] for x in exp]
print("note onset max dev ms", mx * msper)
print("meta", [(t, msg.type, getattr(msg, "numerator", None), getattr(msg, "denominator", None), getattr(msg, "tempo", None)) for t, msg in tr[0][1]])
# mute: drop ch k (no track, rebuild by filtering) -> others unchanged
for k in range(4):
    mm = mido.MidiFile("combined.mid")
    mm.tracks = [t for t in mm.tracks if not any(getattr(x, "channel", -1) == k for x in t)]
    mm.save("mute.mid"); _, t2 = load("mute.mid")
    rest = [i for i in range(1, 5) if i != k + 1]
    assert len(t2) == 5 and all(sorted(t2[j][0]) == sorted(tr[i][0]) for j, i in zip([x for x in range(1, 5)], rest)), k
    assert sorted(t2[4][0]) == sorted(tr[5][0])
print("mute ok (each of 4 channels dropped; remaining notes+click identical)")
# tempo scaling: only set_tempo changes
mm = mido.MidiFile("combined.mid")
for t in mm.tracks:
    for x in t:
        if x.type == "set_tempo": x.tempo = int(x.tempo / 1.5)
mm.save("fast.mid"); _, tf = load("fast.mid")
assert all(sorted(tf[i][0]) == sorted(tr[i][0]) for i in range(1, 6))
print("tempo x1.5: note ticks identical all tracks; length s", mido.MidiFile("combined.mid").length, "->", mido.MidiFile("fast.mid").length)
for name in ("combined", "fast"):
    s = time.time()
    subprocess.run(["fluidsynth", "-ni", "-F", f"{name}.wav", "-r", "44100", "-o", "synth.reverb.active=0", "-o", "synth.chorus.active=0",
                    "D:/PiyaNota/soundfont/piano.sf2", f"{name}.mid"], check=True, capture_output=True)
    print(name, "render s", round(time.time()-s, 2), "wav bytes", os.path.getsize(f"{name}.wav"))
