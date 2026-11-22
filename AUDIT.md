# Audit, protocol ledger and baseline (2026-11-21)

Source of truth: `protocol.md` (`mechfight/1`, §1-§12), `mechfight.schema.json`,
and the live `hello.config` extracted from `check/stream.jsonl.gz`.
Commit at time of audit: `574e3fb`. Nothing has been submitted officially.

## 1. Protocol fact and uncertainty ledger

Classification: **A** = explicit protocol fact, **B** = conditional on config /
visibility, **C** = observation-based inference, **D** = experimental hypothesis,
**E** = unknown / unavailable to the bot.

| # | Statement | Class | Reference |
| --- | --- | --- | --- |
| 1 | One decision per 0.1 s; each action covers 2 sim ticks (20 Hz); 50 ms wall budget; lockstep; answering early gives no advantage | A | §2, §3 |
| 2 | `ready` within 20 s; echo `tick`; skip queued observations to the newest | A | §2 |
| 3 | No answer coasts (`move`/`boost`/`aim`) for 1 s, then idles; crash idles for the rest of the match | A | §2 |
| 4 | Score = mean of `16 - place`; same-tick deaths share a place; clock-out ranks survivors by HP | A | §4 |
| 5 | `hello.config` is the complete rule set; defaults may change between matches | A | §6 |
| 6 | `hello.seed` is fixed per slot and is **not** the match seed | A | §6 |
| 7 | `obs.mechs` keeps tracking a previously seen mech's **real current position** for `vision.memory_s` after it leaves view | A | §8 |
| 8 | Everything else (crates, cubes, pickups, projectiles) is listed only while visible | A | §8 |
| 9 | Vision: 45 m proximity (any direction) or 200 m inside a 120° yaw wedge around the *actual* torso aim; buildings block; canopy is soft; trunks block sight but not shots | A/B | §8, §7 |
| 10 | Sounds give world-frame bearing with Gaussian error (σ=7° default), a coarse distance class (`near`<60 / `mid`<160 / `far`), `age`, and kind; no source id; own sounds omitted | A/B | §8 |
| 11 | `beams` include shooter id (`by`), kind, path, age. Projectiles have **no** shooter id | A | §6, §8 |
| 12 | `events` are about us only: `damaged` (with `by`, `bearing`, `rear`), `hit`, `effect`, `kill`, `drop`, `pickup`, `upgrade`, `took`, `dropped`, `take_failed` | A | §6 |
| 13 | Enemy hp/max_hp only when `vision.show_enemy_hp`; enemy upgraded stats, upgrade lists, energy, ammo, cooldowns, reload are never exposed | A/B/E | §6 |
| 14 | Rear hits outside `front_arc_deg` deal `rear_mult` damage; facing an attacker is defensive | A | §7 |
| 15 | Regen needs `regen_delay` (5 s) with **no damage dealt or taken**, then 45 HP/s; none outside the zone; zone damage bypasses armor and resets the timer | A | §7, §9 |
| 16 | Gun: 252 m/s, 45 dmg, 0.24 s, 12-round mag, 2.4 s reload, spread; must lead. Shots leave along the *actual* torso aim | A | §7 |
| 17 | Mortar: ballistic, splash blocked by walls, **own splash hurts at 50%**, concussion throws and drains energy | A | §7 |
| 18 | Laser: hold to charge, release to fire, hitscan, half move speed, telegraphed, +60% cook-off vs mortar carriers | A | §7 |
| 19 | Lightning: nearest eligible target in 45 m / 30° cone, chains, 3 energy/shot, interrupts laser charge | A | §7 |
| 20 | Trees do not stop shots; canopy/trunk affect vision only | A | §7, §8 |
| 21 | Cubes: +4% max HP (heals the difference) and +4% damage up to `stat_cap`; +5% size **uncapped**; killed mechs drop their cubes + 2 | A | §10 |
| 22 | Upgrade offers at cube thresholds; exact effects in `hello.config.upgrades`; timeout applies choice 0; weapon upgrades persist across drops | A | §10 |
| 23 | Drops are always known; 3 per match; stand alone in the ring for 4 s for 3 cubes + full HP/energy | A | §7 |
| 24 | Zone always exposes current/next circle, shrink window, dps; next circle always inside current | A | §9 |
| 25 | Map: 1 m int16-cm heightmap (bilinear), solid prisms with rings/holes, bridges/overhangs, trees | A | §11 |
| 26 | Container: 1 CPU, 512 MB, 128 threads, no network, read-only except 64 MB `/tmp`, uid 65534, `/arena` read-only, linux/amd64, ≤20 MB repo, ≤10 min build | A | §1, §3 |
| 27 | `check/check.py` replays 300 recorded observations and does **not** simulate the game | A | §1 |
| 28 | House squad shares vision, never fights each other, hunts us; number of hunters grows with time | A (track page) | track §RULES |
| 29 | Practice seeds are private and fixed; slot/spawn vary; no practice/final flag exists | A/E | track §RULES |
| 30 | Final FFA opponent policies are unknown; expert house bots fill empty slots | E | track §THE FINAL |
| 31 | Local A/B simulator house-bot AI is an approximation; only paired deltas are meaningful | D | local harness |
| 32 | Any mapping from local A/B score to official practice score is unvalidated (no official submissions yet) | D/E | - |

## 2. Repository architecture audit

Tracked (21 files, 2.0 MB total; image context is a subset via `.dockerignore`):

| Module | Role | State |
| --- | --- | --- |
| `bot.py` | `mechfight.run(Bot)` entrypoint | OK |
| `mechfight.py` | Official wrapper (tick echo, newest-obs, exception guard, clean exit) | unchanged kit file |
| `brain.py` | Mode selection, threat model, zone, kiting, escape, NPC flee, aim dispatch | 23 KB; survival-first |
| `world.py` | 1 m column grid, solid tops + overhangs, 9-point body collision, LOS, tree canopy | rewritten this session |
| `nav.py` | 8 m A* (6 ms guard), `reach()`, clearance fan, `safe_heading()` | 7.7 KB |
| `zone.py` | Circle interpolation + 12-candidate hide-spot scoring | 3.2 KB |
| `combat.py` | Intercept aim, future-aim, per-slot fire, dodge, mortar arc | 10.6 KB |
| `econ.py` | `choose_take`, `loot_goal`, `seek_goal`, upgrade valuation | 7.5 KB |
| `cover.py` | LOS-breaking spot search | 2.4 KB, **disabled by default** |
| `params.py` | 68 knobs + `load()` (`BOT_PARAMS`) | production reads env via `load()` |
| `check/`, `arena/`, `mechfight.schema.json`, `tools/example_bot.py` | Official kit, excluded from image | - |

- `sim/` and `tests/` **exist locally but are empty** and are absent from the public tree (git cannot track empty dirs). README previously claimed they were a local harness — corrected here.
- The A/B simulator actually used is an **external, uncommitted** clone in `%TEMP%/at-sim` (public MIT repo `anthonyteti/buildathon-mech-royale`). Its `config_default.json` was diffed against the official `hello.config`: **0 differences**. Its house-bot AI is approximate; `check/check.py` is not a simulator.
- Git: clean tree, 8 commits, `574e3fb` HEAD.
- `.dockerignore` is exclusion-based; image contains all `.py`, `LICENSE`, `Dockerfile`, `README.md`. No kit assets in the image.

## 3. Verified defects and unused features

| # | Defect | Evidence | Impact |
| --- | --- | --- | --- |
| D1 | **FIXED (`7addbb2`)** — server-tracked positions are dead-reckoned. `_threats()` added `vel * min(age,2)` to *every* enemy record, contradicting §8's real-current-position guarantee | `brain.py:_threats` | Wrong threat geometry, bad cover/kite decisions |
| D2 | **FIXED (`7addbb2`)** — sound bearings are turned into exact points (55/135/210 m) with no σ or interval model; `step`, `boost`, `jet`, `reload`, `npc_gun`, `crate`, `drop` are discarded | `brain.py:_update` | False precision, lost information |
| D3 | **FIXED (`7addbb2`)** — two weapon slots can command conflicting aims. `aim_cmd` is set by slot 0; slot 1 computes its own yaw/pitch and can fire while the commanded torso aim is still slot 0's | `combat.py:act` (gun/laser/lightning/mortar branches) | Missed shots; violates single-torso-aim constraint (§7) |
| D4 | **FIXED (`f78d3f5`)** — upgrade ranking is hand-assigned and never reads `hello.config.upgrades` effects | `econ.py:upgrade_value` | Suboptimal or illegal choices under balance changes |
| D5 | **FIXED** — hardcoded geometry: radius 2.5, height 9, eye 8, muzzle 7, `step_up` 1.2, pitch clamps ±0.7/1.3, turn/pitch rates, `walk_speed`, `step_speed` fallbacks | `world.py`, `nav.py`, `combat.py`, `brain.py` | Wrong after cube size scaling or config changes |
| D6 | **PARTIAL (`7addbb2`)** — unused observation channels: `alive`, `beams` (used), `in_zone`, `rear`, `by`, `hit`, `effect`, `kill`, `took`, `take_failed`, `drops.progress`, `drops.capture_s`, `sounds.age` | source scan | No kill confirmation, no third-party data, no regen-timer awareness |
| D7 | **Unused parameters**: `retreat_hp`, `pressure_hide`, `stuck_speed`, `ffa_mode` (`mortar_self_safe` now used by the arbiter) | `params.py` | Dead knobs mislead A/B |
| D8 | **`hello.seed` used as a directional prior** (`ZoneModel` base angle, scan base, roam sweep) even though it is slot-fixed and says nothing about the match | `brain.py`, `zone.py`, `econ.py` | Reproducibility is fine; treating it as match information would be wrong (currently not done) |
| D9 | **FIXED** — `vision_clear` used hardcoded canopy density instead of `world.json` `rules.canopyDensity` / `canopyBlockT` | `world.py:vision_clear` | Inaccurate visibility estimate |
| D10 | **FIXED (`7addbb2`)** — mortar fired without self-splash check (`mortar_self_safe` unused) and with no moving-target lead | `combat.py` mortar branch | Self-damage, misses |
| D11 | `dodge_vector` is 2-D closest approach; no vertical separation / gravity / impact timing | `combat.py` | Poor mortar/laser dodging |
| D12 | README claimed an in-repo simulator that does not exist | `README.md` | Documentation defect (fixed) |
| D13 | `BOT_PARAMS` loader was previously *not* wired into `Brain` (it imported `DEFAULT`) — **verified fixed** in `84e97cb`: `Brain.__init__` now calls `load(params)` | `brain.py:28` | Earlier A/B claims would have been invalid; current A/B is valid |
| D14 | Conformance check passing says nothing about competitiveness | §1 | Process risk |

## 4. Observation field map (current bot)

| Field | Used | How |
| --- | --- | --- |
| `tick` | yes | wrapper echoes it |
| `t`, `self.pos/vel/aim/hp/max_hp/energy/grounded/cubes/upgrades/weapons/stats` | yes | state, aim, HP gates |
| `self.in_zone` | **no** | zone is inferred from geometry only |
| `self.max_energy` | **no** | - |
| `alive` | **no** | - |
| `mechs` (mech) | yes | enemy memory, target list, NPC avoidance |
| `mechs` (npc) | yes | drone aggro break |
| `projectiles` | yes | 2-D dodge |
| `crates`, `cubes`, `pickups` | yes | `choose_take`, `loot_goal`, `seek_goal` |
| `sounds` | partial | gun/laser/etc bearings only; 7 kinds discarded; no σ/interval |
| `beams` | **no** | - |
| `events.damaged` | partial | pressure + bearings; `by`/`rear` ignored |
| `events.hit/effect/kill/took/take_failed/upgrade` | **no** | - |
| `drops` | partial | `drop_aggression=0` disables it; `progress/capture_s` unused |
| `zone` | yes | circle interpolation, `dps` unused |
| `offer` | yes | `pick_upgrade` (hand-ranked) |

## 5. Action and mechanic map (current bot)

| Action / mechanic | Emitted | Notes |
| --- | --- | --- |
| `move`, `boost`, `aim` | yes | quiet speed ≤ `step_speed`; boost on emergency/kite/NPC flee |
| `fire[0]` (gun) | yes | gated by alignment, ammo, cooldown, range |
| `fire[1]` (laser/lightning/mortar) | yes | **conflicting aim defect D3** |
| `jump`, `reload` | yes | conditional |
| `pick`, `take`, `drop` | yes | conditional |
| `debug` | no | unavailable value, non-functional |
| Rear-armor facing | partial | `face_threat` aims at nearest threat; `rear` events ignored |
| HP regen management | **no** | no calm-window tracking |
| Weapon-matchup decisions | **no** | fixed `weapon_pref` |
| Supply-drop capture | **no** | disabled |
| Cube-size tradeoff | **no** | not modelled |
| Scanning while idle | yes | sinusoidal torso sweep |

## 6. Baseline report (all local; **no official results exist**)

| Item | Value |
| --- | --- |
| Commit | `574e3fb` |
| Native `check.py` | PASS, 300/300, p50 0.8 ms, p99 3.2 ms, max 4.8 ms |
| Docker match sandbox (`--cpus 1 --memory 512m --read-only ...`) | PASS, 299/300, 1 late, p99 24.7 ms, max 106 ms |
| Image size / repo size | 2.0 MB (limit 20 MB) |
| Local A/B (external sim, 20-24 paired matches/variant) | v1 survival 0.58; competitor 4.50-official brain 1.42; **current build 1.21-1.50 depending on seed** |
| Death cause (sim) | gun ~1000-1250, lightning/laser/mortar ~400, NPC ~70 |
| Death time (sim) | v1 77 s → current 97-120 s |
| Official submissions | **0**. No score, no placement distribution, no official death causes |
| Conformance ≠ performance | acknowledged (§1) |

Measured paired effects this session (local sim only): aggression 0.00 / −0.31; LOS cover
0.00 ± 0.07; early roam −0.50 ± 0.17; **kiting +0.55 ± 0.27**; kite 8 s ≈ 5 s;
14 s −0.21 ± 0.13; loud movement −0.67 ± 0.26. Retained: 1 m collision model,
collision-safe heading, drone break, net-progress escape, 6 s kiting, quiet movement.

## 7. Prioritized opportunities

1. **D1 + D2**: replace dead reckoning with server-tracked positions; model sounds as
   bearing-with-σ + distance interval. Highest confidence (protocol fact), low cost.
2. **D3**: single-torso-aim controller. Directly affects every shot we fire.
3. **D4 + D5**: read exact upgrade effects and live geometry/speeds from `hello.config`.
4. **D6**: use `alive`, `beams`, `hit`/`effect`/`kill`/`rear`/`by`, `in_zone`, drop
   progress to build engagement/third-party/regen awareness.
5. **Strategy**: engagement utility (expected damage in/out, weapon matchup, escape
   options) instead of fixed aggression/HP thresholds. Must be A/B-tested.
6. **Resources**: contextual weapon/upgrade/drop decisions; cube-size tradeoff.
7. **Official calibration**: one practice submission is needed to validate the local
   sim, but submission requires an authorised headless path (see §12 constraint).

## 8. Proposed architecture (smallest practical increment)

Keep the existing modules; add one thin **battlefield-intelligence layer**
(`intel.py`) that produces a per-opponent belief record with explicit confidence and
source tags, plus a **single aim arbiter** in `combat.py`. `brain.py` consumes belief
records for goal selection, engagement gating and facing. No POMDP / MCTS until an
A/B shows a simple utility policy is insufficient. Keep runtime p99 well under 50 ms.

## 9. Experiment plan

- All variants via `BOT_PARAMS` env through the external protocol-speaking sim;
  paired seeds, ≥24 matches per arm, `--jobs 4`, identical seeds for A and B.
- Primary: paired mean `16 - place`; secondary: death time, damage dealt/taken,
  kills, cubes, shots/hits, missed decisions.
- Ablate each retained component individually; report ±SE and say "inconclusive"
  when |Δ| < ~2·SE.
- Every change: one atomic commit, conformance native + Docker, log entry in
  README experiment table, then keep or revert on evidence.
- Official submissions: at most one per hour, preserve one slot for the user,
  never lock/select a final entry; validate Docker first; record commit + score.
- Local simulator numbers are never reported as official scores.
