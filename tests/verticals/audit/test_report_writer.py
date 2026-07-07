import io

from pypdf import PdfReader
from saap.verticals.audit.report_writer import render_opportunity_matrix_pdf
from saap.verticals.audit.roi_calculator import (
    ManualProcessOpportunity,
    OpportunityMatrix,
    ROICalculator,
)


def _matrix() -> OpportunityMatrix:
    opportunities = [
        ManualProcessOpportunity(name="Case status calls", hours_per_month=20, hourly_cost=400),
        ManualProcessOpportunity(
            name="Intake scheduling", hours_per_month=40, hourly_cost=50, automation_monthly_cost=500
        ),
    ]
    return ROICalculator().build_matrix(opportunities)


def test_render_produces_a_genuine_pdf() -> None:
    pdf_bytes = render_opportunity_matrix_pdf(_matrix(), client_name="Acme Legal")
    assert pdf_bytes.startswith(b"%PDF-")
    assert pdf_bytes.rstrip().endswith(b"%%EOF")


def test_rendered_pdf_is_parseable_and_has_one_page() -> None:
    pdf_bytes = render_opportunity_matrix_pdf(_matrix(), client_name="Acme Legal")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1


def test_rendered_pdf_contains_client_name_and_opportunity_names() -> None:
    pdf_bytes = render_opportunity_matrix_pdf(_matrix(), client_name="Acme Legal")
    text = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()
    assert "Acme Legal" in text
    assert "Case status calls" in text
    assert "Intake scheduling" in text


def test_rendered_pdf_contains_the_computed_savings_figures() -> None:
    matrix = _matrix()
    pdf_bytes = render_opportunity_matrix_pdf(matrix, client_name="Acme Legal")
    text = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text()
    # 20 hrs x $400/hr = $8,000/mo for the first opportunity (the
    # plan's own worked example); total combined monthly savings below.
    assert "8,000" in text
    assert f"{matrix.total_monthly_savings:,.0f}" in text


def test_render_of_empty_matrix_still_produces_a_valid_pdf() -> None:
    empty_matrix = ROICalculator().build_matrix([])
    pdf_bytes = render_opportunity_matrix_pdf(empty_matrix, client_name="Acme Legal")
    reader = PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "0" in text
