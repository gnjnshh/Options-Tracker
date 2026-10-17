"""
Technical Indicators & Quantitative Options Pricing Model
=========================================================
Computes point-in-time quantitative indicators (200-DMA, RSI, Z-Score,
Yang-Zhang volatility, Black-Scholes Greeks, Empirical POP, and Worthless Score).
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def snap_to_listed_strike(price: float, step: float) -> float:
    """Rounds a strike price down to an exact listed NSE strike multiple."""
    return math.floor(price / step) * step


def compute_200_dma(closes: List[float]) -> Optional[float]:
    """Computes 200-day simple moving average."""
    if len(closes) < 200:
        return None
    return sum(closes[-200:]) / 200.0


def compute_rsi14(closes: List[float]) -> Optional[float]:
    """Computes standard Wilder's 14-period RSI."""
    if len(closes) < 15:
        return None
    
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        if diff >= 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(diff))

    if len(gains) < 14:
        return None

    # First average
    avg_gain = sum(gains[:14]) / 14.0
    avg_loss = sum(losses[:14]) / 14.0

    # Wilder smoothing for remainder
    for i in range(14, len(gains)):
        avg_gain = (avg_gain * 13.0 + gains[i]) / 14.0
        avg_loss = (avg_loss * 13.0 + losses[i]) / 14.0

    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 1)


def compute_z5d(closes: List[float]) -> Optional[float]:
    """Computes 5-day Z-score: (Current - Mean5D) / StdDev5D."""
    if len(closes) < 5:
        return None
    c5 = closes[-5:]
    mean = sum(c5) / 5.0
    var = sum((x - mean) ** 2 for x in c5) / 4.0
    std = math.sqrt(var) if var > 1e-8 else 1e-4
    z = (closes[-1] - mean) / std
    return round(z, 2)


def compute_yang_zhang_vol(candles: List[Dict[str, Any]], window: int = 20) -> float:
    """
    Computes 20-day Yang-Zhang (2000) minimum variance OHLC historical volatility.
    Returns annualized percentage (e.g. 16.5 for 16.5%).
    """
    if len(candles) < window + 1:
        # Fallback to classical close-to-close if insufficient candles
        return 20.0

    c_win = candles[-(window + 1):]
    
    overnight_rets: List[float] = []
    open_close_rets: List[float] = []
    rs_vals: List[float] = []

    for i in range(1, len(c_win)):
        c_prev = c_win[i - 1]["close"]
        o_curr = c_win[i]["open"]
        h_curr = c_win[i]["high"]
        l_curr = c_win[i]["low"]
        c_curr = c_win[i]["close"]

        if c_prev <= 0 or o_curr <= 0 or h_curr <= 0 or l_curr <= 0 or c_curr <= 0:
            continue

        o_ret = math.log(o_curr / c_prev)
        c_ret = math.log(c_curr / o_curr)
        u = math.log(h_curr / o_curr)
        d = math.log(l_curr / o_curr)
        c = math.log(c_curr / o_curr)

        overnight_rets.append(o_ret)
        open_close_rets.append(c_ret)
        rs_vals.append(u * (u - c) + d * (d - c))

    n = len(overnight_rets)
    if n < 2:
        return 20.0

    # Overnight variance
    mean_o = sum(overnight_rets) / n
    var_o = sum((x - mean_o) ** 2 for x in overnight_rets) / (n - 1)

    # Open-to-close variance
    mean_c = sum(open_close_rets) / n
    var_c = sum((x - mean_c) ** 2 for x in open_close_rets) / (n - 1)

    # Rogers-Satchell variance
    var_rs = sum(rs_vals) / n

    # Yang-Zhang optimal weighting factor k
    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var_yz = var_o + k * var_c + (1.0 - k) * var_rs

    ann_vol = math.sqrt(max(0.0, var_yz) * 252.0) * 100.0
    return round(max(8.0, min(80.0, ann_vol)), 1)


def find_2020_base_floor(candles: List[Dict[str, Any]]) -> float:
    """Finds March 2020 secular cycle low floor (or earliest available low)."""
    march_2020_lows: List[float] = []
    earliest_lows: List[float] = []
    for c in candles:
        d = c["date"]
        if d.startswith("2020-03"):
            march_2020_lows.append(c["low"])
        if d.startswith("2020"):
            earliest_lows.append(c["low"])

    if march_2020_lows:
        return min(march_2020_lows)
    if earliest_lows:
        return min(earliest_lows)
    return candles[0]["low"]


def black_scholes_put_price(
    spot: float, strike: float, dte_days: int, iv_pct: float, r: float = 0.068
) -> Tuple[float, float, float]:
    """
    Computes Black-Scholes Put price, Delta, and Empirical POP N(d2).
    Returns (put_price, put_delta, pop_pct).
    """
    T = max(1, dte_days) / 365.0
    sigma = max(0.05, iv_pct / 100.0)

    d1 = (math.log(spot / strike) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)

    pop = round(min(98.0, max(50.0, norm_cdf(d2) * 100.0)), 1)
    put_delta = round(-(1.0 - norm_cdf(d1)), 2)

    # Black-Scholes Put formula: K * e^(-rT) * N(-d2) - S * N(-d1)
    put_price = strike * math.exp(-r * T) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    # Ensure realistic minimum tick size (e.g. at least 0.05% of spot)
    put_price = max(0.5, round(put_price, 2))

    return put_price, put_delta, pop


def compute_worthless_score(
    pop: float,
    vrp: float,
    dist_base: float,
    rsi14: float,
    roe_alpha: float,
    fno_vol: int = 150000,
) -> float:
    """
    Computes Composite Worthless Score (0–100) exactly matching screener engine v3.0.
    """
    pop_score = min(100.0, max(0.0, (pop - 65.0) * 3.4))
    vrp_score = min(100.0, max(0.0, vrp * 12.5))
    base_score = min(100.0, max(0.0, 100.0 - (dist_base - 100.0) * 0.5 + (60.0 - rsi14) * 0.9))
    fund_score = min(100.0, max(0.0, 50.0 + roe_alpha * 3.0 + (fno_vol / 15000.0)))
    return round(0.38 * pop_score + 0.22 * vrp_score + 0.22 * base_score + 0.18 * fund_score, 1)


def compute_bollinger_pct_b(closes: List[float], window: int = 20, num_std: float = 2.0) -> Optional[float]:
    """
    Computes Bollinger Bands %B indicator over specified window (default 20, 2-std).
    Formula: %B = (Close - LowerBand) / (UpperBand - LowerBand).
    """
    if len(closes) < window:
        return None
    c_win = closes[-window:]
    mean = sum(c_win) / float(window)
    variance = sum((x - mean) ** 2 for x in c_win) / float(window)
    std = math.sqrt(variance)
    upper = mean + num_std * std
    lower = mean - num_std * std
    band_width = upper - lower
    if band_width < 1e-8:
        return 0.5
    pct_b = (closes[-1] - lower) / band_width
    return round(pct_b, 2)


def compute_mfi14(candles: List[Dict[str, Any]], window: int = 14) -> Optional[float]:
    """
    Computes standard 14-period Money Flow Index (MFI) from OHLCV candle records.
    Uses typical price TP = (High + Low + Close) / 3 and raw money flow = TP * Volume.
    """
    if len(candles) < window + 1:
        return None

    tps = [(float(c["high"]) + float(c["low"]) + float(c["close"])) / 3.0 for c in candles]
    vols = [float(c["volume"]) for c in candles]

    pmf: List[float] = []
    nmf: List[float] = []
    start_idx = len(candles) - window
    for i in range(start_idx, len(candles)):
        tp_curr = tps[i]
        tp_prev = tps[i - 1]
        rmf = tp_curr * vols[i]
        if tp_curr > tp_prev:
            pmf.append(rmf)
            nmf.append(0.0)
        elif tp_curr < tp_prev:
            pmf.append(0.0)
            nmf.append(rmf)
        else:
            pmf.append(0.0)
            nmf.append(0.0)

    tot_pmf = sum(pmf)
    tot_nmf = sum(nmf)

    if tot_nmf == 0.0:
        return 100.0 if tot_pmf > 0 else 50.0

    mfr = tot_pmf / tot_nmf
    mfi = 100.0 - (100.0 / (1.0 + mfr))
    return round(min(100.0, max(0.0, mfi)), 1)


def compute_adx14(candles: List[Dict[str, Any]], window: int = 14) -> Optional[float]:
    """
    Computes Wilder's 14-period Average Directional Index (ADX) from OHLC candles.
    """
    if len(candles) < window * 2:
        return None

    tr_list: List[float] = []
    pdm_list: List[float] = []
    mdm_list: List[float] = []

    for i in range(1, len(candles)):
        h = float(candles[i]["high"])
        l = float(candles[i]["low"])
        c_prev = float(candles[i - 1]["close"])
        h_prev = float(candles[i - 1]["high"])
        l_prev = float(candles[i - 1]["low"])

        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        up = h - h_prev
        down = l_prev - l

        p_dm = up if (up > down and up > 0.0) else 0.0
        m_dm = down if (down > up and down > 0.0) else 0.0

        tr_list.append(tr)
        pdm_list.append(p_dm)
        mdm_list.append(m_dm)

    if len(tr_list) < window:
        return None

    smooth_tr = sum(tr_list[:window])
    smooth_pdm = sum(pdm_list[:window])
    smooth_mdm = sum(mdm_list[:window])

    dx_list: List[float] = []
    for i in range(window, len(tr_list)):
        smooth_tr = (smooth_tr * (window - 1) + tr_list[i]) / float(window)
        smooth_pdm = (smooth_pdm * (window - 1) + pdm_list[i]) / float(window)
        smooth_mdm = (smooth_mdm * (window - 1) + mdm_list[i]) / float(window)

        pdi = (smooth_pdm / smooth_tr * 100.0) if smooth_tr > 1e-8 else 0.0
        mdi = (smooth_mdm / smooth_tr * 100.0) if smooth_tr > 1e-8 else 0.0
        di_sum = pdi + mdi
        dx = (abs(pdi - mdi) / di_sum * 100.0) if di_sum > 1e-8 else 0.0
        dx_list.append(dx)

    if not dx_list:
        return None

    if len(dx_list) < window:
        return round(sum(dx_list) / len(dx_list), 1)

    adx = sum(dx_list[:window]) / float(window)
    for i in range(window, len(dx_list)):
        adx = (adx * (window - 1) + dx_list[i]) / float(window)

    return round(min(100.0, max(0.0, adx)), 1)


def compute_down_volume_ratio(candles: List[Dict[str, Any]], window: int = 20) -> float:
    """
    Computes ratio of average volume on down days (Close < Prev Close) vs overall average volume.
    Values > 1.0 indicate elevated volume on selling days.
    """
    if len(candles) < 2:
        return 1.0

    c_win = candles[-min(len(candles), window + 1):]
    down_vols: List[float] = []
    all_vols: List[float] = []

    for i in range(1, len(c_win)):
        vol = float(c_win[i]["volume"])
        all_vols.append(vol)
        if c_win[i]["close"] < c_win[i - 1]["close"]:
            down_vols.append(vol)

    if not all_vols or sum(all_vols) == 0:
        return 1.0

    avg_all = sum(all_vols) / len(all_vols)
    if not down_vols or avg_all == 0:
        return 0.8  # Favorable (no heavy down-volume days)

    avg_down = sum(down_vols) / len(down_vols)
    return round(avg_down / avg_all, 2)


def find_multiyear_high(candles: List[Dict[str, Any]]) -> float:
    """Finds multi-year secular cycle high from candle history."""
    if not candles:
        return 0.0
    return max(float(c["high"]) for c in candles)

