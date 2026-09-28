# reconcile-py

**Deterministic, explainable fuzzy reconciliation of financial record sets.**

`reconcile-py` matches one set of records against another — bank transactions against invoices or ledger entries, and any similar two-sided problem — under tolerance rules you configure. Every run is **deterministic** (same input + config → identical output), every match is **explainable** (it records why it matched), and genuinely uncertain matches are **flagged for review** instead of guessed. The engine is a generic pairwise matcher: it has no hardcoded bank/invoice/ledger types — you supply your own records.

> Status: `0.1.0`, pre-release. Not yet published to PyPI (install from source — see [Installation](#installation)).

## Key Features

- **Configurable tolerance** — exact, absolute, or percentage amount tolerance; a ± day date window; fuzzy text matching on references and counterparties.
- **Gates and grades** — amount/date are hard *gates* (a pair outside tolerance can never match); reference/counterparty are *graded* (0..1 similarity that feeds a score).
- **1:1 and split (1:many) matches** — batch settlements (one payment → many invoices) and installments (one invoice → many payments), searched in both directions.
- **Deterministic & replayable** — no wall-clock, no randomness; stable ordering by record id then input position.
- **Explainable** — every match carries the gates it passed and each field's similarity.
- **Ambiguity surfacing** — near-tie matches are flagged, not silently resolved.
- **Pluggable scorer** — zero-dependency `difflib` default; drop in your own (e.g. `rapidfuzz`) via config.
- **Typed, pure, zero-core-dependencies** — ships `py.typed`; the engine imports nothing outside the standard library. pandas is an optional adapter.

## Table of Contents

- [How It Works](#how-it-works)
- [Tech Stack](#tech-stack)
- [Requirements](#requirements)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Usage Guide](#usage-guide)
  - [Building a config](#building-a-config)
  - [Criteria fields](#criteria-fields)
  - [Graded matching and the threshold](#graded-matching-and-the-threshold)
  - [Split (1:many) matches](#split-1many-matches)
  - [Ambiguous matches](#ambiguous-matches)
  - [A custom scorer](#a-custom-scorer)
  - [The pandas adapter](#the-pandas-adapter)
- [API Reference](#api-reference)
- [Determinism & Explainability](#determinism--explainability)
- [Project Structure](#project-structure)
- [Design Decisions (ADRs)](#design-decisions-adrs)
- [Testing](#testing)
- [Packaging & Publishing](#packaging--publishing)
- [Troubleshooting](#troubleshooting)
- [Scope & Roadmap](#scope--roadmap)
- [Contributing](#contributing)
- [License](#license)

## How It Works

A **match pass** takes two record sets (a *Left set* and a *Right set*) plus a `ReconcileConfig`, and returns a `ReconcileResult`. The engine treats the two sides symmetrically — which real-world type sits on which side is your choice.

```
                 ┌─────────────────────────────────────────────┐
 left, right ──▶ │ 1. GATES   amount + date within tolerance?   │  fail ─▶ drop candidate
                 │ 2. GRADES  weighted-mean similarity of        │
                 │            reference / counterparty (0..1)     │
                 │ 3. THRESHOLD  score ≥ threshold?              │  fail ─▶ drop candidate
                 │ 4. RESOLVE  greedy best-first, consume-once,  │
                 │            near-ties flagged ambiguous         │
                 │ 5. SPLITS  bounded subset-sum over residuals  │
                 │            (1:many, both directions)           │
                 └─────────────────────────────────────────────┘
                                      │
                                      ▼
        ReconcileResult(matches, left_residuals, right_residuals)
```

1. **Gates** (`amount`, `date`) are pass/fail. A pair outside any gate's tolerance is rejected before scoring — amount is a gate, never a weight, so a perfect reference string can't rescue a wrong amount.
2. **Grades** (`reference`, `counterparty`) each produce a 0..1 similarity. The **match score** is their weighted mean (1.0 when no graded fields are configured).
3. A candidate is accepted only when it passes all gates **and** `score ≥ threshold`.
4. Accepted candidates are resolved **greedy best-first**; each record is consumed by at most one match; score ties break by record id then input position. When the top two candidates for a record are within `ambiguity_epsilon`, the match is flagged **ambiguous** rather than chosen silently.
5. Whatever the 1:1 pass leaves over is searched for **splits**: subsets of residuals whose amounts sum, within tolerance, to an opposite-side residual — bounded so pathological inputs stay residual instead of hanging.

The domain vocabulary (Match pass, Record, Gate/Graded field, Similarity, Residual, Ambiguous match, …) is defined in **[`CONTEXT.md`](CONTEXT.md)**. The reasoning behind each design choice lives in **[`docs/adr/`](docs/adr/)** — see [Design Decisions](#design-decisions-adrs).

## Tech Stack

- **Language**: Python ≥ 3.10
- **Core dependencies**: none (standard library only — `difflib`, `decimal`, `itertools`, `datetime`)
- **Optional**: `pandas` ≥ 2.0 (the DataFrame adapter only)
- **Testing**: `pytest`
- **Packaging**: `setuptools` (`src/` layout), typed (`py.typed`), PyPI-ready

## Requirements

- **Python 3.10 or higher**
- **pip** (and, for the optional adapter, `pandas>=2.0`)
- No database, no services, no environment variables — it is a pure library.

## Installation

The package is not yet on PyPI. Install from source:

```bash
# Clone
git clone https://github.com/duongdanghung20/reconcile-py.git
cd reconcile-py

# Core engine only (no third-party dependencies)
pip install -e .

# With the optional pandas adapter
pip install -e '.[pandas]'
```

Or install directly from the repository without cloning:

```bash
pip install "git+https://github.com/duongdanghung20/reconcile-py.git"
```

Once published, this becomes:

```bash
pip install reconcile-py            # core
pip install 'reconcile-py[pandas]'  # with the DataFrame adapter
```

## Quick Start

```python
from datetime import date
from decimal import Decimal
from reconcile import FieldRule, ReconcileConfig, Record, reconcile

# Bank side and invoice side — you choose which is "left" and which is "right".
bank = [
    Record(Decimal("100.00"), date(2024, 1, 5), reference="INV-1024", id="B1"),
    Record(Decimal("250.00"), date(2024, 1, 9), reference="ACME wire", id="B2"),
]
invoices = [
    Record(Decimal("100.00"), date(2024, 1, 4), reference="inv 1024", id="I1"),
    Record(Decimal("250.00"), date(2024, 1, 30), reference="ACME",     id="I2"),  # date too far
]

config = ReconcileConfig(
    rules=(
        FieldRule("amount", "gate", abs_tol=Decimal("0.00")),  # amounts must match to the cent
        FieldRule("date",   "gate", day_tol=3),                # within ± 3 days
        FieldRule("reference", "grade", weight=1.0),           # fuzzy-match the reference text
    ),
    threshold=0.6,
)

result = reconcile(bank, invoices, config)

for m in result.matches:
    print(f"match {m.left_ids} <-> {m.right_ids}  score={m.score:.2f}  ambiguous={m.ambiguous}")
print("left residuals :", [r.id for r in result.left_residuals])
print("right residuals:", [r.id for r in result.right_residuals])
```

Output:

```
match ('B1',) <-> ('I1',)  score=1.00  ambiguous=False
left residuals : ['B2']
right residuals: ['I2']
```

`B1`/`I1` match: same amount, one day apart, `"INV-1024"` vs `"inv 1024"` normalizes to an identical string. `B2`/`I2` do not: the amounts and references agree, but the dates are 21 days apart, and **date is a gate**.

## Usage Guide

### Building a config

A `ReconcileConfig` is one immutable object describing the whole pass: the field rules plus global knobs. It is validated at construction — an invalid config raises `ValueError` immediately, rather than misbehaving mid-pass.

```python
config = ReconcileConfig(
    rules=(
        FieldRule("amount", "gate", abs_tol=Decimal("0.01")),
        FieldRule("date",   "gate", day_tol=5),
        FieldRule("reference",    "grade", weight=2.0),   # weigh reference twice as heavily
        FieldRule("counterparty", "grade", weight=1.0),
    ),
    threshold=0.8,
    ambiguity_epsilon=0.05,
    max_subset_size=4,
    max_group_size=16,
)
```

An **Amount gate rule is mandatory** — a config without one raises `ValueError`.

### Criteria fields

| Field          | Allowed role(s) | Tolerance / weight                                             | Notes |
| -------------- | --------------- | ------------------------------------------------------------- | ----- |
| `amount`       | `gate`          | `abs_tol` (Decimal) and/or `pct_tol` (Decimal, in **percent**) | Mandatory gate. If neither tolerance is set, requires an **exact** match. `pct_tol` is measured against the larger of the two amounts. |
| `date`         | `gate`          | `day_tol` (int, required for a date gate)                     | Matches within ± `day_tol` days (inclusive). |
| `reference`    | `grade`         | `weight` (float, default 1.0)                                 | Fuzzy text. Normalized (case-folded, punctuation/whitespace stripped) before scoring. |
| `counterparty` | `grade`         | `weight` (float, default 1.0)                                 | Fuzzy text, same normalization. |

`amount`/`date` can only be gates; `reference`/`counterparty` can only be graded. Violations raise `ValueError` at config construction.

### Graded matching and the threshold

The **match score** is the weighted mean of the configured graded fields' similarities. A candidate is accepted only if it clears both the gates and `threshold`.

- **Default `threshold` is `1.0`** — with graded fields configured, that means only a *perfect* similarity match is accepted. Lower it to admit fuzzier matches (the Quick Start uses `0.6`).
- A **gate-only** config (no graded fields) gives every gate-passing pair a score of `1.0`.

### Split (1:many) matches

Split search runs **after** the 1:1 pass, on the residuals. For a residual, the engine groups opposite-side residuals that clear its gates, then looks for a subset whose amounts sum within tolerance of it. It searches **both directions** — one left → many right, and one right → many left.

```python
config = ReconcileConfig(
    rules=(FieldRule("amount", "gate", abs_tol=Decimal("0.00")),),
    max_subset_size=4,   # a split has 2..4 members
    max_group_size=16,   # groups larger than this are skipped (stay residual)
)

payments = [Record(Decimal("300.00"), id="P1")]              # one payment
invoices = [Record(Decimal("100.00"), id="I1"),
            Record(Decimal("200.00"), id="I2")]              # covers two invoices

result = reconcile(payments, invoices, config)
# -> one match: left_ids=('P1',), right_ids=('I1', 'I2')
```

The `max_subset_size` / `max_group_size` bounds keep the (otherwise exponential) subset-sum search finite: above the group cap, a record is left as a residual rather than triggering a blow-up.

### Ambiguous matches

When a record's best two candidates score within `ambiguity_epsilon` of each other, the winning match is flagged `ambiguous=True` instead of being chosen silently. Ambiguous matches stay in `result.matches`; `result.ambiguous` is a convenience view over just those.

```python
config = ReconcileConfig(rules=(...), threshold=0.7, ambiguity_epsilon=0.05)
result = reconcile(left, right, config)

for m in result.ambiguous:
    print("needs review:", m.left_ids, m.right_ids, m.score)
```

`ambiguity_epsilon` defaults to `0.0` (flag only exact-tie competitors).

### A custom scorer

A `Scorer` is any `Callable[[str, str], float]` returning a 0..1 similarity. The default normalizes strings and uses `difflib.SequenceMatcher`. Swap in your own — for example `rapidfuzz` for speed or token-set matching — via `config.scorer`:

```python
from rapidfuzz.fuzz import token_set_ratio

config = ReconcileConfig(
    rules=(FieldRule("amount", "gate", abs_tol=Decimal("0")),
           FieldRule("counterparty", "grade")),
    scorer=lambda a, b: token_set_ratio(a, b) / 100.0,  # rapidfuzz returns 0..100
)
```

### The pandas adapter

If your data lives in DataFrames, the optional adapter converts to and from `Record`s so pandas never touches the engine.

```python
from reconcile import ReconcileConfig, FieldRule, reconcile
from reconcile.pandas_adapter import from_dataframe, to_dataframe
from decimal import Decimal

left = from_dataframe(bank_df,     amount="amt", date="posted", reference="memo", id="txn_id")
right = from_dataframe(invoice_df, amount="total", date="issued", reference="number", id="inv_no")

result = reconcile(left, right, ReconcileConfig(
    rules=(FieldRule("amount", "gate", abs_tol=Decimal("0.00")),
           FieldRule("date", "gate", day_tol=3)),
))

frames = to_dataframe(result)   # NamedTuple(matches, left_residuals, right_residuals)
frames.matches.to_csv("matches.csv", index=False)
```

The adapter owns pandas' dtype quirks: `NaN`/`NaT` become absent optional fields, float amounts are converted through `str` so they land on their exact decimal value, and a numeric date column (ambiguous encoding) is rejected rather than silently misread — convert it with `pd.to_datetime(...)` first.

> Importing `reconcile.pandas_adapter` requires pandas; importing `reconcile` never does.

## API Reference

Everything below is importable from the top-level `reconcile` package.

### `reconcile(left, right, config) -> ReconcileResult`

The single entrypoint. `left` and `right` are sequences of `Record`; `config` is a `ReconcileConfig`. Pure and deterministic.

### `Record`

Frozen dataclass — one entry on either side of a pass.

| Field          | Type              | Default | Notes |
| -------------- | ----------------- | ------- | ----- |
| `amount`       | `Decimal`         | —       | Mandatory. Signed. |
| `date`         | `date \| None`    | `None`  | |
| `reference`    | `str \| None`     | `None`  | |
| `counterparty` | `str \| None`     | `None`  | |
| `id`           | `str \| None`     | `None`  | Stable identity; falls back to input position when absent. |

### `FieldRule`

Frozen dataclass — how one criteria field participates.

| Field     | Type              | Notes |
| --------- | ----------------- | ----- |
| `field`   | `"amount" \| "date" \| "reference" \| "counterparty"` | |
| `role`    | `"gate" \| "grade"` | |
| `abs_tol` | `Decimal \| None` | Amount gate: absolute tolerance. |
| `pct_tol` | `Decimal \| None` | Amount gate: percentage tolerance (e.g. `Decimal("0.5")` = 0.5%). |
| `day_tol` | `int \| None`     | Date gate: ± day window (required for a date gate). |
| `weight`  | `float \| None`   | Graded field weight (default 1.0; must be positive). |

### `ReconcileConfig`

Frozen dataclass — the full description of a pass.

| Field               | Type                      | Default | Notes |
| ------------------- | ------------------------- | ------- | ----- |
| `rules`             | `tuple[FieldRule, ...]`   | —       | Must include an Amount gate rule. |
| `threshold`         | `float`                   | `1.0`   | Minimum score to accept a match. |
| `ambiguity_epsilon` | `float`                   | `0.0`   | Near-tie band for ambiguity flagging (≥ 0). |
| `max_subset_size`   | `int`                     | `4`     | Max members in a split (≥ 2). |
| `max_group_size`    | `int`                     | `16`    | Max split-search group before a record stays residual (≥ 1). |
| `scorer`            | `Scorer \| None`          | `None`  | Custom similarity function; defaults to normalized `difflib`. |

### `Match`

Frozen dataclass. `left_ids` / `right_ids` are tuples (carrying both 1:1 and split matches, either direction); each id is the record's `id`, or its input position when absent.

| Field       | Type                       |
| ----------- | -------------------------- |
| `left_ids`  | `tuple[str \| int, ...]`   |
| `right_ids` | `tuple[str \| int, ...]`   |
| `score`     | `float`                    |
| `reasons`   | `Reason`                   |
| `ambiguous` | `bool`                     |

### `Reason`

Frozen dataclass — why a match was made. `gates_passed: tuple[str, ...]`, `similarities: tuple[tuple[str, float], ...]` (field, similarity).

### `ReconcileResult`

Frozen dataclass. `matches: tuple[Match, ...]`, `left_residuals: tuple[Record, ...]`, `right_residuals: tuple[Record, ...]`, and a computed `ambiguous` property (the matches flagged ambiguous).

### `Scorer`

Type alias: `Callable[[str, str], float]` returning a 0..1 similarity.

## Determinism & Explainability

Determinism is a **hard guarantee**, not a best effort (see [ADR-0004](docs/adr/0004-deterministic-explainable-no-audit-log.md)):

- The engine uses no wall-clock time and no randomness.
- Output ordering is stable: by record `id`, then input position. Shuffling the input order of either set produces a byte-identical `ReconcileResult` (this is locked by a property test).
- Every `Match` carries a `Reason` (which gates passed, each graded similarity), so a result explains itself without re-running.

"Replayable" means re-running reproduces the result — the library does **not** persist a decision log; that is the consuming application's job.

## Project Structure

```
reconcile-py/
├── src/reconcile/
│   ├── __init__.py          # public API surface (re-exports)
│   ├── types.py             # frozen domain types + all config validation
│   ├── engine.py            # the pure pairwise match engine (reconcile)
│   ├── pandas_adapter.py    # optional pandas edge (from_dataframe/to_dataframe)
│   └── py.typed             # PEP 561 typing marker
├── tests/                   # one file per capability, all through a public seam
│   ├── test_reconcile_seam.py
│   ├── test_graded_scoring.py
│   ├── test_greedy_resolution.py
│   ├── test_split_matches.py
│   ├── test_determinism_property.py
│   └── test_dataframe_adapter.py
├── docs/adr/                # architecture decision records (0001–0008)
├── CONTEXT.md               # domain glossary
├── CLAUDE.md                # guidance for AI coding agents
├── pyproject.toml
└── README.md
```

**Two seams**: the `reconcile()` call (the engine) and the adapter functions (`from_dataframe`/`to_dataframe`). Tests assert through these only, never engine internals.

## Design Decisions (ADRs)

Each decision, and why it was made, is recorded under [`docs/adr/`](docs/adr/):

| ADR | Decision |
| --- | -------- |
| [0001](docs/adr/0001-generic-pairwise-match-engine.md) | Generic pairwise engine — no hardcoded bank/invoice/ledger types. |
| [0002](docs/adr/0002-typed-records-core-pandas-adapter.md) | Typed records are the core contract; pandas is an edge adapter. |
| [0003](docs/adr/0003-gates-then-grades-matching.md) | Gate fields prune, graded fields score. |
| [0004](docs/adr/0004-deterministic-explainable-no-audit-log.md) | Deterministic and explainable, but no persisted audit log. |
| [0005](docs/adr/0005-pluggable-scorer-difflib-default.md) | Weighted-mean score; pluggable scorer, `difflib` by default. |
| [0006](docs/adr/0006-greedy-resolution-with-ambiguity-flag.md) | Greedy resolution, near-ties flagged rather than guessed. |
| [0007](docs/adr/0007-split-matches-after-1to1-bounded.md) | Split matches after the 1:1 pass, bounded subset-sum. |
| [0008](docs/adr/0008-percentage-amount-tolerance-uses-larger-side.md) | Percentage amount tolerance uses the larger of the two amounts. |

## Testing

```bash
# Run the full suite (pythonpath and testpaths are set in pyproject.toml)
python -m pytest

# A single file
python -m pytest tests/test_split_matches.py

# Match by name
python -m pytest -k determinism

# Verbose
python -m pytest -v
```

The suite is 64 tests across six files, one per capability, all asserting external behavior through a public seam. Because the engine is a pure function, the tests are plain input/output assertions — no fixtures, no mocks. `test_determinism_property.py` locks the reproducibility guarantee by shuffling inputs and asserting identical results.

## Packaging & Publishing

The project is configured for PyPI (`src/` layout, `py.typed`, metadata in `pyproject.toml`).

```bash
# Build sdist + wheel
pip install build
python -m build          # writes dist/reconcile_py-<version>.tar.gz and .whl

# Check and upload (first publish sets up the PyPI project)
pip install twine
twine check dist/*
twine upload dist/*      # needs a PyPI API token
```

Bump `version` in `pyproject.toml` before each release. A PyPI API token is required for upload — store it in `~/.pypirc` or a CI secret; never commit it.

## Troubleshooting

**`ValueError: ReconcileConfig requires an Amount gate rule`**
Every config must include `FieldRule("amount", "gate", ...)`. Amount is mandatory.

**`ValueError: 'reference' cannot be a gate field` / `'amount' cannot be a graded field`**
Only `amount`/`date` are gates; only `reference`/`counterparty` are graded.

**`ValueError: date gate rule requires day_tol`**
A date gate needs a window: `FieldRule("date", "gate", day_tol=3)`.

**Nothing matches even though the data looks close**
The default `threshold` is `1.0`. With graded fields configured, only a perfect similarity clears it — lower `threshold`. Also confirm amounts are within tolerance: with no `abs_tol`/`pct_tol`, the amount gate requires an *exact* match.

**Float amounts silently miss the amount gate**
Build `Record.amount` from `Decimal`, and from a string, not a float: `Decimal("100.10")`, not `Decimal(100.10)` (which carries binary-float noise). The pandas adapter already converts through `str` for you.

**`ValueError: date column holds a numeric value ...` (pandas adapter)**
A numeric date column's encoding is ambiguous (Excel serial? epoch? YYYYMMDD?). Parse it explicitly with `pd.to_datetime(...)` before `from_dataframe`.

**`ModuleNotFoundError: No module named 'pandas'`**
The adapter needs pandas: `pip install 'reconcile-py[pandas]'` (or `pip install pandas`). The core engine does not.

## Scope & Roadmap

Deliberately **out of scope** (see the ADRs and `.scratch/reconcile-engine/spec.md`):

- Full many-to-many matching (only 1:1 and 1:many are supported).
- A persisted decision/event log (the consuming app persists results itself).
- Global optimal assignment (Hungarian) — greedy + ambiguity flagging is the chosen trade-off.
- A non-stdlib scorer as the default (`rapidfuzz` is available as a caller-supplied scorer).

Tracked shortcuts, to revisit only if real data demands it: swap `difflib` → `rapidfuzz` if similarity quality/speed falls short; a smarter split-search solver if a consumer hits the subset/group cap.

## Contributing

1. Install with the dev/adapter extra: `pip install -e '.[pandas]'`.
2. Read [`CONTEXT.md`](CONTEXT.md) (vocabulary) and the relevant [ADRs](docs/adr/) before changing behavior — use the glossary's terms.
3. Follow the existing test pattern: assert through a public seam, never engine internals; determinism must hold.
4. Put new config invariants in `ReconcileConfig.__post_init__` (fail loud at construction, not deep in the engine).
5. `python -m pytest` must be green before you open a PR.

## License

[MIT](LICENSE) © 2026 duongdanghung20.
