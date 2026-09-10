"""Turning an opportunity's cost and income bands into a bankable projection.

A project report is only taken seriously if it answers the four questions a
credit officer actually asks: what does it cost, where does the money come
from, what does it earn year by year, and can it service the loan. This module
produces exactly those, from the mid-point of the knowledge base's ranges
scaled to the farmer's own plot.

Everything is deliberately conservative and deliberately simple:

* income is nil until the gestation period ends and then ramps to full;
* maintenance cost is charged from year one, including while nothing is
  earning, because that is what actually happens in an orchard;
* the loan is repaid in equal principal instalments after a moratorium that
  matches the gestation, which is how agricultural term loans are normally
  structured;
* nothing is discounted and no subsidy is assumed, so a sanctioned subsidy can
  only improve the picture rather than being needed to make it work.

Interest and margin are inputs, not constants, because they are the bank's to
set. The defaults are ordinary agricultural term-loan terms and are stated in
the report as assumptions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .opportunities import Economics, revenue_factor

#: A bank funds part of the cost; the promoter brings the rest. 25% is a
#: common margin for an agricultural term loan of this size.
DEFAULT_MARGIN = 0.25

#: Ordinary agri term-loan rate. Shown in the report as an assumption so a
#: farmer can see immediately what a different rate would do.
DEFAULT_INTEREST_RATE = 0.11

#: Contingency on capital cost. Real quotations always come in above estimate.
CONTINGENCY_RATE = 0.05

#: What an orchard costs to keep alive in a year it earns nothing.
GESTATION_OPEX_FACTOR = 0.6

#: Longest repayment a bank will normally write for a farm term loan.
MAX_REPAYMENT_YEARS = 9


@dataclass(frozen=True)
class LoanTerms:
    margin: float = DEFAULT_MARGIN
    interest_rate: float = DEFAULT_INTEREST_RATE
    repayment_years: int | None = None
    moratorium_years: int | None = None


@dataclass
class CostLine:
    key: str
    amount: float


@dataclass
class ProjectionYear:
    year: int
    revenue: float
    operating_cost: float
    gross_surplus: float
    interest: float
    depreciation: float
    net_surplus: float
    opening_balance: float
    principal_repaid: float
    closing_balance: float
    debt_service: float
    dscr: float | None


@dataclass
class Financials:
    capital_cost: float
    contingency: float
    working_capital: float
    total_project_cost: float

    promoter_contribution: float
    term_loan: float
    margin: float
    interest_rate: float
    repayment_years: int
    moratorium_years: int

    projection: list[ProjectionYear] = field(default_factory=list)

    average_dscr: float | None = None
    minimum_dscr: float | None = None
    break_even_capacity: float | None = None
    payback_years: float | None = None
    net_at_full_yield: float = 0.0
    return_on_cost: float | None = None


def build(
    economics: Economics,
    terms: LoanTerms | None = None,
    *,
    horizon_years: int | None = None,
) -> Financials:
    """Produce the full cost, finance, projection and repayment picture."""
    terms = terms or LoanTerms()

    capital_cost = economics.capex.mid
    contingency = capital_cost * CONTINGENCY_RATE
    working_capital = economics.working_capital
    total_project_cost = capital_cost + contingency + working_capital

    margin = min(max(terms.margin, 0.0), 1.0)
    promoter_contribution = total_project_cost * margin
    term_loan = total_project_cost - promoter_contribution

    # A loan is not written for longer than the asset lasts, nor beyond what a
    # bank will normally allow.
    repayment_years = terms.repayment_years or min(
        MAX_REPAYMENT_YEARS, max(3, economics.project_life_years)
    )

    # Principal cannot start falling due before the project earns anything.
    natural_moratorium = math.ceil(economics.gestation_months / 12)
    moratorium_years = terms.moratorium_years
    if moratorium_years is None:
        moratorium_years = natural_moratorium
    moratorium_years = max(0, min(moratorium_years, repayment_years - 1))

    horizon = horizon_years or max(repayment_years, economics.full_yield_year, 5)

    full_revenue = economics.revenue_per_year.mid
    full_opex = economics.opex_per_year.mid
    # Depreciation is written over the life of the asset, not the loan.
    depreciation = (capital_cost + contingency) / max(economics.project_life_years, 1)

    repaying_years = repayment_years - moratorium_years
    principal_instalment = term_loan / repaying_years if repaying_years > 0 else 0.0

    projection: list[ProjectionYear] = []
    balance = term_loan
    dscr_values: list[float] = []
    cumulative_net = 0.0
    payback_years: float | None = None

    for year in range(1, horizon + 1):
        factor = revenue_factor(
            year, economics.gestation_months, economics.full_yield_year
        )
        revenue = full_revenue * factor
        operating_cost = full_opex * (1.0 if factor > 0 else GESTATION_OPEX_FACTOR)
        gross_surplus = revenue - operating_cost

        opening = balance
        interest = opening * terms.interest_rate
        principal = (
            min(principal_instalment, balance)
            if year > moratorium_years and balance > 0
            else 0.0
        )
        balance = max(0.0, balance - principal)

        net_surplus = gross_surplus - interest - depreciation
        debt_service = interest + principal
        # Cash available to service debt is the surplus before the two charges
        # that are not cash going out this year.
        available = net_surplus + depreciation + interest
        # Quoted only for years principal actually falls due, which is how a
        # credit officer reads it. During the moratorium the project is not yet
        # earning and the ratio would be a meaningless negative number; the
        # cost of that period is shown in the profitability table instead.
        dscr = available / debt_service if principal > 0 and debt_service > 0 else None
        if dscr is not None:
            dscr_values.append(dscr)

        if payback_years is None:
            cash = gross_surplus
            if cumulative_net + cash >= total_project_cost and cash > 0:
                shortfall = total_project_cost - cumulative_net
                payback_years = (year - 1) + shortfall / cash
            cumulative_net += cash

        projection.append(
            ProjectionYear(
                year=year,
                revenue=revenue,
                operating_cost=operating_cost,
                gross_surplus=gross_surplus,
                interest=interest,
                depreciation=depreciation,
                net_surplus=net_surplus,
                opening_balance=opening,
                principal_repaid=principal,
                closing_balance=balance,
                debt_service=debt_service,
                dscr=dscr,
            )
        )

    net_at_full_yield = full_revenue - full_opex

    # Break-even: the share of full production at which the project still
    # covers the charges that do not shrink when output does.
    contribution = full_revenue - full_opex
    fixed_charges = depreciation + (term_loan * terms.interest_rate)
    break_even = fixed_charges / contribution if contribution > 0 else None

    return Financials(
        capital_cost=capital_cost,
        contingency=contingency,
        working_capital=working_capital,
        total_project_cost=total_project_cost,
        promoter_contribution=promoter_contribution,
        term_loan=term_loan,
        margin=margin,
        interest_rate=terms.interest_rate,
        repayment_years=repayment_years,
        moratorium_years=moratorium_years,
        projection=projection,
        average_dscr=(sum(dscr_values) / len(dscr_values)) if dscr_values else None,
        minimum_dscr=min(dscr_values) if dscr_values else None,
        break_even_capacity=break_even,
        payback_years=payback_years,
        net_at_full_yield=net_at_full_yield,
        return_on_cost=(
            net_at_full_yield / total_project_cost if total_project_cost > 0 else None
        ),
    )
