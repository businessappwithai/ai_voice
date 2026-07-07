"""ROICalculator — Phase 5 Epic 5.4 (AI Audit flow): the Automation
Economist agent's calculation component. Turns identified manual-
process opportunities into a per-opportunity cost/benefit summary and
an aggregate Opportunity Matrix — the artifact the Report Writer agent
turns into the client-facing PDF.

Deliberately pure arithmetic, no LLM call: the plan's worked example
("20 hrs x $400/hr = $8k/mo savings", Epic 5.3) is exact math, not
something a model should be asked to estimate and possibly round wrong.
"""
from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel


class ManualProcessOpportunity(BaseModel, frozen=True):
    name: str  # "patient intake calls", "lease document sorting", ...
    hours_per_month: float
    hourly_cost: float  # fully-loaded staff cost, tenant's currency
    automation_monthly_cost: float = 0.0  # platform retainer/usage cost allocated here
    one_time_setup_cost: float = 0.0


class OpportunityROI(BaseModel, frozen=True):
    name: str
    current_monthly_cost: float
    automation_monthly_cost: float
    monthly_savings: float
    annual_savings: float
    payback_months: float | None  # None if monthly_savings <= 0 (never pays back)


class OpportunityMatrix(BaseModel, frozen=True):
    opportunities: tuple[OpportunityROI, ...]

    @property
    def total_monthly_savings(self) -> float:
        return sum(o.monthly_savings for o in self.opportunities)

    @property
    def total_annual_savings(self) -> float:
        return sum(o.annual_savings for o in self.opportunities)


class ROICalculator:
    def calculate(self, opportunity: ManualProcessOpportunity) -> OpportunityROI:
        current_monthly_cost = opportunity.hours_per_month * opportunity.hourly_cost
        monthly_savings = current_monthly_cost - opportunity.automation_monthly_cost
        payback_months = (
            opportunity.one_time_setup_cost / monthly_savings if monthly_savings > 0 else None
        )
        return OpportunityROI(
            name=opportunity.name,
            current_monthly_cost=current_monthly_cost,
            automation_monthly_cost=opportunity.automation_monthly_cost,
            monthly_savings=monthly_savings,
            annual_savings=monthly_savings * 12,
            payback_months=payback_months,
        )

    def build_matrix(self, opportunities: Sequence[ManualProcessOpportunity]) -> OpportunityMatrix:
        return OpportunityMatrix(opportunities=tuple(self.calculate(o) for o in opportunities))
