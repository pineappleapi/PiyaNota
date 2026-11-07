"""Build combined MIDI from the saved real Moonriver pipeline run (data/eval_moonriver_diag)."""
import json, sys
sys.path.insert(0, ".")
from build_combined import build_combined, VOICES

d = json.load(open("D:/PiyaNota/data/eval_moonriver_diag/pipeline_out.json"))
rep, ev = d["report"], d["events"]
events = {v: ev[v.lower()] for v in VOICES}
pickup = rep["pickup_ticks"]
bars = []
if pickup:
    s0 = rep["systems"][0]
    n, dn = map(int, s0["time_signature"].split("/"))
    bars.append(dict(bar=0, startTick=0, durTicks=pickup, numerator=n, denominator=dn, pickup=True))
for s in rep["systems"]:
    n, dn = map(int, s["time_signature"].split("/"))
    for k in range(s["n_bars"]):
        bars.append(dict(bar=s["first_bar"] + k, startTick=pickup + s["start_tick"] + k * s["bar_ticks"],
                         durTicks=s["bar_ticks"], numerator=n, denominator=dn, pickup=False))
print(len(bars), "bars; last end", bars[-1]["startTick"] + bars[-1]["durTicks"], "total_ticks", rep["total_ticks"])
build_combined(events, bars, 90, "moonriver_combined.mid")
