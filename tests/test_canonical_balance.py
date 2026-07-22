"""Regression guard for the 2026-07 prod incident.

Parent SSC20257990 (Shanice Karamba) queried term 2026-1. The bot billed $490,
saw $190 cash, and displayed "Balance Owed: $300.00" — but the account carried a
legacy write-off CreditNote (-$300) so the admin app's canonical outstanding
balance was $0. The bot must source the canonical balance, never fees-minus-cash.
"""
import pytest

import webhook_handler as wh


class StubClient:
    """Mimics SMSClient.get_student_account_statement's return shape."""

    def __init__(self, balance, raise_it=False):
        self._balance = balance
        self._raise = raise_it

    def get_student_account_statement(self, student_id, term):
        if self._raise:
            raise RuntimeError("SaaS down")
        return {"data": {"balance": self._balance}}


def test_canonical_balance_uses_api_not_fees_minus_payments():
    # The exact incident: local math would say 300, the API says 0.
    assert wh._canonical_balance(StubClient(0.0), "SSC20257990", "2026-1") == 0.0


def test_prefetched_account_is_reused():
    bal = wh._canonical_balance(
        StubClient(999), "X", "2026-1", account={"data": {"balance": 0.0}}
    )
    assert bal == 0.0


def test_returns_none_when_lookup_fails():
    # Never guess a balance — signal unavailable so callers show the notice.
    assert wh._canonical_balance(StubClient(0.0, raise_it=True), "X", "2026-1") is None


def test_unavailable_notice_when_balance_none():
    line = wh._render_balance_line("X", "Kid", 490.0, 190.0, balance=None, has_bills=True)
    assert "temporarily unavailable" in line.lower()
    assert "$300" not in line and "$0.00" not in line  # no number invented


def test_summary_line_settled_and_reconciled():
    line = wh._render_balance_line(
        "SSC20257990", "Shanice Karamba",
        total_fees=490.0, total_paid=190.0, balance=0.0, has_bills=True,
    )
    assert "Fully settled" in line
    assert "Balance Owed: $0.00" in line
    assert "Credits/Adjustments: $300.00" in line          # numbers reconcile
    assert "Balance Owed: $300.00" not in line              # no false alarm


def test_summary_line_real_debtor_still_flagged():
    line = wh._render_balance_line("S2", "Owing Kid", 500.0, 200.0, balance=300.0, has_bills=True)
    assert "Balance Owed: $300.00" in line
    assert "Fully settled" not in line


def test_statement_block_reconciles():
    stmt = wh._render_statement_block(
        "SSC20257990", "Shanice Karamba", "2026-1",
        490.0, 190.0, 0.0, "- $490.00 (Tuition)", "- $190.00 (Cash)",
    )
    assert "Fully Settled" in stmt
    assert "Credits/Adjustments*: $300.00" in stmt


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
