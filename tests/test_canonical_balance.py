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
    line = wh._render_balance_line("X", "Kid", 490.0, 190.0, balance=None, has_bills=True, term="2026-1")
    assert "temporarily unavailable" in line.lower()
    assert "$300" not in line and "$0.00" not in line  # no number invented


def test_summary_headline_is_account_balance_not_fees_minus_paid():
    # The incident: term fees 490 / paid 190 but the account is settled ($0).
    # Headline must be the account balance; the $300 fees-minus-paid must never show,
    # and term fees/paid appear only as context (not subtracted against the balance).
    line = wh._render_balance_line(
        "SSC20257990", "Shanice Karamba",
        total_fees=490.0, total_paid=190.0, balance=0.0, has_bills=True, term="2026-1",
    )
    assert "Account settled" in line
    assert "$0.00 owed" in line
    assert "Term 2026-1: billed $490.00, paid $190.00" in line   # context only
    assert "$300" not in line                                    # no phantom, no artifact


def test_summary_line_real_debtor_still_flagged():
    line = wh._render_balance_line("S2", "Owing Kid", 500.0, 200.0, balance=300.0, has_bills=True, term="2026-1")
    assert "Account balance owed: $300.00" in line
    assert "settled" not in line.lower()


def test_statement_block_account_headline_with_term_detail():
    stmt = wh._render_statement_block(
        "SSC20257990", "Shanice Karamba", "2026-1",
        490.0, 190.0, 0.0, "- $490.00 (Tuition)", "- $190.00 (Cash)",
    )
    assert "Account settled" in stmt
    assert "Term 2026-1 detail" in stmt
    assert "$300" not in stmt


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
