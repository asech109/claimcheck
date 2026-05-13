# claimcheck

> Paper-code consistency verifier for LaTeX manuscripts. Every reported number carries a `file:line` anchor — nothing is asserted without provenance.

`claimcheck` scans a `.tex` file for four kinds of claims — numeric results,
hyperparameters, integer counts, and natural-language method descriptions —
then re-derives each value from your code, configs, or experiment logs and
produces a three-column report: `claim` / `source-of-truth` / `status`.

When a mismatch is found it proposes both a paper edit and a code edit
(unified-diff style) so you choose which side to align. A git pre-commit
hook blocks `.tex` commits that introduce unresolved claims unless they are
waived in `claims_waived.yaml` (with TTL).

## Why

Numbers drift. A learning rate changes in `config.yaml` but the paper still
says `3e-4`. An accuracy is re-run after a bug fix but only the abstract
gets updated. Manual cross-checking does not scale past one experiment.

`claimcheck` does the cross-check mechanically and refuses to assert any
value without an explicit source anchor.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/<your-account>/claimcheck.git
cd claimcheck
pip install -e .
```

## Quick start

```bash
claimcheck scan path/to/paper.tex \
  --code-root path/to/repo \
  --logs path/to/experiment-logs \
  --report report.md
```

Exit code is `0` when every claim matches or is actively waived, `1`
otherwise.

### Example output

```markdown
| Claim | Source-of-Truth | Status |
|---|---|---|
| `3 \times 10^{-4}` (paper.tex:9) — learning_rate | `0.0001` (configs/train.yaml:4) | ❌ mismatch |
| `87.3\%` (paper.tex:12) — accuracy | `0.873` (logs/metrics.json:4) | ✅ match |
| `127` (paper.tex:5) — transitions | — | ⚠️ unverifiable |
| Method section (paper.tex:7) | PPO confirmed, GAE missing in code | ❌ method-drift |
```

For every mismatch a `Proposed fixes` section lists both options:

```diff
# claim b426c3559875 (hyperparam/learning_rate)
# Option A — edit paper at paper.tex:9
- 3 \times 10^{-4}
+ 0.0001
# Option B — edit code at configs/train.yaml:4
- 0.0001
+ 3 \times 10^{-4}
```

## Claim types

| Type | What it captures | Source of truth |
|---|---|---|
| `numeric` | accuracy, loss, F1, AUC, reward, perplexity, … | `*.json` / `*.jsonl` / `*.csv` / `*.tsv` under `--logs` |
| `hyperparam` | learning rate, batch size, dropout, epochs, … | `*.yaml` / `*.yml` / `*.json` / `*.py` under `--code-root` |
| `count` | transitions, episodes, samples, parameters, tokens, … | logs (same as numeric) |
| `method` | algorithm names + architecture descriptors in NL method sections | tokens parsed from `*.py` / `*.ipynb` / `*.ts` / … under `--code-root` |

Method claims are structurally compared, not paraphrased. The extractor
recognises a fixed vocabulary of algorithms (PPO, DQN, SAC, transformer,
LoRA, AdamW, …) plus architecture descriptors like `3-layer MLP`. Anything
outside that vocabulary is ignored rather than guessed at.

## Strict grounding

`claimcheck` will never print a source-of-truth value without an
accompanying `file:line` anchor. If a claim cannot be resolved its status is
`unverifiable` — and the report tells you which log or config was missing
and how to re-run the relevant experiment. The tool does not invent
numbers, paraphrase methodology, or "round to a plausible value".

## Pre-commit hook

```bash
claimcheck install-hook path/to/your/paper-repo
```

The installed hook runs in **lenient mode**: only claims whose `.tex`
anchor lands inside a staged hunk — plus any claim whose fingerprint has
drifted from the lock snapshot — are re-verified on each commit. Typo
fixes and prose edits do not trigger experiment lookups.

If a commit cannot pass, the hook writes a full report to
`.paper-verify/last-report.md` and prints the relevant `claim_id` values
plus the `claimcheck waive` command needed to bypass.

```bash
claimcheck waive b426c3559875 --reason "log will land after run finishes" --repo .
```

Waivers default to 30-day TTL and are stored in
`.paper-verify/claims_waived.yaml`. Expired waivers are ignored
automatically, so the dashboard cannot rot silently.

## Configuration overrides for the hook

```bash
# In the hosting repo
export PAPER_VERIFY_CODE_ROOT=/path/to/code   # default: repo root
export PAPER_VERIFY_LOG_ROOT=/path/to/logs    # default: repo root
git commit -m "update results"
```

To temporarily bypass the hook for an unrelated commit:

```bash
git commit --no-verify -m "fix typo in bibliography"
```

## Commands

| Command | Purpose |
|---|---|
| `claimcheck scan TEX [...]` | One-off verification and report generation |
| `claimcheck install-hook REPO` | Install a `pre-commit` hook in a git repository |
| `claimcheck waive ID --reason "..."` | Add a TTL-bounded waiver for one claim |
| `claimcheck hook --repo R --code-root C --logs L` | Internal entrypoint used by the installed hook |

## Tolerance and units

- Numeric comparisons use a 1% relative tolerance by default.
- Percent / fraction reconciliation is applied only when the paper number
  is plausibly a percentage (`1 < x ≤ 100`) and the log value plausibly a
  fraction (`0 ≤ y ≤ 1`). This prevents spurious matches between small
  hyperparameters like `3e-4` and `1e-4`.
- LaTeX scientific notation (`3 \times 10^{-4}`), inline math (`$0.873$`),
  and escaped percent (`87.3\%`) are normalised before comparison.

## Limitations

- The method extractor recognises a fixed vocabulary; novel algorithm names
  not on the list are silently ignored (status: `unverifiable` rather than a
  false positive). PRs adding tokens are welcome.
- Heuristic key matching for logs uses a small alias table
  (`accuracy ↔ acc ↔ eval_accuracy`). If your metric is logged under an
  unconventional key, add it to `paper_verify/resolvers/log_resolver.py::_LABEL_ALIASES`
  or open an issue.
- No web requests, no LLM calls. Future versions may add an opt-in
  `--use-llm` flag for richer method-section parsing.

## Development

```bash
pip install -e ".[dev]"
pytest                              # 15 tests, runs in <1s
```

```
paper_verify/
├── extractors/        # .tex parsing, method-description structuring
├── resolvers/         # source-of-truth lookups (logs, configs, code)
├── verifier.py        # orchestrates extraction → resolution → status
├── reporter.py        # markdown rendering
├── diff_proposer.py   # paper-edit vs code-edit suggestions
├── waivers.py         # claims_waived.yaml with TTL
├── hook.py            # git pre-commit (lenient mode)
└── cli.py             # argparse entry point
```

## License

MIT — see [LICENSE](LICENSE).
