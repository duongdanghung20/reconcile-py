# reconcile-py

The reconciliation context: fuzzy-matching one set of financial records against another (e.g. bank transactions against invoices or ledger entries) under configurable tolerance rules, in a deterministic, replayable pass.

## Language

**Match pass**:
A single deterministic run that takes two record sets plus a configuration and produces matches and residuals. The same inputs always yield the same output.
_Avoid_: reconciliation run, sync, batch

**Record**:
One typed entry on either side of a pass — a bank transaction, an invoice, a ledger entry. The engine does not privilege any of these types; they are all records supplied by the caller.
_Avoid_: row, transaction (when speaking generically), entry

**Left set / Right set**:
The two record collections a pass matches against each other. Which real-world type sits on which side is the caller's choice (e.g. bank transactions left, invoices right); the engine treats the two sides symmetrically.
_Avoid_: source/target, primary/secondary

**Match**:
An association linking one Left record to one or more Right records, or vice versa. Carries the records involved and the reason they matched.
_Avoid_: pair, link, hit

**Split match**:
A one-to-many Match — one payment covering several invoices, or one invoice settled in installments. The general shape of a Match; a one-to-one Match is the degenerate case.
_Avoid_: partial match, batch match

**Residual**:
A record left unmatched after a pass completes.
_Avoid_: leftover, orphan, exception

### Criteria fields

The record fields the engine is allowed to match on. Amount is mandatory; the rest are opt-in per configuration. Each field is either a **gate field** or a **graded field** (see Match mechanics).

**Amount**:
The signed monetary value of a record. The mandatory criterion of every pass.

**Date**:
The record's effective date, matched within a tolerance window.

**Reference**:
Free-text description or memo (payment reference, invoice number). One of the two fuzzy criteria.

**Counterparty**:
The other party named on the record (payee, customer). The second fuzzy criterion.

### Match mechanics

**Gate field**:
A criteria field evaluated pass/fail. A record pair failing any gate cannot match; gates prune the candidate set before scoring. Amount and Date are gate fields.
_Avoid_: filter, hard criterion

**Graded field**:
A criteria field that yields a similarity in 0..1 rather than pass/fail, contributing to a Match's score. Reference and Counterparty are graded fields.
_Avoid_: soft criterion, weight

**Similarity**:
The 0..1 closeness of two graded-field values after normalization (case-fold, punctuation and whitespace stripped).
_Avoid_: distance, fuzz score

**Match reason**:
The explanation attached to every Match: which gates passed and each graded field's Similarity. Makes a result auditable without re-running the pass.
_Avoid_: audit log, trace

**Record id**:
A caller-supplied stable identifier for a Record, used to order output deterministically. Falls back to input position when absent.
_Avoid_: key, index, primary key

**Match score**:
The weighted mean of a candidate's graded-field Similarities, in 0..1. A candidate that passes all gates with no graded fields configured scores 1.0.
_Avoid_: confidence, weight, rank

**Threshold**:
The minimum Match score for a candidate to be accepted as a Match.
_Avoid_: cutoff, minimum confidence

**Scorer**:
The pluggable component that computes Similarity for a graded field. The default normalizes strings and uses `difflib.SequenceMatcher`.
_Avoid_: matcher, comparator

**Ambiguous match**:
A Match flagged for review because its top two competing candidate scores fell within an epsilon of each other, so the engine declined to pick silently.
_Avoid_: conflict, duplicate, needs-review (as a bare term)
