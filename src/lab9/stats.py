"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

from collections.abc import Sequence
import math

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def _paired_labels(human: Sequence[str], judge: Sequence[str]) -> tuple[list[str], list[str]]:
    if len(human) != len(judge):
        raise ValueError("human and judge labels must have the same length")
    h = [str(x).strip().upper() for x in human]
    j = [str(x).strip().upper() for x in judge]
    invalid = sorted((set(h) | set(j)) - {"PASS", POS})
    if invalid:
        raise ValueError(f"labels must be PASS or FAIL; got {invalid}")
    return h, j


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    h, j = _paired_labels(human, judge)
    tp = sum(a == POS and b == POS for a, b in zip(h, j))
    fp = sum(a != POS and b == POS for a, b in zip(h, j))
    fn = sum(a == POS and b != POS for a, b in zip(h, j))
    tn = sum(a != POS and b != POS for a, b in zip(h, j))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    cm = confusion(human, judge)
    precision_den = cm["tp"] + cm["fp"]
    recall_den = cm["tp"] + cm["fn"]
    precision = cm["tp"] / precision_den if precision_den else 0.0
    recall = cm["tp"] / recall_den if recall_den else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    h, j = _paired_labels(human, judge)
    n = len(h)
    if n == 0:
        raise ValueError("kappa is undefined for an empty sample")
    cm = confusion(h, j)
    observed = (cm["tp"] + cm["tn"]) / n
    human_fail = (cm["tp"] + cm["fn"]) / n
    judge_fail = (cm["tp"] + cm["fp"]) / n
    expected = human_fail * judge_fail + (1.0 - human_fail) * (1.0 - judge_fail)
    denominator = 1.0 - expected
    if math.isclose(denominator, 0.0, abs_tol=1e-12):
        raise ValueError("kappa is undefined when expected agreement is 1")
    return (observed - expected) / denominator


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    rates = (observed_rate, sensitivity, specificity)
    if any(not math.isfinite(x) or x < 0.0 or x > 1.0 for x in rates):
        raise ValueError("observed rate, sensitivity, and specificity must be between 0 and 1")
    denominator = sensitivity + specificity - 1.0
    if math.isclose(denominator, 0.0, abs_tol=1e-12):
        raise ValueError("Rogan-Gladen correction is undefined when sensitivity + specificity = 1")
    corrected = (observed_rate + specificity - 1.0) / denominator
    return min(1.0, max(0.0, corrected))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy.stats import bootstrap

    if len(a) != len(b):
        raise ValueError("paired samples must have the same length")
    if len(a) == 0:
        raise ValueError("paired bootstrap requires at least one item")
    if n_resamples < 1:
        raise ValueError("n_resamples must be positive")
    if not math.isfinite(confidence) or not 0.0 < confidence < 1.0:
        raise ValueError("confidence must be between 0 and 1")

    sample_a = np.asarray(a, dtype=float)
    sample_b = np.asarray(b, dtype=float)
    if not np.all(np.isfinite(sample_a)) or not np.all(np.isfinite(sample_b)):
        raise ValueError("paired samples must contain only finite values")
    differences = sample_a - sample_b
    delta = float(np.mean(differences))
    if np.all(differences == 0.0):
        return 0.0, 0.0, 0.0

    result = bootstrap(
        (sample_a, sample_b),
        lambda x, y: np.mean(x - y),
        paired=True,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="percentile",
        rng=np.random.default_rng(rng),
    )
    return delta, float(result.confidence_interval.low), float(result.confidence_interval.high)


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    if any(not isinstance(x, int) or isinstance(x, bool) for x in (n, c, k)):
        raise ValueError("n, c, and k must be integers")
    if n <= 0 or c < 0 or c > n or k <= 0 or k > n:
        raise ValueError("require n > 0, 0 <= c <= n, and 1 <= k <= n")
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    if any(not isinstance(x, int) or isinstance(x, bool) for x in (n, c, k)):
        raise ValueError("n, c, and k must be integers")
    if n <= 0 or c < 0 or c > n or k <= 0 or k > n:
        raise ValueError("require n > 0, 0 <= c <= n, and 1 <= k <= n")
    if c < k:
        return 0.0
    return math.comb(c, k) / math.comb(n, k)
