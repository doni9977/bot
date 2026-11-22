"""Feed every golden session's inputs to a bot command and count obs answers without a debug label
(a missing label on the real bot means Act panicked and safeAct emitted the fallback action).
usage: python -I panicscan.py GOLDEN.jsonl.gz -- BOT_CMD..."""
import gzip, json, subprocess, sys

argv = sys.argv[1:]
k = argv.index("--")
golden, cmd = argv[0], argv[k + 1:]
sessions = {}
with gzip.open(golden, "rt", encoding="utf-8") as f:
    for line in f:
        r = json.loads(line)
        if r.get("type") == "meta" or r.get("nomount"):
            continue
        sessions.setdefault(r["s"], []).append(r)
bad_total = 0
for name, recs in sessions.items():
    if recs[0].get("nomount") or name in ("syn_blind", "syn_panic", "syn_malformed"):
        continue
    recs.sort(key=lambda r: r["i"])
    data = "".join(r["in"] + "\n" for r in recs).encode()
    out = subprocess.run(cmd, input=data, capture_output=True, timeout=600).stdout.decode().splitlines()
    acts = [o for o in out if o.startswith('{"tick"')]
    bad = [o for o in acts if '"label"' not in o]
    bad_total += len(bad)
    print(f"{name}: {len(acts)} actions, {len(bad)} without label")
print("TOTAL without label:", bad_total)
