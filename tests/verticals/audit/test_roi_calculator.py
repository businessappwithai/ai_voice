from saap.verticals.audit.roi_calculator import ManualProcessOpportunity, ROICalculator


def test_matches_the_plans_worked_example_20_hours_at_400_per_hour() -> None:
    # implementation-plan.md Epic 5.3: "20 hrs x $400 = $8k/mo savings"
    opportunity = ManualProcessOpportunity(name="case status calls", hours_per_month=20, hourly_cost=400)
    result = ROICalculator().calculate(opportunity)

    assert result.current_monthly_cost == 8000
    assert result.monthly_savings == 8000
    assert result.annual_savings == 96000


def test_monthly_savings_subtracts_automation_cost() -> None:
    opportunity = ManualProcessOpportunity(
        name="intake", hours_per_month=40, hourly_cost=50, automation_monthly_cost=500
    )
    result = ROICalculator().calculate(opportunity)

    assert result.current_monthly_cost == 2000
    assert result.monthly_savings == 1500
    assert result.annual_savings == 18000


def test_payback_months_is_setup_cost_over_monthly_savings() -> None:
    opportunity = ManualProcessOpportunity(
        name="triage",
        hours_per_month=40,
        hourly_cost=50,
        automation_monthly_cost=500,
        one_time_setup_cost=3000,
    )
    result = ROICalculator().calculate(opportunity)

    assert result.monthly_savings == 1500
    assert result.payback_months == 2.0


def test_payback_months_is_none_when_automation_costs_more_than_it_saves() -> None:
    opportunity = ManualProcessOpportunity(
        name="overkill", hours_per_month=5, hourly_cost=20, automation_monthly_cost=1000
    )
    result = ROICalculator().calculate(opportunity)

    assert result.monthly_savings < 0
    assert result.payback_months is None


def test_payback_months_is_zero_when_savings_are_immediate_with_no_setup_cost() -> None:
    opportunity = ManualProcessOpportunity(name="free_win", hours_per_month=10, hourly_cost=100)
    result = ROICalculator().calculate(opportunity)

    assert result.payback_months == 0.0


def test_build_matrix_aggregates_across_opportunities() -> None:
    opportunities = [
        ManualProcessOpportunity(name="intake", hours_per_month=20, hourly_cost=400),
        ManualProcessOpportunity(name="scheduling", hours_per_month=10, hourly_cost=100),
    ]
    matrix = ROICalculator().build_matrix(opportunities)

    assert [o.name for o in matrix.opportunities] == ["intake", "scheduling"]
    assert matrix.total_monthly_savings == 8000 + 1000
    assert matrix.total_annual_savings == (8000 + 1000) * 12


def test_build_matrix_of_empty_opportunities_has_zero_totals() -> None:
    matrix = ROICalculator().build_matrix([])

    assert matrix.opportunities == ()
    assert matrix.total_monthly_savings == 0
    assert matrix.total_annual_savings == 0
