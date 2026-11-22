# Mech Royale — Complete Handoff Dossier

> **Superseded in places — read [`docs/`](docs/README.md) first.**
> This file is a frozen snapshot written for external review on 2026-11-21 and is
> still the best single reference for the rules, the full protocol and the live
> config (Appendices A and B). But several of its conclusions have since been
> measured and corrected:
> - the "survival ceiling" table's pacifist row is invalid (the fire gate could not
>   suppress fire); a true pacifist scores **0.38**, not 1.69 — see `docs/FINDINGS.md` F5
> - laser DPS is **131**, not 190 (charge + cooldown is a 2.4 s cycle) — F8
> - a laser is **not** a damage upgrade; it is DPS-neutral with the gun — F8
> - official scores are now known: 1.83 → 2.44 → **2.52** → 2.50, and local deltas
>   transfer 1:1 while the offset moves with the policy — F17
>
> Where this file and `docs/` disagree, **`docs/` wins**.

**Purpose.** This document contains everything a strong external reasoner needs to  
independently re-derive a better policy for this game: the competition rules, the  
full protocol, the live configuration, the arena, the current implementation, every  
experiment we ran with its numbers, and the open problems. It is written so that  
you can reason from *this file alone* without repo access.

**What I want back** (details in §15): a critique, a ranked list of structural  
changes with expected effect, and your own implementation of the decision policy  
— not a parameter tweak. Our own sweep already proved the parameter space is  
exhausted.

**Status at time of writing.** 2026-11-21 13:41 UTC. Cutoff is 2026-11-22 20:00  
GMT+4 = **16:00 UTC, ~26 hours away**. Official practice scores so far: 0.25 →  
1.83 → 2.44, then `7468dcb` scored higher but the exact number was not recorded.  
Leader 5.96. 206 teams.

---

## 0. Executive summary — read this even if you read nothing else

1. **The scoring identity.** `score = 16 − place`, and `place = 1 + (number of
   mechs that died before you)`. Therefore **score = the number of mechs that  
   died before you**, per match, averaged over 48 matches. Maximum 15.
2. **The 15 opponents never fight each other.** They are one squad with shared  
   vision. So every opponent death is caused by *us* or by the *environment*  
   (NPC drones, zone, falls). Measured locally: `score ≈ kills + 0.7`, i.e. about  
   70 % of our score is kills and 30 % is environmental attrition.
3. **Consequence: kills and survival time are the only two terms, and fighting is  
   free.** We verified the identity directly: over 16 matches, mean score 2.00 =  
   1.31 kills + 0.69 environmental deaths. And we verified that fighting costs  
   *nothing* in survival: a bot configured to never fire and never hunt still dies  
   at 56 s, versus 59 s for the default. **Survival is capped at ~60–75 s for every  
   policy we have tried (9 variants), so there is no survival reserve left to  
   trade away.** The binding constraint is damage throughput inside that ~60 s  
   window: we deal ~3200 damage and convert 1.3 kills. Five kills needs ~10,000  
   damage, which is not reachable with the starting gun alone.
4. **The game is a sequence of duels, not a battle royale.** The squad escalates:  
   "one early, more as you thin them out, all of them late" (verbatim, track  
   page). Early game is a 1v1 gift; late game is a 1v15 you cannot win.
5. **Kills snowball.** Each cube is +4 % max HP and +4 % damage (capped +40 %),  
   and a kill drops 3 cubes. Killing early makes later kills cheaper. This is the  
   only multiplicative growth in the game and we currently do not exploit it.
6. **Weapon quality is the real damage ceiling.** 1400 HP / 45 damage = 31 gun  
   hits ≈ 7.4 s of perfect fire per kill, and we only get ~20 s of trigger time  
   before we die. The laser is 315 damage (4.4 hits) at 190 dps — roughly triple  
   the gun. Forty weapons lie on the floor and we only pick up the ones we happen  
   to walk over. Early weapon acquisition measured **+0.46 on train, +0.10 on  
   holdout** (weak, see §9.6).
7. **Measurement is the hard part.** Seed *range* behaves as a random effect: the  
   same change reads +0.67 on one range and −0.10 on another. Effects below ~0.5  
   score are unresolvable at feasible sample sizes. We already published one false  
   positive (focus fire) and had to retract it. Any claim you make must survive  
   per-range reporting on ≥3 ranges and a holdout.

---

## 1. The competition

### 1.1 Track facts (verbatim from the track page unless marked)

| Item             | Value                                                                                                                              |
| ---------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| Event            | Builders Buildathon, **Mech Royale** track                                                                                         |
| Game             | 16-mech 3D battle royale on the Ohio State campus (Ohio Stadium → the Oval)                                                        |
| Zone             | closes over ~7 minutes (6 phases, 480 s match)                                                                                     |
| Metric           | **placement points, higher is better** = `mean(16 − place)` over a run                                                             |
| Baseline to beat | **1.15** (the kit's Python example bot)                                                                                            |
| Scorer version   | `builders-3`                                                                                                                       |
| Practice run     | **48 matches** vs 15 house bots                                                                                                    |
| House bots       | **4 easy, 4 medium, 4 hard, 3 expert — acting as one squad**                                                                       |
| Squad behaviour  | *"they share vision, never fight each other, and hunt you weakest first (one early, more as you thin them out, all of them late)"* |
| Seeds            | **private and fixed all event.** The bot never sees the seed; slot and spawn vary each match                                       |
| Submission limit | **4 per hour per team** (the human operator is additionally self-limiting to 2/h to keep a slot free)                              |
| Build            | linux/amd64, network on during build, ≤10 min build, repo ≤20 MB at the submitted commit                                           |
| Repo             | must stay **public** with every submitted commit until results are published; finalists are **rebuilt**                            |
| Ties             | equal scores rank the **earlier submission** first                                                                                 |
| Cutoff           | **Sun 8:00 PM GMT+4**                                                                                                              |
| Qualification    | top **32** → 16 qualifying FFAs on new seeds → top **16** → 64-match FFA series on new seeds                                       |
| Live final       | the last 4 play live at the venue, counted the same                                                                                |
| Ranking          | series mean alone; earlier submissions break ties; non-finalists shown as negative                                                 |

**Rule that matters and is easy to miss:** practice seeds are *fixed for the whole  
event*. Every submission is therefore measured on the same 48 seeds with only  
slot/spawn varying. That makes official scores more comparable across submissions  
than fresh seeds would be — it is closer to a paired test than it looks.

**Rules that shape strategy:**

- A bot that crashes or stops answering stays in the match as a sitting target and  
  is *scored*, not rejected. So a timing failure is not a DQ, it is a 0-point match.
- Failed builds/checks are rejected and never affect your best score. Free retries.
- "Your chosen submission (your best unless you pick another) locks" at cutoff.

### 1.2 Leaderboard snapshot (2026-11-21)

| Rank | Team                  | Score |
| ---- | --------------------- | ----- |
| 1    | `azing`               | 5.96  |
| 16   | —                     | 5.38  |
| 32   | —                     | 5.13  |
| 48   | —                     | 4.88  |
| 197  | us (first submission) | 1.83  |
| —    | teams                 | 206   |

### 1.3 Our submission history

| Commit    | What it was                                                                       | Official score                       |
| --------- | --------------------------------------------------------------------------------- | ------------------------------------ |
| (initial) | starter-derived v0                                                                | 0.25                                 |
| `ac7f72a` | survival iteration: drone-aggro break, kiting, no static camping, reciprocal fire | **1.83**                             |
| `407c50e` | hunt mode v1 (close on nearest known enemy)                                       | **2.44**                             |
| `7468dcb` | hunt v2 (target the weakest, standoff 45 m)                                       | "jumped a bit" — number not recorded |

Local prediction for `7468dcb` was ~2.0–2.2 (see §14 calibration), so the official  
number is probably 2.5–3.0. We do not have it.

### 1.4 What the score means in places

`place = 16 − score`, and `kills ≈ score − 0.7` (local measurement of the  
environmental component).

| Score              | Avg place | Bots dead before us | Implied kills |
| ------------------ | --------- | ------------------- | ------------- |
| 15.0               | 1         | 15                  | win           |
| 5.96 (leader)      | 10.0      | 5.96                | ~5.3          |
| 5.38 (rank 16)     | 10.6      | 5.38                | ~4.7          |
| 5.13 (rank 32)     | 10.9      | 5.13                | ~4.4          |
| 4.88 (rank 48)     | 11.1      | 4.88                | ~4.2          |
| 2.44 (us)          | 13.6      | 2.44                | ~1.7          |
| 1.83 (us, earlier) | 14.2      | 1.83                | ~1.1          |
| 1.15 (starter)     | 14.9      | 1.15                | ~0.5          |

The distribution is discrete (16 places), so 48 matches give a granularity of  
0.021. Official score noise is roughly ±0.3–0.5 (see §9.4), which means the  
1.83 → 2.44 jump is probably real but the 2.44 → 2.6 kind of move is not  
distinguishable without several submissions.

---

## 2. The scoring identity, expanded

This is the single most important analytical result in this document. Derive it  
yourself from §4 of the protocol and check it:

- `place` is the death order: first to die is 16th, last alive is 1st.
- `score = 16 − place`.
- If `p−1` mechs died before you, `place = p`, so `score = 16 − p = 15 − (p−1)`.
- Equivalently: **score = number of mechs that died before you.**

Since the 15 house bots are one squad that never fights itself, the only ways an  
opponent dies are:

| Cause                         | Controllable?           | Measured rate          |
| ----------------------------- | ----------------------- | ---------------------- |
| We kill it                    | yes, directly           | **1.31/match**         |
| NPC drone kills it            | indirectly (lure/aggro) | 11 deaths / 16 matches |
| Zone kills it                 | indirectly (lure/delay) | 0 observed             |
| Fall / self-splash / drowning | indirectly              | 0 observed             |
| Total environmental           | —                       | **0.69/match**         |

**Verified on 16 matches:** mean score **2.00** = 1.31 kills + 0.69 environmental  
deaths, to two decimal places. The identity is exact, not an approximation.

### 2.1 The survival ceiling (measured, and it is the surprise)

We assumed survival was the thing to buy. It is not buyable. Nine policy variants  
over 16 seeds each, same seed set, same opponents:

| Policy                                     | Death time | Score | Kills |
| ------------------------------------------ | ---------- | ----- | ----- |
| default                                    | 59 s       | 2.00  | 1.38  |
| **true pacifist** (never fire, never hunt) | **56 s**   | 1.69  | 1.19  |
| coward (no fire, no hunt, kite always)     | 58 s       | 1.75  | 1.31  |
| no kiting, no hunting                      | **44 s**   | 1.38  | 1.19  |
| hide in cover always                       | 66 s       | 2.00  | 1.50  |
| kite always, range 200                     | 74 s       | 1.88  | 1.44  |
| turtle (kite hard, high HP floor)          | 73 s       | 1.75  | 1.25  |

Read that table carefully:

1. **Fighting costs nothing.** A bot that never fires dies at 56 s; the default,  
   which fights continuously, dies at 59 s. There is no survival/aggression  
   trade-off to optimise — aggression is free.
2. **Kiting is the only thing that buys life**, and it buys ~15 s (44 s → 74 s).
3. **Nothing reaches 100 s.** Eight variants, and the best is 74 s. Our survival is  
   not a tuning problem; it is an architectural wall.

Three consequences:

1. **There is no survival reserve to trade away.** Every "be more careful"  
   experiment was doomed: the careful variants die at the same time or sooner.
2. **Score is a damage-throughput problem inside a fixed ~60 s window.** 3200  
   damage → 1.3 kills. Five kills needs ~10,000 damage in 60 s = 167 sustained dps,  
   which is 89 % trigger time with the gun and zero misses. **Impossible with the  
   gun.** It requires the laser (190 dps) or the mortar (200 + splash).
3. **Therefore the leverage is: weapon quality, hit rate, and target selection** —  
   not positioning for safety.

### 2.1 The escalation rule is an explicit difficulty schedule

"one early, more as you thin them out, all of them late."


- The squad's *hunter count* is a function of how many of them we have killed.
- Early: 1 hunter → a winnable 1v1, against (probably) a weak bot.
- Mid: killing N brings more → each kill raises the marginal risk of the next.
- Late: all 15 → unwinnable; survival only.

This implies an **optimal kill rate**, not "kill as fast as possible": converting  
HP into kills faster than the escalation raises incoming pressure. It also implies  
kills should be **front-loaded**, because the same kill costs less early.

**Open interpretation (class D hypothesis):** "hunt you weakest first" most  
plausibly means the squad sends *its weakest member* first, then escalates. If  
true, the first hunter is the single easiest kill in the match and should be  
farmed deliberately. The alternative reading — they target the weakest *mech*  
(us, when hurt) — would instead mean low HP attracts more hunters, which changes  
the retreat calculus. This is worth 30 minutes of testing and we have not done it.

---

## 3. Runtime contract

| Constraint      | Value                                                                   |
| --------------- | ----------------------------------------------------------------------- |
| Decision budget | **50 ms** wall, measured server-side from `obs` send to action read     |
| CPU             | 1 core (hard cap)                                                       |
| RAM             | 512 MB, no swap                                                         |
| Processes       | ≤128 threads/processes                                                  |
| Network         | **none** at runtime                                                     |
| Filesystem      | read-only except `/tmp`, 64 MB                                          |
| User            | uid 65534, no capabilities                                              |
| Map             | mounted read-only at `/arena`                                           |
| Platform        | `linux/amd64`                                                           |
| stdout          | protocol only, one JSON object per line, ≤64 KiB, flushed               |
| stderr          | logs; the tail is shown to the submitter if the conformance check fails |
| Match clock     | 480 s, 20 Hz sim, one decision per 2 ticks (10 Hz)                      |
| Late answer     | mech keeps `move`/`boost`/`aim` for `coast_s` = 1 s, then idles         |
| Crash           | mech idles for the rest of the match, still scored                      |

Timing is the sharpest engineering constraint: at 10 Hz with a 50 ms budget you  
have ~5 ms of comfortable headroom per decision if you want p99 safely inside.  
Our current p99 is 4.3 ms (native) / 24.7 ms (Docker, 1 CPU, cold cache), max  
106 ms on one decision out of 300 in the sandbox check (allowed: ≤2 % late).

---

## 4. Protocol summary (full text in Appendix A)

Message flow:

```
server → bot   {"type":"hello", config, seed, map, slot, ...}      once
bot → server   {"type":"ready", "name": ...}                        within 20 s
loop 10×/s while alive:
  server → bot {"type":"obs", "tick":N, "me":..., "mechs":[...], ...}
  bot → server {"tick":N, "move":[x,y], "boost":b, "aim":[yaw,pitch], "fire":[a,b], ...}
server → bot   {"type":"end", "place":P, "kills":K}
```

Facts that shaped our design (each is a protocol fact unless marked):

- `hello.config` is the **complete rule set**. Read every number from it; never  
  hard-code. Balance patches are config patches.
- `hello.seed` is **slot-fixed and is NOT the match seed**. It carries no  
  information about the match. Using it as a prior is a bug (we removed that).
- `obs.mechs` keeps a previously-seen mech's **real current position** for  
  `vision.memory_s` (5 s) after it leaves view. Dead reckoning on top of that is  
  double-counting and was our defect D1.
- `beams` carry the shooter id (`by`); `projectiles` carry **no** shooter id.
- `events` are about *us* only: `damaged` (with `by`, `bearing`, `rear`), `hit`,  
  `effect`, `kill`, `drop`, `pickup`, `upgrade`, `took`, `dropped`, `take_failed`.
- Enemy HP is visible (`show_enemy_hp: true`); enemy energy, ammo, cooldowns,  
  reload state and upgrade lists are **never** exposed.
- Sound gives a world-frame bearing with σ = 7°, a coarse distance class  
  (`near`<60, `mid`<160, `far`), an `age`, and a kind — no source id, and your own  
  sounds are omitted.
- Vision: 45 m proximity in any direction, or 200 m inside a 120° wedge around  
  the **actual torso aim** (not the commanded aim). Buildings block; canopy is  
  soft (blocks with probability 0.35, at most 0.25 s of exposure); trunks block  
  sight but not shots.
- One torso, two weapon slots. `fire[0]` is the arm gun, `fire[1]` is the  
  secondary (mortar/laser/lightning). Both shots leave along the *actual* torso  
  aim, so the two slots must agree on an aim or one of them misses. Our arbiter  
  (defect D3 fix) enforces this.
- `fire=[false,true]` on a laser means "hold the charge", not "shoot". We  
  misread this once; it matters for any charge logic.
- Regen requires 5 s with **no damage dealt or taken**, then 45 HP/s, and does  
  not work outside the zone. Zone damage bypasses armor and resets the timer.  
  This makes disengage-and-heal a real mechanic that we do not model well.
- Rear hits outside a 180° front arc deal ×1.5. Facing an attacker is defensive,  
  which is why we hold the torso on the nearest threat even when not firing.

---

## 5. Live configuration (verbatim in Appendix B)

Everything below was extracted from `check/stream.jsonl.gz` — it is the *real*  
`hello.config` the scorer sends, not a default file.

### 5.1 Mech

| Field                 | Value      | Field              | Value   |
| --------------------- | ---------- | ------------------ | ------- |
| radius                | 2.5        | height             | 9       |
| eye_height            | 8          | muzzle_height      | 7       |
| hp                    | 1400       | energy             | 100     |
| walk_speed            | 11.7       | boost_speed        | 19.5    |
| ground_accel          | 58.5       | air_accel          | 12      |
| gravity               | 22         | jump_speed         | 11      |
| jet_accel             | 34         | max_rise_speed     | 10      |
| step_up               | 1.2        | max_slope_deg      | 50      |
| energy_regen          | 18         | energy_regen_delay | 0.6     |
| boost_drain           | 17         | jet_drain          | 15      |
| turn_rate             | 4 rad/s    | pitch_rate         | 3 rad/s |
| min_pitch / max_pitch | −0.7 / 1.3 | regen_delay        | 5       |
| regen_per_s           | 45         | charge_move_mult   | 0.5     |
| self_damage_mult      | 0.5        | armor              | 0       |
| rear_mult             | 1.5        | front_arc_deg      | 180     |

Derived numbers worth carrying in your head:

- 1400 HP at 45 dmg/shot = **31 gun hits** to kill; 315 laser = 4.4 hits.
- Walk 11.7 m/s crosses the 200 m vision range in 17 s.
- Boost 19.5 m/s but 17 energy/s against 100 energy → ~5.9 s of boost, then a  
  0.6 s delay + 18/s refill.
- Time-to-kill with the gun at 0.24 s cooldown and a 12-round mag: 12 shots =  
  540 damage in 2.9 s, then 2.4 s reload. So ~10 s of sustained fire per kill,  
  assuming every shot hits. **This is why kills are hard and why the laser and  
  mortar matter.**

### 5.2 Weapons

|          | gun         | mortar                                                             | laser                                                                | lightning                                            |
| -------- | ----------- | ------------------------------------------------------------------ | -------------------------------------------------------------------- | ---------------------------------------------------- |
| damage   | 45          | 200                                                                | 315                                                                  | 60                                                   |
| cooldown | 0.24        | 2.6                                                                | 1.65                                                                 | 0.25                                                 |
| speed    | 252 m/s     | 72 m/s                                                             | hitscan                                                              | instant                                              |
| range    | 230         | (ttl 7 s)                                                          | 280                                                                  | 45                                                   |
| mag      | 12          | —                                                                  | —                                                                    | —                                                    |
| reload   | 2.4         | —                                                                  | —                                                                    | —                                                    |
| special  | spread 0.6° | splash 160 @ r7, edge 0.3, gravity 22, knock 16/9, energy drain 45 | charge 0.75 s, min_charge 0.15, min_frac 0.35, hold 2 s, cookoff 0.6 | cone 30°, chain 2 @ 14 m, falloff 0.7, 3 energy/shot |

Notes that matter:

- Mortar is the only area weapon (160 splash in a 7 m radius) → **the only tool  
  that punishes the squad for clustering on us**, which they do by design late.
- Laser is the highest burst in the game and is telegraphed for 0.75 s, so it is  
  best used as an opener at range or on a target already committed to a fight.
- Lightning is a 45 m finisher: 60 damage per 0.25 s is 240 dps at contact range,  
  but it costs energy and interrupts laser charge.
- Only the gun is guaranteed. Mortar/laser/lightning come from 40 floor pickups,  
  36 crates (50 % weapon chance) and death drops.

### 5.3 Zone

| Phase | Hold | Shrink | Radius              | DPS |
| ----- | ---- | ------ | ------------------- | --- |
| start | —    | —      | 560 @ (41.3, −72.8) | 0   |
| 1     | 60   | 50     | 380                 | 20  |
| 2     | 45   | 40     | 240                 | 35  |
| 3     | 35   | 35     | 140                 | 60  |
| 4     | 30   | 30     | 70                  | 100 |
| 5     | 25   | 25     | 25                  | 160 |
| 6     | 15   | 25     | 0                   | 260 |

Total 480 s. The arena is 1067 × 722 m, so the starting circle covers a fraction  
of it and the first shrink is the only one that allows long rotations. By phase 4  
(radius 70) the match is a knife fight in ~150 m of space; at radius 25 everything  
is inside 50 m of everything. **All late-game decisions are therefore decided by  
who is already inside the small circle and facing the right way.**

### 5.4 Economy

|                    | Value                                                                                                                               |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------------- |
| cubes              | pickup r 3.5; +4 % max HP (heals the difference) and +4 % damage, capped at 10 cubes (+40 %); **+5 % body size per cube, uncapped** |
| death drop         | 1 cube + `death_drop_extra` 2 = **3 cubes per kill**                                                                                |
| upgrade thresholds | 1, 3, 6, 10, 15, 21, 28, 36, 45 cubes                                                                                               |
| crates             | 36, hp 300, r 1.4, 25 % on roofs, 1 cube, 50 % weapon chance                                                                        |
| floor loot         | 40 weapons, 25 % on roofs, equip 1 s                                                                                                |
| supply drops       | t = 70 / 140 / 210, fall 25 s, radius 8, capture 4 s alone, 3 cubes + **full HP and energy**                                        |
| NPCs               | 12, hp 350, speed 5, aggro 45, deaggro 90, 25 dmg @1 s, leash 30/60, 2 cubes                                                        |

Two things stand out:

- **A supply drop is a full heal plus 3 cubes for 4 s of standing still.** At  
  t=70/140/210 that is potentially a second life. We score `drop_aggression: 0.0`  
  — we ignore them entirely. This is almost certainly wrong for a kill-focused  
  policy, and it is untested.
- **Cube size growth is a downside**: +5 % radius per cube, uncapped. At 10 cubes  
  you are 1.5× wider — much easier to hit. Damage/HP gains cap at 10 cubes, so  
  cubes 11+ are pure downside except for upgrade thresholds.

### 5.5 Upgrades (exact, from `hello.config.upgrades`)

| id                   | effect                                          | max | requires  |
| -------------------- | ----------------------------------------------- | --- | --------- |
| plating              | +15 % max HP                                    | 3   | —         |
| armor                | −8 % damage taken                               | 3   | —         |
| servos               | +8 % walk & boost                               | 3   | —         |
| capacitor            | +30 energy                                      | 3   | —         |
| reactor              | +30 % energy regen                              | 3   | —         |
| jets                 | −25 % boost/jet drain                           | 2   | —         |
| nanites              | +60 % regen, −1.5 s delay                       | 2   | —         |
| gyros                | +30 % turn/pitch                                | 2   | —         |
| sensors              | +15 m proximity, +25 m vision, half sound error | 2   | —         |
| gun_damage           | +15 % gun damage                                | 3   | gun       |
| gun_rate             | +15 % gun fire rate                             | 3   | gun       |
| gun_velocity         | +25 % projectile speed, +15 % range             | 2   | gun       |
| gun_mag              | +8 rounds, −20 % reload                         | 2   | gun       |
| mortar_splash        | +30 % splash radius                             | 2   | mortar    |
| mortar_reload        | −18 % cooldown                                  | 3   | mortar    |
| mortar_velocity      | +20 % shell speed                               | 2   | mortar    |
| laser_charge         | −25 % charge time                               | 2   | laser     |
| laser_damage         | +18 % damage                                    | 3   | laser     |
| laser_pierce         | +1 pierce                                       | 1   | laser     |
| lightning_chain      | +1 chain                                        | 2   | lightning |
| lightning_range      | +20 % range & cone                              | 2   | lightning |
| lightning_efficiency | −35 % energy, +10 % damage                      | 2   | lightning |


Offers arrive at cube thresholds; timing out applies choice 0. Our valuation  
(`econ.py`) computes the exact marginal effect of each offer from the config and  
weights by survival value (hp 70, armor 60, mobility 9, aim 9, sensors 4). Weapon  
upgrades are gated on `requires`, and weapon upgrades persist across weapon drops.

**Note for a kill-focused policy:** this weighting is survival-biased. For a  
kill-rate objective, `gun_damage`, `gun_rate`, `laser_damage` and `laser_charge`  
should rank much higher, and `armor`/`plating` are only worth it because they buy  
more fighting time.

---

## 6. The arena

|           | Value                                                                                          |
| --------- | ---------------------------------------------------------------------------------------------- |
| Bounds    | x ∈ [−512.38, 555.08], y ∈ [−333.09, 388.64] (1067 × 722 m)                                    |
| Terrain   | `terrain.i16`: int16 little-endian **centimetres**, 1070 × 724 vertex grid, 1 m step, bilinear |
| Solids    | **259 prisms** (223 building prisms, 64 blocks) with rings/holes                               |
| Overhangs | **9 bridges** (bridge overhang intervals over columns)                                         |
| Trees     | **1560** (trunk radius ~0.6–0.7, crown radius 2–13 m, crown base 2–17 m above ground)          |
| Cars      | 446                                                                                            |
| Water     | 2 regions                                                                                      |
| Map rules | `maxStep` 1.5, `maxSlopeDeg` 50, `canopyDensity` 0.35, `canopyBlockT` 0.25                     |

The map is a real OSU campus slice: a stadium with sector rings and openings, the  
Oval, roads, and dense tree cover in the west. Consequences:

- **Terrain is the only thing that beats shared vision.** Distance does not: 200 m  
  of vision with a squad that shares it means "being seen" is effectively  
  permanent. Buildings and the stadium rim are hard occluders; trees are soft  
  (canopy blocks vision probabilistically, trunks block sight but not shots).
- **Buildings are climbable** (roofs are solid prisms, `step_up` 1.2 m), which  
  makes rooftops both a strong position and a trap: you cannot dodge off a roof.
- **Bridges create overhangs**: a shot can pass under a bridge that blocks vision,  
  and vice versa. Our world model handles this with per-column interval lists.
- The stadium has `sectors`, `rimWidth`, `rOuter`, `knots`, `openings`, `outline`  
  — it is a ring you can enter and be trapped inside.

---

## 7. Current solution — architecture

Python 3.13, standard library only, ~130 KB of source. Entry point `bot.py` wraps  
the official `mechfight.py` (protocol loop only). Everything else is ours.

| File        | Lines | Role                                                                                |
| ----------- | ----- | ----------------------------------------------------------------------------------- |
| `brain.py`  | ~800  | Decision core: state update, mode selection, movement, firing gate, torso           |
| `combat.py` | ~700  | Aiming, lead, torso slew, target selection, weapon dispatch, arbiter, dodging       |
| `intel.py`  | ~570  | Belief layer: per-mech records, sound sectors with live σ, explicit unknowns        |
| `world.py`  | ~420  | 1 m engine-accurate arena model: solid tops, overhangs, 9-point body collision, LOS |
| `nav.py`    | ~230  | 8 m nav grid, bounded A*, steering, collision-safe heading filter                   |
| `zone.py`   | ~150  | Circle interpolation, hide-spot scoring, route clearance, goal hysteresis           |
| `econ.py`   | ~300  | Upgrade valuation from live config, pickup/take logic, loot goals                   |
| `cover.py`  | ~70   | Local occlusion spot search (optional, off)                                         |
| `params.py` | ~175  | All knobs + `BOT_PARAMS` env override for A/B                                       |

### 7.1 World model (`world.py`)

The important design decision: it is **not** a heightmap walker, it is a  
per-column solid-interval model at 1 m resolution.

- For each (x,y) cell it stores `top` (the highest solid surface) and, for cells  
  under bridges, an overhang interval `[ohb, oht]`.
- `solid(x,y,z)` = `z < top[k]` or inside the overhang interval. This is used for  
  projectile lines and LOS.
- `blocked(x,y,z,h,step_up,radius)` tests a **9-point body ring** (centre + 8  
  points on the radius) against the column tops with `step_up` tolerance — the  
  engine's cylinder is not a point.
- `shot_clear(a,b)` marches the segment and rejects on `solid`.
- `vision_clear(a,b)` additionally applies canopy probability from  
  `rules.canopyDensity` / `canopyBlockT`.
- Every geometric constant is read from `hello.config`, not hard-coded  
  (`radius`, `height`, `eye_height`, `muzzle_height`, `step_up`, `size_per_cube`).

This fixed a hard bug: the original heightmap-only model let the mech wedge into  
a building corner where it was farmed to death by a single NPC drone at t≈70 s.  
Nine-point collision plus composed-vector revalidation removed it.

`NullWorld(cfg)` mirrors the same interface when the map cannot be read, so a  
missing `/arena` degrades to "no terrain knowledge" rather than a crash.

### 7.2 Intelligence layer (`intel.py`)

`Belief` per mech id (0–15 only; anything else is an NPC/crate/zone id):

```
pos (protocol-current), pos_t, vel, hp, max_hp, cubes, weapons, confidence,
unknown = ("energy","ammo","cooldown","reload","upgrades","stats")
```

- Positions from `obs.mechs` are treated as **protocol-current** (no dead  
  reckoning) because the protocol guarantees real current position for 5 s.
- Sounds become `Sector(source, kind, bearing, sigma, rmin, rmax, age)` with  
  `sigma = bearing_noise_deg × me.stats.hearing` and the distance interval from  
  the class (`near` 0–60, `mid` 60–160, `far` 160–∞). `effective_age()` adds wall  
  time since receipt, so a stale sector decays honestly.
- `penalty(x,y)` returns how much a candidate position is contradicted by a  
  sector — used as a soft cost in zone-goal scoring, never as a hard constraint.
- `sound_pressure()` sums sector confidence; it feeds the `adapt` factor.
- Queries: `threat_points()`, `uncertain_points()`, `visible_dicts()`,  
  `sector_contacts()`, `sound_bearing()`.

The design principle is **explicit uncertainty**: never fabricate a point from a  
bearing, never pretend to know energy/ammo/cooldowns.

### 7.3 Navigation (`nav.py`)

- 8 m coarse grid built from the 1 m model, marking a cell blocked if the body  
  cannot stand at its centre.
- A* with a **wall-clock budget of 2.6 ms** and a node cap; if it fails, fall back  
  to greedy steering. This is what keeps p99 inside 50 ms on 1 CPU.
- `steer()` returns a unit vector toward the next waypoint with local avoidance.
- `safe_heading()` is the important one: after composing *all* desired motion  
  (path + dodge + NPC repulsion + strafe), it re-validates the **resultant**  
  vector and rotates it in a fan until it is collision-free. Composing  
  individually-valid vectors can produce an invalid sum, which is how the mech  
  used to wedge.

### 7.4 Zone logic (`zone.py`)

`choose_goal` scores 12 candidate points on a ring at `goal_offset × next_radius`  
from the next circle centre:

```
score = −|dist to ring point|·travel_bias
        + cover_score(gx,gy)          · cover_bias
        + min(dist to nearest threat, 200) · threat_bias
        + ground height · slope_bias
        − sound sector penalty
        − route clearance penalty
```

Two additions mattered:

- **Route clearance**: the ring is scored by *endpoint* distance, so the bot would  
  drive straight through a visible squad to reach a spot a few metres better. The  
  route is now sampled every ~45 m and penalised if the worst clearance along it  
  is under `path_threat_r`.
- **Goal hysteresis**: hold a goal for 6 s unless a candidate beats it by 14  
  points. Without this the argmax flipped every decision and the mech oscillated  
  in place (measured: 0 net displacement over 40 s while under fire).

### 7.5 Combat (`combat.py`)

- `intercept(src, tgt, vel, speed)`: constant-velocity lead. For the gun this is  
  exact enough; for the mortar it solves the ballistic pitch (`mortar_pitch`).
- `future_aim(me, yaw, pitch, dt=0.1)`: predicts where the torso will actually  
  point after the slew, because `turn_rate` is 4 rad/s and the command is applied  
  over 0.1 s. Aiming at the target's current bearing while the torso is still  
  turning is how shots miss.
- `shot_error(src, point, yaw, pitch)`: perpendicular miss distance, used as the  
  firing tolerance.
- `target_center(actor, frac=0.5)`: aim at mid-body. We measured that aiming high  
  (0.75) is worse (−0.47) because it clips intervening geometry.
- `pick_target`: **hysteresis** — keep the same target until it dies or another  
  beats it by `focus_switch_margin`. Without this, damage spread across the squad  
  and 40 % of output went into bots that never died.
- `dodge_vector` / `laser_dodge`: perpendicular displacement away from the  
  closest-approach point of incoming projectiles, and out of a charging laser's  
  line.
- **The arbiter** (`_act_arbiter`) is the core fix for D3: each weapon branch  
  proposes `(slot, kind, aim, point, tol, utility, fire, fired)`. The arbiter  
  picks the highest-utility candidate as the single torso aim, then fires any  
  *other* candidate whose shot would still land given that aim (within its  
  tolerance, or inside its cone for lightning). One torso, no contradictions.
- **Critical detail we discovered late:** the gun/lightning/mortar branches pass  
  literal `fire=True` and the caller's `fire_gate` only scales *utility*. So the  
  gate never actually suppressed a chosen weapon. Every "fire discipline"  
  experiment we ran measured flat for that reason, and we wasted several runs on  
  it. Any new gating must zero the `fire` flag or drop the candidate.

### 7.6 Decision loop (`brain.act`), in order

1. Update state; compute `hp_frac`, visible enemies, threat points, nearest NPC,  
   net displacement over 2 s.
2. `adapt` factor: \`1 + min(1.2, recent_damage·0.18) + min(0.8, sound_pressure·0.12)
   - (0.5 if t > 250)\`. Everything downstream divides engagement range by it.
3. Situational controller (`trade_adapt`, **off**): `press` if dealt/taken > 1.35  
   and HP > 45 %; `disengage` if ratio < 0.65 or HP < 32 %.
4. Zone goal (with sectors, route clearance, hysteresis). If outside the circle  
   by more than 12 % of its radius → emergency, goal = centre.
5. **Drone aggro break**: if an NPC is inside 50 m and we have taken damage (or  
   it is inside 26 m), sprint directly away for 2.8 s. Drones move 5 m/s; a quiet  
   4.85 m/s walk cannot outrun them, so this is a boost, not a walk.
6. Early roam (`roam_until = 0`, off).
7. Opportunistic loot: if nothing is within 55 m and `t < 250`, detour to a  
   pickup/cube within 30 m.
8. **Hunt**: if enabled, HP > 45 %, `t < 420`, not emergency, not disengaging →  
   pick the weakest visible enemy within 170 m and walk to it until 45 m.
9. Kill-loot detour (`loot_kill_enabled`, **off**).
10. LOS-breaking cover (`cover_enabled`, **off**; neutral locally, ~10 ms/decision).
11. **Kiting**: if the nearest enemy is inside 100 m and we are below 97 % HP,  
    pick an occlusion-seeking heading (12-way fan, score = hidden·60 + gain·0.35)  
    and boost along it for 6 s.
12. Movement: A* replan if the goal moved >18 m or 3.5 s elapsed; add dodge  
    vectors (×1.4), laser dodge (×1.2), NPC repulsion inside 42 m, and strafe  
    within 120 m. Stop at the goal only if no enemy is within 120 m.
13. Stuck escape: if net displacement < 8 m over 2 s while damaged, or stuck > 0.7 s,  
    commit to the highest-reach heading for 1.6 s.
14. Re-validate the composed heading with `safe_heading`.
15. Speed: quiet (≤4.85 m/s) when nothing is within 70 m and not fleeing/hunting;  
    boost on emergency, on kiting, and to break drone aggro.
16. Firing gate → `combat.act(allow_fire, allow_charge)`; arbiter returns one aim  
    plus per-slot fire flags.
17. Torso: the arbiter's aim, else face the nearest threat, else scan (±0.55 rad  
    sine at 7 s period, biased toward the sound bearing).
18. `pick` an upgrade offer; `take` a weapon if standing on one.


## 9. Experiment ledger — everything we tried

Local deltas are paired score differences in the simulator (not official points).  
"Rejected" means the measured effect was negative or unresolvable and the default  
stayed unchanged.

### 9.1 Adopted (kept)

| Change                                                                                                | Paired result                                                                            | Why kept                                                                        |
| ----------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| Single torso-aim arbiter (D3)                                                                         | **+0.54 ± 0.28** harsh / **+0.71 ± 0.59** mild                                           | Only one aim can be commanded; without it shots miss                            |
| Protocol-first belief layer (D1/D2)                                                                   | +0.04 ± 0.07                                                                             | Neutral, but removes double-counted dead reckoning and false precision          |
| D1+D2+D3 together                                                                                     | **+0.63 ± 0.25** / **+1.50 ± 0.40**                                                      | The combination is much better than the parts                                   |
| 1 m engine-accurate collision + composed-heading validation                                           | fixed a hard wedging bug (farmed to death by one drone at t≈70 s)                        | Correctness                                                                     |
| Squad kiting (boost away from incoming-fire bearings, 5–6 s)                                          | **+0.55 ± 0.27**                                                                         | Death time 80 → 105 s                                                           |
| Live-config geometry (D5)                                                                             | +0.42 ± 0.51 / +0.13 ± 0.18                                                              | Inconclusive as a gain; kept as correctness                                     |
| Movement discipline (route clearance, goal hold, reciprocal fire, kite range gate, no static camping) | score −0.22 ± 0.44, survival −3.5 ± 13.2 s, **dealt +335 ± 239**, **kills +0.25 ± 0.21** | Neutral on survival, positive on offence; each item fixes a demonstrated defect |
| Quiet movement (≤ step_speed)                                                                         | vs full speed: **+0.67** for quiet                                                       | Footsteps are audible at 40 m, boost at 90 m                                    |
| Exact config upgrade valuation (D4)                                                                   | +0.04 ± 0.09 / 0.00 ± 0.12                                                               | Neutral; correct under balance patches                                          |
| Hunt mode v1 → v2 (target the weakest)                                                                | local neutral/negative, official **+0.61** (1.83 → 2.44)                                 | The one case where the official result beat the local proxy                     |

### 9.2 Rejected (measured negative, default unchanged)

| Change                                       | Result                                               | Note                                    |
| -------------------------------------------- | ---------------------------------------------------- | --------------------------------------- |
| Aggression 0.95 / 0.7                        | 0.00 / −0.31                                         | flat to negative                        |
| LOS-breaking cover on                        | 0.00 ± 0.07                                          | neutral, costs 10 ms/decision           |
| Early roam + weapon/cube farming             | **−0.50 ± 0.17**                                     | the bundle included loud crate shooting |
| Kite hold 14 s vs 8 s                        | −0.21 ± 0.13                                         | over-commits                            |
| Laser pre-charge                             | −0.16 ± 0.13                                         | telegraphs, and the gate did not gate   |
| Indirect mortar (accept LOS-blocked targets) | −0.28 ± 0.11                                         | wastes shells                           |
| Economy bundle (roam + crates + drops)       | **−0.78 ± 0.36**                                     | loud and slow                           |
| High aim point (0.75 body)                   | −0.47 ± 0.23                                         | clips geometry                          |
| Open ground (`cover_bias` 0)                 | −0.22 ± 0.19                                         | cover matters                           |
| Statue (never move)                          | **−0.46**                                            | survival without agency is worse        |
| Coward (never fire)                          | 0.00                                                 | firing is not what kills us             |
| Trade-ratio controller                       | **−0.062 ± 0.233** per-range [−0.25 / −0.44 / +0.50] | noise                                   |
| Hunter v3 (aggressive variant)               | −0.15                                                |                                         |
| Zone-edge goal                               | +0.19 / +0.67 / −0.10 → +0.25 ± 0.23 pooled          | inconclusive                            |

### 9.3 Inconclusive (left at default)

| Change                              | Result                                              |
| ----------------------------------- | --------------------------------------------------- |
| Aggression 1.0 / `engage_range` 240 | +0.12 ± 0.12                                        |
| Mortar-preferring loadout           | −0.02 ± 0.09                                        |
| Focus fire                          | +0.38 ± 0.13 then −0.04 ± 0.08 → **false positive** |
| Kill-loot collection                | not yet measured (built, default off)               |

### 9.4 The 14-dimension sweep

Harness: cached per-seed baseline, so a candidate costs one arm (~82 s). Three  
training ranges × 16 seeds, holdout on three untouched ranges.

Baselines: train **1.96 / 71 s / 1.27 kills**; holdout **1.65 / 66.5 s / 1.17 kills**.

Dimensions swept: `aggression`, `cover_bias`, `engage_range`, `focus_switch_margin`,  
`hp_floor`, `hunt_hp`, `hunt_range`, `hunt_standoff`, `hunt_target`, `hunt_until`,  
`kite_range`, `quiet_when_safe`, `strafe_gain`, `threat_bias`.

**Result: no reliable winner.** Per-range deltas swing by up to 1.2 score *within a  
single config* (e.g. `+0.31 / −1.00 / +0.12`). Only one config was positive on all  
three training ranges and it had *negative* kills — self-contradictory.

Best by mechanism (kills):

| Set     | Pooled score | Δkills | Per-range             |
| ------- | ------------ | ------ | --------------------- |
| train   | +0.33        | +0.38  | +0.69 / −0.25 / +0.56 |
| holdout | +0.15        | +0.06  | +0.38 / +0.06 / +0.00 |

5 of 6 ranges non-negative, pooled ≈ +0.24 — real but small, and **not clearly  
better than the already-submitted build**. Conclusion: **this parameter space is  
exhausted; remaining gains are structural.**

### 9.5 Decision-time budget (why firing discipline never mattered)

Over 387 sampled decisions:

| State                               | Fraction |
| ----------------------------------- | -------- |
| A shootable target exists           | **21 %** |
| Alone (no enemies visible or heard) | 35 %     |
| Enemies visible but terrain-blocked | **44 %** |

Damage is limited by **target availability**, not by permission to shoot. That is  
the strongest local evidence that the policy should spend its effort on *creating*  
engagement opportunities (positioning, closing, weapon acquisition) rather than on  
when to pull the trigger.

### 9.6 Early weapon acquisition (the most promising open lever)

Motivation: §2.1 shows the gun cannot physically reach 5 kills in a 60 s life.  
The laser can. Forty weapons sit on the floor.

| Config                                             | Train (48)       | Holdout (48)     | Per-range (train)     | Δkills        |
| -------------------------------------------------- | ---------------- | ---------------- | --------------------- | ------------- |
| `roam_until 45`, `weapon_seek_range 200`, hunt off | **+0.46 ± 0.30** | **+0.10 ± 0.24** | +0.44 / +0.12 / +0.81 | +0.46 / +0.19 |

Train is positive on all three ranges and kills rise on both sets, but the holdout  
is mixed (+0.94 / −0.12 / −0.50). By our own standard this is **inconclusive, not  
a win** — the same profile as the configs the sweep rejected. It is recorded  
because the *mechanism* (laser → damage throughput) is the only one that can  
plausibly bridge a 3× kill gap, and because it is the one change where kills moved  
on both train and holdout.

A single-match trace shows the failure mode directly: one match dealt **4463  
damage with 0 kills** while holding a lightning for 30 % of the match. Damage was  
spread across several bots, each of which regened it back at 45 HP/s. **Damage  
that does not kill is worth almost nothing in this game.**

---

## 10. Findings — the physics and economics of this game

1. **Terrain beats vision; distance does not.** 200 m vision + shared intel means  
   being seen is permanent. Only hard occluders (buildings, stadium rim) break  
   contact. Our kiting works because it seeks occlusion, not because it runs away.
2. **The zone is the real clock.** By phase 4 (r=70) the fight is in ~150 m. A bot  
   that is late to rotate fights the zone and the squad simultaneously. Zone  
   damage (100–260 dps) dwarfs gun damage, so being caught outside is fatal in  
   under 10 s at phase 5.
3. **Regen is a fighting resource.** 45 HP/s after 5 s of no damage dealt *or*  
   taken. A kill-focused policy needs a deliberate "disengage → 5 s clean → heal →  
   re-engage" cycle. We have no such cycle: we heal only incidentally.
4. **Kills compound.** 3 cubes per kill = +12 % HP and +12 % damage, plus an  
   upgrade offer at 1/3/6 cubes. Two early kills make the third much cheaper.  
   This is the only snowball in the game and it is the mechanism by which the  
   leader is at 5.96 while we are at 2.44.
5. **Time-to-kill is long.** ~10 s of sustained gun fire per kill, or 4.4 laser  
   hits. A duel is decided by who lands more of a long exchange, not by burst.  
   That favours: cover, strafing, facing the enemy (rear ×1.5), and the mortar  
   (200 damage + 160 splash, no line-of-fire requirement beyond the arc).
6. **The squad clusters on us late.** By design ("all of them late"). A mortar  
   into 3 bots at 7 m radius deals 200 + 160×2 = up to 520 damage per shell. That  
   is the single highest-value weapon in the endgame and we barely use it.
7. **NPC drones are a neutral third party.** 12 of them, 350 HP, 25 dps, aggro 45  
   m, deaggro 90 m. They damage anyone. Luring them into a house bot is a  
   legitimate, unexplored kill mechanism; we only ever run away from them.
8. **Supply drops are a second life.** Full HP + full energy + 3 cubes for 4 s of  
   standing still, three times per match. We ignore them entirely.
9. **Body size grows with cubes** (+5 % radius each, uncapped) while the HP/damage  
   bonus caps at 10. So cubes beyond 10 are a net negative except for upgrade  
   thresholds — an unusual incentive that no one seems to model.
10. **`hello.seed` is worthless as information.** It is slot-fixed. Any policy that  
    derives a direction or spawn prior from it is fitting noise.


## 12. Known defects and open opportunities

### 12.1 Defects still open

| #   | Defect                                                                                                                                                  | Impact                                                          |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| D6  | Unused observation channels: `drops.progress`, `drops.capture_s`, `rear`, `by` (for attribution), `kill`, `effect`, `took`, `take_failed`, `sounds.age` | No drop contest, no kill confirmation, no regen-timer awareness |
| D7  | Unused parameters: `retreat_hp`, `pressure_hide`, `stuck_speed`, `ffa_mode`                                                                             | Dead knobs mislead future A/B                                   |
| D11 | `dodge_vector` is 2-D closest-approach; no vertical separation, gravity or impact timing                                                                | Poor mortar/laser dodging                                       |
| —   | Fire gate only scales utility, never suppresses fire                                                                                                    | Every "discipline" experiment was a no-op (documented)          |
| —   | No heal cycle (disengage → clean 5 s → re-engage)                                                                                                       | Fights are all-in                                               |
| —   | No weapon-acquisition priority                                                                                                                          | Damage capped at gun rate                                       |
| —   | Damage is spread, so regen erases it (4463 dealt → 0 kills in one trace)                                                                                | ~40 % of output wasted                                          |
| —   | No drop contest, no NPC luring, no mortar-into-cluster play                                                                                             | Three unused kill mechanisms                                    |

### 12.2 Open opportunities, ranked by expected value (my judgement, post-measurement)

1. **Damage conversion.** We deal 3200–4500 per match and kill 1.3. Either the  
   damage is spread across targets that regen it back, or it is overkill. A  
   kill requires 1400 damage inside the regen window; anything less is refunded at  
   45 HP/s. **Fix the conversion before adding aggression** — it is the cheapest  
   multiplier we have, and it needs no new mechanics, only stricter target  
   commitment (do not switch, do not chip, do not poke at range).
2. **Weapon acquisition.** The only mechanism that raises the damage ceiling.  
   Measured +0.46 train / +0.10 holdout, kills up on both. Weak but mechanistically  
   necessary: the gun cannot reach 5 kills in 60 s, the laser can.
3. **Weapon-choice quality.** We currently take whatever we walk over, and  
   `weapon_pref` ranks lightning above the gun even though lightning is 45 m /  
   60 damage. Picking the *right* weapon (laser > mortar > gun > lightning for this  
   matchup) and dropping a bad one is a free win.
4. **Supply-drop contest at t = 70/140/210.** Full heal + 3 cubes for 4 s. Contest  
   when no enemy is within ~50 m and we are below ~70 % HP.
5. **Mortar-into-cluster.** When ≥2 enemies are within 7 m of each other and  
   40–120 m away, lob a shell: 520 damage per shell vs 200 self-damage risk.
6. **NPC luring.** Drag drone aggro into a house bot and break contact. 25 dps for  
   free on a target we are not trading with — and NPCs already kill 0.69 bots per  
   match without our help.
7. **Heal-cycle controller.** `engage → break (occlusion, boost) → clean 5 s →
   heal to 80 % → re-engage`. Regen is currently accidental.
8. **Kill-loot collection.** 3 cubes at the corpse we just made, 7 s window, only  
   when nothing is within 55 m. Built, default off, unmeasured.

### 12.3 Things that are *not* worth doing (already measured)

Parameter tuning of the existing policy; firing discipline; cover-seeking;  
indirect fire; high aim; laser pre-charge; crate/NPC farming as a primary plan;  
zone-edge camping; trade-ratio adaptation. All measured, all flat or negative.

---

## 13. Calibration: local proxy vs official score

| Build                        | Local (paired mean) | Official                      |
| ---------------------------- | ------------------- | ----------------------------- |
| v0 starter-derived           | ~0.2                | **0.25**                      |
| `ac7f72a` survival iteration | 1.9–2.1             | **1.83**                      |
| `407c50e` hunt v1            | ~2.0                | **2.44**                      |
| `7468dcb` hunt v2            | ~2.0–2.2            | not recorded ("jumped a bit") |

Conclusions:

- **Absolute calibration is good**: local 1.9–2.1 vs official 1.83.
- **Aggression transfers better officially than locally**: hunt mode was neutral  
  locally and +0.61 officially. The local squad over-punishes aggression, probably  
  because the emulation's expert bots are stronger than the real ones.
- **The local ceiling is ~2.0** because the emulated house bots survive 87 % of  
  matches. The score signal is nearly flat, so survival time and kills are the  
  primary local signals, not score.

**Practical implication:** a change that improves *kills* locally without hurting  
score is more promising than its score delta suggests. This is exactly the  
profile of the best sweep config (+0.33 score, +0.38 kills).

---

## 14. What the human operator does, and the constraints I work under

- **All official submissions are made manually by the human.** I never submit. I  
  notify via a Discord webhook when a submission is warranted (with `@everyone`),  
  and send ordinary devlogs without it.
- **Budget:** the platform allows 4 submissions/hour; the human self-limits to 2  
  and wants at least one slot left free. Default policy: at most one submission  
  per hour, only for genuinely promising changes.
- **Autonomy:** I operate headless/terminal only. No desktop takeover, no  
  simulated input, no browser-profile or cookie access, no interference with the  
  human's session.
- **Repo:** public, Dockerfile at root, ≤20 MB, MIT, atomic commits per experiment.
- **Never lock or select a final entry** — the platform locks the best score  
  automatically, and the human decides.

---

## 15. What I want from you

Please return, in this order:

### 15.1 Critique (short)

Where is the reasoning in this document wrong? Specifically check:

- the scoring identity in §2 and the `score = kills + 0.69` decomposition;
- **the central puzzle:** every policy we try dies at 44–74 s, and the best score  
  any of them reaches locally is ~2.6. Yet the leaderboard leader is at 5.96, which  
  needs ~5 opponent deaths per match. Either (a) they kill 5 bots in ~60 s, which  
  requires ~10,000 damage and therefore the laser, or (b) they survive far longer  
  than our 60 s and collect environmental deaths as the zone collapses, or (c) our  
  local proxy is systematically harsher than the real squad. **Tell me which you  
  believe and what would discriminate between them**, because the entire strategy  
  hinges on it;
- the claim that weapon acquisition is a prerequisite for kill rate (measured, but  
  only +0.46 train / +0.10 holdout — argue with it);
- whether "never fight each other" has any loophole we are missing (e.g. can we  
  make them damage each other with splash, knockback, or by body-blocking?).

### 15.2 A ranked plan (the main deliverable)

5–8 structural changes, each with:

- the mechanism (why it raises `bots dead before us`),
- the expected effect size in score and kills,
- the risk to survival,
- the cheapest experiment that would falsify it.

Order them by expected value per hour of implementation, given ~26 hours left and  
a ~4-minute local A/B cycle.

### 15.3 Your own implementation

A complete decision policy for `mechfight/1`. It can be Python pseudocode or real  
code. It must:

- respect the 50 ms budget on 1 CPU (state your complexity per decision);
- read all numbers from `hello.config`, never hard-code;
- handle: no map available, no visible enemies, being outside the zone, being  
  hunted by 2+ bots, a charging laser pointed at us, a mortar in flight;
- specify its behaviour in the first 60 s, the mid game, and the final 60 s  
  separately, since the squad's escalation makes these different games.

### 15.4 The first three things to test

Concrete, with the exact metric and the sample size you would accept as evidence.

### 15.5 Things you would need that are not in this document

Be explicit about what you cannot decide without more data. I can run experiments  
and report back.

**Do not** propose parameter tuning of the existing knobs (exhausted, §9.4), and  
do not re-propose anything in §9.2 without a new mechanism that explains why the  
previous measurement was wrong.

---

## 16. Repo layout and how to run things

```
work-dir/
  bot.py                 entrypoint (wraps mechfight.run)
  brain.py               decision core
  combat.py              aiming, arbiter, dodging
  intel.py               belief layer
  world.py               1 m arena model
  nav.py                 nav grid, A*, safe heading
  zone.py                circle + hide-spot selection
  econ.py                upgrades, pickups, loot goals
  cover.py               occlusion spot search (off)
  params.py              all knobs, BOT_PARAMS override
  mechfight.py           official protocol wrapper
  mechfight.schema.json  official schema
  check/                 official conformance check + recorded stream
  arena/v2/              world.json + terrain.i16
  Dockerfile             python:3.13-slim, ENTRYPOINT bot.py
  AUDIT.md               protocol ledger (classes A–E), defect table D1–D14
  README.md              experiment log + measurement protocol
  HANDOFF.md             this file
```

```sh
# build + conformance, native
docker build --platform linux/amd64 -t mech-bot .
python3 check/check.py -- python3 -u bot.py

# conformance inside the real sandbox (this is what the scorer runs)
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none \
  --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m \
  --user 65534:65534 -v "$PWD/arena:/arena:ro" mech-bot

# A/B a variant locally (dev harness, not in the repo)
BOT_PARAMS='{"hunt_range": 230}' ./ab.sh <seed> <range>
```



---

## Appendix A — Full protocol, verbatim

# Bot protocol `mechfight/1`

This document is the complete specification for writing a bot. A bot is a program that pilots one mech in a 16-mech free-for-all on the Ohio State campus (Ohio Stadium to the Oval). Your bot reads observations on stdin and writes actions on stdout. The server is authoritative; your bot only sends intentions.

**Machine-readable contract:** `mechfight.schema.json` (JSON Schema, draft-07) describes every message below: `ServerMessage` (`hello`, `obs`, `end`) and `BotMessage` (`ready`, action). Generate your types from it. In the repo it is `kit/mechfight.schema.json`; in the bot kit it sits next to this file.

**Bot kit:** This document, the schema, single-file wrappers for Python (`python/mechfight.py`, standard library only) and TypeScript (`ts/mechfight.ts`, no dependencies) with an example bot each, Dockerfiles, a conformance check, and the map. The wrappers only handle the stdin/stdout loop, typed messages, and debug drawing. Everything else (navigation, aiming, and a model of the world) is yours to build.

### 1. Packaging, testing, and submitting

#### Docker packaging

Your bot is a Docker image whose entrypoint speaks this protocol on stdin and stdout. The kit's `python/Dockerfile` and `ts/Dockerfile` are ready to use:

```dockerfile
FROM python:3.13-slim
WORKDIR /bot
COPY . .
ENTRYPOINT ["python3", "-u", "/bot/example_bot.py"]
```

- There is no network at runtime, so vendor every dependency into the image.
- Use `-u` (or flush stdout after every line) so output is not buffered.
- Print logs to stderr. Anything on stdout that is not a protocol message fails the conformance check.
- The bot runs as an unprivileged user (uid 65534, not root) on a read-only disk. Install packages system-wide (not `pip install --user` or into `/root`) and write files only to `/tmp`.

#### Conformance check

`check/check.py` (standard library only) feeds your bot a recorded `hello` and 300 observations from a real match. It checks that your bot:

- sends `ready` within the hello budget
- sends one schema-valid action per observation, echoing its `tick`
- answers within `tick_budget_ms` (more than 2% late fails; a late pass is retried with a fresh bot, up to 3 passes, and the best counts)
- answers only the newest observation when several are queued
- keeps debug drawings inside the caps
- exits cleanly after `end`

`check/check.py` is not a simulation. The observations do not react to your actions.

```sh
python3 check/check.py -- python3 -u python/example_bot.py
docker build -t my-bot python
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" my-bot
```

`--map-dir /arena` makes `hello.map.dir` the path the map has inside the container, as in a match. Without it the check sends the kit folder's path on your machine, which a container cannot open. The `docker run` flags are the match sandbox (§3): the scorer runs this same check that way before your matches, so a bot that passes only without them is rejected.

#### Submitting for real games

Push your bot to a public GitHub repository with the `Dockerfile` at its top level (copy the files of `python/` or `ts/` there), and submit it on the Mech Royale track page (joinbuilders.org/buildathon). The repository may hold 20 MB at the commit you submit. It is built on linux/amd64 with the network on, and the build must finish in 10 minutes. Each submission is built, checked with `check.py`, and played in 48 practice matches against built-in bots. The page shows your score, or what to fix when a submission is rejected.

### 2. Match lifecycle and timing

```
server → bot   {"type":"hello", ...}           once
bot → server   {"type":"ready", ...}           within hello_budget_ms (20 s; covers container start)
loop, 10 times per match-second while your mech is alive:
  server → bot {"type":"obs", "tick":N, ...}
  bot → server {"tick":N, ...action...}         within tick_budget_ms (50 ms)
server → bot   {"type":"end","place":P,"kills":K}   then stdin closes; exit
```

The match is **lockstep**. The server sends all 16 observations at once, waits until every bot answers or the 50 ms budget runs out, applies the actions, and simulates 2 ticks (0.1 s of match time). Scored matches run much faster than real time. A fast bot speeds up the match and is never at a disadvantage for answering early.

After your mech dies, you receive no more observations, only `end`.

#### Timing rules

- **50 ms per decision:** You have 50 ms of wall time per decision, measured by the server from sending `obs` to reading your line. Your CPU is capped to 1 core.
- **Echo the tick:** Every action must carry `"tick"` equal to the observation's `tick`. Answers with any other tick (including a late answer to an earlier observation) are dropped.
- **No answer = coast, then idle:** If no valid answer arrives in time, your mech keeps the *continuous* parts of your last action (`move`, `boost`, `aim`) and drops the one-shot parts (`fire`, `jump`, `reload`, `pick`, `take`, `drop`). After `coast_s` (1.0 s) of missed answers, your mech idles: no movement, aim held. Idling starts on the first decision tick past `coast_s`, so up to one decision (0.1 s) later.
- **Crash = idle:** If your process exits, your mech idles for the rest of the match. The match goes on.
- **Fall behind gracefully:** If observations queue up on stdin, skip to the newest one and answer that. The kit wrappers do this for you.

### 3. Transport and runtime limits

- **JSON lines:** Send one JSON object per line, UTF-8, `\n`-terminated, at most 64 KiB per line (`bot.max_line_bytes`, measured on the raw line: trailing spaces count).
- **stdin and stdout:** **stdin** carries server→bot messages. **stdout** carries bot→server messages. Flush stdout after every line.
- **stderr:** Reserved for your logs. Matches do not show stderr to you. When your bot fails the conformance check at submission, the end of its stderr appears in the message.
- **Bad lines and bot name:** Lines that are not valid JSON, or that exceed the line limit, are counted as bad lines and ignored. A bot's `ready` name is cut to 32 characters with control characters removed.
- **Container sandbox:** Your process runs in Docker as an unprivileged user (uid 65534, no capabilities) with:
  - **no network**
  - a read-only filesystem (writable `/tmp`, 64 MB)
  - 1 CPU and 512 MB RAM (no swap)
  - at most 128 processes and threads
  - map files mounted read-only at `/arena`

### 4. Scoring

- Placement is the order mechs die in: the last mech alive is 1st, and the first to die is 16th.
- Mechs that die on the same tick share a placement.
- If the clock runs out, survivors are ranked by HP.
- Each match gives `16 - place` points (15 for a win, 0 for dying first).
- Your score is the mean over the matches you play. Surviving matters more than kills, though kills give you cubes.

### 5. Coordinates and units

- **Units:** Meters, seconds, radians.
- **Axes:** **x = east, y = north, z = up.** Heights are relative to the ground at the map origin (lat 40.0005, lon −83.0165), the same frame as `v2/world.json`.
- **Yaw and pitch:** **Yaw** is measured from +x (east) counter-clockwise: 0 = east, π/2 = north, ±π = west. **Pitch** is up-positive. A direction vector is `[cos(pitch)·cos(yaw), cos(pitch)·sin(yaw), sin(pitch)]`.
- **Mech dimensions:** Mech `pos` is the **feet** (bottom center). A mech is a vertical cylinder of radius 2.5 m and height 9 m:
  - center of mass: `pos.z + 4.5`
  - eyes: `pos.z + 8`
  - gun muzzle: `pos.z + 7`
  - mortar tube: `pos.z + 9.5` (`height + 0.5`)
- **Shot origin:** Every shot leaves `radius + 0.5` = 3.0 m out along the aim (less if a wall is closer, so nothing fires from inside geometry).
- **NPC dimensions:** Radius 1.8, height 3.5.


### 6. Messages

#### `hello` (server → bot)

```json
{
  "type": "hello",
  "protocol": "mechfight/1",
  "slot": 3,
  "seed": 2873465123,
  "map": { "dir": "/arena", "files": ["v2/world.json", "v2/terrain.i16"] },
  "config": { "match": {...}, "bot": {...}, "mech": {...}, "vision": {...}, "sound": {...},
              "weapons": {...}, "projectile": {...}, "cubes": {...}, "crates": {...}, "loot": {...}, "npc": {...}, "drops": {...},
              "zone": {...}, "replay": {...}, "debug": {...}, "upgrades": [...] }
}
```

- `slot` is your mech id for this match (0–15).
- `seed` is yours: seed your RNG with it to make your bot reproducible. It is fixed per slot and says nothing about the match (it is not the match seed).
- `config` is the **complete rule set** the server uses. Read numbers from it instead of hard-coding them, because balance changes between matches.

#### `ready` (bot → server)

```json
{ "type": "ready", "name": "my-bot" }
```

- `name` (≤ 32 chars) is shown on the spectator stream.

#### `obs` (server → bot)

A real observation (trimmed only where marked):

```json
{
  "type": "obs", "tick": 508, "t": 25.4, "alive": 15,
  "self": {
    "id": 1, "pos": [-217.98, -22.04, -4.73], "vel": [6.22, -6.5, 0], "aim": [0.935, -0.143],
    "hp": 580, "max_hp": 1400, "energy": 19, "max_energy": 100, "grounded": true,
    "cubes": 0, "upgrades": [], "in_zone": true,
    "weapons": [
      { "kind": "gun", "cooldown": 0.03, "ammo": 10, "reload": 0,
        "stats": { "damage": 45, "cooldown": 0.24, "speed": 252, "range": 230, "spread_deg": 0.6, "mag": 12, "reload": 2.4 } },
      null
    ],
    "stats": { "walk_speed": 11.7, "boost_speed": 19.5, "turn_rate": 4, "muzzle_height": 7, "...": "your [mech] numbers after upgrades" }
  },
  "mechs": [
    { "id": 5, "kind": "mech", "pos": [-208.24, -7.7, -4.7], "vel": [7.42, -5.1, 0], "aim": [-2.173, -0.147],
      "hp": 950, "max_hp": 1400, "cubes": 0, "weapons": ["gun", "lightning"], "charging": false },
    { "id": 104, "kind": "npc", "pos": [10.2, 55.1, 0.3], "vel": [1.1, 0, 0], "aim": [0.1, 0], "hp": 350, "max_hp": 350 }
  ],
  "projectiles": [ { "id": 280, "kind": "gun", "pos": [-211.61, -10.94, -0.45], "vel": [192.67, 161.87, -13.28] } ],
  "crates": [ { "id": 1007, "pos": [12.5, -40.2, 0.1], "hp": 300 } ],
  "cubes": [ { "id": 5012, "pos": [14.0, -41.0, 0.1] } ],
  "pickups": [ { "id": 8013, "kind": "mortar", "pos": [-214.6, -19.3, -4.71] } ],
  "sounds": [
    { "kind": "lightning", "bearing": 1.167, "dist": "near", "age": 0.1 },
    { "kind": "gun", "bearing": -2.68, "dist": "near", "age": 0.05 }
  ],
  "beams": [ { "by": 5, "kind": "lightning", "path": [[22.1, -40.3, 6.2], [14.0, -44.1, 4.5]], "age": 0.1 } ],
  "events": [ { "type": "damaged", "amount": 90, "weapon": "lightning", "bearing": 0.974, "by": 5, "rear": true } ],
  "drops": [ { "id": 20000, "pos": [-80.4, 12.9, -3.1], "radius": 8, "lands_in": 11.3, "capture_s": 4, "progress": 0, "holder": null } ],
  "zone": { "center": [41.3, -72.8], "radius": 560, "next_center": [-23.72, 2.21], "next_radius": 380,
            "shrink_start": 60, "shrink_end": 110, "dps": 20 },
  "offer": null
}
```

| Field | Meaning |
| --- | --- |
| `tick`, `t` | Sim tick (20 per second) and match time in seconds. Echo `tick`. |
| `alive` | Mechs still alive (NPCs not counted). Your placement if you died now would be `alive`. |
| `self.aim` | Your torso's **actual** aim. It slews toward the aim you command at `turn_rate` (yaw) and `pitch_rate` rad/s. Shots leave along this, not along what you asked for. |
| `self.grounded` | On a surface. Jumping requires it. |
| `self.weapons[i]` | Slot i, or `null` if the slot is empty (slot 1 is empty at spawn). `cooldown`: seconds until it can fire. Gun: `ammo`, `reload` (seconds left, 0 = not reloading). Laser: `charge` (seconds charged so far; 0 = not charging). `stats`: this weapon's numbers after your upgrades. |
| `self.stats` | Your `[mech]` numbers after upgrades (speeds, turn rate, armor, bonuses). |
| `mechs` | Everything you can **see** right now: other mechs (`kind: "mech"`) and NPC drones (`kind: "npc"`). `aim` is their torso aim; `charging` = their laser is charging (it fires along their aim when they let go). `weapons` lists what they hold (empty slots omitted). `hp` is shown while `vision.show_enemy_hp` is true. |
| `projectiles` | Visible enemy gun bullets, mortar shells, and NPC bullets with position and velocity. Shells fall at `weapons.mortar.gravity`. Your own are omitted. |
| `crates`, `cubes` | Visible loot crates (with HP) and power cubes. |
| `pickups` | Visible weapons lying on the ground: `id`, `kind`, `pos`. Same visibility rules as cubes. Take one with the `take` action. |
| `sounds` | Everything you **heard** since your last observation. See §8. |
| `beams` | Laser beams and lightning arcs fired by other mechs since your last observation that you could see (either end, or the middle of a segment, in view): `{ by, kind: "laser" \| "lightning", path: [[x,y,z], ...], age }`. `path` starts at the shooter's muzzle; a laser has two points, a lightning arc one per jump. |
| `events` | Things that happened to you since your last observation. See below. |
| `drops` | Supply drops that have been called and not yet taken (always known, like the zone). `lands_in`: seconds until it is on the ground (0 = capturable). `holder`: the mech whose capture clock is running, `progress`: seconds it has banked of `capture_s`. See §7, *Supply drops*. |
| `zone` | Always known. See §9. |
| `offer` | A pending upgrade choice, or null. See §10. |

Events:

| `type` | Fields | Meaning |
| --- | --- | --- |
| `damaged` | `amount`, `weapon`, `bearing`, `by`, `rear?` | You took damage. `bearing` is the world-frame yaw (same convention as `aim[0]`, not relative to your facing) toward where it came from (null for zone). `by` is the attacker's id (null for zone). `rear: true` when it came from outside your front arc (rear armor, §7). |
| `hit` | `target`, `amount`, `weapon`, `effect?`, `rear?` | You damaged `target` (mech, NPC, or crate id; crate hits are reported since 2026-11-16). `effect` is set when the hit carried a signature effect (`cookoff`, `short`, `concuss`); `rear: true` when you hit a mech's back. |
| `effect` | `effect`, `by` | A signature effect landed on you: `cookoff` (a laser set off the mortar you carry), `short` (lightning took your laser offline), `concuss` (a mortar blast threw you and drained energy). `by` is who did it. |
| `drop` | `id`, `cubes` | You captured supply drop `id`; `cubes` is your new total. |
| `kill` | `target` | You killed a mech. |
| `pickup` | `cubes` | You picked up a cube; `cubes` is your new total. |
| `upgrade` | `id` | An upgrade was applied (your pick or the timeout default). |
| `took` | `id`, `kind`, `slot` | Your `take` succeeded: pickup `id` is now in `slot`. |
| `dropped` | `id`, `kind`, `slot` | A weapon left your `slot` and lies on the ground as pickup `id` (a swap or a `drop`). |
| `take_failed` | `id`, `reason` | Your `take` didn't happen. `reason`: `gone` (no such pickup, or someone closer took it this tick), `range`, `have` (you already hold that kind), `full` (no empty slot and no `drop`), `busy` (the slot's laser is charging). |

`weapon` is one of `gun`, `mortar`, `laser`, `lightning`, `npc`, `zone`.

Id ranges: mechs 0–15, NPCs 100+, crates 1000+, cubes 5000+, weapon pickups 8000+, supply drops 20000+.

#### action (bot → server)

```json
{ "tick": 508, "move": [0.7, -0.7], "boost": false, "jump": false,
  "aim": [0.95, -0.05], "fire": [true, false], "reload": false, "pick": 1, "take": 8013 }
```

| Field | Default | Meaning |
| --- | --- | --- |
| `tick` | required | Echo of the observation tick. |
| `move` | `[0,0]` | Desired horizontal direction in the world frame. Length is clamped to 1; length < 1 walks slower. Legs are independent of the torso: you can move one way and aim another. |
| `boost` | false | On the ground while moving: run at `boost_speed`, draining `boost_drain`/s energy. In the air: jet upward (`jet_accel`, capped at `max_rise_speed`), draining `jet_drain`/s. |
| `jump` | false | Jump if grounded (`jump_speed` upward). |
| `aim` | last aim | Desired `[yaw, pitch]`. The torso slews toward it; pitch is clamped to `[min_pitch, max_pitch]`. |
| `fire` | `[false,false]` | Hold the trigger of slot 0 / slot 1 until the next decision (2 ticks). |
| `reload` | false | Start a gun reload early. |
| `pick` | none | Index (0–2) into the current offer's `choices`. |
| `take` | none | Id of a weapon pickup within `loot.pickup_radius` (4 m horizontally) and 4 m vertically (fixed, not configurable). It goes into your empty slot, or into slot `drop` if given. |
| `drop` | none | Slot 0 or 1. With `take`: the slot the new weapon replaces; the old one is left on the ground at your feet. Alone: empty that slot, leaving the weapon on the ground. |
| `debug` | none | Debug drawing for your team (below). Never affects the match. |

Each action applies for the 2 ticks until the next decision. Missing fields take the defaults above (`aim` defaults to your previous commanded aim). Unknown fields are ignored. A dead mech's place arrives in `end`.

#### Debug drawing

`debug` attaches drawings to an action for your own tools. The server checks them against the caps below, keeps them out of the public replay, and never reads them to play the match. Nothing on the track shows them to you.

```json
{ "tick": 508, "move": [1, 0],
  "debug": {
    "label": "chasing 5",
    "lines":  [ { "a": [-217.9, -22.0, 2.3], "b": [-208.2, -7.7, -0.2], "color": "#ff5040" } ],
    "points": [ { "at": [-23.7, 2.2, -4.7], "color": "#40c0ff", "size": 6 } ],
    "text":   [ { "text": "drop here", "at": [-80.4, 12.9, 0], "color": "#ffd060" }, { "text": "low energy" } ] } }
```

| Field | Meaning |
| --- | --- |
| `lines[]` | `a`, `b`: world points (x east, y north, z up, meters, the frame of §5). |
| `points[]` | `at`: a world point. `size`: radius in screen pixels, 1–12 (default 4). |
| `text[]` | `text`, and `at` (a world point) or no `at` to stack it above your mech. |
| `label` | One short line above your mech. |
| `color` | `"#rgb"` or `"#rrggbb"` on any item. Missing or invalid: your mech's color. |

Retention and caps:

- A drawing stays on screen until your next action that carries `debug`, or for `debug.hold_s` (0.5 s), whichever comes first. Send `"debug": {}` to clear it early.
- The server cuts each drawing to the caps in `hello.config.debug` and says nothing:
  - `max_lines` (64) lines
  - `max_points` (64) points
  - `max_text` (16) texts
  - `max_text_chars` (80) characters per text and label
  - `max_bytes` (8192) bytes serialized, keeping the label, then text, lines, and points in that order
- Bad items are dropped and numbers are rounded to 0.01.
- Once a mech has recorded `max_match_bytes` (8 MB) in a match, later drawings are dropped.
- The whole action line still has to fit in `bot.max_line_bytes`.


### 7. Rules of the world

All numbers below are defaults. Read the live values from `hello.config`.

#### Movement

Mechs accelerate toward the commanded velocity (`ground_accel` 58.5 m/s² on the ground, `air_accel` 12 in the air), so changing direction takes time. You are a vertical cylinder standing on the surface under your center.

- **Walls** stop the part of your move that goes into them and keep the part that goes along them: you slide. You never end up inside a wall.
- **Ledges** up to `step_up` (1.2 m) are walked up. Anything taller is a wall unless your feet are already above it: jump and jet (boost in the air) until they clear the edge, then move over it.
- **Slopes** steeper than `max_slope_deg` (50°) cannot be walked up, at any speed. Go around or jet.
- **Bridges and overhangs** that clear your head (9 m) can be walked under, and their underside stops a jet. Lower overhangs are walls, and so is a step up under one that would put your head into it. An eave over any part of you stops a jet too; unless a wall holds you under it, you are slid out from under it (up to 0.6 m per tick) and climb on.
- **Roof edges:** Coming down past the edge of a roof you still overhang (your center is off it), you land on the edge instead of dropping into the wall below. Keep moving toward the roof and you step onto it; otherwise you are slid off (up to 0.6 m per tick) and fall clear of the wall. If a wall on the other side holds you there, you stay on the edge: nothing falls into a gap narrower than itself.

With 100 energy you can climb about 60 m (almost every campus roof; the 70 m towers are out of reach). Energy regenerates at `energy_regen`/s after `energy_regen_delay` s without spending. Gravity is 22 m/s². The map edge is a wall. Overlapping mechs are pushed apart.

#### Health

You start with 1400 HP. After `regen_delay` (5 s) without dealing or taking damage, you regenerate `regen_per_s` (45) HP/s, except while outside the zone. Zone damage counts as taking damage: the 5 s timer starts again when you step back inside. Armor (upgrades) reduces weapon damage, not zone damage.

#### Rear armor

A hit from outside your torso's front arc (`mech.front_arc_deg` 180°, centered on your aim yaw) deals `mech.rear_mult` (×1.5) damage. The direction is where the shot came at you from: the bullet's path, the beam's or arc's origin, or the blast point of a shell. Facing your attacker protects you; `damaged.rear` tells you when you were hit from behind.

#### Weapons

Every shot leaves along your *actual* torso aim. There is no lock-on. You start with only the `gun` (slot 0); the other weapons are loot (below). Firing an empty slot does nothing.

| Weapon | How it works |
| --- | --- |
| `gun` | Projectile at `speed` 252 m/s, `damage` 45, one shot per `cooldown` 0.24 s (held down, exactly that rate), `mag` 12 then `reload` 2.4 s, small Gaussian spread (`spread_deg`). Flies straight (no drop) for `range` m. You must lead moving targets. |
| `mortar` | Shell launched at `speed` 72 m/s along your aim, falling at `gravity` 22 m/s² (so pitch sets range; max range ≈ v²/g ≈ 235 m at 45°). Explodes on impact: `damage` 200 to a directly hit target, plus `splash` 160 falling to 30% at `splash_radius` 7 m, blocked by walls. Lob it over buildings at targets you can't see. Your own splash hurts you at 50%. **Concussion:** every mech the blast reaches is thrown away from it (`knock` 16 m/s, `knock_up` 9 m/s) and loses `drain` 45 energy, scaled by the same falloff. Your own blast throws you too. |
| `laser` | **Hold the trigger to charge, let go to fire.** The charge builds for up to `charge` 0.75 s; let go and the hitscan beam fires along your aim at that moment (`range` 280 m). Damage scales with the charge, from `min_frac` 35% at none to `damage` 315 at full; let go before `min_charge` 0.15 s and it fires as soon as that much is in, and a full charge held for `hold_s` 2 s more fires on its own. Then `cooldown` 1.65 s. While charging you move at half speed; your torso turns as usual (`charge_turn_mult` 1), so the beam goes where you aim when you let go. Everyone who can see you sees `charging: true` and your `aim`, and it makes a sound, so the line can be dodged. Your `charge` (in `self.weapons`) is the seconds charged so far. **Cook-off:** +60% (`cookoff`) to a mech that is holding a mortar. |
| `lightning` | Instant. Hits the nearest target (mech, NPC or crate) within `range` 45 m and within `cone_deg` 30° of your aim yaw, with line of sight, for `damage` 60, then chains to up to `chain` 2 more targets within `chain_range` 14 m (×0.7 damage per jump). Costs `energy` 3 per shot; fires every `cooldown` 0.25 s. Without a target it still fires (and costs energy): the arc goes out along your aim to the first wall or `range`. **Short:** a mech it hits that holds a laser loses any charge in progress and can't start one for `short_s` 2 s. |

**Weapon triangle:**

- Laser beats mortar (cook-off, plus it outranges the shell).
- Mortar beats lightning (concussion keeps it out of arc range and drains the energy it fires with).
- Lightning beats laser (short).
- The gun is neutral.

What you carry against what opponents carry is a decision, and so is which weapon you pick up.

**Cover and shots:** Gun bullets, mortar shells, and lasers hit buildings, bridges, and terrain exactly where you see them. You can shoot under a bridge. A shot whose barrel pokes into a wall stops at that wall. **Trees do not stop shots:** you can fire blind into trees at a sound.

**Cube scaling:** Damage is scaled by power cubes (§10): `× (1 + damage_per_cube × min(cubes, stat_cap))`.

#### NPC drones

NPC drones (`kind: "npc"`, 12 per match, 350 HP) wander within `npc.leash` (30 m) of home.

- They shoot (25 damage, 90 m/s bullets, 1 s cooldown) at whoever attacks them, or at mechs within 45 m with line of sight while the drone is within 30 m of home.
- A drone chases until its target is 90 m away or the drone is `npc.chase_leash` (60 m) from home, then walks back.
- Each drone drops 2 cubes. Drones do not take zone damage.
- **Cubes** go to the closest mech within `cubes.pickup_radius` (ties go to the lower id).

#### Crates

There are 36 crates per match (300 HP, about a quarter on rooftops). Destroying a crate drops 1 cube, and drops a weapon with probability `loot.crate_weapon_chance` (0.5).

#### Weapon loot

Weapons lie on the ground as pickups (`obs.pickups`, ids 8000+). They come from:

- `loot.floor_count` (40) spawns at match start on open ground and roofs (a quarter on roofs)
- destroyed crates (above)
- dead mechs, which drop every weapon they held except the gun

Loot rules:

- Random spawns use `loot.weights` (mortar, laser, lightning 1:1:1; gun 0).
- Taking a weapon is explicit: send `"take": <id>` while within `loot.pickup_radius` (4 m).
- It goes into your empty slot. If both slots are full, also send `"drop": <slot>` to swap it in, leaving the old weapon on the ground at your feet (anyone can pick it up).
- You cannot hold two weapons of the same kind.
- A weapon you take cannot fire for `max(loot.equip_s, its cooldown)` seconds (1 s for the gun, 1.65 s for a laser). A dropped gun keeps its ammo, so swapping never skips a cooldown or a reload.
- You cannot drop or swap out a laser while it is charging.
- You can also drop the gun.
- If two mechs take the same pickup on the same tick, the closer one gets it.
- Weapons on the ground never despawn, though the zone closes over them.

#### Supply drops

There are three supply drops per match (`drops.times`: called at 70, 140, and 210 s).

- Each drop lands `fall_s` (25 s) after it is called, on open ground inside the circle the zone is closing to.
- Every mech sees it in `obs.drops` from the moment it is called.
- Once it is on the ground, stand inside its ring (`radius` 8 m) **alone** for `capture_s` (4 s) to gain `cubes` (3) power cubes, full HP, and full energy.
- While two or more mechs are in the ring, the capture clock freezes. If the ring empties, or a different mech becomes the only one in it, the clock restarts.

### 8. Vision and sound

#### Vision

**You see** an object if your eye (`pos.z + 8`) has line of sight to its center or top, and either:

- it is within `near_range` (45 m) in any direction (proximity sensors; buildings block, canopy does not), or
- it is within `range` (200 m) and inside your `fov_deg` (120°) **yaw wedge** centered on your torso aim yaw (horizontal only: pitch does not matter, so you see straight up and down), with no building blocking the line.

Canopy is soft: a line through a little foliage still sees, while a line through a dense crown does not (`rules.canopyDensity` / `canopyBlockT` in `v2/world.json`). Tree trunks block sight but not shots.

Once you have seen a mech or an NPC drone, you keep tracking its real, current position for `memory_s` (5 s) after it leaves view, so a mech ducking behind cover does not vanish immediately. Everything else (crates, cubes, weapon pickups, projectiles) is listed only while you see it.

Where you aim is where you look. Turning your torso to scan costs aim time.

#### Sound

**You hear** sounds within their carry range (`sound.range`):

- `gun`: 320 m
- `mortar` launch: 420
- `explosion`: 420
- `laser`: 380
- `laser_charge`: 140
- `lightning`: 160
- `jet`: 90
- `death`: 600
- `crate`: 220
- `npc_gun`: 200
- `step`: 40
- `boost`: 90
- `reload`: 60
- `drop`: 600 (a supply drop landing)

A mech moving faster than `sound.step_speed` (5 m/s) on the ground makes a `step` every `sound.step_every` (0.6 s), or a `boost` while boosting. Walking slowly or standing still is silent. Each weapon has its own kind, so a sound tells you what the shooter is holding.

Each heard sound gives:

- `bearing`: world-frame yaw to the source (like `aim[0]`, not relative to your facing), with Gaussian error (σ = `bearing_noise_deg` 7°)
- `dist`: `"near"` (< 60 m), `"mid"` (< 160 m), or `"far"`
- `age`: seconds since it happened

Your own sounds are not reported. Sounds do not say who made them.

### 9. The zone

The zone is a circle that shrinks in phases. Outside it, you lose `dps` HP per second (no armor, no regen).

`zone` always gives the current circle, the **next** circle it will shrink to, and the shrink window:

- Before `shrink_start`, the circle holds still.
- Between `shrink_start` and `shrink_end`, the center and radius move linearly from the current circle to the next one.
- The next circle is always entirely inside the current one.

Defaults:

- Starts at radius 560 m around (41.3, −72.8), then shrinks 380 → 240 → 140 → 70 → 25 → 0 m.
- Each phase's damage applies from its hold through its shrink: 20, 35, 60, 100, 160, and 260 HP/s (`zone.dps` gives the current value).
- The last circle closes by about 6:55. Matches end when one mech is left or at 8:00, whichever comes first.

### 10. Cubes and upgrades

- Picking up a cube (walk within `pickup_radius` 3.5 m horizontally and 4 m vertically) gives +4% max HP (healing the difference) and +4% damage, up to `stat_cap` 10 cubes.
- Killed mechs drop all their cubes plus two.
- Each cube also makes you `size_per_cube` 5% bigger, with no cap: radius, height, eye, and muzzle height all scale by 1 + 0.05 × cubes (`self.stats` shows your current `eye_height` and `muzzle_height`). A bigger mech is easier to hit, and sees and shoots from higher up.

Every time your cube count reaches a threshold in `cubes.upgrade_thresholds` (1, 3, 6, 10, 15, 21, …), you receive an **offer**:

```json
"offer": { "id": 2, "expires": 61.35, "choices": [
  { "id": "gun_rate", "name": "Rotary feed", "desc": "+15% arm gun fire rate" },
  { "id": "armor", "name": "Reactive armor", "desc": "-8% damage taken" },
  { "id": "sensors", "name": "Sensor suite", "desc": "+15 m proximity sensors, +25 m vision, halves sound bearing error" } ] }
```

- Answer with `"pick": i`. If you do not pick by `expires` (5 s), choice 0 is applied.
- Offers queue; the next offer appears after you resolve the current one.
- Choices are 3 distinct upgrades you can still take (weapon upgrades only for weapons you hold when the offer is drawn, each up to its `max` stacks).
- Weapon upgrades belong to your mech, not the item: they persist if you drop that weapon and apply again if you pick up the same kind later.
- The full list and exact effects are in `hello.config.upgrades`: each effect multiplies (`mul`) or adds to (`add`) one of your `self.stats` or `self.weapons[i].stats` numbers.

### 11. Map files

`hello.map.dir` (`/arena` in Docker) holds the static map. The map is the same every match; spawns, crates, NPCs, loot, the zone, and supply drops are random per match.

Two files define the world the server simulates:

- `v2/world.json`: `bounds`, `terrain` (grid description), `prisms`, and `trees`.
  - `prisms[]`: every solid that is not terrain. Each prism has `kind` (`building`, `stadium`, `bridge`), `base` and `top` heights, `ring` (footprint polygon, flat `[x0, y0, x1, y1, ...]`), and `holes` (same format). A point is inside a prism if it is inside the ring, outside the holes, and between `base` and `top`. A bridge has a `base` above the ground: you walk and shoot under it.
  - `trees`: `fields` names the columns of the flat `data` array (`x`, `y`, `z`, `height`, `crownR`, `crownBase`, `trunkR`, ...). Trees block vision only (crowns fade it, trunks stop it).
  - `rules`: `maxStep`, `maxSlopeDeg` (the viewer's walking rules; the server uses `config.mech`) and the canopy numbers in §8.
  - Scenery the server ignores: `blocks` (which prisms make up each named building), `stadium` (the stadium's shape for drawing; its solid parts are the `stadium` prisms), `cars`, `parking`, `water`, `barriers` (fences, walls, hedges), and `stats`. None of them block movement, sight, or shots, and water does not slow you.
- `v2/terrain.i16`: little-endian int16 centimeters, `terrain.nx × terrain.ny` (1070 × 724), row-major from (`terrain.minX`, `terrain.minY`) with `terrain.step` = 1 m. Index `j * nx + i` is the ground height × 100 at `x = minX + i·step`, `y = minY + j·step`. Sample it bilinearly.

### 12. Versioning

`hello.protocol` is `"mechfight/1"`. Fields may be **added** within version 1, never removed or changed in meaning. Ignore fields you do not know. A breaking change bumps the version.


---


## Appendix B — Full live `hello.config`, verbatim

This is the exact JSON the scorer sends in `hello`. It is the complete rule set.

```json
{
 "match": {
  "tick_hz": 20,
  "decide_every": 2,
  "duration_s": 480,
  "mechs": 16,
  "spawn_min_separation": 130,
  "spawn_zone_fraction": 0.8,
  "arena_margin": 30
 },
 "bot": {
  "tick_budget_ms": 50,
  "hello_budget_ms": 20000,
  "coast_s": 1,
  "offer_timeout_s": 5,
  "max_line_bytes": 65536
 },
 "mech": {
  "radius": 2.5,
  "height": 9,
  "eye_height": 8,
  "muzzle_height": 7,
  "hp": 1400,
  "walk_speed": 11.7,
  "boost_speed": 19.5,
  "ground_accel": 58.5,
  "air_accel": 12,
  "gravity": 22,
  "jump_speed": 11,
  "jet_accel": 34,
  "max_rise_speed": 10,
  "step_up": 1.2,
  "max_slope_deg": 50,
  "energy": 100,
  "energy_regen": 18,
  "energy_regen_delay": 0.6,
  "boost_drain": 17,
  "jet_drain": 15,
  "turn_rate": 4,
  "pitch_rate": 3,
  "min_pitch": -0.7,
  "max_pitch": 1.3,
  "regen_delay": 5,
  "regen_per_s": 45,
  "charge_move_mult": 0.5,
  "self_damage_mult": 0.5,
  "armor": 0,
  "rear_mult": 1.5,
  "front_arc_deg": 180,
  "near_range_bonus": 0,
  "vision_bonus": 0,
  "hearing": 1
 },
 "vision": {
  "range": 200,
  "fov_deg": 120,
  "near_range": 45,
  "canopy_blocks": true,
  "show_enemy_hp": true,
  "memory_s": 5
 },
 "sound": {
  "bearing_noise_deg": 7,
  "near": 60,
  "mid": 160,
  "step_speed": 5,
  "step_every": 0.6,
  "range": {
   "step": 40,
   "boost": 90,
   "reload": 60,
   "gun": 320,
   "mortar": 420,
   "explosion": 420,
   "laser_charge": 140,
   "laser": 380,
   "lightning": 160,
   "jet": 90,
   "death": 600,
   "crate": 220,
   "npc_gun": 200,
   "drop": 600
  }
 },
 "weapons": {
  "gun": {
   "damage": 45,
   "cooldown": 0.24,
   "speed": 252,
   "range": 230,
   "spread_deg": 0.6,
   "mag": 12,
   "reload": 2.4
  },
  "mortar": {
   "damage": 200,
   "splash": 160,
   "splash_radius": 7,
   "splash_edge": 0.3,
   "cooldown": 2.6,
   "speed": 72,
   "gravity": 22,
   "ttl": 7,
   "knock": 16,
   "knock_up": 9,
   "drain": 45
  },
  "laser": {
   "damage": 315,
   "charge": 0.75,
   "min_charge": 0.15,
   "min_frac": 0.35,
   "hold_s": 2,
   "cooldown": 1.65,
   "range": 280,
   "pierce": 0,
   "charge_turn_mult": 1,
   "cookoff": 0.6
  },
  "lightning": {
   "damage": 60,
   "cooldown": 0.25,
   "range": 45,
   "cone_deg": 30,
   "chain": 2,
   "chain_range": 14,
   "chain_falloff": 0.7,
   "energy": 3,
   "short_s": 2
  }
 },
 "projectile": {
  "gun_radius": 0.3,
  "npc_radius": 0.3
 },
 "cubes": {
  "pickup_radius": 3.5,
  "hp_per_cube": 0.04,
  "damage_per_cube": 0.04,
  "stat_cap": 10,
  "death_drop_extra": 2,
  "size_per_cube": 0.05,
  "upgrade_thresholds": [
   1,
   3,
   6,
   10,
   15,
   21,
   28,
   36,
   45
  ]
 },
 "crates": {
  "count": 36,
  "roof_fraction": 0.25,
  "hp": 300,
  "radius": 1.4,
  "height": 2.4,
  "cubes": 1
 },
 "loot": {
  "pickup_radius": 4,
  "equip_s": 1,
  "floor_count": 40,
  "floor_roof_fraction": 0.25,
  "crate_weapon_chance": 0.5,
  "death_drop": 1,
  "weights": {
   "gun": 0,
   "mortar": 1,
   "laser": 1,
   "lightning": 1
  }
 },
 "npc": {
  "count": 12,
  "hp": 350,
  "radius": 1.8,
  "height": 3.5,
  "speed": 5,
  "leash": 30,
  "chase_leash": 60,
  "aggro_range": 45,
  "deaggro_range": 90,
  "spawn_clear": 0,
  "damage": 25,
  "cooldown": 1,
  "projectile_speed": 90,
  "spread_deg": 2.5,
  "cubes": 2
 },
 "drops": {
  "times": [
   70,
   140,
   210
  ],
  "fall_s": 25,
  "radius": 8,
  "capture_s": 4,
  "cubes": 3,
  "repair": 1,
  "spread": 0.7
 },
 "zone": {
  "start_center": [
   41.3,
   -72.8
  ],
  "start_radius": 560,
  "phases": [
   {
    "hold_s": 60,
    "shrink_s": 50,
    "radius": 380,
    "dps": 20
   },
   {
    "hold_s": 45,
    "shrink_s": 40,
    "radius": 240,
    "dps": 35
   },
   {
    "hold_s": 35,
    "shrink_s": 35,
    "radius": 140,
    "dps": 60
   },
   {
    "hold_s": 30,
    "shrink_s": 30,
    "radius": 70,
    "dps": 100
   },
   {
    "hold_s": 25,
    "shrink_s": 25,
    "radius": 25,
    "dps": 160
   },
   {
    "hold_s": 15,
    "shrink_s": 25,
    "radius": 0,
    "dps": 260
   }
  ]
 },
 "debug": {
  "max_lines": 64,
  "max_points": 64,
  "max_text": 16,
  "max_text_chars": 80,
  "max_bytes": 8192,
  "max_match_bytes": 8000000,
  "hold_s": 0.5
 },
 "replay": {
  "frame_every": 2
 },
 "upgrades": [
  {
   "id": "plating",
   "name": "Composite plating",
   "desc": "+15% max HP",
   "max": 3,
   "effects": [
    {
     "path": "mech.hp",
     "mul": 1.15
    }
   ]
  },
  {
   "id": "armor",
   "name": "Reactive armor",
   "desc": "-8% damage taken",
   "max": 3,
   "effects": [
    {
     "path": "mech.armor",
     "add": 0.08
    }
   ]
  },
  {
   "id": "servos",
   "name": "Leg servos",
   "desc": "+8% walk and boost speed",
   "max": 3,
   "effects": [
    {
     "path": "mech.walk_speed",
     "mul": 1.08
    },
    {
     "path": "mech.boost_speed",
     "mul": 1.08
    }
   ]
  },
  {
   "id": "capacitor",
   "name": "Capacitor bank",
   "desc": "+30 max energy",
   "max": 3,
   "effects": [
    {
     "path": "mech.energy",
     "add": 30
    }
   ]
  },
  {
   "id": "reactor",
   "name": "Reactor tune",
   "desc": "+30% energy regen",
   "max": 3,
   "effects": [
    {
     "path": "mech.energy_regen",
     "mul": 1.3
    }
   ]
  },
  {
   "id": "jets",
   "name": "Efficient jets",
   "desc": "-25% boost and jet energy drain",
   "max": 2,
   "effects": [
    {
     "path": "mech.boost_drain",
     "mul": 0.75
    },
    {
     "path": "mech.jet_drain",
     "mul": 0.75
    }
   ]
  },
  {
   "id": "nanites",
   "name": "Repair nanites",
   "desc": "+60% out-of-combat regen, starts 1.5 s sooner",
   "max": 2,
   "effects": [
    {
     "path": "mech.regen_per_s",
     "mul": 1.6
    },
    {
     "path": "mech.regen_delay",
     "add": -1.5
    }
   ]
  },
  {
   "id": "gyros",
   "name": "Torso gyros",
   "desc": "+30% aim turn rate",
   "max": 2,
   "effects": [
    {
     "path": "mech.turn_rate",
     "mul": 1.3
    },
    {
     "path": "mech.pitch_rate",
     "mul": 1.3
    }
   ]
  },
  {
   "id": "sensors",
   "name": "Sensor suite",
   "desc": "+15 m proximity sensors, +25 m vision, halves sound bearing error",
   "max": 2,
   "effects": [
    {
     "path": "mech.near_range_bonus",
     "add": 15
    },
    {
     "path": "mech.vision_bonus",
     "add": 25
    },
    {
     "path": "mech.hearing",
     "mul": 0.5
    }
   ]
  },
  {
   "id": "gun_damage",
   "name": "Tungsten rounds",
   "desc": "+15% arm gun damage",
   "requires": "gun",
   "max": 3,
   "effects": [
    {
     "path": "weapons.gun.damage",
     "mul": 1.15
    }
   ]
  },
  {
   "id": "gun_rate",
   "name": "Rotary feed",
   "desc": "+15% arm gun fire rate",
   "requires": "gun",
   "max": 3,
   "effects": [
    {
     "path": "weapons.gun.cooldown",
     "mul": 0.87
    }
   ]
  },
  {
   "id": "gun_velocity",
   "name": "Rail barrel",
   "desc": "+25% arm gun projectile speed",
   "requires": "gun",
   "max": 2,
   "effects": [
    {
     "path": "weapons.gun.speed",
     "mul": 1.25
    },
    {
     "path": "weapons.gun.range",
     "mul": 1.15
    }
   ]
  },
  {
   "id": "gun_mag",
   "name": "Drum magazine",
   "desc": "+8 rounds, -20% reload time",
   "requires": "gun",
   "max": 2,
   "effects": [
    {
     "path": "weapons.gun.mag",
     "add": 8
    },
    {
     "path": "weapons.gun.reload",
     "mul": 0.8
    }
   ]
  },
  {
   "id": "mortar_splash",
   "name": "Cluster shells",
   "desc": "+30% mortar splash radius",
   "requires": "mortar",
   "max": 2,
   "effects": [
    {
     "path": "weapons.mortar.splash_radius",
     "mul": 1.3
    }
   ]
  },
  {
   "id": "mortar_reload",
   "name": "Autoloader",
   "desc": "-18% mortar cooldown",
   "requires": "mortar",
   "max": 3,
   "effects": [
    {
     "path": "weapons.mortar.cooldown",
     "mul": 0.82
    }
   ]
  },
  {
   "id": "mortar_velocity",
   "name": "Long tube",
   "desc": "+20% shell speed",
   "requires": "mortar",
   "max": 2,
   "effects": [
    {
     "path": "weapons.mortar.speed",
     "mul": 1.2
    }
   ]
  },
  {
   "id": "laser_charge",
   "name": "Fast capacitors",
   "desc": "-25% laser charge time",
   "requires": "laser",
   "max": 2,
   "effects": [
    {
     "path": "weapons.laser.charge",
     "mul": 0.75
    }
   ]
  },
  {
   "id": "laser_damage",
   "name": "Focusing lens",
   "desc": "+18% laser damage",
   "requires": "laser",
   "max": 3,
   "effects": [
    {
     "path": "weapons.laser.damage",
     "mul": 1.18
    }
   ]
  },
  {
   "id": "laser_pierce",
   "name": "Phased beam",
   "desc": "Laser passes through one more target",
   "requires": "laser",
   "max": 1,
   "effects": [
    {
     "path": "weapons.laser.pierce",
     "add": 1
    }
   ]
  },
  {
   "id": "lightning_chain",
   "name": "Arc relay",
   "desc": "+1 lightning chain jump",
   "requires": "lightning",
   "max": 2,
   "effects": [
    {
     "path": "weapons.lightning.chain",
     "add": 1
    }
   ]
  },
  {
   "id": "lightning_range",
   "name": "Tesla coil",
   "desc": "+20% lightning range and cone",
   "requires": "lightning",
   "max": 2,
   "effects": [
    {
     "path": "weapons.lightning.range",
     "mul": 1.2
    },
    {
     "path": "weapons.lightning.cone_deg",
     "mul": 1.2
    }
   ]
  },
  {
   "id": "lightning_efficiency",
   "name": "Superconductor",
   "desc": "-35% lightning energy cost, +10% damage",
   "requires": "lightning",
   "max": 2,
   "effects": [
    {
     "path": "weapons.lightning.energy",
     "mul": 0.65
    },
    {
     "path": "weapons.lightning.damage",
     "mul": 1.1
    }
   ]
  }
 ]
}
```

---

*End of dossier. It contains the competition rules, the full protocol, the full
live config, the arena, the current architecture, 40+ measured experiments, the
calibration data, and the open problems.*
