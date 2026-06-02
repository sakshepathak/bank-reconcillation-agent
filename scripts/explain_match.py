"""
explain_match.py — a live, step-by-step trace of the reconciliation matcher.

Built for demos: it runs the REAL matching pipeline on one bank line vs one
candidate invoice/bill and prints every intermediate the engine computes —
normalisation, alias lookup, the four lexical sub-scores, the embedding cosine,
the ensemble decision, the amount/date gates, and the final composite score.

The numbers it prints are identical to what the app shows, because it calls the
same `explain_candidate()` the API does.

Usage:
    # Built-in worked examples (no DB needed) — great for a first walkthrough:
    python scripts/explain_match.py

    # Trace a real statement line from your database (top candidate):
    python scripts/explain_match.py --line 42

    # Show ALL candidates for that line, ranked:
    python scripts/explain_match.py --line 42 --all

    # A one-off manual example:
    python scripts/explain_match.py --bank "SQ *DAILYBEAN 03/14" --bank-amount 4.50 \
        --bank-date 2026-03-14 --vendor "The Daily Bean Ltd" --cand-amount 4.50 \
        --cand-date 2026-03-14 --label INV-204
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Windows consoles default to cp1252, which can't encode the box/arrow glyphs
# rich emits — force UTF-8 so the trace renders on any terminal.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
except Exception:  # noqa: BLE001
    pass

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from engine.vendor_matching.explain import explain_candidate

# legacy_windows=False keeps rich off the cp1252 win32 path and on UTF-8 ANSI.
console = Console(legacy_windows=False)


# ─── Rendering ────────────────────────────────────────────────────────────────

def _bar(value: float, width: int = 24) -> str:
    """A little unicode progress bar for a 0..1 score."""
    filled = int(round(max(0.0, min(1.0, value)) * width))
    return "█" * filled + "░" * (width - filled)


def render_trace(trace: dict) -> None:
    inp = trace["input"]
    final = trace["final"]

    console.print()
    console.print(Panel.fit(
        f"[bold]BANK LINE[/]   {inp['bank_description']!r}\n"
        f"             {inp['bank_amount']:.2f}  ·  {inp['bank_date']}\n"
        f"[bold]CANDIDATE[/]   {inp['candidate_label']}  ·  {inp['candidate_vendor']!r}\n"
        f"             {inp['candidate_amount']:.2f}  ·  {inp['candidate_date']}",
        title="Input", border_style="cyan",
    ))

    for s in trace["steps"]:
        n, title, detail = s["n"], s["title"], s["detail"]

        if n == 1:
            body = (
                f"bank:      [yellow]{s['bank_raw']!r}[/]\n"
                f"           → [green]{s['bank_canonical']!r}[/]\n"
                f"candidate: [yellow]{s['candidate_raw']!r}[/]\n"
                f"           → [green]{s['candidate_canonical']!r}[/]"
            )
        elif n == 2:
            body = (
                f"[green]HIT[/] → {s['resolved_to']!r}" if s["hit"]
                else "[dim]miss — no learned alias for this description[/]"
            )
        elif n == 3:
            m = s["metrics"]
            if m is None:
                body = "[dim]no candidate[/]"
            else:
                w = s["weights"]
                tbl = Table(box=box.SIMPLE, show_header=True, header_style="dim", pad_edge=False)
                tbl.add_column("metric"); tbl.add_column("score", justify="right")
                tbl.add_column("weight", justify="right"); tbl.add_column("contribution", justify="right")
                for key in ("jaro_winkler", "token_set", "token_sort", "partial"):
                    tbl.add_row(key, f"{m[key]:.3f}", f"×{w[key]:.2f}", f"{m[key]*w[key]:.3f}")
                console.print(Panel(tbl, title=f"[bold]Step {n} — {title}[/]",
                                    subtitle=detail, border_style="blue", subtitle_align="left"))
                console.print(f"   [bold]composite = {s['composite']:.3f}[/]  {_bar(s['composite'])}\n")
                continue
        elif n == 4:
            if not s["fired"]:
                body = "[dim]skipped — lexical already locked in (≥0.95)[/]"
            elif s["cosine"] is None:
                body = "[dim]fired, but model returned no signal[/]"
            else:
                rescued = s["cosine"] >= s["floor"]
                body = (
                    f"fired (lexical < 0.95)\n"
                    f"cosine similarity = [bold]{s['cosine']:.3f}[/]  {_bar(s['cosine'])}\n"
                    + (f"[green]≥ {s['floor']} floor → semantic match counts[/]"
                       if rescued else f"[dim]< {s['floor']} floor → no embedding signal[/]")
                )
        elif n == 5:
            body = (
                f"name score = [bold]{s['name_score']:.3f}[/]  {_bar(s['name_score'])}\n"
                f"winning method = [magenta]{s['method']}[/]"
            )
        elif n == 6:
            tbl = Table(box=box.SIMPLE, show_header=True, header_style="dim", pad_edge=False)
            tbl.add_column("component"); tbl.add_column("value", justify="right")
            tbl.add_column("why")
            tbl.add_row("amount (≤0.50)", f"{s['amount_component']:.2f}", s["amount_reason"])
            tbl.add_row("date (≤0.20)", f"{s['date_component']:.2f}", s["date_reason"])
            tbl.add_row("name ×0.30", f"{s['name_component']:.3f}", f"raw {s['name_raw']:.3f} × 0.30")
            console.print(Panel(tbl, title=f"[bold]Step {n} — {title}[/]",
                                subtitle=detail, border_style="blue", subtitle_align="left"))
            console.print(f"   [bold]TOTAL = {s['total']:.3f}[/]  {_bar(s['total'])}\n")
            continue
        elif n == 7:
            colour = {"strong": "green", "likely": "green", "possible": "yellow", "weak": "red"}[s["strength"]]
            verdict = "AUTO-APPROVE QUALITY" if s["auto_approve_quality"] else "needs human review"
            body = f"[bold {colour}]{s['label']}[/]  ·  {verdict}"
        else:
            body = ""

        console.print(Panel(body, title=f"[bold]Step {n} — {title}[/]",
                            subtitle=detail, border_style="blue", subtitle_align="left"))

    c = {"strong": "green", "likely": "green", "possible": "yellow", "weak": "red"}[final["strength"]]
    console.print(Panel.fit(
        f"[bold {c}]{final['strength_label']}  —  {final['score_pct']}%[/]  "
        f"(score {final['score']:.3f}, method {final['method']})",
        title="Result", border_style=c,
    ))
    console.print()


# ─── Example sources ──────────────────────────────────────────────────────────

_DEMO_CASES = [
    dict(  # exact: amount+date+name all line up
        bank_desc="ACME CORP", bank_amount=1200.00, bank_date="2026-05-06",
        cand_label="INV-005", cand_vendor="Acme Corp", cand_amount=1200.00, cand_date="2026-05-06",
    ),
    dict(  # semantic: spelling differs, embedding rescues
        bank_desc="SQ *DAILYBEAN COFFEE 03/14", bank_amount=4.50, bank_date="2026-03-14",
        cand_label="INV-204", cand_vendor="The Daily Bean Ltd", cand_amount=4.50, cand_date="2026-03-14",
    ),
    dict(  # weak: different vendor + amount off — shows a low score
        bank_desc="UBER *EATS 8210", bank_amount=58.00, bank_date="2026-05-02",
        cand_label="INV-013", cand_vendor="Zenith Retail", cand_amount=410.00, cand_date="2026-05-25",
    ),
]


def from_demo() -> list[dict]:
    return [explain_candidate(**case) for case in _DEMO_CASES]


def from_line(line_id: int, show_all: bool) -> list[dict]:
    """Pull a real statement line + its candidate invoices/bills from the DB."""
    from sqlmodel import Session, select
    from memory.db import engine
    from memory.models import StatementLine, Invoice, Bill, VendorAlias, DocumentStatus

    with Session(engine) as db:
        line = db.get(StatementLine, line_id)
        if not line:
            console.print(f"[red]No statement line with id {line_id}.[/]")
            return []
        org_id = line.org_id
        is_inflow = line.received > 0
        amount = line.received if is_inflow else line.spent

        if is_inflow:
            docs = db.exec(select(Invoice).where(
                Invoice.org_id == org_id,
                Invoice.status != DocumentStatus.PAID,
                Invoice.status != DocumentStatus.VOIDED,
            )).all()
            cands = [(d.number, d.contact_name, d.issue_date, round(d.total - d.paid_amount, 2))
                     for d in docs if (d.total - d.paid_amount) > 0]
        else:
            docs = db.exec(select(Bill).where(
                Bill.org_id == org_id,
                Bill.status != DocumentStatus.PAID,
                Bill.status != DocumentStatus.VOIDED,
            )).all()
            cands = [(d.number or f"Bill #{d.id}", d.contact_name, d.issue_date, round(d.total - d.paid_amount, 2))
                     for d in docs if (d.total - d.paid_amount) > 0]

        alias_rows = db.exec(select(VendorAlias).where(VendorAlias.org_id == org_id)).all()
        alias_map = {a.alias.lower(): a.canonical_name for a in alias_rows}

        if not cands:
            console.print(f"[yellow]Line {line_id} ({line.description!r}) has no open "
                          f"{'invoices' if is_inflow else 'bills'} to match against.[/]")
            return []

        traces = [
            explain_candidate(
                bank_desc=line.description or "", bank_amount=amount, bank_date=line.date,
                cand_label=label, cand_vendor=contact or "", cand_amount=outstanding, cand_date=doc_date,
                alias_map=alias_map,
            )
            for (label, contact, doc_date, outstanding) in cands
        ]
        traces.sort(key=lambda t: t["final"]["score"], reverse=True)
        return traces if show_all else traces[:1]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Step-by-step trace of the reconciliation matcher.")
    ap.add_argument("--line", type=int, help="Trace a real statement line id from the DB.")
    ap.add_argument("--all", action="store_true", help="With --line: show every candidate, ranked.")
    # Manual one-off:
    ap.add_argument("--bank", help="Bank description.")
    ap.add_argument("--bank-amount", type=float)
    ap.add_argument("--bank-date", default="2026-01-01")
    ap.add_argument("--vendor", help="Candidate vendor/contact name.")
    ap.add_argument("--cand-amount", type=float)
    ap.add_argument("--cand-date", default="2026-01-01")
    ap.add_argument("--label", default="DOC-001")
    args = ap.parse_args()

    if args.line is not None:
        traces = from_line(args.line, args.all)
    elif args.bank and args.vendor:
        traces = [explain_candidate(
            bank_desc=args.bank, bank_amount=args.bank_amount or 0.0, bank_date=args.bank_date,
            cand_label=args.label, cand_vendor=args.vendor,
            cand_amount=args.cand_amount or 0.0, cand_date=args.cand_date,
        )]
    else:
        console.print("[dim]No --line or --bank given — showing built-in demo cases.[/]")
        traces = from_demo()

    for i, t in enumerate(traces):
        if len(traces) > 1:
            console.rule(f"[bold]Candidate {i + 1} of {len(traces)}[/]")
        render_trace(t)


if __name__ == "__main__":
    main()
