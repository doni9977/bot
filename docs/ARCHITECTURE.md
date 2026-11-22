# ARCHITECTURE — how the bot works

> Living document. Last updated **2026-11-22 06:45 UTC**.
> If you change structure, change this file in the same commit.

Static compiled **Go** binary (`FROM golang:1.26.1-bookworm → FROM scratch`, `4.03 MB`), standard library only, zero external dependencies, one process, one core, 50 ms per decision
(**1-CPU Docker sandbox: 299/300 PASS, p50 1.1 ms, p90 2.5 ms, p99 6.5 ms; native: 300/300 PASS, p50 0.2 ms, max 3.8 ms**).

## Active Engine: `Apex-Go v3` (`cmd/mechbot/` + `internal/{proto,world,bot}/`)

```
stdin ─► goroutine line drainer (queue-skip) ─► safeAct(recover) ─► Bot.Act(obs) ─► AppendJSON ─► stdout
                                                                         │
                                                                         ├─► observe()       memory tracks, exact prism LOS, BeamFFA (segPointDist2D > 22), LaserCDTrack (obs.Beams), adaptive lead history
                                                                         ├─► belief()        Open (24s Brawl) → Squad Hunt → Late Cautious (t≥265s / r≤72m) | Instant FFA Brawl | Duel
                                                                         ├─► assess()        range-aware 6-band fightPlan (r+6 lightning fix + practice 2s laser CD punish window) + live exchange model
                                                                         ├─► steer()         34-candidate forward-simulated trajectory MPC (gun bullets, 3D mortar arcs, charging lasers, all-carrier anti-lightning forcefield, RearAvoidW=35 2v1 rear-arc shield)
                                                                         ├─► engage()        cooldown-aware tick latency, dynamic gun speed in lead, online adaptive lead, rear_mult & cookoff lethal/priority, odd-tick laser release, CoverReload behind cover
                                                                         └─► econ            config-driven upgrade pick, NoMortar FFA cookoff guard, PracticeRim (88% outer rim while r≥180), RetreatPest drone swatting, roof/overland jump-jet nav, shrinking FinalHold
```

| Path | Responsibility | Key entry points |
| --- | --- | --- |
| `cmd/mechbot/main.go` | Zero-GC-pause (`SetGCPercent(800)`), async stdin drainer, `stripZeroFractions` resilient JSON, `BOT_PARAMS` env JSON overrides, crash-safe `defer recover()` | `main`, `safeAct` |
| `internal/proto/proto.go` | Full `mechfight/1` protocol types and allocation-free `Action.AppendJSON` | `Hello`, `Obs`, `Action.AppendJSON` |
| `internal/world/*.go` | Exact bilinear terrain, exact polygon prism raycasting, 2 m nav grid, wall clearance, connected components, roof/access map, overland surface A*, exposure map | `World.Raycast`, `World.Visible`, `Nav.Path`, `Nav.SurfacePath`, `Nav.Flood` |
| `internal/bot/bot.go` | `Params`, `DefaultParams` (`Apex-Go v2`), `observe()`, track memory, fixed `BeamFFA` segment check | `Bot.Act`, `Bot.observe` |
| `internal/bot/policy.go` | Main tactical decision loop: zone, roof/peek/slip/retreat/fight/loot, charging-laser cover break, **all-carrier anti-lightning forcefield**, **rear/cookoff target scoring**, **shrinking FinalHold** | `Bot.think`, `Bot.cubeRun`, `Bot.fightMove` |
| `internal/bot/move.go` | 34-candidate forward-simulated trajectory MPC (`approach2` exact accel), `gatherIncoming` (bullets + integrated 3D mortar blasts), `navDir`, `unstick` | `Bot.steer`, `Bot.gatherIncoming`, `Bot.navDir` |
| `internal/bot/combat.go` | **Cooldown-aware gun/laser latency**, head-aim fallback, mortar ballistic solver, **`rear_mult` & `cookoff` lethal laser release**, **`LaserEarlyRel`**, DPS models | `Bot.engage`, `Bot.solveDirectLat`, `Bot.solveMortar` |
| `internal/bot/lead.go` | Online adaptive per-opponent gun lead (virtual-shot scoring + persistence) using live upgraded `gun.speed` | `Bot.leadRecord`, `Bot.gunLead` |
| `internal/bot/plan.go` | 6-range `fightPlan` trade evaluator + coarse exploration map (`roamGoal`) | `Bot.fightPlan`, `Bot.roamGoal` |
| `internal/bot/hide.go` | Lobby belief (`open`/`squad`/`late`/`ffa`/`duel`) with **`CautiousT=265`** & **`BeamFFA`** + `chooseHide` | `Bot.belief`, `Bot.chooseHide` |
| `internal/bot/cover.go`, `peek.go`, `roof.go`, `hidemap.go`, `strategy.go` | `deeperCover`, laser corner-peek, rooftop climb/hold + overland jet travel, embedded `hidemap.gz`, loot/drop/upgrade/pickup logic | `Bot.deeperCover`, `Bot.overland`, `Bot.chooseLoot` |

## Legacy Python Engines (`apex.py`, `brain.py` — retained in repo, superseded by `Dockerfile`)

```
stdin ──► mechfight.run ──► Bot.act(obs) ──► Brain.act ──► Action ──► stdout
                               │
                               ├─► Intel.update(obs)      belief records + sectors
                               ├─► Zone.choose_goal(...)  where to go
                               ├─► Nav.path / steer       how to get there
                               ├─► Combat.act(...)        what to shoot, where to aim
                               └─► Econ.pick_upgrade / choose_take
```

`mechfight.py` is the organiser's wrapper and owns the stdin/stdout loop, tick
echoing, and queue-skipping. Do not modify it; everything else is ours.

## Files

| File | ~LOC | Responsibility | Key entry points |
| --- | --- | --- | --- |
| `bot.py` | 17 | Thin adapter: `Brain` behind `mechfight.run` | `Bot.act` |
| `brain.py` | 800 | Decision core: state, mode selection, movement, firing gate, torso | `Brain.act`, `_update`, `_threats`, `_break_heading` |
| `combat.py` | 700 | Aiming, lead, torso slew, target selection, weapon dispatch, arbiter, dodging | `Combat.act`, `_act_arbiter`, `pick_target`, `dodge_vector`, `laser_dodge` |
| `intel.py` | 570 | Belief layer: per-mech records, sound sectors with live σ, explicit unknowns | `Intel.update`, `threat_points`, `sectors`, `sound_pressure` |
| `world.py` | 420 | 1 m engine-accurate arena: solid column tops, overhangs, 9-point body, LOS | `solid`, `blocked`, `shot_clear`, `vision_clear`, `cover_score` |
| `nav.py` | 230 | 8 m nav grid, bounded A*, steering, collision-safe heading filter | `Planner.path`, `steer`, `safe_heading`, `reach` |
| `zone.py` | 150 | Circle interpolation, hide-spot scoring, route clearance, hysteresis | `choose_goal`, `score_at` |
| `econ.py` | 300 | Upgrade valuation from live config, pickups, loot goals, drops | `upgrade_value`, `pick_upgrade`, `choose_take`, `loot_goal`, `seek_goal` |
| `cover.py` | 70 | Local occlusion spot search (optional, off) | `find_spot` |
| `params.py` | 175 | Every knob + `BOT_PARAMS` env override | `DEFAULT`, `load` |

`sim/` and `tests/` are empty placeholders and are excluded from the image.

## The decision loop, in order

`Brain.act` is a straight-line pipeline. Order matters: later stages override
earlier goals.

1. **State** — `hp_frac`, visible enemies, threat points, nearest NPC, net
   displacement over 2 s.
2. **`adapt`** — `1 + min(1.2, recent_damage·0.18) + min(0.8, sound_pressure·0.12)
   + 0.5 if t > 250`. Divides engagement range downstream.
3. **Situational controller** (`trade_adapt`, off) — press/disengage by damage ratio.
4. **Zone goal** — 12 candidates on a ring, scored by travel, cover, threat
   distance, slope, sound penalty, route clearance. Hysteresis holds a goal 6 s.
   Outside the circle → emergency, goal = centre.
5. **Drone aggro break** — NPC inside 50 m and damaged (or inside 26 m) → sprint
   away 2.8 s. Drones move 5 m/s; a 4.85 m/s quiet walk cannot outrun them.
6. **Early roam** (`roam_until`, off by default).
7. **Opportunistic loot** — if nothing is within 55 m and `t < 250`, detour to a
   pickup or cube within 30 m.
8. **Hunt** — weakest visible enemy within `hunt_range`, walk to `hunt_standoff`.
9. **Kill-loot detour** (`loot_kill_enabled`, off).
10. **LOS cover** (`cover_enabled`, off).
11. **Kiting** — nearest enemy inside `kite_range` and HP below `kite_hp` → pick an
    occlusion-seeking heading (12-way fan) and boost for `kite_hold_s`.
12. **Movement** — A* replan on 18 m goal drift or 3.5 s; add dodge (×1.4), laser
    dodge (×1.2), NPC repulsion inside 42 m, strafe inside 120 m. Stop at goal only
    if no enemy within 120 m.
13. **Stuck escape** — net displacement < 8 m in 2 s while damaged → commit to the
    highest-reach heading 1.6 s.
14. **`safe_heading`** — revalidate the composed vector; rotate in a fan until clear.
15. **Speed** — quiet (≤ 4.85 m/s) when nothing within 70 m; boost on emergency,
    kiting, and drone breaks.
16. **Firing gate** — computes `allow_fire`, then `Combat.act`. **See the defect
    below: this gate does not actually suppress fire.**
17. **Torso** — arbiter aim, else face nearest threat, else scan (±0.55 rad sine,
    7 s, biased to the sound bearing).
18. **`pick`** an upgrade offer, **`take`** a weapon if standing on one.

## Invariants

These are load-bearing. Breaking one has caused a real bug before.

- **One torso aim per tick.** Two weapon slots, one `aim`. The arbiter enforces it;
  `_act_legacy` does not, and it measurably destroys performance (shots 66 → 19,
  kills 1.12 → 0.08).
- **Never dead-reckon `obs.mechs`.** The protocol guarantees real current position
  for `memory_s`. Adding `vel × age` double-counts (defect D1).
- **Revalidate the composed movement vector**, not the individual components.
  Dodges and repulsion can rotate a clear heading into a wall.
- **Read every rule number from `hello.config`.** No hard-coded geometry, speeds,
  or cooldowns.
- **`hello.seed` is not the match seed.** It is slot-fixed. Never derive a prior
  from it.
- **A crash is a 0-point match, not a disqualification.** `Warden.act_safe` in the
  external code is the pattern to copy.

## Known defects

| # | Defect | Impact |
| --- | --- | --- |
| D6 | Unused observation channels: `drops.progress`, `drops.capture_s`, `rear`, `by`, `kill`, `effect`, `took`, `take_failed`, `sounds.age` | No drop contest, no kill confirmation, no regen-timer awareness |
| D7 | Unused params: `retreat_hp`, `pressure_hide`, `stuck_speed`, `ffa_mode` | Dead knobs mislead A/B |
| D11 | `dodge_vector` is 2-D closest-approach; no vertical separation or impact timing | Poor mortar/laser dodging |
| **D15** | **Fire gate is inert** — `allow_fire` only scales utility, branches pass `fire=True` | Every fire-discipline experiment was a no-op; no hold-fire policy is testable |
| D16 | No heal cycle — regen is incidental | 45 HP/s resource unexploited |
| D17 | No verticality — `jump` only fires when stuck | 25 % of loot and all roof positions unreachable |
| D18 | Damage is spread; no per-target damage ledger | ~40 % of output refunded by regen |

## Where to change what

| You want to change | File | Watch out for |
| --- | --- | --- |
| When to fight | `brain.py` firing gate + `combat.pick_target` | D15: the gate does not suppress |
| Where to go | `zone.choose_goal`, `nav` | Goal thrashing without hysteresis |
| How to aim | `combat.intercept`, `future_aim`, `shot_error` | The torso slews; aim at where it *will* point |
| Weapon choice | `econ.choose_take`, `params.weapon_pref` | F8: lightning is 240 dps inside 45 m |
| Upgrade choice | `econ.upgrade_value` | Must read `hello.config.upgrades` |
| Movement safety | `nav.safe_heading` | Revalidate the composed vector |

**Next:** [`OPERATIONS.md`](OPERATIONS.md) — how to build and measure.
