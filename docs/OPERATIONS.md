# OPERATIONS — build, test, measure

> Living document. Last updated **2026-11-21 22:50 UTC**.
> Everything here is terminal-only and headless. No desktop control, no browser
> automation, no simulated input.

## Build and conform

```sh
# native
docker build --platform linux/amd64 -t mech-bot .
python3 check/check.py -- python3 -u bot.py

# inside the real match sandbox (this is what the scorer runs)
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none \
  --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m \
  --user 65534:65534 -v "$PWD/arena:/arena:ro" mech-bot
```

`check.py` proves protocol compliance and timing only. **It is not a game.** A bot
that crashes can still pass it.

Gotchas that have cost us time:

- `.dockerignore` must not strip `mechfight.schema.json`; mount the schema
  separately when running the check.
- The Docker `ENTRYPOINT` swallows an overridden command — use
  `--entrypoint python3`.
- Git Bash mangles `-v` paths; prefix with `MSYS_NO_PATHCONV=1` and use Windows
  paths.
- `/tmp` in Git Bash is not `/tmp` to Windows Python. Use an explicit
  `C:/Users/.../AppData/Local/Temp/...` path when a script and a shell must agree.

## The local simulator

Derived from the public MIT repo `anthonyteti/buildathon-mech-royale` (TypeScript
simulator with a house-squad emulator and an `ExtBot` protocol hook). **Not in the
repo** — it is a dev harness only, and no third-party bot code ships in the image.

Verified: its config is byte-identical to the official `hello.config` (0 diffs).

Harness lives in `%TEMP%/at-sim/`:

| File | Purpose |
| --- | --- |
| `ab.sh` | One arm: exports `CFG`, `KIT`, `OPP_REGISTRY`, runs `sim/run.ts` |
| `sim/run.ts` | Match runner; `practice` mode = us vs 15 house bots |
| `sim/ext.ts` | Spawns a protocol-speaking bot from `opponents.json` |
| `paired.py` | Paired stats from an `ABDATA` line |
| `sweep.py` | Cached-baseline sweep over ranges, with holdout |
| `rank.py` | Ranks configs by range agreement |
| `prof_brain.py` | Replays a recorded stream, reports p50/p99 decision time |

### Running an arm

```sh
cd "$TEMP/at-sim"
./ab.sh practice 16 8000 4 '{"ext":"cand"}'
```

`--a` takes a JSON spec. **`'{}'` is not our bot** — it runs the simulator's
built-in TypeScript bot. Our bot is `{"ext":"cand"}`, resolved through
`opponents.json`:

```json
{ "cand": { "cwd": ".../work-dir", "cmd": ["python","-u","bot.py"],
            "env": { "BOT_PARAMS": "{}" } } }
```

To test a different tree (a worktree, or an external review's code), point `cwd`
elsewhere:

```json
{ "warden": { "cwd": ".../work-warden", "cmd": ["python","-u","bot.py"], "env": {} } }
```

### Reading the output

```
practice: 16 matches in 24 s
  house  score 7.87 ± 0.29  kills 0.07  death t 56  ...
  A      score 2.00 ± 0.42  kills 1.31  death t 60  dealt 3185 taken 1794  ...
```

`house` is the mean over 15 house bots; `A` is us. `causes alive:208 gun:19 npc:11
laser:2` counts how the 15×16 house bots died — `alive` is the survival count, the
rest are death causes. That line is how you see environmental attrition.

Add `AB_VERBOSE=1` for the `ABDATA` JSON (per-match rows) and `EXTSTDERR=1` to see
the bot's stderr (which is where `BOT_DEBUG=1` telemetry goes).

### Parameters without editing code

`BOT_PARAMS` is a JSON object merged over `params.DEFAULT`:

```sh
BOT_PARAMS='{"hunt_range":230,"kite_hp":0.7}' python -u bot.py
```

Production has no `BOT_PARAMS`, so the default dict is what ships.

## Measurement protocol

**This is the part that has burned us. Follow it.**

- **Seed *range* is a random effect.** The same comparison can read +0.67 on one
  range and −0.10 on another. Per-range deltas swing by up to 1.2 score inside one
  config.
- **n ≥ 48 pairs across ≥ 3 ranges**, plus a holdout on untouched ranges.
- Report **per-range deltas**, not just the pooled mean.
- **Under ~0.5 is unresolvable.** Call it inconclusive. Do not write "win".
- Prefer **kills and death time** as secondary signals when score is flat, because
  the local score is compressed (house bots survive 87 % of matches, so the ceiling
  is ≈ 2.0).
- Keep a **cached baseline** so a candidate costs one arm, not two.

Canonical ranges: train `8000 / 11000 / 13000`, holdout `14000 / 15000 / 16000`,
16 seeds each.

### The false positive to remember

Focus fire measured `+0.38 ± 0.13` on 32 pairs from range 4000 (11 wins / 2 losses,
looked decisive) and `−0.04 ± 0.08` on 48 pairs from range 8000. The first result
was noise, and it had already been written up as a win. See E19.

## Submission protocol

The human submits. The agent never does.

When a submission is warranted, send a notification containing:

1. the commit SHA,
2. what changed and why,
3. the expected effect and its evidence,
4. the exact test requested.

Budget: platform allows 4/hour; we self-limit to **2/hour** and leave a slot free.

### The transfer function (measured — see F17)

| | Local | Official |
| --- | --- | --- |
| Resolution | ~±0.5 | **~±0.05** |
| Cost | free, unlimited | 1 slot, a few minutes |
| Bias | under-prices aggression | ground truth |

- **Within an architecture, Δlocal ≈ Δofficial.** A change that moves local by
  +0.5 moves the board by ~+0.5.
- **The offset is not constant.** It was ~−0.2 before hunt mode and ~+0.55 after.
  Never carry an offset across a change of aggression class.
- **Official is the fine instrument.** Because practice seeds are fixed, resubmitting
  the same bot varies only by slot and spawn. Use the board to confirm, and to
  measure anything under 0.5.
- **A worse submission costs nothing but a slot** — the leaderboard keeps your best.
  So probes are cheap, and the only real constraint is the human's patience.

### Cadence that follows from this

1. Generate candidates locally; keep anything ≥ +0.3 with a mechanism you can name.
2. Probe one candidate at a time. Bundling two changes makes the result
   uninterpretable.
3. After the board answers, record it in `EXPERIMENTS.md` E40 **and** update the
   offset table in F17 if the architecture changed.

### Reverting

If a probe comes back negative, revert the default but **keep the knob and the
measurement**. Example: `roam_until` is back to 0.0, but the 8 % → 35 % weapon
uptime result and the −0.02 official delta are both recorded (E37, E40).

## Debugging

```sh
BOT_DEBUG=1 EXTSTDERR=1 ./ab.sh practice 1 8000 1 '{"ext":"cand"}'
```

`DBG` lines carry: time, position, goal and its kind, movement vector, reach,
stuck timer, escape flag, nearest NPC, threat/visible counts, HP, fire flags,
kiting/covered/roaming flags, `adapt`, target, gate state, and range/LOS skip
counters plus gun/laser shot counts, and `w1` (secondary weapon).

To find out why the bot never fires, check `gate=` (was permission given), `rng=`
and `los=` (why candidates were dropped) and `ok=` (valid candidates). If `ok > 0`
and `g=0`, the arbiter is discarding them.

**Next:** [`DECISIONS.md`](DECISIONS.md) — why it is shaped this way.
