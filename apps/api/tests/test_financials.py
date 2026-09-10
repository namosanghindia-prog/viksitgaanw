"""The projection that goes in front of a bank.

A credit officer checks four things: that the cost adds up, that the loan is
repaid by the end of the schedule, that the DSCR is quoted for the years it
means something, and that nothing earns before it can. These tests hold those.
"""

from __future__ import annotations

import pytest

from app import knowledge
from app.services import financials as money
from app.services.opportunities import compute_economics, compute_sizing


def _economics(code: str, hectares: float = 1.2):
    from app.services.opportunities import LandProfile

    opportunity = knowledge.get_opportunity(code)
    assert opportunity is not None
    land = LandProfile(area_hectares=hectares, state_code="9")
    return compute_economics(opportunity, compute_sizing(opportunity, land))


def test_project_cost_is_the_sum_of_its_parts():
    plan = money.build(_economics("guava_meadow"))
    assert plan.total_project_cost == pytest.approx(
        plan.capital_cost + plan.contingency + plan.working_capital
    )
    assert plan.contingency == pytest.approx(plan.capital_cost * money.CONTINGENCY_RATE)


def test_finance_splits_into_margin_and_loan():
    plan = money.build(_economics("guava_meadow"), money.LoanTerms(margin=0.25))
    assert plan.promoter_contribution == pytest.approx(plan.total_project_cost * 0.25)
    assert plan.promoter_contribution + plan.term_loan == pytest.approx(
        plan.total_project_cost
    )


def test_the_loan_is_fully_repaid_by_the_end_of_the_schedule():
    plan = money.build(_economics("guava_meadow"))
    final = plan.projection[plan.repayment_years - 1]
    assert final.closing_balance == pytest.approx(0.0, abs=1.0)
    assert sum(row.principal_repaid for row in plan.projection) == pytest.approx(
        plan.term_loan, rel=1e-6
    )


def test_no_principal_falls_due_during_the_moratorium():
    plan = money.build(_economics("mango_orchard_hd"))
    assert plan.moratorium_years >= 1
    for row in plan.projection[: plan.moratorium_years]:
        assert row.principal_repaid == 0.0


def test_the_moratorium_covers_the_gestation():
    """Principal cannot start before the trees have fruited."""
    economics = _economics("mango_orchard_hd")
    plan = money.build(economics)
    assert plan.moratorium_years >= min(
        economics.gestation_months // 12, plan.repayment_years - 1
    )


def test_dscr_is_quoted_only_for_repayment_years():
    """During the moratorium the ratio would be a meaningless negative number."""
    plan = money.build(_economics("mango_orchard_hd"))
    for row in plan.projection:
        if row.principal_repaid == 0:
            assert row.dscr is None
        else:
            assert row.dscr is not None


def test_average_dscr_ignores_the_moratorium_years():
    plan = money.build(_economics("guava_meadow"))
    quoted = [row.dscr for row in plan.projection if row.dscr is not None]
    assert plan.average_dscr == pytest.approx(sum(quoted) / len(quoted))


def test_nothing_is_earned_during_the_gestation_but_upkeep_is_still_paid():
    plan = money.build(_economics("mango_orchard_hd"))
    first = plan.projection[0]
    assert first.revenue == 0.0
    assert first.operating_cost > 0.0
    assert first.gross_surplus < 0.0


def test_a_longer_repayment_lowers_the_yearly_instalment():
    economics = _economics("guava_meadow")
    short = money.build(economics, money.LoanTerms(repayment_years=5))
    long = money.build(economics, money.LoanTerms(repayment_years=9))
    assert short.projection[4].principal_repaid > long.projection[4].principal_repaid


def test_a_higher_margin_shrinks_the_loan_and_the_interest():
    economics = _economics("guava_meadow")
    light = money.build(economics, money.LoanTerms(margin=0.15))
    heavy = money.build(economics, money.LoanTerms(margin=0.50))
    assert heavy.term_loan < light.term_loan
    assert heavy.projection[0].interest < light.projection[0].interest


def test_break_even_is_a_fraction_of_capacity():
    plan = money.build(_economics("guava_meadow"))
    assert plan.break_even_capacity is not None
    assert 0 < plan.break_even_capacity < 1


def test_payback_matches_the_ramped_income_not_the_full_yield():
    economics = _economics("mango_orchard_hd")
    plan = money.build(economics)
    assert plan.payback_years is not None
    # A forty-eight month gestation means payback cannot land in year three.
    assert plan.payback_years > economics.gestation_months / 12


def test_the_schedule_covers_at_least_the_repayment_period():
    plan = money.build(_economics("guava_meadow"))
    assert len(plan.projection) >= plan.repayment_years
