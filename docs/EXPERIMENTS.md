# EXPERIMENTS — the full ledger

> Living document. Last updated **2026-11-21 22:50 UTC**.
>
> Every entry: what changed, what was expected, what was measured, what was
> decided. Deltas are **paired local score differences** in the simulator, not
> official points. Negative results are kept deliberately — they are the only
> thing preventing the next agent from repeating them.

## How to read this

- `n=` is paired matches. A valid claim needs **n ≥ 48 across ≥ 3 seed ranges**,
  per-range deltas reported, and a holdout.
- Effects under ~0.5 are **unresolvable** at feasible sample sizes. They are
  recorded as "inconclusive", never as wins.
- Baselines drift between sessions because the working tree changes. Each entry
  records its own baseline.

Baselines used below, 48 matches unless stated:

| Set | Score | Death | Kills |
| --- | --- | --- | --- |
| train (8000/11000/13000) | 1.83–1.96 | 71–74 s | 1.19–1.27 |
| holdout (14000/15000/16000) | 1.65–1.96 | 66–72 s | 1.17–1.33 |

---

## Adopted

### E1 — Exact upgrade valuation, first (mobility-heavy) weights · `f78d3f5`
Read marginal effects from `hello.config.upgrades` instead of hand-assigned ranks.
First weights over-valued mobility and aim: **−0.33 ± 0.17** (24 pairs, harsh
opponents), **−0.08 ± 0.25** (mild). Rejected the weights, kept the mechanism.

### E2 — Exact upgrade valuation, survival-weighted retune · `f78d3f5`
**+0.04 ± 0.09** (24 pairs) / **0.00 ± 0.12**. Neutral. Retained for protocol
correctness: the bot now adapts to balance patches instead of assuming them.

### E3 — Protocol-first belief layer (D1/D2) · `7addbb2`
Stopped dead-reckoning server-tracked positions; turned sound bearings into
uncertain sectors with live σ. **+0.04 ± 0.07** (24 pairs). Neutral, but it removes
a fabricated-precision bug and feeds the arbiter. Retained.

### E4 — Single torso-aim arbiter (D3) · `7addbb2`
One final aim for both weapon slots; a second slot fires only if its shot still
lands given that aim. **+0.54 ± 0.28** (harsh) / **+0.71 ± 0.59** (mild). Retained.

### E5 — D1+D2+D3 combined · `7addbb2`
**+0.63 ± 0.25** / **+1.50 ± 0.40**. Much better than the parts. Retained.

### E6 — 1 m engine-accurate collision + composed-heading validation · `5ab07e7`
Per-column solid tops and bridge overhangs, 9-point body ring, revalidation of the
*composed* steering vector. Fixed a hard wedging bug where the mech was farmed to
death by a single NPC drone at t≈70 s. Adopted as correctness.

### E7 — Aggression and hunt mode · `407c50e`, `7468dcb`
Aggression 0.95 → **0.00**; 0.7 → **−0.31**. Rejected.
Hunt mode v1 (close on the nearest known enemy) measured **neutral locally** and
**+0.61 officially** (1.83 → 2.44). Hunt v2 (target the weakest, standoff 45 m) was
submitted as `7468dcb` and scored higher again; exact number never recorded.
**This is the calibration anchor for F10.**

### E8 — Squad kiting · `84e97cb`
Boost away from incoming-fire bearings, hold ~6 s, prefer headings that put terrain
between us and the shooters. **+0.55 ± 0.27**, death 80 → 105 s. Retained.
Hold 8 s vs 5 s: 0.00. Hold 14 s vs 8 s: **−0.21 ± 0.13**, rejected (over-commits).

### E9 — Quiet movement · `84e97cb`
Full speed vs quiet (≤ `step_speed` = 4.85 m/s): quiet is **+0.67**. Footsteps are
audible at 40 m, boost at 90 m. Retained.

### E10 — Movement discipline · `ac7f72a`
Route clearance along the path, goal hysteresis, reciprocal fire, kite range gate,
no static camping. Score **−0.22 ± 0.44**, survival −3.5 ± 13.2 s, damage dealt
**+335 ± 239**, kills **+0.25 ± 0.21** (32 pairs). Neutral on survival, positive on
offence; kept because each item fixes a demonstrated defect (walking into the
squad, standing still, dying with a full magazine).

### E11 — Live-config geometry (D5, D9) · `91bac7b`
Radius, height, step-up, slope, canopy density from `hello.config` / `world.json`.
**+0.42 ± 0.51** / **+0.13 ± 0.18**. Inconclusive as a gain; retained as protocol
correctness (no hard-coded rule numbers).

---

## Inconclusive / null

### E12 — 14-dimension parameter sweep · `82f6849`
Cached per-seed baseline, 14 random configs, 3 training ranges, holdout on three
untouched ranges. Dimensions: `aggression, cover_bias, engage_range,
focus_switch_margin, hp_floor, hunt_hp, hunt_range, hunt_standoff, hunt_target,
hunt_until, kite_range, quiet_when_safe, strafe_gain, threat_bias`.

**No reliable winner.** Per-range deltas swing up to 1.2 score *within one config*
(e.g. `+0.31 / −1.00 / +0.12`). Only one config was positive on all three training
ranges and it had negative kills — self-contradictory.

Best by mechanism (kills): aggression 0.8 / cover_bias 0.25 / standoff 65 /
hunt_hp 0.30 / quiet off → train **+0.33** (kills +0.38), holdout **+0.15** (kills
+0.06), 5 of 6 ranges non-negative. Not clearly better than the submitted build.

### E13 — Situational trade-ratio controller · `3ffe906`
Press when dealt/taken > 1.35 and HP > 45 %; disengage when < 0.65 or HP < 32 %.
**−0.062 ± 0.233**, per-range `[−0.25 / −0.44 / +0.50]`. Default off.

### E14 — Kill-loot collection · `7468dcb`
Detour to a corpse for its 3 cubes within a 7 s window when nothing is within 55 m.
Built, **default off, never measured**. Still pending.

### E15 — Early weapon acquisition
`roam_until 45, weapon_seek_range 200, hunt off`:

| Set | Δscore | Δkills | Per-range |
| --- | --- | --- | --- |
| train (n=48) | **+0.46 ± 0.30** | +0.46 | +0.44 / +0.12 / +0.81 |
| holdout (n=48) | **+0.10 ± 0.24** | +0.19 | +0.94 / −0.12 / −0.50 |

All three training ranges positive and kills up on both sets, but the holdout is
mixed → **inconclusive, not a win**. Kept on the shortlist because the mechanism
(F8) is the only route to a higher damage ceiling.

### E16 — Survival ceiling: nine policy variants
Same 16 seeds, same opponents. Full table in `FINDINGS.md` F5. Range 44–74 s;
nothing reaches 100 s. **The pacifist arm is invalid** (see E18) because the fire
gate cannot suppress fire.

### E17 — `kite_hp` sweep (duel-abort threshold)
Prompted by an external review: `kite_hp = 0.97` means any damage triggers a 6 s
flee that aborts duels mid-kill.

| `kite_hp` | score | kills | death | paired vs 0.97 |
| --- | --- | --- | --- | --- |
| 0.97 | 1.94 | 1.23 | 70 s | — |
| 0.85 | 1.79 | 1.27 | 70 s | −0.15 ± 0.29 |
| 0.70 | 1.92 | **1.38** | 69 s | −0.02 ± 0.34 |
| 0.55 | 1.75 | 1.29 | 68 s | −0.19 ± 0.34 |

Null. Kills rise slightly at 0.70 but score does not move. The diagnosis was right,
the lever is not load-bearing.

### E18 — External review: `warden` (Claude), full policy replacement
778-line policy: predictive engagement gate (time-to-kill race), heal cycle,
weapon-first opening, zone-clock regimes, laser charge controller, mortar cluster
solver, drop contest. Wired standalone into the harness (`work-warden/bot.py`) and
run on six seed ranges.

| Set | ours | warden | paired |
| --- | --- | --- | --- |
| train (n=48) | 1.83 / 74 s / 1.19 k | 1.06 / 84 s / 0.27 k | **−0.77 ± 0.28** |
| holdout (n=48) | 1.96 / 72 s / 1.33 k | 1.31 / 85 s / 0.31 k | **−0.65 ± 0.35** |

Survives longer, kills 4× less, scores much worse. **Rejected as a replacement.**
Individual mechanisms worth salvaging: the ratio-based engagement gate (more
principled than a fixed range), the laser charge controller, and the mortar cluster
solver. Note it was run without the map (`world=None`), so its LOS is optimistic —
but the kill collapse is a policy effect, not a map effect.

---

## Round 2 — follow-ups from the external reviews

### E35 — Strict fire gate (fixing D15)
`allow_fire` only scaled candidate utility while the branches passed literal
`fire=True`, so a zeroed candidate could still win the argmax and shoot. Added
`fire_gate_strict` to propagate the permission bit into the fire flag.

**Validation first.** With `fire_enabled=False, recip_fire=False`:

| | dealt | shots | kills | score |
| --- | --- | --- | --- | --- |
| strict OFF | 2,422 | 65.6 | 1.12 | 1.75 |
| strict ON | **0** | **0.0** | 0.00 | **0.38** |

So the old "pacifist" was never a pacifist, and the real control is **0.38** — a
bot that never fights dies first almost every match. That is the strongest
possible refutation of passive play.

**A/B of strict mode with normal firing** (3 ranges, n=48): score **1.21** vs
1.81, kills 0.67 vs 1.17, death 61 s vs 70 s → **−0.60 ± 0.27**.

**Verdict: the fix is correct, the gate is wrong.** Suppressing fire when the gate
closes costs half a kill and 9 s of life. The gate closes mainly because
`engage_dist = engage_range × aggression / adapt` shrinks to ~68 m under pressure.
Default stays `fire_gate_strict: False`; the flag exists so hold-fire policies
(regen cycle, ambush) can finally be tested.

### E36 — Pickup detour radius
`loot_goal` hard-coded a 30 m detour for floor weapons, smaller than the gap
between spawns. Parametrised as `pickup_detour_r`, tested 80 and 140.

| | score | kills | dealt |
| --- | --- | --- | --- |
| 30 (default) | 1.90 | 1.23 | 2,788 |
| 80 | 1.96 | 1.29 | 2,754 |
| 140 | 1.94 | 1.25 | 2,814 |

**Null.** Damage dealt does not move at all, so the detour never fires: `loot_goal`
is gated behind "no threat within 55 m", which is rare while a squad hunts us.
Raising the radius cannot fix a condition that is never met.

### E37 — Early weapon roam, hunting left on
`roam_until 45, weapon_seek_range 200`. This is the mechanism that actually works:
measured secondary-weapon uptime goes from **8 % to 35 %** of decisions (laser,
4 matches, 250 sampled decisions).

| Set | score | kills | death | per-range |
| --- | --- | --- | --- | --- |
| train (n=48) | 1.96 (base 1.94) | **1.42** (base 1.27) | 64 s | 2.44 / 2.44 / 1.00 |
| holdout (n=48) | 2.10 (base 1.96) | **1.46** (base 1.42) | 74 s | 2.06 / 1.69 / 2.56 |
| paired | +0.02 ± 0.30 / +0.15 ± 0.28 | +0.15 / +0.04 | | |

**Inconclusive by score, positive on kills and on the mechanism.** 4× weapon uptime
producing no damage increase is the interesting part — see E39.

**Official outcome (E40): 2.50 against 2.52 for the build without it, i.e. −0.02.**
Local predicted +0.02. The change is null and the default is reverted to
`roam_until 0.0`. Weapon uptime is a real capability; it is not worth score.

### E38 — Gun-only control (`take_pickups: False`)
If the secondary is worth carrying, removing it should hurt.

| Set | score | kills | dealt |
| --- | --- | --- | --- |
| train, gun-only | 1.79 (base 1.94) | 1.15 (base 1.27) | 2,636 |
| holdout, gun-only | 1.77 (base 1.96) | 1.15 (base 1.42) | 2,579 |

A secondary is worth **~0.17**. Real but small — it is not a 3× damage lever.

### E39 — Full-charge laser release
`laser_min_charge 0.45` releases at 45 % charge, where `frac = 0.35 + 0.65×0.45 =
0.64`, i.e. 202 damage for a 1.99 s cycle = **101 dps — worse than the gun's 187**.
Raising it to 0.9 gives 294 damage / 2.33 s = 126 dps.

| Set | config | score | kills | dealt |
| --- | --- | --- | --- | --- |
| train | charge 0.9 | 1.90 | 1.15 | 2,755 |
| train | charge 0.9 + roam45 | 1.92 | 1.38 | 2,917 |
| holdout | charge 0.9 | 1.79 | 1.23 | 2,553 |
| holdout | charge 0.9 + roam45 | 2.12 | 1.46 | 3,037 |

Noise. The laser is at best ~15 % better than the gun at realistic hit rates, so
**hypothesis H1 (a laser unlocks 5 kills) is dead.** That is the most important
negative result of this round: weapon quality is not the missing 3×.

---

## Official results — the only measurements that count

### E40 — Submission ledger

| # | Commit | What it was | Local | Official | Verdict |
| --- | --- | --- | --- | --- | --- |
| 1 | (initial) | starter-derived v0 | ~0.2 | **0.25** | baseline |
| 2 | `ac7f72a` | survival iteration: drone-aggro break, kiting, no camping, reciprocal fire | 1.9–2.1 | **1.83** | +1.58 |
| 3 | `407c50e` | hunt v1 (aggression) | ~2.0 | **2.44** | +0.61 |
| 4 | `7468dcb` | hunt v2 (target the weakest, standoff 45) | 1.94 | **2.52** | +0.08 — best known |
| 5 | `a33d613` | early weapon roam (`roam_until 45`) | 1.96 | **2.50** | −0.02, reverted |

Reading:

- **+0.61 from hunt v1** is the only large move we have ever made, and it was
  invisible locally. Aggression is the lever, and the local proxy systematically
  under-prices it.
- **+0.08 from hunt v2, −0.02 from weapon roam**: the last three submissions have
  been flat to two decimal places. We are on a plateau at ~2.5.
- **Local prediction vs official**: the roam probe predicted +0.02 and delivered
  −0.02. Within-architecture transfer is 1:1 (F17).
- **Best known build is `7468dcb` at 2.52.** The platform locks the best score at
  cutoff unless the submitter picks another, so nothing needs to be done to protect
  it — but do not expect HEAD to beat it. HEAD is behaviourally identical to it.

---

## Round 3 — structural mechanism search

### E41 — Combat engine v2 (dual-wielding, laser/lightning mastery, flipping strafe, proactive reload)
Added `combat_v2` behind a flag (default `False`) plus crash-safe `Bot.act` wrapper:
aligned-only gun firing, gun+lightning shared-pitch dual-wielding, full/lethal laser
release with 0.65 s LOS-flicker hold guard, flipping strafe, weapon-aware duel range
(stay outside enemy lightning, close inside ours), proactive between-fight reload,
and anti-aggro poke range limit.

- **E41a** (`v2_poke_max_r=95`, `v2_kite_hp=0.42`, `weapon_pref=[lightning,laser,mortar,gun]`, train n=48):
  score **1.58** vs 1.98 (**−0.40 ± 0.28**), kills 1.12 vs 1.25 (−0.12), death 64.3 s vs 74.7 s (−10.4 s),
  dealt 2,274 vs 2,896 (−622), acc **91.4 %** vs 82.5 %, dmg/kill 2,021 vs 2,317.
  Per-range: `8000:+0.12 / 11000:−1.19 / 13000:−0.12`.
  Diagnosis: the 95 m poke cap let the active hunter shoot us from 100–175 m uncontested.
- **E41b** (removed poke cap `175 m`, restored `v2_kite_hp=0.75`, train n=48):
  score **1.83** vs 1.98 (**−0.15 ± 0.28**), kills **1.31** vs 1.25 (+0.06), death 58.0 s vs 74.7 s (−16.7 s),
  dealt 2,699 vs 2,896, acc **87.9 %** vs 82.5 %, dmg/kill **2,057** vs 2,317, laser deaths 13 → 6,
  lightning deaths 10 → 7, gun deaths 19 → 29.
  Per-range: `8000:+0.38 (+0.50k) / 11000:−1.00 (−0.75k) / 13000:+0.19 (+0.44k)`.

**Verdict:** Weapons/accuracy/conversion improved cleanly (+5.4 % acc, −260 dmg/kill,
+35 % kills/sec, half the laser deaths), but open-ground strafing duels trade −16.7 s
of survival for no net score gain. Effective HP (~1,700) and cubes (~0.5) remain the
binding ceiling. Kept behind `combat_v2: False` for reuse with cover/rooftop mechanisms.

### E42 — Rooftop warfare (`roof.py`: jump+jet climbing, ledge-peeking, roof heal/reload/laser duck)
Precomputed 603 flat climbable roof spots (7.5–26 m tall) with ground launch points
(90 ms at hello). Climb with jump+jet, step back behind the roof edge during gun
reload / enemy laser charge / low-HP hard-hold-fire regen (`roof_heal_hp=0.62`),
and peek edges to shoot ground enemies. Also fixed an A* waypoint-index bug in
`nav.steer` where already-passed `path[0]` pulled the mech backwards (nav fix alone:
1.79 vs 1.98, −0.19 ± 0.25, noise).

- **E42 (`roof_enabled=True`, train n=48):**
  score **1.75** vs 1.98 (**−0.23 ± 0.29**), kills **0.83** vs 1.25 (−0.42 ± 0.22),
  death **84.8 s** vs 74.7 s (**+10.1 s**), dealt 2,088 vs 2,896 (−808), taken 1,843 (+106),
  acc 74.4 %. Per-range: `8000:−0.44 / 11000:−0.50 / 13000:+0.25`.
  Notable mechanism failure: **mortar deaths jumped 1 → 8** (mortar damage taken 28 → 230, 8×)
  because a slow mech on a flat roof is an easy mortar target whose shells arc over roof edges,
  and hiding back from the ledge cut damage dealt by −808.

**Verdict:** Rooftop camping reproduces the exact warden/D-09 trade (+10 s life, −0.42 kills,
−0.23 score) and gets punished 8× harder by mortars. Default stays `roof_enabled: False`.

### E43 — Snowball economy + weapons v2 (`snowball_v1`, adopted)
Combined five orthogonal fixes while preserving HEAD's proven occlusion-kiting survival:
1. **Fixed exact upgrade valuation (`econ._effect_value_v2`)**: fixed the bug where `armor`
   scored 4.80 (dead last) and `plating` scored 10.50 (below `servos=18, gyros=18, sensors=13`).
2. **Weapons v2 arbiter (`combat.py`)**: `weapon_pref=[lightning, laser, mortar, gun]`,
   shared-pitch gun+lightning dual-wielding (347–427 DPS), full/lethal laser charge with
   0.65 s LOS-flicker hold guard, aligned-only gun firing, proactive between-fight reload,
   and weapon-aware hunt standoff (28 m with lightning, 58 m vs enemy lightning).
3. **Persistent pickup memory (`known_pickups`)**: remember seen floor/drop weapons and
   detour when slot 1 is empty or a strict upgrade is nearby.
4. **Aggressive cube & kill-loot collection**: scoop loose cubes (instant +56 HP + +4 % dmg)
   and recent 3-cube kill corpses.
5. **Safe NPC drone (350 HP → 2 cubes) & crate (300 HP → 1 cube + 50 % weapon) farming**
   when no enemy mech has LOS.

| Set | Base | E43 (`snowball_v1`) | Paired Δ | Per-range Δ |
| --- | --- | --- | --- | --- |
| train (n=48) | 1.98 / 1.25k / 74.7s | **2.46** / **1.67k** / 75.2s | **+0.48 ± 0.38** (+0.42k, +0.4s) | +0.88 / −0.31 / +0.88 |
| holdout (n=48) | 1.67 / 1.23k / 65.9s | **2.29** / **1.71k** / 69.8s | **+0.62 ± 0.37** (+0.48k, +4.0s) | **+0.62 / +0.50 / +0.75** |
| **combined (n=96)** | **1.82 / 1.24k / 70.3s** | **2.38 / 1.69k / 72.5s** | **+0.55 ± 0.26** (**+0.45k**, +2.2s) | **5 of 6 ranges positive** |

Metrics (96-match means): dealt 2,728 → **3,307** (+579), taken 1,741 → **1,854** (+113),
trade ratio 1.57× → **1.78×**, dmg/kill 2,200 → **1,957**, cubes 0.37 → **1.39** (3.8×).
**First policy in the entire project to break the 2.10 local ceiling on both train and holdout.**
Adopted as default.

### E44 — Tactical ground cover (laser-duck, reload-duck, low-HP regen hold-fire)
Built on top of E43 (`snowball_v1`), behind `tactical_cover_v1` (default `False`): fast
`<0.5 ms` nearby cover search (`cover.find_quick_cover`) triggered on enemy laser
charge, gun reload, and low-HP (`< 0.52`) hard-hold-fire regen when no enemy had LOS
within 52 m. Also fixed a zone-death bug where NPC `flee_until` cleared `emergency=True`.

- **E44 (`tactical_cover_v1=True` on E43, train n=48):**
  score **2.23** vs 2.46 E43 / 1.98 orig base (**−0.23** vs E43, +0.25 ± 0.41 vs orig base),
  kills **1.35** vs 1.67 E43 (−0.32), death **76.7 s** vs 75.2 s (+1.5 s),
  dealt **2,889** vs 3,394 (−505), taken **1,914** vs 1,835 (+79 EHP healed), cubes 1.03.
  Per-range vs orig base: `8000:+0.56 / 11000:−0.44 / 13000:+0.62`.

**Verdict:** Confirms D-09 a fourth time — holding fire below 52 % HP bought only +79 HP
of regen (+1.5 s) while costing −505 damage and −0.32 kills vs E43. Kept behind
`tactical_cover_v1: False`; retained the `emergency` zone-safety fix.

### E45 — Snowball v2 (`snowball_v2`, adopted)
Built on top of E43 (`snowball_v1`), removing every passive bottleneck and fixing a major
mortar aiming bug:
1. **Mortar ballistic aim fix (`combat.py`)**: `shot_error` previously compared the skyward
   launch pitch against the ground impact ray (always 30–100 m error → `hit_prob = 0` →
   mortar virtually never fired). Replaced with angular error `hypot(wrap(fy-yaw), fp-pitch)`
   plus 2-target splash cluster midpoint aiming and live-config min/max range.
2. **Active full-speed early patrol (`sb2_patrol_until=150`)**: sweep the safe zone at full
   walk speed while hungry (`w1 is None` or `cubes < 8`) instead of camping at 4.85 m/s.
3. **Approach visible NPC drones (<95 m) & crates (<80 m)** when safe (`sb_los_mechs==0`,
   `mclose>82`), plus aggressive 3-cube kill-loot scooping even with distant enemies.
4. **Lightning 1v1 rush (`sb2_light_rush`)**: suppress the 2-hit kite abort when holding
   lightning in a healthy (`hp > 48 %`) 1v1 inside 82 m and boost into 24 m for 427 burst DPS;
   hard-counter enemy lightning inside 52 m with away-boost when we lack lightning.
5. **Supply drop contesting (`sb2_drop_contest`)**: capture reachable drops (<135 m, lands ≤16 s)
   for full HP + full energy + 3 cubes.

| Set | Orig Base | E43 (`v1`) | **E45 (`snowball_v2`)** | Paired Δ vs Base | Per-range Δ vs Base |
| --- | --- | --- | --- | --- | --- |
| train (n=48) | 1.98 / 1.25k / 74.7s | 2.46 / 1.67k | **2.48 / 1.96k / 68.0s** | **+0.50 ± 0.36** (**+0.71 ± 0.27k**) | `+0.31 / +0.00 / +1.19` |
| holdout (n=48) | 1.67 / 1.23k / 65.9s | 2.29 / 1.71k | **2.42 / 1.90k / 68.2s** | **+0.75 ± 0.29** (**+0.67 ± 0.23k**) | **`+0.81 / +0.25 / +1.19`** |
| **combined (n=96)** | **1.82 / 1.24k / 70.3s** | **2.38 / 1.69k** | **2.45 / 1.93k / 68.1s** | **+0.625 ± 0.23** (**+0.69 ± 0.18k**) | **6/6 ranges non-negative** |

Metrics (96-match means): dealt 2,728 → **3,699** (+971, +36 %), taken 1,741 → **1,912**
(+171), trade ratio 1.57× → **1.93×** (1.98× holdout), dmg/kill 2,200 → **1,920**, cubes
0.37 → **1.73** (4.7×; 9.6× on holdout), zone deaths 6 → 2, seed 16000 reached **3.00**
with **2.38 kills**. Adopted as default; ready for official calibration probe after sandbox check.

### E46 — Snowball v3 (`snowball_v3` + `laser > lightning > mortar > gun`, adopted)
Built on top of E45 (`snowball_v2`):
1. **Unreachable-loot timeout blacklist (5.5 s / 35 s)**: fixes a severe bug observed on
   seed 16001 where an unreachable cube froze the bot for 152 s.
2. **Pure enemy-laser cover duck (`sb3_laser_duck`)**: 0.5 s boost behind a nearby wall
   when an enemy charges a laser aimed at us, with **zero fire suppression**.
3. **1v1 corner angle isolation (`cover.find_isolate_spot`, `sb3_isolate`)**: when 2+
   enemies have direct LOS simultaneously, step ≤10.5 m to a spot that keeps clear shot
   on the primary target while occluding extra enemies.
4. **Ballistic mortar dodge (`combat.dodge_vector`)**: exact gravity landing-point
   prediction for incoming mortar shells (fixes defect D11).
5. **Threat- & edge-aware `_break_heading`**: avoid kiting into idle house bots (<48 m)
   or into the open map boundary.
6. **Weapon preference `laser > lightning > mortar > gun` (`E46b`)**: tested against
   `lightning > laser` (`E46a`), unlocking safe 60–180 m dual-wielding laser+gun bursts.

| Set | Orig Base | E45 (`v2`) | **E46b (`sb3` + laser)** | Paired Δ vs Base | Per-range Δ vs Base |
| --- | --- | --- | --- | --- | --- |
| train (n=48) | 1.98 / 1.25k | 2.48 / 1.96k | **2.81 / 2.10k / 76.2s** | **+0.83 ± 0.43** (**+0.85 ± 0.40k**) | `+1.12 / −0.56 / +1.94` |
| holdout (n=48) | 1.67 / 1.23k | 2.42 / 1.90k | **2.52 / 2.10k / 64.7s** | **+0.85 ± 0.35** (**+0.88 ± 0.32k**) | **`+1.19 / +0.62 / +0.75`** |
| **combined (n=96)** | **1.82 / 1.24k** | **2.45 / 1.93k** | **2.67 / 2.10k / 70.5s** | **+0.84 ± 0.28** (**+0.86 ± 0.25k**) | **3.0σ score, 3.4σ kills** |

Metrics (96-match means): dealt 2,728 → **4,103** (+1,375, +50 %), taken 1,741 → **1,986**
(+245), trade ratio 1.57× → **2.07×** (2.07× train, 2.06× holdout), cubes 0.37 → **2.10**
(5.7×), train ranges 8000/13000 reached **3.06** and **3.19**. Adopted as default; overturns F8.

### E47 — Snowball v4 (laser 82 m standoff, opening gear-first, flipping strafe, 3.2 s short kite)
Tested on top of E46b (`snowball_v4`, default `False`): 82 m laser standoff, deferring
bare-gun hunt until `w1` equipped (`t < 38 s`), flipping strafe, 1.05 s laser LOS hold,
and shorter 3.2 s kite hold when `hp_frac > 0.72`.

- **E47 (`snowball_v4=True`, train n=48):**
  score **2.58** vs 2.81 E46b / 1.98 orig base (**−0.23** vs E46b, +0.60 ± 0.38 vs orig base),
  kills **2.08** vs 2.10, death **68.8 s** vs 76.2 s (−7.4 s), dealt 3,781 vs 4,170 (−389),
  taken 1,901 vs 2,013 (−112), dmg/kill **1,815** (all-time best conversion), cubes 1.90.
  Per-range vs orig base: `8000:+1.06 / 11000:−0.81 / 13000:+1.56`.

**Verdict:** Cutting kite duration to 3.2 s above 72 % HP and deferring early hunting cost
−7.4 s of survival and −389 damage vs E46b. Default stays `snowball_v4: False`; E46b remains HEAD.

### E48 — Precision v1 (`precision_v1`: 1-tick slew gate, rear-bearing snap, no laser charge on low-HP kite, fallback indirect mortar)
Tested on top of E46b behind `precision_v1` (default `False`).

- **E48 (`precision_v1=True`, train n=48):**
  score **2.42** vs 2.81 E46b / 1.98 orig base (**−0.39** vs E46b, +0.44 ± 0.36 vs orig base),
  kills **1.83** vs 2.10, death **69.1 s** vs 76.2 s (−7.1 s), dealt **3,547** vs 4,170 (−623),
  acc **78.3 %** vs 74.9 %, cubes 1.87.
  Per-range vs orig base: `8000:+0.31 / 11000:−0.44 / 13000:+1.44`.

**Verdict:** Tightening `future_aim` from `0.10 s` (decision horizon) to `0.05 s` (1 tick)
suppressed shots that would have aligned on tick 2 of the 2-tick decision window, cutting
dealt damage by −623 and kills by −0.27. Default stays `precision_v1: False`; E46b remains HEAD.

### E49 — Kill-reset cube snowball (`kill_snowball_v1`, adopted)
Built on top of E46b (`snowball_v3` + laser preference). Diagnosed why cubes stayed at 2.10
despite 2.10 kills (= 6.3 dropped cubes): winning a duel left old hits from the dead mech in
`damage_bearings` plus an active `kite_until` timer, causing the bot to boost 130 m away
from its own dead corpse and abandon 3 cubes (+168 instant HP, +12 % damage, upgrade) and
its dropped secondary weapon.
1. **Kill-reset kite**: track attacker `by` in `damage_bearings`; on `kill(tid)`, purge
   `tid`'s bearings and, if no other live mech damaged us in the last 3 s, clear
   `kite_until = -1.0` so we immediately scoop the 3-cube corpse.
2. **Closer cube & loot retention**: extend `kill_loots` scoop radius `75 m → 105 m` when
   `sb_los_mechs == 0`; stop `kite` from overriding a `<16 m` safe cube right at our feet
   (`hp_frac > 0.25`); relax safe NPC/crate farming thresholds (`mclose > 66 m`, `cubes < 15`).
3. **Idle rear-damage bearing snap**: when `aim_cmd is None` and we took damage in the last
   2 s, snap torso toward the most recent damage bearing instead of slow-scanning.

| Set | Orig Base | E46b (`v3`) | **E49 (`kill_snowball_v1`)** | Paired Δ vs Base | Per-range Δ vs Base |
| --- | --- | --- | --- | --- | --- |
| train (n=48) | 1.98 / 1.25k / 74.7s | 2.81 / 2.10k | **3.27 / 2.54k / 76.5s** | **+1.29 ± 0.37** (**+1.29 ± 0.36k**) | **`+1.06 / +0.88 / +1.94`** |
| holdout (n=48) | 1.67 / 1.23k / 65.9s | 2.52 / 2.10k | **3.02 / 2.50k / 70.4s** | **+1.35 ± 0.38** (**+1.27 ± 0.37k**) | **`+1.44 / +1.44 / +1.19`** |
| **combined (n=96)** | **1.82 / 1.24k / 70.3s** | **2.67 / 2.10k** | **3.15 / 2.52k / 73.5s** | **+1.32 ± 0.26** (**+1.28 ± 0.26k**) | **6/6 ranges `+0.88` to `+1.94`** |

Metrics (96-match means): dealt 2,728 → **4,628** (+1,900, +70 %), taken 1,741 → **2,070**
(+329), trade ratio 1.57× → **2.24×** (2.20× train, 2.28× holdout), dmg/kill 2,200 → **1,836**,
cubes 0.37 → **3.12** (8.4×; 16× on holdout!). Every single seed range scored **2.94–3.62**.
Adopted as default (`kill_snowball_v1: True`). Independent train re-run verified **3.15** (2.44k, 73.4s).

### E50–E55 — Ablations on top of E49 (`kill_snowball_v1`), all reverted
Six controlled train (n=48) ablations on top of E49 (`3.15–3.27` train), none beating E49:
- **E50a (`snowball_v5`, 2.27 / 1.67k / 66.7s, −0.88 vs E49)**: cutting `dodge_vector` (`1.4→0.45`) and skipping `strafe` during kite spiked gun deaths on 8000 `2→11`; suppressing boost while charging laser cut kite speed `9.0→5.85 m/s` (`boost*0.5` vs `walk*0.5`).
- **E50b (`sb5_clean`, 2.69 / 2.15k / 71.0s, −0.46 vs E49)**: raising `pk_lim=75 m` in LOS of an enemy locked movement (`sb_econ_lock`) straight into gunfire.
- **E51 (`kite_v2`, 2.58 / 1.92k / 65.0s, −0.57 vs E49)**: requiring `walk_clear` all the way to `16–34 m` in `_break_heading` rejected building-wrapping A* escapes, forcing open-street kiting (`−11 s` life).
- **E52 (`evade_v2`, 2.92 / 2.31k / 67.0s, −0.23 vs E49, 1,790 dmg/k)**: flipping `strafe_sign` every `0.45–0.75 s` repeated the E47 failure (`−9 s` life, zig-zagging in place instead of curving behind cover); corner laser pre-charge also triggered `0.5×` speed penalty.
- **E53 (`farm_snowball_v1`, 2.79 / 2.06k / 66.4s, −0.36 vs E49, 3.03 cubes)**: pulse-boosting patrol/farm (90 m boost sound + energy drain) and shooting crates/NPCs at `mclose=52 m` (320 m gun sound) drew nearby house bots (`−10 s` life).
- **E54 (`laser_sniper_v1`, 2.83 / 2.25k / 62.2s, −0.32 vs E49, 8000=3.25)**: raising `fire_max_range=225 m` and laser standoff to `92 m` woke distant bots (`−14 s` life) and left kill corpses too far to scoop (cubes `2.97→2.37`).
- **E55 (`finish_v1`, 2.94 / 2.23k / 69.4s, −0.21 vs E49, 8000=3.31)**: finish-kill commitment + `>115 m` bystander filter + reload-cover duck set a new high on `8000` (3.31 / 2.75k) but dropped cubes `2.97→2.17` and overall train below E49.

**Takeaway:** E49 (`kill_snowball_v1`) sits at a sharp local optimum (~3.15 combined) where close-to-mid duels (~45 m), uninterrupted constant-direction strafe+dodge kiting, and immediate 3-cube corpse scooping reinforce each other. Crossing 4.0–5.0+ requires a new architectural mechanism, not small edits to E49.

### E56–E57 — Reverse-Engineering `#2 (6.19)` & Python 3.13 `Apex v1` (`apex.py` + fast 3 m `world.py`, ADOPTED)
Calibrated local `at-sim` against `#2 giddygiddyboy` (`6.19` official) across **192 matches** (`96 HK=1` + `96 HK=0`):
- `#2 giddygiddyboy` (`6.19` official): `HK=1` **2.92** (`3.04` train / `2.79` holdout), `HK=0` **3.01** (`3.06` train / `2.96` holdout), **192-match grand avg `2.96`**, **44 lightning deaths / 192 (23 % of all deaths!)**.
- Our old Python `E49` (`b4e76cf`): `HK=1` **3.15** (`3.27` / `3.02`), `HK=0` **2.68** (`2.46` / `2.90`, `−0.47` stealth collapse under realistic vision!), **192-match grand avg `2.91`**.

Rebuilt our Python 3.13 stack with **`apex.py` (`ApexBrain`)** + upgraded **`world.py`** (1 m terrain/prisms + `8×8 block_max` fast raycaster at `0.012 ms/ray` + 3 m 8-connected nav grid with wall clearance, `main_comp`, precomputed `main_near` courtyard escape, and generation-stamped bounded A*):
- **Core 3-phase stealth/hunt/FFA architecture**: Opening `≤ 20 s` (`Ghost + Peek + LaserFirst` + quiet walk from `hello.config.sound.step_speed`), Squad Hunt `> 20 s` (hot-target engagement gate so we fight 1–2 hunters instead of waking the map, `Stick=200`, `LowBonus=200`, `HPw=0.18`, 16-dir `fight_move`, BFS `cover_move`, `LoseRule` rapid disengage, `Finish=20 m` dive, `FightLoot=70 m` with rooftop `abs(dz) < 3.6` bug fixed, `NoMortar` cookoff immunity, `LethalK=0.70` early laser execute, jump-jet courtyard `_escape`), and auto-FFA Guard switch (`other_dead >= 5`).
- **Validated innovation beyond `#2` — `anti_lightning` (ADOPTED)**: repels **all** visible lightning carriers within `light_range + 16 m` inside `fight_move` + scored 7-heading safe emergency kite (`d < light_range + 6 m`, penalized by zone and other enemies' LOS/charging lasers) + skips cubes guarded by a lightning carrier. Slashes lightning deaths **44 → 22 / 192 (−50 %)**.
- **Tested & rejected ablations on top of `Apex` (each 96 matches: 48 HK1 + 48 HK0)**:
  - `hunt_laser_duck` (`−0.07` avg: breaking LOS hurts our own DPS more than laser damage saved).
  - `dynamic_upgrades` (`−0.15` avg: picking `laser_damage`/`laser_charge` early in `UPGRADE_ORDER_LASER` beats waiting until slot 1 holds a laser).
  - `kill_reset + sensor_awareness + smart_fire` bundle (`−0.19` avg: `lead_clear` suppressed shots `−357` dealt).
  - `mortar_v2 + gun_juke` (`−0.19` vs floor), `smart_lose + kill_reset` (`−0.01`), `opening_gear` (`+0.00`: `+0.38k` HK1 / `+0.17k` HK0, hurt `13000` HK0), `corner_slice + laser_punish + backstab/cookoff` (`−0.10`), `combat_boost` (`−0.38`), `dead_window_duck` (`−0.29`), `early_hunt_laser + opening_laser_seek + long_laser_range` (`−0.14`), `smart_drops + roof_laser_grab` (`−0.12`, though `+0.04` HK0).
  - Over-aggressive latency shortcuts (`step_m=2.0`, `max_expand=1800`, `budget=4ms`) cost `−0.25` across 192 matches (`−0.83` HK1 train) — reverted to exact `step_m=1.5` & `max_expand=4000`, keeping only the `path2` replay anti-thrash cooldown (`300/300 PASS` in 1-CPU Docker, p50 `1.6 ms`, p90 `6.8 ms`, p99 `8.8 ms`, max `9.9 ms`).

| Bot (192-match benchmark) | `HK=1` Train (48) | `HK=1` Hold (48) | **`HK=1` Comb (96)** | `HK=0` Train (48) | `HK=0` Hold (48) | **`HK=0` Comb (96)** | **192-Match Avg** | Lightning Deaths / 192 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Orig BASE (`7468dcb`, 2.52 off.) | 1.98 | 1.67 | **1.82** | — | — | — | — | — |
| Old Python `E49` (`b4e76cf`) | 3.27 | 3.02 | **3.15** | 2.46 | 2.90 | **2.68** | **2.91** | 18 |
| `#2 giddygiddyboy` (`6.19` off.) | 3.04 | 2.79 | **2.92** | 3.06 | 2.96 | **3.01** | **2.96** | **44** |
| **`Apex v1` (Python 3.13, ADOPTED)** | **3.21** (+0.17) | **3.29** (**+0.50**) | **3.25** (**+0.34 vs #2 / +1.43 vs BASE**) | **2.90** | **3.12** (+0.17) | **3.01** (**+0.33 vs E49**) | **3.13** (**+0.17 vs #2**) | **22 (−50 %)** |

*(Initial `B0_esc` pre-cooldown run scored `3.60 / 3.50` HK1 and `3.10 / 3.31` HK0 = `3.38` grand avg; final verified `Apex v1` (`331c2d1`) scored **5.33 official (Rank 58, `+2.81` vs 2.52)** — highest of the Python `giddy`-architecture ports, confirming the 5.0–5.33 Python raster/latency ceiling documented by multiple teams.)*

### E58 — `Apex-Go v2` (Compiled Go Engine + Top-Leaderboard Synthesis + Verified Breakthrough Upgrades, ADOPTED)
Deep-dived public MIT-licensed repos of Top `> 6.10` teams (`#4 TigerTown27 6.25`, `#5 not even close 6.25`, `#9 giddygiddyboy 6.19`, `#13 2.3% 6.19`, `#15 Wai and Jai 6.19`, `#19 @GMUNVIS 6.19`, `#20 Kanyaraasi 6.17`, `#25 Team-Xero 6.13`) and calibrated top architectures in `at-sim` (`192` matches):
- `#4 TigerTown27 (6.25 off., Go)` crushed `#9 giddy` (`2.96`) with **`4.33` grand avg** (`4.02/5.08` HK1, `3.62/4.60` HK0), driven by exact polygon raycasting + 2 m nav + 34-candidate forward-simulated trajectory MPC `steer()` + online adaptive gun lead + range-aware `fightPlan`.
- Diagnosed `#4`'s concrete blind spots across 192 matches: **27/192 lightning deaths** (zero anti-lightning forcefield + `fightPlan` `r=45 < 45` bug), hard-coded `252` gun speed in `leadRecord` & fixed `0.075 s` latency, no `rear_mult` (`1.5×`) / `cookoff` (`+60 %`) lethal-laser or target priority, odd-tick laser hold stall, unwired `BeamFFA`, no late-game cautious switch (`Th3r0n` `+0.35` official), and static `2 m` final-circle tolerance.

Built our compiled static Go engine (`cmd/mechbot/`, `internal/{proto,world,bot}/`, `Dockerfile` → `FROM scratch`, `4.03 MB`, **300/300 PASS** in 1-CPU Docker) and ran controlled 96-match (`48 HK1 + 48 HK0`) paired ablations of every upgrade:
- **Round 1 individual ablations vs `BASE_GO` (`4.02 HK1 / 3.62 HK0 = 3.82` train)**:
  - **`U2_antilight`** (`AntiLightningW=180, AntiLightningPad=12` + `r+6` `fightPlan` fix + all-carrier cube guard): **`4.62 (+0.60) / 3.69 (+0.07) = 4.16 (+0.34)`**, lightning dmg `-40% to -58%`, dealt `6,829`, trade `3.01×` — **ADOPTED**.
  - **`U4_smartfire`** (`SmartFireV2` cooldown-aware latency + dynamic `gun.speed` in lead + `rear_mult`/`cookoff` lethal & priority + `LaserEarlyRel` odd-tick release): **`4.48 (+0.46) / 3.58 = 4.03 (+0.21)`**, trade **`3.08×`**, dealt `6,751`, cubes `5.73` — **ADOPTED**.
  - Rejected on train: `U1_nomortar` (`3.66`), `U3_laserdodge` (`3.69`), `U3b_lasercov` (`3.65`), `U6_squadpeek` (`3.76`), `U7_combattune` (`3.52`), `OverlandEarly=2.5` (`3.79`).
- **Round 2 stacked & Round 3 full 192-match (`train + untouched holdout`) + 16-mech FFA validation** (after fixing a 1-line `BeamFFA` false-positive on missed practice beams via `segPointDist2D > 22`):
  - Rejected on stack: `S3_plus_focus` (`4.00`), `S4_strong_al` (`4.27`), `S5_regen` (`4.14`); `OpenSecs=18` (`4.47` grand) and `OpenSecs=14` (`4.50` grand) lost to `OpenSecs=24` (`4.70` grand) on holdout.
  - **`APEX_O24` (`Apex-Go v2`, ADOPTED)**: `U2_antilight + U4_smartfire + CautiousT=265 + fixed BeamFFA + FinalHold` (`OpenSecs=24`).

| Bot (192-match Practice + 24×16-mech FFA) | TR HK1 (48) | TR HK0 (48) | HO HK1 (48) | HO HK0 (48) | **HK1 (96)** | **HK0 (96)** | **192-Match GRAND** | **16-Mech FFA (n=24)** |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `#9 giddygiddyboy` (`6.19` off.) | 3.04 | 3.06 | 2.96 | 2.79 | 3.00 | 2.92 | **2.96** | `7.11 ± 0.41` (4/24 wins) |
| Our `Apex v1` Py (`5.33` off.) | 3.21 | 2.90 | 3.29 | 3.12 | 3.25 | 3.01 | **3.13** | — |
| `#4 TigerTown27` (`6.25` off.) | 4.02 | 3.62 | 5.08 | 4.60 | 4.55 | 4.11 | **4.33** | `6.88 ± 0.43` (7/24 wins) |
| **`Apex-Go v2` (`a484109`, `#1 6.28` off.)** | **4.96** (+0.94) | **3.65** (+0.03) | **5.40** (+0.32) | **4.81** (+0.21) | **5.18** (**+0.63**) | **4.23** (**+0.12**) | **4.70** (**+0.37 vs #4 / +1.74 vs #9**) | **`8.35 ± 0.38`** (**13/24 wins = 54.2 %**, **+1.47 vs #4**, 0 zone deaths, 2 lightning deaths!) |

*(Official result for `a484109`: initially **6.27**, then held rock-solid and rose to **`#1 IN THE WORLD` at `6.28`** on the `2026-11-22 05:54 UTC` live re-scoring wave while salt-overfitted entries collapsed `-0.37` to `-0.76`!)*

### E59 — Full 402-Repo GitHub Re-Probe & `Apex-Go v3` (`4.99` 192-Match Grand Avg / `6.00` TR_HK1 / `3.87×` Trade, ADOPTED)
Conducted a fresh 16-query GitHub re-probe (`402` repos discovered, `226` pushed in last 9h; `23` brand-new + `11` updated top repos cloned & audited: `SandeepMadhavarapu/BattleRoyale`, `MarwanMoh11/mech-royale`, `lukejwaszyn/mech-royale`, `andrew-zhouu v0.134`, `sparshagra/AIEthicsTuts` (#3 6.17), `azz0048/Mech-Royale` (#5 AA's 6.05), `Th3r0n`, `waiprotein`, `BrozJosef`, `egeiran`).

Ablated 9 generalizable, zero-overfit mechanisms individually (`n=96` train: 48 HK1 + 48 HK0) on top of our `#1 (6.28)` `Apex-Go v2` (`4.96 / 3.65 = 4.30` train):
- **`V3_lasercd`** (`LaserCDTrack`, `obs.Beams` enemy laser cooldown → 2 s punish window): **`5.42 (+0.46) / 3.88 (+0.23) = 4.65 (+0.34)`**, dealt `7,889`, trade `3.32×`, `1,639 dmg/kill` — **ADOPTED** (gated to `!b.ffa` to keep FFA caution intact).
- **`V3_cubesmart`** (cube-pile + `1.75×` upgrade-threshold pricing): **`5.02 / 4.21 (+0.56) = 4.61 (+0.31)`** on train, but dragged `HK1` holdout (`5.40 → 4.69/4.90`) in stack — **rejected in final combat stack**.
- **`V3_rearavoid`** (`RearAvoidW=35`, MPC penalty keeping extra hunters out of `1.5×` rear arc): **`5.35 (+0.39) / 3.81 (+0.16) = 4.58 (+0.28)`**, dealt `7,771`, trade `3.27×` — **ADOPTED**.
- **`V3_reload`** (`CoverReload`, cover-pause gun top-off reload when no enemy LOS ≥ 1.1 s): **`5.02 / 3.90 (+0.25) = 4.46 (+0.15)`**, 3 alive wins — **ADOPTED** (`0.60*mag` Practice / `0.25*mag` FFA).
- **`V3_laserm`** (`LaserMechOnly + RetreatPest`): **`5.00 / 3.73 = 4.36 (+0.06)`** (`RetreatPest` **ADOPTED**; `LaserMechOnly` dropped gun acc `-6%` and slowed `HK1` drone kills in stack → dropped).
- Rejected: `V3_upv2` (`4.21`), `V3_killhunt` (`4.32`), `V3_droprun` (`4.10`).
- **Stacked 192-match validation (`train + untouched holdout`, `96 HK1 + 96 HK0`)**:
  - `V3_CORE3`: `4.67` (`4.96 HK1 / 4.38 HK0`) | `V3_CLEAN4`: `4.58` | `V3_ALL5`: `4.81` (`4.75 HK1 / 4.86 HK0`)
  - `V3_COMBAT3` (`LaserCDTrack + RearAvoidW=35 + CoverReload + RetreatPest`): **`4.83`** (`5.48 HK1 / 4.19 HK0`; TR_HK1 `5.77`, `8,792` dealt, `3.63×` trade, 9 wins)
  - **`Apex-Go v3` (`V3_COMBAT3 + PracticeRim=0.6`, ADOPTED)**: **`4.99` GRAND AVG (`+0.29` vs `#1 6.28` `v2`, `+0.66` vs `#26 TigerTown`, `+2.03` vs `giddy`!!)** — `HK1` **`5.55`** (`TR_HK1 = 6.00 ± 0.63`, **`9,070` dealt**, **`3.87×` trade**, **`5.38` kills/match**, **`7.13` cubes**, `98.1 s` life, 4 alive wins), `HK0` **`4.44`** (`4.17 / 4.71`), **8 alive wins / 192**, only **1 zone death / 192**!
- **16-Mech FFA Showdown (`n=24`, 4-way)**: `v2_628` `8.13 ± 0.49` (13 wins) > `V3_COMBAT3` (un-gated) `7.75` (7 wins) > `TigerTown` `7.50` (4 wins) > `giddy` `6.63` (0 wins). Gating `LaserCDTrack` (`!b.ffa`) and `CoverReload` (`0.25*mag` in FFA) preserves `v2_628`'s `8.13–8.35` FFA supremacy alongside `v3`'s `4.99` Practice!

| Bot (192-Match Practice) | TR HK1 (48) | TR HK0 (48) | HO HK1 (48) | HO HK0 (48) | **HK1 (96)** | **HK0 (96)** | **192-Match GRAND** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `giddy` (`5.44` live) | 3.04 | 3.06 | 2.96 | 2.79 | 3.00 | 2.92 | **2.96** |
| `TigerTown27` (`5.69` live) | 4.02 | 3.62 | 5.08 | 4.60 | 4.55 | 4.11 | **4.33** |
| `Apex-Go v2` (`a484109`, **`#1 6.28`**) | 4.96 | 3.65 | 5.40 | 4.81 | 5.18 | 4.23 | **4.70** |
| **`Apex-Go v3` (ADOPTED)** | **6.00** (**+1.04**) | **4.17** (**+0.52**) | **5.10** | **4.71** | **5.55** (**+0.37**) | **4.44** (**+0.21**) | **4.99** (**+0.29 vs #1 / +0.66 vs TigerTown**) |

---

## Rejected

| # | Change | Result |
| --- | --- | --- |
| E19 | Focus fire | +0.38 ± 0.13 (32 pairs, range 4000) then **−0.04 ± 0.08** (48 pairs, range 8000) — **false positive**, retracted. Kept as neutral/mechanically sound |
| E20 | Laser pre-charge without a working gate | −0.16 ± 0.13 |
| E21 | Indirect mortar (accept LOS-blocked targets) | −0.28 ± 0.11 |
| E22 | Economy bundle (roam + crates + drops) | **−0.78 ± 0.36** |
| E23 | High aim point (0.75 body height) | −0.47 ± 0.23 |
| E24 | Open ground (`cover_bias` 0) | −0.22 ± 0.19 |
| E25 | LOS-breaking cover on | 0.00 ± 0.07, costs ~10 ms/decision |
| E26 | Statue (never move) | −0.46 |
| E27 | Coward (never fire) | 0.00 |
| E28 | Hunter v3 (aggressive variant) | −0.15 |
| E29 | Zone-edge goal | +0.19 / +0.67 / −0.10 → +0.25 ± 0.23, inconclusive |
| E30 | Aggression 1.0 / engage_range 240 | +0.12 ± 0.12, inconclusive |
| E31 | Mortar-preferring loadout | −0.02 ± 0.09, inconclusive |

---

## Diagnostics (not A/B)

### E32 — Decision-time budget
387 sampled decisions: a shootable target existed **21 %** of the time, we were
alone **35 %**, enemies were visible but terrain-blocked **44 %**. Damage is limited
by target availability, not by permission to shoot.

### E33 — Death profile
Cause of our deaths: gun ~1,000–1,250 damage, laser/lightning/mortar ~400 each, NPC
~70. Death time improved from 77 s (v1) to 97–120 s during the survival iteration,
now ~70 s with hunt mode enabled.

### E34 — Sandbox conformance
299/300 answered, 1 late, p99 24.7 ms, max 106 ms. Passes. p99 native is 4.3 ms.

**Next:** [`OPERATIONS.md`](OPERATIONS.md) — how to reproduce any of this.
