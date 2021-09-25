"""Scale-free / heavy-tail testing (Barabasi Network Science Ch.4; Clauset-Shalizi-Newman).

Rigorous discrete power-law fitting on the 2015 directed weighted spatial taxi
flow network. For each quantity in ``config.POWERLAW_QUANTITIES`` we run the full
CSN pipeline:

  1. Discrete MLE of the power-law exponent alpha for every candidate x_min,
     using the continuous closed form alpha = 1 + n / sum(ln(x_i / (x_min - 0.5)))
     as a warm start and then refining with the EXACT discrete log-likelihood
     (Hurwitz zeta normalization, scipy.special.zeta). x_min is chosen to
     minimize the Kolmogorov-Smirnov distance D between the empirical CCDF and
     the fitted discrete power-law CCDF over x >= x_min.
  2. A semiparametric bootstrap goodness-of-fit p-value (CSN): the power law is
     plausible only if p > 0.1 (the logic is inverted vs a usual test).
  3. Likelihood-ratio (Vuong) tests of the power law against lognormal and
     exponential alternatives on the tail x >= x_min, plus a nested
     truncated-power-law (power law with exponential cutoff) test. Each reports
     the LR statistic R, the normalized Vuong statistic, and a two-sided p.

This is NOT a 'powerlaw'-package wrapper. We try to import ``powerlaw`` only as
an optional cross-check and never depend on it.

CAVEAT (Stumpf-Porter): with only 262 zones the tail is short (often a few dozen
points), so power law vs lognormal is frequently statistically indistinguishable.
We report alpha with its KS p AND the lognormal Vuong result and refuse to claim
'scale-free' when the alternatives are tied. Degree distributions are structurally
truncated by N-1 (max in-degree 249 of ~260 possible), so a clean power law is
impossible there by construction; the scientifically central quantities are the
in/out/total STRENGTH distributions (large integers up to ~5.1M).
"""
from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd
from scipy import optimize, special

from . import common, config as C

warnings.filterwarnings("ignore")
rng = np.random.default_rng(C.SEED)

# CSN bootstrap replicates for the goodness-of-fit p-value. 1000 is the CSN
# recommendation for p accurate to ~0.01; on 262 nodes each replicate is cheap.
N_BOOTSTRAP = 1000


# ---------------------------------------------------------------------------
# Discrete power-law primitives  p(x) = x^-alpha / zeta(alpha, x_min)
# ---------------------------------------------------------------------------
def _discrete_alpha_mle(tail: np.ndarray, x_min: float) -> float:
    """Exact discrete MLE of alpha for a fixed x_min.

    The discrete MLE has no closed form: we maximize the log-likelihood
    L(alpha) = -n*ln(zeta(alpha, x_min)) - alpha*sum(ln x_i) over alpha, using
    the continuous closed-form estimate (with the -0.5 continuity correction,
    Clauset eq 3.7) as a warm start.
    """
    n = tail.size
    s_log = np.log(tail).sum()
    # Continuous closed form (warm start / sanity value).
    cont = 1.0 + n / np.sum(np.log(tail / (x_min - 0.5)))

    def neg_ll(alpha: float) -> float:
        # zeta here is the Hurwitz zeta (Riemann zeta from x_min onward).
        return n * np.log(special.zeta(alpha, x_min)) + alpha * s_log

    lo = max(1.01, cont - 1.0)
    hi = cont + 1.0
    res = optimize.minimize_scalar(neg_ll, bounds=(max(1.01, lo), max(hi, 5.0)),
                                   method="bounded")
    return float(res.x)


def _discrete_pl_ccdf(x: np.ndarray, alpha: float, x_min: float) -> np.ndarray:
    """Fitted discrete power-law CCDF P(X >= x) for x >= x_min."""
    z = special.zeta(alpha, x_min)
    return special.zeta(alpha, x) / z


def _ks_distance(tail: np.ndarray, alpha: float, x_min: float) -> float:
    """KS distance between the empirical and fitted discrete CCDF on x >= x_min."""
    xs = np.sort(tail)
    n = xs.size
    # Empirical CCDF P(X >= x) evaluated just below each observed value so the
    # step is counted: at the i-th smallest, fraction >= it is (n - i) / n + 1/n.
    emp_ccdf = 1.0 - np.arange(n) / n  # P(X >= xs[i]) = (n - i)/n
    fit_ccdf = _discrete_pl_ccdf(xs, alpha, x_min)
    return float(np.max(np.abs(emp_ccdf - fit_ccdf)))


def fit_powerlaw(data: np.ndarray):
    """Full CSN x_min scan. Returns (alpha, x_min, D, n_tail, alpha_continuous)."""
    data = np.asarray(data, dtype=float)
    data = data[data > 0]
    uniq = np.unique(data)
    # Candidate x_min values: every distinct value, but keep a tail of >= ~10
    # points so the MLE is meaningful (CSN drops the last few candidates).
    candidates = uniq[:-9] if uniq.size > 12 else uniq[:-1]
    best = None
    for x_min in candidates:
        tail = data[data >= x_min]
        if tail.size < 10:
            continue
        try:
            alpha = _discrete_alpha_mle(tail, x_min)
            D = _ks_distance(tail, alpha, x_min)
        except (ValueError, FloatingPointError):
            continue
        cont = 1.0 + tail.size / np.sum(np.log(tail / (x_min - 0.5)))
        if best is None or D < best[2]:
            best = (alpha, float(x_min), D, int(tail.size), float(cont))
    if best is None:
        # degenerate: fit on the whole support
        x_min = float(uniq.min())
        tail = data[data >= x_min]
        alpha = _discrete_alpha_mle(tail, x_min)
        D = _ks_distance(tail, alpha, x_min)
        cont = 1.0 + tail.size / np.sum(np.log(tail / (x_min - 0.5)))
        best = (alpha, x_min, D, int(tail.size), cont)
    return best


# ---------------------------------------------------------------------------
# Goodness-of-fit: CSN semiparametric bootstrap p-value
# ---------------------------------------------------------------------------
def gof_pvalue(data: np.ndarray, alpha: float, x_min: float, D_obs: float,
               n_boot: int = N_BOOTSTRAP) -> float:
    """Fraction of synthetic datasets whose KS distance >= observed D.

    Each synthetic dataset is power-law (alpha) above x_min and resampled from
    the empirical body below x_min, matching the observed fraction in the tail.
    We refit x_min/alpha on every synthetic set (full CSN), so the p-value
    accounts for the fact that x_min was itself estimated. Power law is
    plausible only if p > 0.1.
    """
    data = np.asarray(data, dtype=float)
    data = data[data > 0]
    n = data.size
    body = data[data < x_min]
    p_tail = float((data >= x_min).mean())
    n_body = body.size

    count_ge = 0
    valid = 0
    for _ in range(n_boot):
        # Each point: with prob p_tail draw from a discrete power law >= x_min,
        # else resample from the empirical body.
        n_tail = int(rng.binomial(n, p_tail))
        synth = np.empty(n)
        if n_tail > 0:
            synth[:n_tail] = _sample_discrete_pl(alpha, x_min, n_tail)
        if n - n_tail > 0:
            if n_body > 0:
                synth[n_tail:] = rng.choice(body, size=n - n_tail, replace=True)
            else:
                synth[n_tail:] = _sample_discrete_pl(alpha, x_min, n - n_tail)
        try:
            _, _, D_s, _, _ = fit_powerlaw(synth)
        except Exception:
            continue
        valid += 1
        if D_s >= D_obs:
            count_ge += 1
    if valid == 0:
        return float("nan")
    return count_ge / valid


def _sample_discrete_pl(alpha: float, x_min: float, size: int) -> np.ndarray:
    """Sample from a discrete power law p(x) ~ x^-alpha, x >= x_min, via the
    CSN approximate transform (Clauset App.D) with a discrete correction."""
    x_min = float(x_min)
    u = rng.random(size)
    # Continuous approximation, then floor to the nearest integer >= x_min.
    x = (x_min - 0.5) * (1.0 - u) ** (-1.0 / (alpha - 1.0)) + 0.5
    x = np.floor(x)
    x[x < x_min] = x_min
    return x


# ---------------------------------------------------------------------------
# Alternative-distribution tail log-likelihoods (per-point), for Vuong LR
# ---------------------------------------------------------------------------
def _ll_powerlaw(tail: np.ndarray, alpha: float, x_min: float) -> np.ndarray:
    return -alpha * np.log(tail) - np.log(special.zeta(alpha, x_min))


def _ll_exponential(tail: np.ndarray, x_min: float):
    """Discrete exponential on x >= x_min: p(x) = (1 - e^-lam) e^-lam(x - x_min)."""
    lam = 1.0 / (tail.mean() - x_min + 1.0)  # MLE for shifted geometric-like fit
    # Use the geometric (discrete exponential) normalization on integers >= x_min.
    ll = np.log(1.0 - np.exp(-lam)) - lam * (tail - x_min)
    return ll, {"lambda": float(lam)}


def _ll_lognormal(tail: np.ndarray, x_min: float):
    """Lognormal fit on the tail (continuous approximation of the discrete tail).

    MLE on ln(tail); normalized to the tail support x >= x_min via the
    upper-tail survival of the normal, which is the standard CSN treatment.
    """
    lx = np.log(tail)
    mu = lx.mean()
    sigma = lx.std(ddof=0)
    sigma = max(sigma, 1e-9)
    # Density of a lognormal, conditioned on X >= x_min (truncation constant).
    # log f(x) = -ln(x) - ln(sigma) - 0.5 ln(2pi) - (ln x - mu)^2 / (2 sigma^2)
    log_f = (-np.log(tail) - np.log(sigma) - 0.5 * np.log(2 * np.pi)
             - (lx - mu) ** 2 / (2 * sigma ** 2))
    # Conditioning constant: P(X >= x_min) under the fitted lognormal.
    z = (np.log(x_min) - mu) / sigma
    surv = 0.5 * special.erfc(z / np.sqrt(2))
    surv = max(surv, 1e-300)
    ll = log_f - np.log(surv)
    return ll, {"mu": float(mu), "sigma": float(sigma)}


def _ll_truncated_pl(tail: np.ndarray, x_min: float):
    """Power law with exponential cutoff: p(x) ~ x^-alpha e^-lam x, x >= x_min.

    Nested in the pure power law (lambda -> 0). MLE over (alpha, lambda) by
    numerical optimization with a discrete normalization computed over a finite
    integer grid from x_min upward.
    """
    x_min = float(x_min)
    hi = float(tail.max()) * 4 + 100
    grid = np.arange(int(x_min), int(hi) + 1, dtype=float)

    def neg_ll(params):
        a, lam = params
        if a <= 0.0 or lam < 0.0:
            return 1e18
        logw = -a * np.log(grid) - lam * grid
        m = logw.max()
        Z = np.exp(m) * np.exp(logw - m).sum()
        if Z <= 0 or not np.isfinite(Z):
            return 1e18
        ll = (-a * np.log(tail) - lam * tail - np.log(Z)).sum()
        return -ll

    res = optimize.minimize(neg_ll, x0=[2.0, 1e-4], method="Nelder-Mead",
                            options={"maxiter": 2000, "xatol": 1e-6, "fatol": 1e-6})
    a, lam = res.x
    logw = -a * np.log(grid) - lam * grid
    m = logw.max()
    Z = np.exp(m) * np.exp(logw - m).sum()
    ll = -a * np.log(tail) - lam * tail - np.log(Z)
    return ll, {"alpha": float(a), "lambda": float(lam)}


def vuong_test(ll_pl: np.ndarray, ll_alt: np.ndarray):
    """Normalized (non-nested) Vuong likelihood-ratio test.

    R = sum(ll_pl - ll_alt). V = R / (sqrt(n) * s) with s the std of the
    per-point differences. Two-sided p = erfc(|V| / sqrt(2)). R > 0 favours the
    power law; p says whether the sign is significant.
    """
    li = ll_pl - ll_alt
    R = float(li.sum())
    n = li.size
    s = float(li.std(ddof=0))
    if s < 1e-12:
        return R, float("nan"), float("nan")
    V = R / (np.sqrt(n) * s)
    p = float(special.erfc(abs(V) / np.sqrt(2)))
    return R, float(V), p


def nested_lr_test(ll_pl: np.ndarray, ll_trunc: np.ndarray):
    """Nested LR test: truncated PL (2 params) vs pure PL (1 param).

    LR = 2 * (LL_trunc - LL_pl) >= 0. One extra free parameter -> chi-square_1
    null. Small p means the cutoff term is a significant improvement (i.e. a
    pure power law is rejected in favour of a cutoff)."""
    LR = 2.0 * float(ll_trunc.sum() - ll_pl.sum())
    LR = max(LR, 0.0)
    p = float(special.gammaincc(0.5, LR / 2.0))  # chi2 sf with df=1
    return LR, p


def _verdict(p_gof: float, R_ln: float, p_ln: float, alpha: float = float("nan")) -> str:
    """One-line honest classification."""
    plausible = (not np.isnan(p_gof)) and p_gof > 0.1
    if not plausible:
        head = f"power law REJECTED by KS bootstrap (p_gof={p_gof:.3f})"
    else:
        head = f"power law plausible (p_gof={p_gof:.3f})"
    if np.isnan(p_ln) or p_ln > 0.1:
        tail = f"power law NOT distinguishable from lognormal (Vuong p={p_ln:.3f})"
    elif R_ln > 0:
        tail = f"power law favoured over lognormal (R={R_ln:.1f}, p={p_ln:.3f})"
    else:
        tail = f"lognormal favoured over power law (R={R_ln:.1f}, p={p_ln:.3f})"
    out = f"{head}; {tail}"
    # Barabasi Ch.4: alpha < 2 is the divergent-mean regime; a fitted alpha below 2
    # is itself evidence the pure power-law model is strained (the first moment
    # does not converge), independent of the GoF/Vuong outcome.
    if (not np.isnan(alpha)) and alpha < 2:
        out += f"; CAVEAT alpha={alpha:.2f} < 2 (divergent-mean regime, pure power law strained)"
    return out


# ---------------------------------------------------------------------------
# Per-quantity driver
# ---------------------------------------------------------------------------
def analyze_quantity(name: str, data: np.ndarray) -> dict:
    data = np.asarray(data, dtype=float)
    data = data[data > 0]
    alpha, x_min, D, n_tail, alpha_cont = fit_powerlaw(data)
    tail = data[data >= x_min]

    p_gof = gof_pvalue(data, alpha, x_min, D)

    ll_pl = _ll_powerlaw(tail, alpha, x_min)
    ll_ln, ln_par = _ll_lognormal(tail, x_min)
    ll_exp, exp_par = _ll_exponential(tail, x_min)
    ll_tpl, tpl_par = _ll_truncated_pl(tail, x_min)

    R_ln, V_ln, p_ln = vuong_test(ll_pl, ll_ln)
    R_exp, V_exp, p_exp = vuong_test(ll_pl, ll_exp)
    LR_tpl, p_tpl = nested_lr_test(ll_pl, ll_tpl)

    return {
        "quantity": name,
        "n": int(data.size),
        "alpha": round(alpha, 4),
        "alpha_continuous": round(alpha_cont, 4),
        "xmin": x_min,
        "D": round(D, 4),
        "n_tail": n_tail,
        "p_gof": round(p_gof, 4) if not np.isnan(p_gof) else None,
        "powerlaw_plausible": bool((not np.isnan(p_gof)) and p_gof > 0.1),
        # Vuong vs lognormal
        "R_lognormal": round(R_ln, 4),
        "V_lognormal": round(V_ln, 4) if not np.isnan(V_ln) else None,
        "p_lognormal": round(p_ln, 4) if not np.isnan(p_ln) else None,
        # Vuong vs exponential
        "R_exponential": round(R_exp, 4),
        "V_exponential": round(V_exp, 4) if not np.isnan(V_exp) else None,
        "p_exponential": round(p_exp, 4) if not np.isnan(p_exp) else None,
        # nested truncated power law (cutoff)
        "LR_truncated": round(LR_tpl, 4),
        "p_truncated": round(p_tpl, 4),
        "lognormal_mu": round(ln_par["mu"], 4),
        "lognormal_sigma": round(ln_par["sigma"], 4),
        "verdict": _verdict(p_gof, R_ln, p_ln, alpha),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    g = common.load_graph()  # 2015, self-loops dropped
    active = set(g.nodes())
    nodes = common.load_nodes()
    nodes = nodes[nodes["zone_id"].isin(active)].copy()
    nodes["total_strength"] = nodes["out_strength"] + nodes["in_strength"]

    # cross-check availability of the optional powerlaw package
    try:
        import powerlaw  # noqa: F401
        have_pl = True
    except Exception:
        have_pl = False

    rows = []
    for q in C.POWERLAW_QUANTITIES:
        data = nodes[q].to_numpy()
        res = analyze_quantity(q, data)
        rows.append(res)

    df = pd.DataFrame(rows)
    out = C.PROCESSED / "powerlaw_fits.parquet"
    df.to_parquet(out, index=False)

    # persist headline numbers
    record_payload = {r["quantity"]: r for r in rows}
    record_payload["_meta"] = {
        "n_bootstrap": N_BOOTSTRAP,
        "method": "Clauset-Shalizi-Newman discrete MLE; Vuong LR vs lognormal/exponential; nested LR vs truncated PL",
        "powerlaw_package_available": have_pl,
        "n_nodes": int(len(active)),
        "note": ("Strength distributions are the scientifically central quantities; "
                 "degree distributions are structurally truncated by N-1 so a clean "
                 "power law is impossible there. Short tail (262 nodes) limits power "
                 "to distinguish power law from lognormal."),
    }
    common.record("scalefree", record_payload)

    # console highlights, analysis.py style
    print(f"[scalefree] CSN discrete power-law fits ({len(active)} active nodes, "
          f"powerlaw pkg cross-check {'available' if have_pl else 'absent'}):")
    for r in rows:
        print(f"  {r['quantity']:14s} alpha={r['alpha']:.3f} xmin={r['xmin']:.0f} "
              f"D={r['D']:.3f} n_tail={r['n_tail']:3d} "
              f"p_gof={r['p_gof'] if r['p_gof'] is not None else float('nan')}")
        print(f"                 -> {r['verdict']}")
    print(f"[scalefree] wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
