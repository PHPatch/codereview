# CodeReview

**One agent builds. Independent models review. A deterministic gate decides.**

CodeReview is a review gate for AI-written code. A panel of models from different providers reviews every change, cross-checks each other's findings, and issues a recorded verdict: **PASS, BLOCKED, or INCONCLUSIVE**. The model that wrote the code is never the only one that checked it, and the builder can never approve its own work.

Ships as a CLI and an MCP server, so your coding agents can submit their own work to the gate before it merges. You bring your own API keys and assign models per role; your code goes to the providers you chose, nowhere else. MIT licensed. Python 3.11+, POSIX (Windows and macOS desktop apps in the works).

```
builder ──diff──▶ deterministic checks ──▶ reviewer A (correctness/security)
                      (secrets, injection,        │
                       data-loss, your tests)     ▼
                                            reviewer B (operations/reliability)
                                                  │
                              ┌───── gate ◀───────┘
                              │  PASS / BLOCKED / INCONCLUSIVE
                              ▼
              fix or rebut ──▶ verification round ──▶ PASS only when
                                                         every reviewer agrees
                                                         the block is resolved
```

## Quick start

```bash
pip install codereview-loop        # or: pip install -e . from a clone

export GEMINI_API_KEY=...          # any two providers are a good start
export OPENAI_API_KEY=...

# Review the staged diff in the current repo
codereview --repo . --staged --provider gemini --provider openai

echo $?   # 0 = PASS, 1 = BLOCKED, 2 = INCONCLUSIVE
```

First run? `codereview setup` walks you through picking providers, keys, and a model per role. CodeReview ships **no default panel**: it never quietly substitutes a vendor-chosen lineup.

The report lands in `codereview-out/` as Markdown (for humans) + JSON (for tooling), and every run writes one versioned verdict record you keep.

## Why

- **Self-review is not review.** The model that wrote the code shares its blind spots. Independent providers catch different things.
- **LLM opinions are not a gate.** Findings are structured, merged across reviewers (consensus raises confidence, never lowers severity), and the pass/block decision is made by deterministic rules over those findings.
- **Every claim needs evidence.** A model finding must carry a quote copied verbatim from the diff, validated deterministically. One that cannot be re-grounded goes to a human instead of silently blocking.
- **No silent substitutes.** Failed providers, rotated accounts, fallback seats, degraded runs: all recorded on the report, never hidden.

## What you get

- **Multi-model panel** - 10+ provider presets (OpenAI, Gemini, Anthropic, DeepSeek, MiniMax, Moonshot, NVIDIA, xAI, Mistral, OpenRouter) plus any OpenAI-compatible endpoint, or seat a coding agent itself (Claude Code, Gemini CLI, your own wrapper) as a reviewer.
- **Cross-family confirmation** - a blocker raised by one vendor family is put to a seat from another; a refutation counts only with a validated quote. Unresolved disputes route to the human gate.
- **Evidence runner** - executes your tests, lint, and SAST in a sandbox (throwaway tree, no network by default, your API keys never reach the process) and stores hashed results. A claims mode re-runs the commands a builder's report claims it ran and downgrades the ones the re-run contradicts.
- **The loop driver** - `codereview loop` runs the full cycle: review, hand BLOCKED findings to your builder agent, verify the fix, repeat up to `--max-rounds`, then hand back to a human.
- **GitHub PR review** - read-only review of public PRs with no token; `--post` adds the report as a PR review comment (never auto-approves) and sets a `codereview` commit status.
- **MCP server** - `codereview mcp serve` exposes the gate (`run_gate` / `get_verdict`) so agents submit their own work before merge.
- **Workflows and intake** - multi-step build workflows where each step must PASS and is committed as its approval record; `codereview intake` turns an issue report into a ranked, testable solution plan before any code is written.
- **Release records** - `codereview record-verify` machine-checks whether a record may be called clean: gate PASS, not degraded, tests passed, at least two vendor families, reviewed range unchanged.
- **Disputes and precedents** - an append-only disposition store and content-addressed precedents, so a settled rebuttal stays settled until the judged code changes.
- **SARIF export** - findings where your other tools live: GitHub code scanning and most static-analysis surfaces.
- **Account pools** - when a free quota dies, the next account reviews; every rotation is on the record.

## Benchmark: prove it, don't pitch it

The repo ships a labelled corpus (36 cases, public + holdout splits) and the harness to score any panel:

```bash
codereview bench run --config panel-gemini-nvidia --split public
codereview bench report --public
```

Headline metric is the **escaped-defect rate**: defects the gate would have shipped.

The default `strict` gate is deliberately unforgiving. In registered confirmation testing it caught every seeded defect (recall 1.00, 7 of 7) and blocked 94% of clean changes (32 of 34). That is the trade, stated plainly: strict is a high-recall gate for code you cannot afford to get wrong, with a documented waiver path. A `balanced` profile exists; an opt-in `corroborated` profile failed its registered confirmation and is marked dev-only. Numbers, intervals, and provenance: `bench/README.md`.

## Gate profiles

Set per project in `.codereview.toml` or per run with `--gate-profile`:

- **`strict`** (default) - every blocking-severity finding blocks, whoever raised it.
- **`balanced`** - a blocking finding raised solely by the operations lens is demoted to a visible minor unless corroborated. Demote, never delete.
- **`corroborated`** - opt-in, dev evidence only (failed its registered confirmation).
- **`quiet`** - rejected by testing; naming it is an error.

## Privacy and safety

Keys come from environment variables only; nothing is stored or logged. Known secret shapes in the diff are redacted before anything is sent to a provider. Feedback is opt-in and off by default. The evidence sandbox and its limits are documented in `THREAT-MODEL.md`; exactly what any report sends is in `PRIVACY.md`.

## Docs

- `bench/` - benchmark corpus, harness, and every registered result, including the failures
- `THREAT-MODEL.md` - every control, trust boundary, and residual risk, stated plainly
- `PRIVACY.md` / `SECURITY.md` - what leaves your machine; how to report security problems
- `examples/` - evidence configs, agent-seat wrappers
- [Full command and policy reference](docs/README-full.md) - everything trimmed from the old README, preserved verbatim

## If something goes wrong

1. `codereview --version`, then re-run the failing command.
2. `codereview support-bundle` writes one redacted zip you can attach to an issue.
3. A crash exits **2**, never 0 or 1, and writes a redacted crash note.
4. Security problems: see `SECURITY.md`; do not open a public issue.

## License

MIT
