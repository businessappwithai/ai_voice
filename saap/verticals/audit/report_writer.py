"""render_opportunity_matrix_pdf — Phase 5 Epic 5.4 (AI Audit flow):
the Report Writer agent step's non-LLM half, turning an
`OpportunityMatrix` into the client-facing PDF the plan calls for
("Opportunity Matrix JSON + rendered PDF with ROI summary").

Real PDF generation via `reportlab` (BSD-3-Clause) — no LLM call here;
the Report Writer agent's job is prose framing around this table, not
the table's own arithmetic or layout, which stays exact and
reviewable independent of any model.
"""
from __future__ import annotations

import io
from datetime import UTC, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .roi_calculator import OpportunityMatrix

_HEADER = ["Opportunity", "Current $/mo", "Automated $/mo", "Savings $/mo", "Payback (mo)"]


def render_opportunity_matrix_pdf(matrix: OpportunityMatrix, *, client_name: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()

    rows = [_HEADER]
    for o in matrix.opportunities:
        payback = f"{o.payback_months:.1f}" if o.payback_months is not None else "n/a"
        rows.append(
            [
                o.name,
                f"{o.current_monthly_cost:,.0f}",
                f"{o.automation_monthly_cost:,.0f}",
                f"{o.monthly_savings:,.0f}",
                payback,
            ]
        )
    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a2b4c")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ]
        )
    )

    story = [
        Paragraph(f"Automation Opportunity Matrix — {client_name}", styles["Title"]),
        Paragraph(f"Generated {datetime.now(UTC).strftime('%Y-%m-%d')}", styles["Normal"]),
        Spacer(1, 16),
        table,
        Spacer(1, 16),
        Paragraph(
            f"Total projected savings: ${matrix.total_monthly_savings:,.0f}/mo "
            f"(${matrix.total_annual_savings:,.0f}/yr)",
            styles["Heading2"],
        ),
    ]
    doc.build(story)
    return buffer.getvalue()
