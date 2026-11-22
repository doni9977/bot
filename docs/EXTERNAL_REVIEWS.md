# EXTERNAL REVIEWS — what outside models said, and whether it held

> Living document. Last updated **2026-11-21 22:50 UTC**.

`HANDOFF.md` was sent to two stronger models with a prompt asking them to overrule
it where they disagreed, resolve the 5.96 puzzle, and return an implementable
policy. Both responded. Their artefacts are in `gemini/` and `claude/`.

This file records **what we tested and what survived**, not what they claimed. A
claim that was not tested is marked as such.

---

## Claude — `claude/warden.py` (778 lines) + tests

**Approach.** Replace the policy wholesale with a predictive engagement gate: enter
a duel only when `T_they_kill_me / T_i_kill_them ≥ 1.15`, computed from per-weapon
DPS, hit probabilities and the number of live hunters. Plus heal cycles, a
weapon-first opening, zone-clock regimes, a laser charge controller, a ballistic
mortar solver with a cluster-value function, and a supply-drop contest. Crash-safe
via `act_safe`, fuzzed over 3,000 malformed observations.

**Engineering quality: high.** Reads every number from `hello.config`, no
hard-coded geometry, ~0.18 ms per decision, and it ships its own test harness. This
is the most rigorous artefact either model produced.

**Tested (E18).** Wired standalone into our harness as `{"ext":"warden"}` and run on
six seed ranges, 48 matches each:

| Set | ours | warden | paired |
| --- | --- | --- | --- |
| train | 1.83 / 74 s / 1.19 k | 1.06 / 84 s / 0.27 k | **−0.77 ± 0.28** |
| holdout | 1.96 / 72 s / 1.33 k | 1.31 / 85 s / 0.31 k | **−0.65 ± 0.35** |

**Verdict: rejected as a replacement.** It survives +11 s and kills 4× less. The
gate is too strict — it only fights when it is mathematically winning, which is
rare against a coordinated squad, so it spends the match not fighting.

**Worth salvaging:**

- The **ratio gate** is a better idea than our fixed `engage_range`, but it needs a
  much lower threshold (`RATIO_MIN` ≈ 0.6, not 1.15) to actually fire.
- The **laser charge controller** (hold until `charge ≥ lethal_charge`, release
  only with clear LOS, step back during cooldown).
- The **mortar cluster solver** (`best_mortar_point`, values a splash point by
  expected damage across targets) — directly relevant to the late-game cluster
  problem in F8.
- `act_safe` as a crash wrapper. We should adopt this pattern regardless.

**Caveat.** Run with `world=None`, so its LOS is optimistic (it always thinks it can
shoot). That inflates its aggression, not deflates it — so the kill collapse is a
policy effect, not a map effect.

---

## Gemini — a specification plus code fragments

**Approach.** Keep the architecture but re-aim it: a 7-state hierarchical FSM
(`ZONE_EMERGENCY`, `RECOVER`, `DROP_CONTEST`, `DUEL_FINISH`, `WEAPON_ACQUIRE`,
`ROOF_CLIMB`, `STALK_ROTATE`) with **hard fire suppression** during recovery, a
laser peek-charge routine, a verified-arc mortar, and rooftop play using jump+jet.

**Its central claim.** The dossier's "survival is a hard ~60 s wall" conclusion is
false, and the experiment that "proved" it was invalid. The leader plays multi-life
attrition over 180–300 s: regen cycles (45 → 115 HP/s with 2× nanites), rooftop LOS
breaks, and supply drops at t = 95/165/235.

### Claims checked

| Claim | Verdict | Evidence |
| --- | --- | --- |
| The "true pacifist" arm is invalid — the fire gate cannot suppress fire | **CORRECT, and important** | E15 / F11. That arm still dealt 2,606 damage. `allow_fire` only scales utility; branches pass `fire=True` |
| Laser DPS is 131, not 190 (charge 0.75 + cooldown 1.65 = 2.4 s cycle) | **CORRECT** | F8. The dossier's 190 dps was wrong |
| Zone phase 1 shrink starts at t = 60 | **CORRECT** | config `hold_s: 60` |
| Supply drops land at t = 95 / 165 / 235 | **CORRECT** | `times [70,140,210]` + `fall_s 25` |
| `kite_hp = 0.97` aborts duels mid-kill | **CORRECT as a mechanism** | But lowering it is null (E17) |
| The leader survives 180–300 s via regen + roofs + drops | **NOT SUPPORTED** | A purpose-built survival policy reached 84 s (E18); our own variants top out at 74 s (E16). At t = 146 s only ~1 opponent had died (F4) |
| Multi-life attrition beats damage throughput | **NOT SUPPORTED locally** | E18: +11 s life, −0.92 kills, −0.77 score |

**Verdict: the diagnosis is sharper than ours; the prescription does not survive
measurement.** Its two factual corrections (the invalid control, the laser DPS) are
real and are now in `FINDINGS.md`. Its strategic conclusion is not supported by the
only instrument we have.

### Worth salvaging

1. **Hard fire suppression during recovery.** The single best untested idea in
   either review: 45 HP/s after 5 s clean is a second health bar, and we never
   deliberately take it. It is untestable until the fire gate is fixed (E15).
2. **Rooftops.** We never jump or jet. 259 prisms, 25 % of loot on roofs. Untested.
3. **Weapon-first opening.** Consistent with our own E15 (+0.46 train / +0.10
   holdout).
4. **Verified-arc mortar.** Agrees with our −0.28 result on naive indirect fire
   (E21): the fix is to validate the parabola, not to abandon indirect fire.

---

## What both models got right, independently

- **The opening is the whole game.** Both spend the first 40–75 s acquiring a
  secondary weapon rather than fighting. Our E15 weakly agrees.
- **Damage conversion, not damage output, is the problem.** Gemini spotted it in the
  4,463/0 trace; Claude's gate is an attempt to fix it (too aggressively).
- **We are wasting the laser.** Both wrote a dedicated charge/release controller.
  Ours charges only behind a gate that does not gate.

## What neither resolved

The 5.96 puzzle. Claude assumed survival pacing; Gemini assumed multi-life
attrition. Neither produced a policy that scored above our current build locally.
The remaining untested explanation is **H3**: the real squad is weaker than the
local emulation, so locally-neutral aggression is officially positive (F10). If
that is true, the correct move is to increase aggression and accept a flat local
score — which is exactly the profile of E15.

**Next:** [`STATE.md`](STATE.md) — the resulting plan.
