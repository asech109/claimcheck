# claimcheck

> Catch the moment your LaTeX paper and your code stop agreeing.
> Every reported number carries a `file:line` anchor — nothing is asserted without provenance.

## 30-second look

Your paper says:

```latex
We train with a learning rate of $3 \times 10^{-4}$ on $127$ transitions,
reaching an accuracy of $87.3\%$.
```

You run:

```
$ claimcheck scan paper.tex --code-root . --logs runs/
report written: paper-verify-report.md
```

You get back:

```markdown
| Claim | Source-of-Truth | Status |
|---|---|---|
| `3 \times 10^{-4}` (paper.tex:9) — learning_rate | `0.0001` (configs/train.yaml:4) | ❌ mismatch |
| `127` (paper.tex:5) — transitions | `127` (runs/2025-05-12/metrics.json:11) | ✅ match |
| `87.3\%` (paper.tex:12) — accuracy | `0.873` (runs/2025-05-12/metrics.json:4) | ✅ match |
| Method section (paper.tex:7) | PPO confirmed, GAE missing in code | ❌ method-drift |
```

And a paste-ready patch for each mismatch:

```diff
# Option A — edit paper at paper.tex:9
- 3 \times 10^{-4}
+ 0.0001
# Option B — edit code at configs/train.yaml:4
- 0.0001
+ 0.0003
```

Exit code is `0` if everything matches, `1` if there is drift — drop it
into CI or use the installed pre-commit hook to block silent drift.

## Why

Numbers drift. A learning rate changes in `config.yaml` but the paper
still says `3e-4`. An accuracy is re-run after a bug fix and only the
abstract gets updated. A reviewer asks for an extra ablation and the
table cell quietly gets edited by hand. Manual cross-checking does not
scale past one experiment.

`claimcheck` does the cross-check mechanically and refuses to assert
any value without an explicit source anchor. When a number cannot be
resolved, the report says `unverifiable` and tells you which log or
config was missing — never a fabricated "looks about right".

## What this is NOT

- **Not a fact-checker.** It does not call an LLM, does not search the
  web, does not validate claims against external literature.
- **Not a plagiarism detector** and not a peer-review substitute.
- **Not a runtime instrumenter.** It does not execute your training
  script. If a hyperparameter is set by `argparse --lr 1e-3` at run
  time, the config file still says whatever it says.
- **Not a fix-it tool.** Mismatch reports include unified-diff
  *suggestions* on both sides. Applying them is on you.
- **Not opinionated about your stack.** No required project layout,
  no required logging schema, no plugins. Point `--code-root` and
  `--logs` at any directories and the tool walks them.

## Install

Requires Python 3.11+.

```bash
git clone https://github.com/asech109/claimcheck.git
cd claimcheck
pip install -e .
```

## Commands

| Command | What it does |
|---|---|
| `claimcheck scan TEX --code-root C --logs L --report R` | Full verification with a markdown report. Exit 1 if drift, 0 otherwise. |
| `claimcheck status TEX --code-root C --logs L` | One-line summary, no file output. CI-friendly. |
| `claimcheck install-hook REPO [--prime]` | Install a `pre-commit` hook. `--prime` records current matches so existing baseline does not block. |
| `claimcheck waive ID --reason "..."` | Add a TTL-bounded waiver (default 30 days). |
| `claimcheck waive --list` | Show active and recently-expired waivers. |

## Claim types

| Type | What it captures | Source of truth |
|---|---|---|
| `numeric` | accuracy, loss, F1, AUC, reward, perplexity, … | `*.json` / `*.jsonl` / `*.csv` / `*.tsv` under `--logs` |
| `hyperparam` | learning rate, batch size, dropout, epochs, … | `*.yaml` / `*.yml` / `*.json` / `*.py` under `--code-root` |
| `count` | transitions, episodes, samples, parameters, tokens, … | logs (same as numeric) |
| `method` | algorithm names + architecture descriptors in NL method sections | tokens parsed from `*.py` / `*.ipynb` / `*.ts` / … under `--code-root` |

Counts use **exact equality** — "127 vs 128" is always a mismatch, never
rounded away. Numeric metrics use a relative tolerance (default 1%,
configurable with `--rel-tol`). Method claims are structurally compared
against a fixed algorithm vocabulary (PPO, DQN, SAC, transformer, LoRA,
AdamW, …); unknown tokens are ignored rather than guessed at.

## Strict grounding

`claimcheck` will never print a source-of-truth value without a
`file:line` anchor. Citations (`\cite{}`, `\ref{}`, `\label{}`) are
stripped before number extraction so digits inside reference lists never
become claims. Python docstrings and comments are stripped before
algorithm-token scanning so a sentence like *"no GAE here"* in a
docstring cannot pretend GAE is implemented.

## Multi-file papers

```bash
claimcheck scan main.tex --code-root . --logs runs/
```

`\input{sections/method}` and `\include{sections/experiments}` are
followed by default. Every claim's anchor points at the real sub-file
that contains the line — so the diff suggestions and the pre-commit
hook always touch the file you actually need to edit. Disable with
`--no-follow-includes` if you want to scan only the top-level file.

## Pre-commit hook

```bash
claimcheck install-hook path/to/paper-repo --prime
```

The hook runs in **lenient mode**: only claims whose `.tex` anchor lands
inside a staged hunk — plus any claim whose fingerprint drifted from
the lock snapshot — are re-verified. Typo fixes and prose edits do not
trigger experiment lookups.

When a commit cannot pass:

```
$ git commit -m "update results"

paper-verify: 2 unresolved claim(s). Report: .paper-verify/last-report.md
Fix the code/paper, or waive with:
  claimcheck waive <claim_id> --reason '...'
```

Waivers live in `.paper-verify/claims_waived.yaml`, default 30-day TTL,
expire automatically. Use `claimcheck waive --list` to audit them.

To temporarily bypass the hook for an unrelated commit:

```bash
git commit --no-verify -m "fix typo in bibliography"
```

## Tolerance and units

- Numeric comparisons use 1% relative tolerance by default; override
  with `--rel-tol`.
- Counts are always exact.
- Percent / fraction reconciliation is applied only when the paper
  number plausibly looks like a percentage (`1 < x ≤ 100`) and the log
  value plausibly a fraction (`0 ≤ y ≤ 1`). This prevents spurious
  matches between small hyperparameters like `3e-4` vs `1e-4`.
- LaTeX scientific notation (`3 \times 10^{-4}`), inline math
  (`$0.873$`), and escaped percent (`87.3\%`) are normalised before
  comparison.

## Limitations

- Hyperparameters set at runtime via CLI flags or environment overrides
  are invisible — `claimcheck` reads the config file as written.
- The method extractor recognises a fixed algorithm vocabulary. PRs
  adding tokens are welcome.
- Log key matching uses an alias table
  (`accuracy ↔ acc ↔ eval_accuracy`). Unconventional metric names need
  an entry added to `paper_verify/resolvers/log_resolver.py`.
- Multiple log files for the same metric: newest by `mtime` wins; older
  conflicting files surface as warnings in the report.

## Development

```bash
pip install -e ".[dev]"
pytest                              # 30+ tests, runs in ~1s
```

```
paper_verify/
├── extractors/        # .tex parsing, method-description structuring
├── resolvers/         # source-of-truth lookups (logs, configs, code)
├── verifier.py        # orchestrates extraction → resolution → status
├── reporter.py        # markdown rendering
├── diff_proposer.py   # paper-edit vs code-edit suggestions, format-aware
├── waivers.py         # claims_waived.yaml with TTL
├── hook.py            # git pre-commit (lenient mode + lock prime)
└── cli.py             # argparse entry point
```

## License

MIT — see [LICENSE](LICENSE).
