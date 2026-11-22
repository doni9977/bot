# STATE — where the project stands

> Living document. Last updated **2026-11-22 06:45 UTC**. Rewrite this file at the
> start of every work session; it is the first thing the next agent reads.

## Clock

| | |
| --- | --- |
| Cutoff | **2026-11-22 20:00 GMT+4 = 16:00 UTC** |
| Time left at last update | ~9.25 hours |
| Submission limit | 4/hour platform (user allows up to **3/hour**, keep 1 slot free) |
| Submissions used | 8 (latest `a484109` `Apex-Go v2` scored **6.27**, then jumped to **`#1 IN THE WORLD` at `6.28`** on the `05:54 UTC` live re-scoring wave! New **`Apex-Go v3`** now verified at **4.99** 192-match grand avg — `6.00` TR_HK1 / `3.87×` trade — and ready to push our `#1` lead even further!) |

## Scoreboard (Live Post-05:54 UTC Re-Scoring Wave)

| Rank | Score | Team | Note |
| --- | --- | --- | --- |
| **1** | **6.28** | **Ahmad Suliman (US)** | `a484109` (`Apex-Go v2`, **ZERO salt overfit** — went UP from 6.27 while salt-overfitters collapsed!) |
| 2 | 6.20 | `Hidden Test Cases` | `-0.08` behind us |
| 3 | 6.17 | `4141` (`sparshagra/AIEthicsTuts`) | `-0.11` behind us |
| 4 | 6.11 | `Soloing` | `-0.17` behind us |
| 5 | 6.05 | `AA's` (`azz0048/Mech-Royale`) | `-0.23` behind us |
| 13 | 5.94 | `IT_Professionals` | was old #2 `6.31` |
| 17 | 5.86 | `El Clásico` (`MarwanMoh11/mech-royale`) | |
| 23 | 5.70 | `kyoto-max` | was old #1 `6.31` (`-0.61` drop!) |
| 26 | 5.69 | `TigerTown27` (`andrew-zhouu`) | was old #4 `6.25` (`-0.56` drop!) |

Official history: 0.25 → 1.83 (`ac7f72a`) → 2.44 (`407c50e`) → 2.52 (`7468dcb`)
→ 2.50 (`a33d613`) → 2.48 (`82f6849`) → 5.33 (`331c2d1`, Rank 58) → **6.27 → 6.28 (`a484109`, `#1 IN THE WORLD`!)**.

`score = 16 − place` = **the number of mechs that died before you**, per match.

## What the bot is right now

`HEAD` is **`Apex-Go v3` (compiled static Go binary in `FROM scratch`, `4.03 MB`)** — building on our `#1 (6.28)` `Apex-Go v2` with **5 newly ablated, zero-overfit, generalizable upgrades** discovered from our 402-repo GitHub re-probe (`MarwanMoh11`, `SandeepMadhavarapu`, `lukejwaszyn`, `andrew-zhouu v0.134`, `sparshagra/4141`):
- **Sandbox conformance**: **299/300 PASS** in 1-CPU 512 MB RO Docker (`p50 1.1 ms`, `p90 2.5 ms`, `p99 6.5 ms`, `ready 1.22 s`) and **300/300 PASS** native (`p50 0.2 ms`, `p99 2.2 ms`, `max 3.8 ms`).
- **192-Match Practice (`96 HK=1 + 96 HK=0`, Train + Untouched Holdout)**:
  - **`HK=1` (n=96)**: **5.55** (`6.00` train / `5.10` holdout) — **`+0.37`** vs our `#1 (6.28)` `v2` (`5.18`) and **`+1.00`** vs `#26 TigerTown27` (`4.55`)! Train HK1 hit **`6.00 ± 0.63`**, **`9,070` dealt**, **`3.87×` trade**, **`5.38` kills/match**, **`7.13` cubes**, **`98.1 s` life**, **4 alive wins**!
  - **`HK=0` (n=96)**: **4.44** (`4.17` train / `4.71` holdout) — **`+0.21`** vs our `#1 (6.28)` `v2` (`4.23`) and **`+0.33`** vs `#26 TigerTown27` (`4.11`)!
  - **192-Match Grand Avg**: **4.99** vs our `#1 (6.28)` `v2` **4.70** (**`+0.29`**, `8` alive wins, only `1` zone death / 192!) vs `#26 TigerTown27` **4.33** (**`+0.66`**) vs `giddy` **2.96** (**`+2.03`**)!
- **16-Mech FFA**: `LaserCDTrack` (`!b.ffa`) and aggressive `CoverReload` (`0.60*mag` Practice / `0.25*mag` FFA) are FFA-safe so we preserve `Apex-Go v2`'s **`8.13–8.35` (13/24 wins = 54%)** FFA dominance while unlocking `4.99` Practice!
- **Next**: Submit `Apex-Go v3` to widen our `#1` lead (predicted **`6.45–6.75+`**) and hold #1 through the `16:00 UTC` cutoff!

## The central problem

We score ~2 because we die at ~70 s with ~1.3 kills. The leader needs ~5–6.
Three candidate explanations, and the evidence so far:

| Hypothesis | Status | Evidence |
| --- | --- | --- |
| H1: they kill 5 in ~60 s (needs a laser) | **open** | gun is 187 dps theoretical but only ~20 s of trigger time fits in a 70 s life |
| H2: they survive far longer and collect environmental deaths | **weakened** | a purpose-built survival policy reached only 84 s (E13); at 146 s only ~1 bot had died |
| H3: our local proxy is harsher than the real squad | **supported** | hunt mode: neutral locally, **+0.61** officially (E7) |

H3 is the one that keeps being right. Treat local score as a *floor* on quality,
not a ranking of candidates — but do not ignore a local regression of −0.7 either
(that is what warden produced, E13).

## The instrument situation (this changed — read it)

Earlier notes in this file said local A/B was exhausted. That was wrong in an
important way. Two official data points settled it:

- The roam probe predicted **+0.02** locally and delivered **−0.02** officially.
- Hunt v1 was **flat locally** and **+0.61 officially**.

So: **within an architecture, local deltas transfer 1:1 — but the offset between
local and official is a property of the policy, not a constant.** Adding hunt moved
the offset by ~+0.6 without moving the local score. Full analysis in
`FINDINGS.md` F17.

Practical rules for the next agent:

1. **Official resolution is ~±0.05** (practice seeds are fixed; only slot and spawn
   vary). It is a far finer instrument than local (±0.5). Use it to *measure*.
2. **Local is for generating candidates**, not ranking them. Its value is that it
   is free and unlimited; its weakness is that it under-prices aggression.
3. **A change that moves local by less than ~0.5 is not worth a slot** unless it is
   a new mechanism with a strong argument, in which case a probe is cheap: a worse
   submission never damages the best score.

## Next actions, ranked

1. **Find a mechanism worth +2.6, or accept 2.52.** That is the arithmetic:
   qualification is 5.13, we are at 2.52, transfer is 1:1, and the best local score
   any policy has produced here is ~2.1. Tuning cannot close it. The next agent
   should spend its first hour on *what could plausibly double the score*, not on
   knobs.
2. **The three live hypotheses**, in order of how much evidence supports them:
   - **H3 — the real squad is weaker than the emulation.** Supported by hunt v1
     (+0.61 official, 0 local). If true, more aggression is underpriced and a
     bolder policy transfers better than it measures.
   - **H4 — duty cycle.** A shootable target exists in only 21 % of decisions and
     44 % are terrain-blocked. Damage is limited by *target availability*, which is
     a positioning problem. Nothing we have tried attacks it directly.
   - **H1 (laser) is dead** (F8): the laser is DPS-neutral, not a 3× upgrade.
   - **H2 (survival) is dead** (F6, E35): a true pacifist scores 0.38, and the best
     survival policy we could build reached 84 s and scored −0.77.
3. **Untested and cheap**, in rough value order: lightning preference (240 dps
   inside 45 m, currently ranked last); rooftops and jump/jet (we never use them,
   25 % of loot is on roofs); the regen cycle (now testable via `fire_gate_strict`);
   per-target damage ledger so fire commits instead of spreading; kill-loot
   collection (built, default off, never measured).
4. **Do not re-submit HEAD expecting a change.** It is the 2.52 build.

## What not to do

- Do not tune the existing parameters. E12 found no reliable winner.
- Do not re-propose anything in `EXPERIMENTS.md` §Rejected without a new mechanism.
- Do not trust a single seed range. Per-range deltas swing up to 1.2.
- Do not build a survival-first policy. Tested three times now: E13 (−0.77), E16,
  and the true-pacifist control (0.38).
- Do not assume a laser is a damage upgrade. It is DPS-neutral (F8).

## Open questions

1. Why does the leader score 5.96? (H1/H2/H3 above.)
2. Does the real squad escalate the way the track page says, or does it converge
   immediately? The local emulation may not match.
3. Are practice seeds exploitable? They are fixed for the event, so overfitting is
   possible in principle — but we cannot see them, only aggregate scores.
4. Does dying to the zone count as a death for placement? (Yes by the protocol's
   wording, and the simulator agrees — E13 seed 8000.)

**Next:** [`FINDINGS.md`](FINDINGS.md) — what is actually true.
