"""Qualification evidence: one ledger, its adapters, and the reports built from it.

Every milestone that has to prove something -- P0's parity inventory, UI0's
operation and case slots, P6's build budgets, P7's support/coverage report,
the skip ledger every gate writes -- records its evidence in the one record
format that `tools.qualification.schema` defines. Its module docstring is the
schema reference.

- `statistics`: the nearest-rank median/p95/p99/p99.9/max P6 reports
  (budget_bench uses it).
- `adapters`: budget_bench reports, JUnit runs, skip reports and boundary-check
  reports turned into ledger records against declared denominators, and the
  host provenance a measurement carries.
- `denominators`: the frozen P0/UI0 inventory denominators
  (``denominators.toml``), immutable per release.
- `report`: the slot rollup and the Markdown/JSON support/coverage report.
- `skips`: expected-skip manifests and the gate that fails on an unexpected skip.
- `store`: raw inputs and ledgers under ``~/.cache/btrc/qualification/``
  (override with ``BTRC_QUALIFICATION_DIR``), never under ``/tmp``: macOS
  deletes anything there that has not been touched for three days.

Run it from the repository root::

    python3 -m tools.qualification report --budget-bench RUN/report.json --junit junit.xml
    python3 -m tools.qualification report --all-ledgers --denominators
    python3 -m tools.qualification denominators
    python3 -m tools.qualification ingest --budget-bench RUN/report.json --btrc-revision 65057cb
    python3 -m tools.qualification skip-gate build/skip-report.json
"""
