# DECISIONS — what we chose, and what we reversed

> Living document. Last updated **2026-11-21 22:50 UTC**.
> One entry per decision that a future agent might otherwise re-litigate. Format:
> context → decision → consequence. Reversals are marked and kept, because the
> reversal is usually the most informative part.

---

## D-01 — Placement is the metric, so build survival-first `[reversed]`

**Context.** The track page says "placement counts, not kills: dying first with
five kills scores worse than surviving to the end with none." We read that as
"survival is the objective".

**Decision.** Built a survival-first policy: stay in the zone, avoid being found,
quiet movement, kite the squad, take only free fights.

**Consequence.** Official 0.25 → 1.83 → 2.44. It worked, then plateaued.

**Reversed by D-07.** The quote is about *ordering*, not about the mechanism. Since
`score = deaths before you` (F1), surviving longer only helps if it produces more
deaths — ours or the environment's. It mostly does not (F4).

---

## D-02 — One torso aim for both weapon slots

**Context.** The protocol gives one torso and two triggers. Our first build let each
weapon branch command its own aim; slot 1 could fire while the torso still pointed
where slot 0 wanted.

**Decision.** A single arbiter picks the highest-utility candidate as the final aim,
then fires a second slot only if its shot still lands given that aim.

**Consequence.** **+0.54 ± 0.28** (E4). Removing it drops shots 66 → 19 and kills
1.12 → 0.08. Non-negotiable.

---

## D-03 — Trust `obs.mechs` positions; do not dead-reckon `[reversal of our own bug]`

**Context.** We added `vel × age` to enemy positions to "correct" for staleness.

**Decision.** Removed it. The protocol guarantees the *real current position* for
`memory_s` (5 s) after a mech leaves view.

**Consequence.** Our correction was double-counting. Neutral in score (E3) but the
threat geometry was wrong, and every cover/kite decision inherited the error.

---

## D-04 — Prefer the local simulator over intuition, but distrust its absolute score

**Context.** The local harness is derived from a public simulator with a house-squad
emulator. Its config is byte-identical to the official one.

**Decision.** Use it as the primary A/B instrument, but judge on **paired deltas**,
never absolute score, and treat kills/death-time as the secondary signal.

**Consequence.** Absolute calibration is good (local ~1.9 vs official 1.83) but the
score signal is compressed (ceiling ≈ 2.0, house bots survive 87 %). We have
therefore accepted a local regression of ~0.2 in exchange for +kills, and rejected
a −0.7.

---

## D-05 — Kill the parameter-tuning approach

**Context.** A 14-dimension sweep with cached baselines, 3 training ranges and a
holdout found no config that was reliably better (E12).

**Decision.** Stop tuning. The remaining gains are structural.

**Consequence.** Every subsequent experiment changes *mechanism*, not constants. If
you find yourself sweeping knobs again, re-read E12 first.

---

## D-06 — Keep `hunt` on despite neutral local results

**Context.** Hunt mode measured neutral locally and **+0.61 officially** (E7).

**Decision.** Keep it, and treat local neutrality as weak evidence rather than
evidence against, for aggression-flavoured changes.

**Consequence.** This is the single calibration anchor we have (F10). It is why
`7468dcb` was submitted at all.

---

## D-07 — Reversal: kills are the objective, survival is the constraint `[supersedes D-01]`

**Context.** Score decomposes exactly into `kills + environmental deaths` (F3), and
environmental attrition is slow early (F4). Fighting costs almost nothing in
survival terms (F5).

**Decision.** Re-aim the policy at kill rate. Survival is a constraint, not a goal.

**Consequence.** This is the current thesis. It is *partially* qualified by D-09.

---

## D-08 — Do not adopt the external `warden` policy

**Context.** Claude produced a 778-line replacement policy built around a predictive
engagement gate, heal cycles and drop contests. It is well-engineered, reads config
properly, and is crash-safe.

**Decision.** Rejected as a replacement. Measured **−0.77** on train and **−0.65** on
holdout (E18): it survives +11 s and kills 4× less.

**Consequence.** The exchange rate is the finding: +13 s of life ≈ +0.2 score; −1
kill ≈ −1.0 score. Salvage individual mechanisms (ratio gate, laser controller,
mortar cluster solver) but never the survival-first posture.

---

## D-09 — Survival bought with aggression is a losing trade `[qualifies D-07]`

**Context.** Two independent attempts at a survival-first policy (ours, and
warden's) both scored worse.

**Decision.** Never accept a change that reduces kills without a large survival
gain. Concretely: reject if Δkills < 0 unless Δdeath ≥ +60 s.

**Consequence.** Narrows D-07 correctly: we are not "ignore survival", we are
"never pay kills for survival".

---

## D-10 — Keep `HANDOFF.md` frozen

**Context.** `HANDOFF.md` is a self-contained snapshot written for external review;
it embeds the full protocol and live config verbatim.

**Decision.** Do not keep editing it as the project evolves. `docs/` is the living
system; `HANDOFF.md` is a dated artefact.

**Consequence.** Numbers in it may drift from `docs/`. If they conflict, `docs/`
wins.

---

## D-11 — The docs are the source of truth, not the commit messages

**Context.** Commit messages accumulated a lot of analysis that was hard to traverse.

**Decision.** Every finding, experiment and decision lives in `docs/`, cross-linked
by ID. Commit messages point at the doc entry they change.

**Consequence.** A new agent can reconstruct the entire reasoning from the repo
without reading git history.

---

## D-12 — Reversal: the local instrument was never broken `[supersedes the "exhausted" note in STATE]`

**Context.** Round 2 produced a run of local nulls and I concluded that local A/B
could no longer rank candidates.

**Decision.** Wrong. Two official results showed that **within an architecture,
local Δ transfers 1:1** (roam predicted +0.02, delivered −0.02). The local nulls
were real nulls, not instrument failure. What is *not* constant is the local→official
**offset**, which is a property of the policy's aggression class and moved by ~+0.6
when hunt was added.

**Consequence.** Local remains the candidate generator and the free instrument; the
official board is the fine one (±0.05 vs ±0.5). Judge a candidate by its local
delta, but never assume the offset is fixed across architectures.

---

## D-13 — Revert the weapon roam, keep the knob

**Context.** `a33d613` (early weapon roam) scored **2.50** officially against
**2.52** for the build without it.

**Decision.** Revert `roam_until` to 0.0 and `weapon_seek_range` to 130, so HEAD is
behaviourally identical to the best-known build. Keep both knobs and the
measurement, because the mechanism (8 % → 35 % weapon uptime) is real and a future
policy may convert it.

**Consequence.** HEAD = the 2.52 build. Nothing in the tree is a regression. The
platform locks the best score at cutoff, so 2.52 is safe regardless.

---

## D-14 — Reversal: dual-wielding laser + snowball economy overturns F8 `[supersedes F8 "H1 is dead"]`

**Context.** E38/E39 measured the laser as ~DPS-neutral with the gun because the old
arbiter released at 45 % charge, lacked gun+secondary dual-wielding, dumped charges on
LOS flicker, and compared laser DPS (131) against gun peak burst (187) rather than gun
sustained DPS with reload (107).

**Decision.** Adopt `snowball_v1` + `snowball_v2` + `snowball_v3` with
`weapon_pref = ["laser", "lightning", "mortar", "gun"]` (E43, E45, E46b): full/lethal
dual-wielding laser + shared-pitch lightning + ballistic-fixed mortar + active cube/drone/
crate/kill-loot snowballing + fixed upgrade valuation + pure laser-duck + 1v1 corner
angle isolation.

**Consequence.** Combined 96-match local score jumped from **1.82 → 2.67 (+0.84 ± 0.28,
3.0σ)** with identical deltas on train (+0.83) and untouched holdout (+0.85), kills
**1.24 → 2.10 (+69 %)**, dealt **2,728 → 4,103 (+50 %)**, and trade ratio **1.57× → 2.07×**.

**Next:** [`EXTERNAL_REVIEWS.md`](EXTERNAL_REVIEWS.md) — what outside models said.
