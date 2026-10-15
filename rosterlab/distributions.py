from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

from .models import DistributionSummary


def quantile(sorted_values: Sequence[float], probability: float) -> float:
    if not sorted_values:
        return 0.0
    probability = min(1.0, max(0.0, probability))
    position = (len(sorted_values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(sorted_values[lower])
    weight = position - lower
    return float(sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight)


def summarize(values: Iterable[float]) -> DistributionSummary:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        return DistributionSummary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    count = len(ordered)
    mean = sum(ordered) / count
    variance = sum((value - mean) ** 2 for value in ordered) / count
    tail_count = max(1, int(math.ceil(count * 0.10)))
    return DistributionSummary(
        count=count,
        mean=mean,
        stdev=math.sqrt(variance),
        minimum=ordered[0],
        p10=quantile(ordered, 0.10),
        p25=quantile(ordered, 0.25),
        p50=quantile(ordered, 0.50),
        p75=quantile(ordered, 0.75),
        p90=quantile(ordered, 0.90),
        maximum=ordered[-1],
        cvar10=sum(ordered[:tail_count]) / tail_count,
        cvar90=sum(ordered[-tail_count:]) / tail_count,
    )


def paired_deltas(baseline: Sequence[float], candidate: Sequence[float]) -> Tuple[float, ...]:
    if len(baseline) != len(candidate):
        raise ValueError("Paired simulations must contain the same number of worlds")
    return tuple(candidate[index] - baseline[index] for index in range(len(baseline)))


def probability_positive(values: Sequence[float]) -> float:
    return sum(1 for value in values if value > 0.0) / len(values) if values else 0.0


def probability_negative(values: Sequence[float]) -> float:
    return sum(1 for value in values if value < 0.0) / len(values) if values else 0.0
