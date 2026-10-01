"""Qualification evidence: one ledger, its adapters, and the reports built from it.

Every milestone that has to prove something -- P0's parity inventory, UI0's
operation and case slots, P6's build budgets, P7's support/coverage report,
the skip ledger every gate writes -- records its evidence in the one record
format that `tools.qualification.schema` defines. Its module docstring is the
schema reference; `tools.qualification.statistics` owns the nearest-rank
summaries P6 reports.

Raw inputs and ledgers live under ``~/.cache/btrc/qualification/`` (override
with ``BTRC_QUALIFICATION_DIR``), never under ``/tmp``: macOS deletes anything
there that has not been touched for three days.
"""
