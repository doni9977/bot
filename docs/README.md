# docs/ — the repo's memory

> Living documentation. Last updated **2026-11-21 22:50 UTC**.
> If you change behaviour, update the doc that describes it in the same commit.

This directory is the single source of truth for *why* the code looks the way it
does. Code tells you what happens; these files tell you what we believe, what we
measured, and what we already ruled out.

## The files

| File | Answers | Update when |
| --- | --- | --- |
| [`STATE.md`](STATE.md) | Where are we right now? What is next? | Every work session |
| [`FINDINGS.md`](FINDINGS.md) | What is true about this game, and how do we know? | A measurement changes a belief |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | How does the bot work? | Code structure changes |
| [`EXPERIMENTS.md`](EXPERIMENTS.md) | What have we tried, and what happened? | Every experiment, win or lose |
| [`OPERATIONS.md`](OPERATIONS.md) | How do I build, test, and measure? | Tooling changes |
| [`DECISIONS.md`](DECISIONS.md) | Why is it like this? What did we reverse? | A decision is made or overturned |
| [`EXTERNAL_REVIEWS.md`](EXTERNAL_REVIEWS.md) | What did outside models say, and did it hold? | A review is received or tested |

## Conventions

- **Every claim carries its evidence.** `(E12)` refers to experiment 12 in
  `EXPERIMENTS.md`. `(F3)` refers to finding 3 in `FINDINGS.md`. A claim with no
  marker is either a protocol fact (cite the section) or an explicit guess.
- **Confidence is stated, not implied.** Findings are tagged `[fact]`,
  `[measured]`, `[inferred]`, or `[hypothesis]`. Do not promote a hypothesis to a
  measured fact without an experiment ID.
- **Negative results are first-class.** Half of `EXPERIMENTS.md` is things that
  did not work. That is the most valuable content here — it is the only thing
  stopping the next agent from re-running our dead ends.
- **Superseded text is deleted, not appended.** If a finding is overturned, rewrite
  it and add a line to `DECISIONS.md` explaining the reversal. Do not leave two
  contradictory paragraphs.

## Traversal

```
AGENTS.md ──► docs/STATE.md ──► docs/FINDINGS.md ──► docs/ARCHITECTURE.md
                    │                  │                    │
                    ▼                  ▼                    ▼
             docs/EXPERIMENTS.md ◄──────┴──────────► docs/OPERATIONS.md
                    │                                       │
                    ▼                                       ▼
             docs/DECISIONS.md ◄──────────────── docs/EXTERNAL_REVIEWS.md
```

Each document ends with a **Next** line pointing at the most useful follow-up, so
you can walk the graph without coming back here.

## Related, outside this directory

| Path | What it is |
| --- | --- |
| `AGENTS.md` | Entry point and non-negotiable rules |
| `HANDOFF.md` | Frozen, self-contained snapshot for external review (includes the full protocol and live config verbatim) |
| `AUDIT.md` | Original protocol ledger: uncertainty classes, defect table D1–D14 |
| `README.md` | Public-facing: layout, attribution, build commands |

**Next:** [`STATE.md`](STATE.md) — the current picture.
