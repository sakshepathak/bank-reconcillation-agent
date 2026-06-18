"""
Phase 1 (overpayment/prepayment): the CreditNote + CreditAllocation data model.

No endpoints exist yet — these tests just lock the schema: the tables persist,
scope by org_id, derive `outstanding = original_amount - allocated_amount`, link
allocations to a credit, and a statement line can remember the credit it booked
(matched_credit_id). FK enforcement is off in the in-memory test DB, so ids can
be plain integers.
"""
from sqlmodel import Session, select

from memory.models import (
    CreditNote, CreditAllocation, CreditDirection, CreditKind,
    DocumentStatus, StatementLine,
)


def test_credit_note_persists_with_sensible_defaults(test_engine):
    with Session(test_engine) as db:
        cn = CreditNote(
            org_id=1, contact_id=10, contact_name="Correct Limited",
            direction=CreditDirection.PAYABLE, kind=CreditKind.OVERPAYMENT,
            issue_date="2026-04-28", currency="GBP",
            original_amount=800.0, source_statement_line_id=5,
            created_at="2026-04-28T00:00:00Z",
        )
        db.add(cn); db.commit(); db.refresh(cn)

    with Session(test_engine) as db:
        cn = db.exec(select(CreditNote)).one()
        assert cn.id is not None
        assert cn.status == DocumentStatus.AWAITING_PAYMENT   # has unallocated credit
        assert cn.tax_rate == 0.0                              # v1: tax-free
        assert cn.allocated_amount == 0.0
        # outstanding is derived (never stored)
        assert round(cn.original_amount - cn.allocated_amount, 2) == 800.0


def test_partial_allocation_leaves_outstanding_remainder(test_engine):
    with Session(test_engine) as db:
        db.add(CreditNote(
            org_id=1, contact_name="Acme", direction=CreditDirection.PAYABLE,
            kind=CreditKind.OVERPAYMENT, issue_date="2026-04-28", original_amount=800.0,
        ))
        db.commit()

    with Session(test_engine) as db:
        cn = db.exec(select(CreditNote)).one()
        cn.allocated_amount = 300.0
        db.add(cn); db.commit()

    with Session(test_engine) as db:
        cn = db.exec(select(CreditNote)).one()
        assert round(cn.original_amount - cn.allocated_amount, 2) == 500.0


def test_credit_allocation_links_to_its_credit(test_engine):
    with Session(test_engine) as db:
        cn = CreditNote(
            org_id=1, contact_name="Acme", direction=CreditDirection.PAYABLE,
            kind=CreditKind.PREPAYMENT, issue_date="2026-04-28", original_amount=800.0,
        )
        db.add(cn); db.commit(); db.refresh(cn)
        db.add(CreditAllocation(
            org_id=1, credit_note_id=cn.id, target_type="bill", target_id=42,
            amount=500.0, created_at="2026-05-01T00:00:00Z",
        ))
        db.commit()

        allocs = db.exec(
            select(CreditAllocation).where(CreditAllocation.credit_note_id == cn.id)
        ).all()
        assert len(allocs) == 1
        assert allocs[0].amount == 500.0
        assert allocs[0].target_type == "bill" and allocs[0].target_id == 42


def test_credit_notes_are_org_scoped(test_engine):
    with Session(test_engine) as db:
        db.add(CreditNote(org_id=1, contact_name="Org-1 supplier",
                          direction=CreditDirection.PAYABLE, kind=CreditKind.OVERPAYMENT,
                          issue_date="2026-01-01", original_amount=100.0))
        db.add(CreditNote(org_id=2, contact_name="Org-2 customer",
                          direction=CreditDirection.RECEIVABLE, kind=CreditKind.PREPAYMENT,
                          issue_date="2026-01-01", original_amount=200.0))
        db.commit()

        org1 = db.exec(select(CreditNote).where(CreditNote.org_id == 1)).all()
        assert len(org1) == 1 and org1[0].contact_name == "Org-1 supplier"


def test_statement_line_remembers_booked_credit(test_engine):
    with Session(test_engine) as db:
        line = StatementLine(
            org_id=1, bank_account_id=1, date="2026-04-28",
            description="CORRECT LIMITED", spent=2000.0, matched_credit_id=7,
        )
        db.add(line); db.commit(); db.refresh(line)

    with Session(test_engine) as db:
        line = db.exec(select(StatementLine)).one()
        assert line.matched_credit_id == 7
