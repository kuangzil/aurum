from backend.research_agent.schemas import ResearchPlan, ResearchResult


def mock_research(query: str, plan: ResearchPlan) -> ResearchResult:
    """A fixed, generated price-index fixture. Not historical or backtested data."""
    prices = [100.0, 101.0, 100.5, 102.0, 101.5, 103.0]
    change = (prices[-1] / prices[0] - 1) * 100
    return ResearchResult(
        query=query, hypothesis=plan.hypothesis, methodology=plan.methodology,
        evidence=[
            f"SYNTHETIC fixture: six hand-authored price-index observations {prices}; no dates or market source.",
            f"SYNTHETIC arithmetic check: first-to-last index change is {change:.1f}%; this is not strategy performance.",
        ],
        findings=[
            "The fixture demonstrates data flow and arithmetic only. It cannot test the proposed hypothesis.",
            "No historical market analysis, trading simulation, or backtest was performed.",
        ],
        limitations=["Synthetic data only; no empirical evidence.", "Too few observations to test the proposed signal.", "No transaction costs, execution model, regime coverage, or statistical significance have been measured."],
    )
