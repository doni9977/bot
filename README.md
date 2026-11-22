# Mech Royale bot (`mechfight/1`)

Entry for the Builders Buildathon 2026, **Mech Royale** track. Python 3.13,
standard library only. Placement is the metric, so the policy is survival-first:
stay inside the circle, avoid being found, break line of sight, and only take
free economy or favourable fights.

> **Working on this repo?** Start at [`AGENTS.md`](AGENTS.md), then
> [`docs/STATE.md`](docs/STATE.md). The `docs/` directory is the living record of
> what we believe, what we measured, and what we already ruled out — it is the
> source of truth, and it supersedes anything below that contradicts it.
> This README is the public-facing summary; `docs/` is the engineering one.

## Layout

| Path | What it is |
| --- | --- |
| `bot.py` | Entrypoint: thin adapter around `mechfight.run`. |
| `brain.py` | Decision core: mode selection, zone rotation, threat handling. |
| `intel.py` | Belief records with source/confidence tags; server-tracked positions, uncertain sound/beam/event sectors, explicit unknowns. |
| `world.py` | 1 m arena model: solid column tops, overhangs, 9-point body collision, LOS. |
| `nav.py` | Navigation grid + bounded A* + local steering + collision-safe heading filter. |
| `zone.py` | Circle interpolation and safe-point selection. |
| `combat.py` | Lead aiming, torso slew, projectile/laser evasion, facing. |
| `econ.py` | Loot, cubes, supply drops, upgrade valuation, optional early roam. |
| `cover.py` | Local line-of-sight breaking spot search (optional policy layer). |
| `params.py` | Tunable policy parameters; `BOT_PARAMS` env JSON overrides them for local A/B. |
| `mechfight.py` | Official protocol wrapper from the organiser's starter kit. |
| `mechfight.schema.json`, `check/`, `arena/` | Official kit files, used only for local conformance testing; excluded from the image. |
| `tools/example_bot.py` | Official starter bot, kept for reference; excluded from the image. |
| `AUDIT.md` | Protocol fact/uncertainty ledger, architecture audit, observation/action maps and baseline. |

`sim/` and `tests/` are **empty local placeholders** and are not in the public tree.
The A/B simulator used for development is external and uncommitted (see Attribution).

## Attribution

- `mechfight.py`, `mechfight.schema.json`, `check/check.py`,
  `check/stream.jsonl.gz`, `arena/v2/world.json` and `arena/v2/terrain.i16` are
  copied unchanged from the official **mechfight bot kit** published on the
  track page (https://www.joinbuilders.org/buildathon/tracks/builders).
- Local relative A/B testing uses a separate, uncommitted headless simulator
  derived from the public MIT-licensed repository
  `anthonyteti/buildathon-mech-royale`, driven through its protocol-speaking
  external-bot hook. **No third-party bot code is included in the submitted
  image**; every file in the Docker context is our own Python or an official kit file.
- Released under the MIT License (see `LICENSE`).

## Build and verify

```sh
docker build --platform linux/amd64 -t mech-bot .
python3 check/check.py -- python3 -u bot.py
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none \
  --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m \
  --user 65534:65534 -v "$PWD/arena:/arena:ro" mech-bot
```

`check.py` only proves protocol compliance and timing; it is not a game.

## Local experiment log (relative scores, not official points)

Paired practice runs, same seeds, external protocol-speaking bots. Only the
paired difference is meaningful; absolute values are not comparable with the
official practice score. **No official practice submission has been made yet.**

| Experiment | Paired delta | Decision |
| --- | --- | --- |
| Exact upgrade effects, first mobility-heavy weights | −0.33 ± 0.17 (24 paired, harsh) / −0.08 ± 0.25 (mild) | rejected; over-weighted mobility/aim |
| Exact upgrade effects, survival-weighted retune | +0.04 ± 0.09 (24 paired, harsh) / 0.00 ± 0.12 (mild) | neutral; retained for protocol correctness |
| Protocol-first belief layer (D1/D2: server-tracked positions, uncertain sound sectors) | +0.04 ± 0.07 (24 paired, harsh) | neutral; retained for protocol correctness and as arbiter input |
| Single torso-aim arbiter (D3) | +0.54 ± 0.28 (24 paired, harsh) / +0.71 ± 0.59 (24 paired, mild) | retained; positive but variance is high |
| Combined D1/D2/D3 | +0.63 ± 0.25 (24 paired, harsh) / +1.50 ± 0.40 (24 paired, mild) | retained |
| 1 m engine-accurate collision + composed-heading validation | fixed a hard wedging bug (bot was farmed to death by one drone at t≈70 s) | adopted |
| Aggression (`aggression` 0.95 / 0.7) | 0.00 / −0.31 | rejected |
| LOS-breaking cover | 0.00 ± 0.07 | optional, off by default |
| Early roam / weapon + cube farming | −0.50 ± 0.17 | rejected (roam_until = 0) |
| Squad kiting (boost away from incoming-fire bearings, 5 s hold) | +0.55 ± 0.27 | adopted |
| Kite hold 8 s vs 5 s | 0.00 ± 0.09 | 6 s default |
| Kite hold 14 s vs 8 s | −0.21 ± 0.13 | rejected |
| Full-speed (loud) movement vs quiet | −0.67 ± 0.26 | quiet movement kept |
| Live-config body geometry (radius/height/step-up/slope/canopy, D5) | +0.42 ± 0.51 (24 paired, harsh) / +0.13 ± 0.18 (24 paired, mild) | **inconclusive**; retained only as protocol correctness (no hardcoded rule numbers), not claimed as a gain |
| Movement discipline: route clearance, goal hold, reciprocal fire, kite range gate, no static camping | score −0.22 ± 0.44, survival −3.5 ± 13.2 s, damage dealt +335 ± 239, kills +0.25 ± 0.21 (32 paired) | neutral on survival, positive on offence; kept because each item fixes a demonstrated defect (walking into the squad, standing still, dying with a full magazine) |

### Calibration caveat on the local metric

In the local simulator the 15 house bots survive **87 %** of matches, so the best
reachable score is about 2.0 and the score signal is nearly flat. Measured score
deltas therefore under-report real differences, and **survival time is the
primary local signal**. Absolute local scores are not comparable with the
official practice score, which reaches 5.96 on the live leaderboard.

### Measurement protocol (learned the hard way)

The seed **range** behaves like a random effect: the same comparison can read
+0.67 on one range and −0.10 on another. Treating individual seeds as
independent understates the error badly, so:

- an effect needs **≥48 pairs spanning at least three seed ranges**;
- report the per-range deltas, not just the pooled one;
- anything under ~0.5 score is **not resolvable** with feasible sample sizes and
  must be called inconclusive, not a win.

A concrete example of why: focus fire measured `+0.38 ± 0.13` on 32 pairs from
one range (11 wins / 2 losses, apparently decisive) and `−0.04 ± 0.08` on 48
pairs from another. The first result was a false positive.

### Experiments measured and rejected (defaults unchanged)

| Change | Paired result | Decision |
| --- | --- | --- |
| Focus fire | +0.38 ± 0.13 (32 pairs, range 4000) then −0.04 ± 0.08 (48 pairs, range 8000) | kept as neutral/mechanically sound; the gain did **not** replicate |
| Laser pre-charge without the fire gate | −0.16 ± 0.13 | off |
| Indirect mortar targets (accept LOS-blocked) | −0.28 ± 0.11 | off |
| Economy: early roam + crates + drops | −0.78 ± 0.36 | off |
| High aim point (0.75 body height) | −0.47 ± 0.23 | off |
| Open ground (`cover_bias` 0) | −0.22 ± 0.19 | off |
| Aggression 1.0 / `engage_range` 240 | +0.12 ± 0.12 | inconclusive, unchanged |
| Mortar-preferring loadout | −0.02 ± 0.09 | inconclusive, unchanged |
| Zone-edge goal (`goal_offset` 0.78) | +0.19 / +0.67 / −0.10 across ranges 8000/11000/13000 | inconclusive (+0.25 ± 0.23 pooled); unchanged |

### Decision-time budget
Over 387 sampled decisions the bot had a shootable target **21 %** of the time,
was alone **35 %**, and had enemies visible but terrain-blocked **44 %**. The
fire gate was never the binding constraint: the arbiter passed literal
`fire=True` and used the gate only for candidate utility, which is why every
gate experiment measured flat. Damage is limited by target availability, not
permission to shoot.



### Parameter sweep (14 dimensions, 14 random configs)

Harness: `sweep.py` (dev-only, uncommitted). Every config is scored on the same
three fixed ranges (8000/11000/13000, 16 seeds each) against a **cached
per-seed baseline**, so a candidate costs one arm (~82 s). Results are reported
as per-range deltas, and a holdout of untouched ranges (14000/15000/16000)
confirms anything that survives.

Baselines: train **1.96 / 71 s / 1.27 kills**; holdout **1.65 / 66.5 s / 1.17**.

Outcome: **no config was reliably better.** Per-range deltas swing by up to 1.2
score *within a single config* (e.g. `+0.31/−1.00/+0.12`), so pooled means are
noise. Only one config was positive on all three training ranges, and it had
negative kills — self-contradictory.

The best candidate by mechanism (kills, the thing that actually improves place)
was aggression 0.8 / cover_bias 0.25 / standoff 65 / hunt_hp 0.30 / quiet off:

| Set | Pooled score | Kills | Per-range |
| --- | --- | --- | --- |
| train | +0.33 | +0.38 | +0.69 / −0.25 / +0.56 |
| holdout | +0.15 | +0.06 | +0.38 / +0.06 / +0.00 |

5 of 6 ranges non-negative, pooled ≈ +0.24 — real but modest, and **not clearly
better than the hunter-v2 build already submitted**. Conclusion: this parameter
space is close to exhausted; remaining gains are structural, not tunable.

## Documentation system

| Path | Contents |
| --- | --- |
| `AGENTS.md` | Entry point: reading order, non-negotiable rules, 60-second summary |
| `docs/README.md` | The map and the conventions |
| `docs/STATE.md` | Where the project stands, next actions, open questions |
| `docs/FINDINGS.md` | What is true about the game, with evidence tags |
| `docs/ARCHITECTURE.md` | File-by-file design, decision loop, invariants, defects |
| `docs/EXPERIMENTS.md` | Every experiment with numbers, including rejections |
| `docs/OPERATIONS.md` | Build, test, local harness, measurement protocol |
| `docs/DECISIONS.md` | Why it is shaped this way, including reversals |
| `docs/EXTERNAL_REVIEWS.md` | Two outside models reviewed this; what survived testing |
| `HANDOFF.md` | Frozen self-contained snapshot (full protocol + config verbatim) |
| `AUDIT.md` | Original protocol ledger: uncertainty classes A–E, defects D1–D14 |
