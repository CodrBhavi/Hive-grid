"""Metrics for a completed simulation."""
def jain(values: list[float]) -> float:
    values = [max(0.0, float(v)) for v in values]
    return (sum(values) ** 2 / (len(values) * sum(v*v for v in values))) if values and sum(v*v for v in values) else 1.0
def summarize(baseline_peak: float, peak: float, solar: float, self_used: float, costs: list[float], base_costs: list[float], comforts: list[float]) -> dict:
    savings = [b-c for b,c in zip(base_costs,costs)]
    return {"baseline_peak_kw": baseline_peak, "peak_kw": peak, "peak_reduction_pct": 100*(baseline_peak-peak)/baseline_peak if baseline_peak else 0,
            "solar_self_consumption_pct": 100*self_used/solar if solar else 0, "total_cost": sum(costs), "baseline_cost": sum(base_costs),
            "cost_saved_pct": 100*(sum(base_costs)-sum(costs))/sum(base_costs) if sum(base_costs) else 0,
            "jain_comfort": jain(comforts), "jain_savings": jain(savings), "worst_home_savings": min(savings, default=0), "violations": 0}
