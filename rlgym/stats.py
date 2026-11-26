"""Small statistics helpers shared by the evaluation CLIs."""
from math import sqrt
from typing import Tuple


def wilson(successes: float, n: int, z: float = 1.96) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion (95% by default)."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
