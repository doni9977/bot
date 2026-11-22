# AGENTS.md — start here

You are picking up a competitive bot project mid-flight. This file is the map.
Read it, then follow the links. Everything you need is in this repository; do not
assume context that is not written down.

**What this is:** a bot for the Builders Buildathon **Mech Royale** track — a
16-mech free-for-all where `score = 16 − place`, averaged over 48 practice
matches. Deadline **2026-11-22 16:00 UTC**. Current official score **2.52**, best
in the world **5.96**, qualification at **5.13**.

**What state it is in:** the bot works, passes the sandbox conformance check, and
has been stuck at ~2.5 for three submissions. The architecture is sound and the
policy is well-measured; what is missing is a mechanism worth **+2.6**, not a
better constant. See [`docs/STATE.md`](docs/STATE.md) for the one-page picture and
[`docs/FINDINGS.md`](docs/FINDINGS.md) for what is actually true about the game.

---

## Read in this order

| # | File | Why |
| --- | --- | --- |
| 1 | [`docs/STATE.md`](docs/STATE.md) | Where we are, what is blocked, what to do next |
| 2 | [`docs/FINDINGS.md`](docs/FINDINGS.md) | Durable truths about the game, each with its evidence |
| 3 | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the code works, file by file, and the decision loop |
| 4 | [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) | Every experiment and its number, so you do not repeat them |
| 5 | [`docs/OPERATIONS.md`](docs/OPERATIONS.md) | How to build, test, and run the local harness |
| 6 | [`docs/DECISIONS.md`](docs/DECISIONS.md) | Why things are the way they are, including reversals |
| 7 | [`docs/EXTERNAL_REVIEWS.md`](docs/EXTERNAL_REVIEWS.md) | Two outside models reviewed this; what survived testing |
| 8 | [`HANDOFF.md`](HANDOFF.md) | Frozen snapshot for external review — self-contained, includes the full protocol and config verbatim |

`AUDIT.md` is the original protocol ledger (uncertainty classes A–E, defect table
D1–D14). It is historical but still the best reference for *what the protocol
guarantees*. Read it when you need a protocol fact, not a strategy.

---

## The rules you must not break

1. **Never submit.** A human submits, at most 2/hour, and wants a slot kept free.
   When a submission is warranted, say so with the commit SHA and the expected
   effect; do not attempt it.
2. **Never claim a win you cannot replicate.** Effects below ~0.5 score are
   unresolvable. See the measurement protocol in
   [`docs/OPERATIONS.md`](docs/OPERATIONS.md#measurement-protocol). We have
   already published one false positive and had to retract it.
3. **Headless only.** No desktop control, no simulated input, no browser profile
   or cookie access.
4. **Read numbers from `hello.config`.** Never hard-code a rule value. Balance
   patches arrive as config.
5. **Atomic commits.** One experiment per commit, message states what changed,
   what was expected, what was measured.
6. **A crash is not a disqualification, it is a 0-point match.** Wrap decision
   code defensively.

---

## The 60-second version of what we know

- `score = 16 − place = the number of mechs that died before you`. Verified
  exactly: mean score 2.00 = 1.31 kills + 0.69 environmental deaths.
- The 15 house bots are **one squad**: shared vision, no infighting, escalating
  hunter count ("one early, more as you thin them out, all of them late").
- Therefore every point above the environmental floor must be **earned by
  killing**, and the squad's escalation means kills are cheapest early.
- Our bot dies at ~70 s. A careful, gate-driven policy from an external reviewer
  survived 84 s but killed 4× less and scored −0.77. **Survival bought with
  aggression is a losing trade.**
- **Local Δ transfers 1:1 to the official board, but the offset is a property of
  the policy, not a constant** (F17). Hunt mode added ~+0.6 of offset while moving
  the local score by zero.
- Two hypotheses are dead: a laser does **not** unlock kills (it is DPS-neutral),
  and survival does **not** unlock score (a true pacifist scores 0.38).
- The open one is the **duty cycle**: a shootable target exists in only 21 % of
  decisions and 44 % are terrain-blocked. Damage is limited by target availability,
  which is a positioning problem nothing has attacked directly.

---

## If you have one hour

Read `docs/STATE.md` §"Next actions", pick the top item, run it with the harness in
`docs/OPERATIONS.md`, and write the result into `docs/EXPERIMENTS.md` before you
commit. That loop — read, test, record, commit — is the whole job.
