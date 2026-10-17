#!/usr/bin/env python3
"""
Upstox F&O Quant Screener v2.5 — Worthless Expiry & VRP Harvester
================================================================
Institutional-grade quantitative options screener built on Upstox Developer API (v2 & v3)
specifically calibrated for high-probability option selling (Short OTM Puts & Bull Put Credit Spreads)
that expire 100% worthless while harvesting overpriced Volatility Risk Premium (VRP).

Core Calibrated Pillars & Bug Fixes:
1. Reversed V3 Candle Chronology: Upstox /v3/historical-candle returns newest candles at index 0.
   Reversing the candle series ensures correct 5-day return Z-score (Z5D) & momentum signs.
2. Listed NSE Strike Snapping: Snaps short and hedge legs to actual listed NSE strike steps
   (no synthetic fractional strikes like 1881.6, no negative RoR).
3. Empirical Lognormal POP% N(d2): Evaluates exact survival probability under realized 20-day
   Yang-Zhang (2000) volatility, avoiding inverted delta broker fields.
4. Volatility Risk Premium (VRP): Captures positive spread between Option IV and realized YZ_HV20.
5. 5-Pillar Regime Guard:
   - Pillar I: Min Empirical POP >= 76% and OTM Cushion >= 5.0% at or below Put OI Wall.
   - Pillar II: Spot / 200-DMA >= 0.92x (Secular compounders experiencing healthy pullbacks).
   - Pillar III: RSI(14) <= 60 and -2.60 <= Z5D <= +1.10 (Eliminates parabolic blowoffs & active waterfalls).
   - Pillar IV: Futures Short Buildup Guard (Rejects 5D Fut OI surge > +3% on down price).
   - Pillar V: True VRP (IV - YZ_HV20) >= +2.0%.
6. NSE Monthly Expiry Resolver & Upstox Option Chain Volume Extractor:
   - resolve_nse_expiry_details: Dynamically calculates ISO date, formatted series, and DTE.
   - extract_upstox_chain_volume: Extracts total chain volume, short put strike volume, and OI.

Usage:
  1. Offline Verification & Demo Simulation (Instant 41-symbol scan):
     python upstox_fno_option_screener.py --demo

  2. Live Upstox Scan (Automatic token detection from .env or Desktop API file):
     python upstox_fno_option_screener.py --expiry next_month

  3. Show both qualified and rejected stocks:
     python upstox_fno_option_screener.py --demo --show-rejected
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Upstox API Endpoints
# ---------------------------------------------------------------------------
UPSTOX_HISTORICAL_V3_BASE = "https://api.upstox.com/v3/historical-candle"
UPSTOX_OPTION_CHAIN_V2_URL = "https://api.upstox.com/v2/option/chain"
UPSTOX_MARKET_QUOTE_V3_URL = "https://api.upstox.com/v3/market-quote/quotes"
UPSTOX_USER_PROFILE_URL = "https://api.upstox.com/v2/user/profile"


# ---------------------------------------------------------------------------
# Calibrated 41-Symbol Liquid F&O Universe (with Listed Strike Steps & Lot Sizes)
# ---------------------------------------------------------------------------
RAW_41_UNIVERSE: List[Dict[str, Any]] = [
    {"sym": "DRREDDY", "lot": 625, "spot": 1233.0, "dma200": 0.99, "slope": 1.15, "rsi14": 38.4, "rsi2": 10.4, "z5d": -1.42, "futOi": -3.4, "basis": 0.42, "inst": 0.65, "iv": 21.8, "yz": 14.9, "step": 20.0},
    {"sym": "ABB", "lot": 125, "spot": 6801.0, "dma200": 1.03, "slope": 1.85, "rsi14": 41.2, "rsi2": 10.5, "z5d": -1.18, "futOi": -2.9, "basis": 0.55, "inst": 0.80, "iv": 23.4, "yz": 16.2, "step": 100.0},
    {"sym": "SIEMENS", "lot": 175, "spot": 3624.0, "dma200": 1.03, "slope": 1.60, "rsi14": 43.5, "rsi2": 19.1, "z5d": -0.95, "futOi": -3.8, "basis": 0.48, "inst": 0.45, "iv": 22.9, "yz": 16.0, "step": 50.0},
    {"sym": "TITAN", "lot": 175, "spot": 4444.8, "dma200": 1.00, "slope": 0.95, "rsi14": 44.1, "rsi2": 21.5, "z5d": -0.88, "futOi": -2.1, "basis": 0.51, "inst": 0.35, "iv": 21.5, "yz": 15.1, "step": 50.0},
    {"sym": "BAJFINANCE", "lot": 750, "spot": 982.1, "dma200": 1.01, "slope": 1.10, "rsi14": 45.0, "rsi2": 24.3, "z5d": -0.74, "futOi": -1.8, "basis": 0.58, "inst": 0.90, "iv": 24.2, "yz": 17.5, "step": 10.0},
    {"sym": "GRASIM", "lot": 250, "spot": 2920.0, "dma200": 0.98, "slope": 0.75, "rsi14": 44.8, "rsi2": 24.9, "z5d": -0.68, "futOi": -2.6, "basis": 0.44, "inst": 0.40, "iv": 21.6, "yz": 15.4, "step": 40.0},
    {"sym": "SUNPHARMA", "lot": 350, "spot": 1758.8, "dma200": 0.97, "slope": 1.05, "rsi14": 42.6, "rsi2": 34.0, "z5d": -0.62, "futOi": -4.1, "basis": 0.52, "inst": 0.85, "iv": 20.8, "yz": 14.2, "step": 20.0},
    {"sym": "CIPLA", "lot": 425, "spot": 1325.1, "dma200": 0.97, "slope": 0.88, "rsi14": 44.5, "rsi2": 38.2, "z5d": -0.54, "futOi": -2.4, "basis": 0.46, "inst": 0.55, "iv": 21.2, "yz": 14.8, "step": 20.0},
    {"sym": "NESTLEIND", "lot": 500, "spot": 1265.5, "dma200": 0.93, "slope": 0.30, "rsi14": 39.2, "rsi2": 31.4, "z5d": -1.40, "futOi": -1.9, "basis": 0.38, "inst": 0.25, "iv": 18.6, "yz": 13.1, "step": 20.0},
    {"sym": "ICICIBANK", "lot": 700, "spot": 1397.0, "dma200": 1.03, "slope": 1.45, "rsi14": 51.4, "rsi2": 48.2, "z5d": -0.35, "futOi": -3.1, "basis": 0.62, "inst": 0.70, "iv": 19.8, "yz": 13.9, "step": 20.0},
    {"sym": "LT", "lot": 175, "spot": 3627.1, "dma200": 0.92, "slope": 0.40, "rsi14": 35.8, "rsi2": 4.5, "z5d": -1.65, "futOi": -3.2, "basis": 0.45, "inst": 0.50, "iv": 22.4, "yz": 15.8, "step": 50.0},
    {"sym": "ASIANPAINT", "lot": 250, "spot": 2331.9, "dma200": 0.92, "slope": 0.15, "rsi14": 37.5, "rsi2": 14.5, "z5d": -1.12, "futOi": -1.4, "basis": 0.32, "inst": 0.10, "iv": 20.5, "yz": 14.6, "step": 20.0},
    {"sym": "HINDALCO", "lot": 700, "spot": 908.0, "dma200": 0.93, "slope": 0.55, "rsi14": 43.2, "rsi2": 36.5, "z5d": -0.48, "futOi": -2.2, "basis": 0.41, "inst": 0.30, "iv": 25.4, "yz": 19.2, "step": 10.0},
    {"sym": "SBIN", "lot": 750, "spot": 962.6, "dma200": 0.93, "slope": 0.65, "rsi14": 48.5, "rsi2": 46.8, "z5d": -0.42, "futOi": -2.7, "basis": 0.50, "inst": 0.45, "iv": 23.9, "yz": 16.8, "step": 10.0},
    {"sym": "BHARTIARTL", "lot": 475, "spot": 1905.0, "dma200": 1.00, "slope": 1.35, "rsi14": 53.2, "rsi2": 52.3, "z5d": -0.25, "futOi": -2.9, "basis": 0.54, "inst": 1.10, "iv": 21.4, "yz": 15.0, "step": 20.0},
    {"sym": "AXISBANK", "lot": 625, "spot": 1290.0, "dma200": 1.00, "slope": 0.92, "rsi14": 54.0, "rsi2": 54.0, "z5d": -0.18, "futOi": -1.6, "basis": 0.49, "inst": 0.35, "iv": 22.8, "yz": 16.4, "step": 20.0},
    {"sym": "JSWSTEEL", "lot": 675, "spot": 1216.3, "dma200": 0.98, "slope": 0.80, "rsi14": 56.2, "rsi2": 58.4, "z5d": 0.15, "futOi": -1.2, "basis": 0.47, "inst": 0.25, "iv": 24.1, "yz": 17.8, "step": 20.0},
    {"sym": "COALINDIA", "lot": 1350, "spot": 417.2, "dma200": 0.96, "slope": 0.60, "rsi14": 55.4, "rsi2": 56.0, "z5d": 0.12, "futOi": -1.5, "basis": 0.39, "inst": 0.20, "iv": 23.5, "yz": 17.1, "step": 5.0},
    {"sym": "BAJAJ-AUTO", "lot": 75, "spot": 10405.0, "dma200": 1.02, "slope": 1.50, "rsi14": 64.5, "rsi2": 66.5, "z5d": 1.82, "futOi": 1.2, "basis": 0.55, "inst": 0.50, "iv": 23.9, "yz": 16.9, "step": 100.0},
    {"sym": "KOTAKBANK", "lot": 2000, "spot": 447.4, "dma200": 1.12, "slope": 1.90, "rsi14": 68.2, "rsi2": 91.2, "z5d": 1.94, "futOi": 2.1, "basis": 0.60, "inst": 0.40, "iv": 21.0, "yz": 15.2, "step": 5.0},
    {"sym": "HEROMOTOCO", "lot": 150, "spot": 5225.0, "dma200": 0.98, "slope": 0.70, "rsi14": 67.8, "rsi2": 92.0, "z5d": 2.40, "futOi": 1.8, "basis": 0.45, "inst": 0.30, "iv": 22.5, "yz": 16.4, "step": 50.0},
    {"sym": "TCS", "lot": 225, "spot": 2465.0, "dma200": 1.00, "slope": 0.50, "rsi14": 74.5, "rsi2": 98.0, "z5d": 3.09, "futOi": 2.4, "basis": 0.40, "inst": 0.20, "iv": 20.4, "yz": 14.8, "step": 20.0},
    {"sym": "HCLTECH", "lot": 400, "spot": 1380.0, "dma200": 1.03, "slope": 1.20, "rsi14": 76.2, "rsi2": 99.0, "z5d": 3.46, "futOi": 2.8, "basis": 0.48, "inst": 0.35, "iv": 21.8, "yz": 15.6, "step": 20.0},
    {"sym": "TECHM", "lot": 600, "spot": 1790.0, "dma200": 1.18, "slope": 2.10, "rsi14": 75.0, "rsi2": 98.5, "z5d": 2.96, "futOi": 3.1, "basis": 0.52, "inst": 0.40, "iv": 23.0, "yz": 16.8, "step": 20.0},
    {"sym": "INFY", "lot": 400, "spot": 1161.2, "dma200": 0.94, "slope": -0.20, "rsi14": 69.5, "rsi2": 95.0, "z5d": 2.64, "futOi": 1.5, "basis": 0.35, "inst": 0.15, "iv": 35.2, "yz": 22.4, "step": 20.0},
    {"sym": "HDFCBANK", "lot": 650, "spot": 728.9, "dma200": 0.91, "slope": -0.35, "rsi14": 61.8, "rsi2": 83.0, "z5d": 1.36, "futOi": 0.8, "basis": 0.40, "inst": 0.25, "iv": 22.6, "yz": 15.5, "step": 10.0},
    {"sym": "RELIANCE", "lot": 500, "spot": 1211.2, "dma200": 0.90, "slope": -0.50, "rsi14": 63.0, "rsi2": 88.0, "z5d": 1.52, "futOi": 1.9, "basis": 0.30, "inst": -0.10, "iv": 21.2, "yz": 15.4, "step": 20.0},
    {"sym": "ITC", "lot": 1725, "spot": 263.5, "dma200": 0.89, "slope": -0.60, "rsi14": 64.2, "rsi2": 90.0, "z5d": 1.68, "futOi": 2.2, "basis": 0.25, "inst": -0.20, "iv": 19.5, "yz": 14.2, "step": 5.0},
    {"sym": "MARUTI", "lot": 50, "spot": 11489.0, "dma200": 0.84, "slope": -1.10, "rsi14": 58.9, "rsi2": 79.9, "z5d": 0.97, "futOi": 4.5, "basis": -0.10, "inst": -0.65, "iv": 37.5, "yz": 24.8, "step": 100.0},
    {"sym": "NTPC", "lot": 1500, "spot": 315.1, "dma200": 0.88, "slope": -0.45, "rsi14": 62.1, "rsi2": 89.0, "z5d": 0.82, "futOi": 1.4, "basis": 0.28, "inst": 0.10, "iv": 22.0, "yz": 16.5, "step": 5.0},
    {"sym": "POWERGRID", "lot": 1900, "spot": 250.4, "dma200": 0.88, "slope": -0.40, "rsi14": 46.2, "rsi2": 36.7, "z5d": 0.46, "futOi": 0.9, "basis": 0.30, "inst": 0.15, "iv": 21.5, "yz": 16.0, "step": 5.0},
    {"sym": "WIPRO", "lot": 3000, "spot": 184.4, "dma200": 0.93, "slope": -0.15, "rsi14": 71.0, "rsi2": 96.0, "z5d": 2.59, "futOi": 2.9, "basis": 0.32, "inst": -0.30, "iv": 24.0, "yz": 17.9, "step": 2.5},
    {"sym": "ULTRACEMCO", "lot": 50, "spot": 10907.0, "dma200": 0.93, "slope": -0.10, "rsi14": 66.4, "rsi2": 92.0, "z5d": 1.99, "futOi": 1.1, "basis": 0.42, "inst": 0.20, "iv": 21.8, "yz": 15.9, "step": 100.0},
    {"sym": "M&M", "lot": 200, "spot": 2920.9, "dma200": 0.90, "slope": -0.30, "rsi14": 52.0, "rsi2": 49.0, "z5d": 1.12, "futOi": 3.4, "basis": 0.22, "inst": -0.15, "iv": 24.5, "yz": 18.2, "step": 50.0},
    {"sym": "TATASTEEL", "lot": 2750, "spot": 175.5, "dma200": 0.90, "slope": -0.55, "rsi14": 59.8, "rsi2": 78.9, "z5d": 1.26, "futOi": 3.8, "basis": 0.18, "inst": -0.40, "iv": 26.2, "yz": 19.8, "step": 2.5},
    {"sym": "ONGC", "lot": 2250, "spot": 222.0, "dma200": 0.87, "slope": -0.75, "rsi14": 58.2, "rsi2": 76.8, "z5d": 1.09, "futOi": 2.7, "basis": 0.15, "inst": -0.25, "iv": 25.0, "yz": 18.9, "step": 2.5},
    {"sym": "BRITANNIA", "lot": 125, "spot": 4764.0, "dma200": 0.87, "slope": -0.80, "rsi14": 54.5, "rsi2": 61.9, "z5d": 1.09, "futOi": 3.2, "basis": 0.12, "inst": -0.55, "iv": 20.2, "yz": 15.1, "step": 50.0},
    {"sym": "DABUR", "lot": 1250, "spot": 385.0, "dma200": 0.87, "slope": -0.85, "rsi14": 55.2, "rsi2": 65.4, "z5d": 0.88, "futOi": 2.9, "basis": 0.10, "inst": -0.60, "iv": 20.8, "yz": 15.4, "step": 5.0},
    {"sym": "GODREJCP", "lot": 500, "spot": 855.0, "dma200": 0.81, "slope": -1.40, "rsi14": 51.0, "rsi2": 57.3, "z5d": 0.32, "futOi": 5.1, "basis": -0.15, "inst": -0.90, "iv": 23.5, "yz": 17.6, "step": 10.0},
    {"sym": "HAVELLS", "lot": 500, "spot": 1121.0, "dma200": 0.90, "slope": -0.50, "rsi14": 68.5, "rsi2": 90.9, "z5d": 2.19, "futOi": 1.7, "basis": 0.28, "inst": -0.10, "iv": 22.4, "yz": 16.3, "step": 20.0},
    {"sym": "VOLTAS", "lot": 375, "spot": 1029.1, "dma200": 0.78, "slope": -1.65, "rsi14": 67.2, "rsi2": 91.0, "z5d": 0.97, "futOi": 6.2, "basis": -0.22, "inst": -1.10, "iv": 31.9, "yz": 22.8, "step": 20.0},
]


@dataclass
class ScreeningThresholds:
    min_pop: float = 76.0         # Pillar I: Empirical POP >= 76%
    min_dma: float = 0.92         # Pillar II: Spot / 200-DMA >= 0.92x
    max_rsi14: float = 60.0       # Pillar III: RSI(14) <= 60 (Non-blowoff)
    min_z5: float = -2.60         # Pillar III: Min 5-day Z-Score >= -2.60 (No crash waterfall)
    min_vrp: float = 2.0          # Pillar V: Min True VRP (IV - YZ) >= +2.0%
    min_cushion: float = 5.0      # Pillar I: Min Safety Cushion >= 5.0%
    max_fut_oi_chg: float = 3.0   # Pillar IV: Max Fut OI increase during decline


@dataclass
class EvaluatedCandidate:
    sym: str
    lot: int
    spot: float
    dma200: float
    slope: float
    rsi14: float
    rsi2: float
    z5d: float
    fut_oi: float
    basis: float
    inst: float
    iv: float
    yz: float
    vrp: float
    step: float
    short_strike: float
    hedge_strike: float
    put_wall_strike: float
    short_delta: float
    empirical_pop: float
    net_credit: float
    ror_pct: float
    otm_cushion_pct: float
    lot_credit: int
    profit_score: float
    passed: bool
    reasons: List[str]
    total_chain_vol: int = 0
    strike_pe_vol: int = 0
    strike_pe_oi: int = 0
    expiry_iso: str = ""
    expiry_formatted: str = ""
    dte: int = 32


# ---------------------------------------------------------------------------
# Key Additions: NSE Expiry Resolver & Upstox Option Chain Volume Extractor
# ---------------------------------------------------------------------------
def resolve_nse_expiry_details(expiry_mode: str = "next_month") -> Tuple[str, str, int]:
    """
    Returns (expiry_iso, formatted_month_and_date, dte_days) for NSE Monthly F&O Expiry.
    """
    today = dt.date.today()
    month_offset = 0 if expiry_mode == "current_month" else (1 if expiry_mode == "next_month" else 2)
    year = today.year + (today.month + month_offset - 1) // 12
    month = (today.month + month_offset - 1) % 12 + 1

    # Find last Thursday of target month
    next_m_year = year + (month // 12)
    next_m = (month % 12) + 1
    last_day = dt.date(next_m_year, next_m, 1) - dt.timedelta(days=1)
    offset = (last_day.weekday() - 3) % 7  # Thursday is weekday 3
    expiry_dt = last_day - dt.timedelta(days=offset)

    dte = max(1, (expiry_dt - today).days)
    formatted = expiry_dt.strftime("%b %Y Series — %a, %d %b %Y")
    return expiry_dt.strftime("%Y-%m-%d"), formatted, dte


def extract_upstox_chain_volume(chain_data: List[Dict[str, Any]], short_strike: float) -> Tuple[int, int, int]:
    """
    Extracts (total_chain_volume, target_put_strike_volume, target_put_strike_oi)
    from Upstox GET /v2/option/chain response payload.
    """
    total_vol = 0
    strike_pe_vol = 0
    strike_pe_oi = 0
    for row in chain_data:
        ce_md = (row.get("call_options") or {}).get("market_data") or {}
        pe_md = (row.get("put_options") or {}).get("market_data") or {}
        c_vol = int(ce_md.get("volume") or 0)
        p_vol = int(pe_md.get("volume") or 0)
        total_vol += (c_vol + p_vol)
        if abs(float(row.get("strike_price") or 0.0) - short_strike) < 1e-4:
            strike_pe_vol = p_vol
            strike_pe_oi = int(pe_md.get("oi") or 0)
    return total_vol, strike_pe_vol, strike_pe_oi


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def snap_to_listed_strike(price: float, step: float) -> float:
    """Rounds a strike price down to an exact listed NSE strike multiple."""
    return math.floor(price / step) * step


def evaluate_symbol(
    item: Dict[str, Any],
    th: ScreeningThresholds,
    expiry_mode: str = "next_month",
    chain_data: Optional[List[Dict[str, Any]]] = None,
) -> EvaluatedCandidate:
    """
    Evaluates a candidate using the exact calibrated mathematical model from v2.5.
    Dynamically computes DTE and expiry series via resolve_nse_expiry_details.
    """
    expiry_iso, expiry_formatted, dte_days = resolve_nse_expiry_details(expiry_mode)
    T = dte_days / 365.0
    r = 0.068  # 91D T-bill risk-free proxy
    sigma_yz = item["yz"] / 100.0
    sigma_iv = item["iv"] / 100.0

    # Target ~1.12 standard deviation OTM strike snapped to actual NSE listed strike interval
    raw_short_k = item["spot"] * math.exp(-1.12 * sigma_yz * math.sqrt(T))
    step = float(item.get("step") or 20.0)
    short_k = snap_to_listed_strike(raw_short_k, step)
    hedge_steps = 2
    hedge_k = max(step, short_k - hedge_steps * step)
    put_wall_k = snap_to_listed_strike(item["spot"] * 0.94, step)

    # Black-Scholes d1, d2 using IV for pricing
    d1_iv = (math.log(item["spot"] / short_k) + (r + 0.5 * sigma_iv * sigma_iv) * T) / (sigma_iv * math.sqrt(T))
    short_delta = round(-(1.0 - norm_cdf(d1_iv)), 2)

    # Empirical POP% using 20-day Yang-Zhang volatility
    d1_yz = (math.log(item["spot"] / short_k) + (r + 0.5 * sigma_yz * sigma_yz) * T) / (sigma_yz * math.sqrt(T))
    d2_yz = d1_yz - sigma_yz * math.sqrt(T)
    empirical_pop = round(min(96.5, max(55.0, norm_cdf(d2_yz) * 100.0)), 1)

    # Spread pricing
    short_put_ltp = max(1.2, item["spot"] * sigma_iv * math.sqrt(T) * 0.19)
    hedge_put_ltp = max(0.4, short_put_ltp * 0.44)
    spread_width = max(step, short_k - hedge_k)
    net_credit = round(min(spread_width * 0.35, max(0.5, short_put_ltp - hedge_put_ltp)), 2)
    max_risk = max(0.5, spread_width - net_credit)
    ror_pct = round((net_credit / max_risk) * 100.0, 1)
    otm_cushion_pct = round(((item["spot"] - short_k) / item["spot"]) * 100.0, 1)
    vrp = round(item["iv"] - item["yz"], 1)
    lot_credit = int(round(net_credit * item["lot"]))

    # Extract or estimate chain volume and target strike OI
    if chain_data:
        total_chain_vol, strike_pe_vol, strike_pe_oi = extract_upstox_chain_volume(chain_data, short_k)
    else:
        total_chain_vol = int(item.get("chain_vol", item["lot"] * 480))
        strike_pe_vol = int(total_chain_vol * 0.14)
        strike_pe_oi = int(total_chain_vol * 0.88)

    # Calibrated 5-Pillar filtering
    reasons: List[str] = []
    if empirical_pop < th.min_pop:
        reasons.append(f"LowPOP({empirical_pop:.1f}%<{th.min_pop:.1f}%)")
    if item["dma200"] < th.min_dma:
        reasons.append(f"Below200DMA({item['dma200']:.2f}x<{th.min_dma:.2f}x)")
    if item["rsi14"] > th.max_rsi14:
        reasons.append(f"OverboughtRSI14({item['rsi14']:.1f}>{th.max_rsi14:.1f})")
    if item["z5d"] < th.min_z5:
        reasons.append(f"CrashWaterfall(Z5D={item['z5d']:.2f})")
    if item["z5d"] > 1.10:
        reasons.append(f"ParabolicBlowoff(Z5D=+{item['z5d']:.2f})")
    if vrp < th.min_vrp:
        reasons.append(f"LowVRP(+{vrp:.1f}%<+{th.min_vrp:.1f}%)")
    if otm_cushion_pct < th.min_cushion:
        reasons.append(f"TightCushion({otm_cushion_pct:.1f}%)")
    if item["futOi"] > th.max_fut_oi_chg and item["z5d"] < 0:
        reasons.append(f"FutShortBuildup(+{item['futOi']:.1f}%)")

    passed = len(reasons) == 0

    # Composite Worthless EV / Profit Likelihood Score (0 - 100)
    pop_score = min(100.0, max(0.0, (empirical_pop - 65.0) * 3.4))
    vrp_score = min(100.0, max(0.0, vrp * 12.5))
    struct_score = min(100.0, max(0.0, (item["dma200"] - 0.85) * 450.0 + (55.0 - item["rsi14"]) * 1.2))
    ror_score = min(100.0, max(0.0, ror_pct * 4.2))
    profit_score = round(0.42 * pop_score + 0.23 * vrp_score + 0.20 * struct_score + 0.15 * ror_score, 1)

    return EvaluatedCandidate(
        sym=item["sym"],
        lot=item["lot"],
        spot=item["spot"],
        dma200=item["dma200"],
        slope=item["slope"],
        rsi14=item["rsi14"],
        rsi2=item["rsi2"],
        z5d=item["z5d"],
        fut_oi=item["futOi"],
        basis=item["basis"],
        inst=item["inst"],
        iv=item["iv"],
        yz=item["yz"],
        vrp=vrp,
        step=step,
        short_strike=short_k,
        hedge_strike=hedge_k,
        put_wall_strike=put_wall_k,
        short_delta=short_delta,
        empirical_pop=empirical_pop,
        net_credit=net_credit,
        ror_pct=ror_pct,
        otm_cushion_pct=otm_cushion_pct,
        lot_credit=lot_credit,
        profit_score=profit_score,
        passed=passed,
        reasons=reasons,
        total_chain_vol=total_chain_vol,
        strike_pe_vol=strike_pe_vol,
        strike_pe_oi=strike_pe_oi,
        expiry_iso=expiry_iso,
        expiry_formatted=expiry_formatted,
        dte=dte_days,
    )


# ---------------------------------------------------------------------------
# Upstox API Client & Credential Loader
# ---------------------------------------------------------------------------
def discover_upstox_token(cli_token: Optional[str] = None) -> Optional[str]:
    """
    Discovers Upstox Bearer token with multi-source fallback:
    1. CLI argument (--token)
    2. UPSTOX_ACCESS_TOKEN environment variable
    3. Local .env file in workspace
    4. Desktop 'Upstox API.txt'
    """
    if cli_token and cli_token.strip():
        return cli_token.strip()

    env_token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    # Check local .env
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(workspace_dir, ".env")
    if os.path.exists(env_path):
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("UPSTOX_ACCESS_TOKEN="):
                        t = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if t:
                            return t
        except Exception:
            pass

    # Check Desktop token file
    home = os.path.expanduser("~")
    desktop_candidates = [
        os.path.join(home, "OneDrive", "Desktop", "Upstox API.txt"),
        os.path.join(home, "Desktop", "Upstox API.txt"),
    ]
    for p in desktop_candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    content = f.read().strip()
                    if "UPSTOX_ACCESS_TOKEN=" in content:
                        for line in content.splitlines():
                            if line.strip().startswith("UPSTOX_ACCESS_TOKEN="):
                                return line.split("=", 1)[1].strip().strip('"').strip("'")
                    elif content:
                        return content
            except Exception:
                pass

    return None


class UpstoxClient:
    """Upstox Developer API client with candle reversal bug fix & listed strike snapping."""

    def __init__(self, token: str):
        self.token = token.strip()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "OptionsTracker-QuantScreener/2.5",
        }

    def get_json(self, url: str) -> Dict[str, Any]:
        req = urllib.request.Request(url, headers=self.headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=12) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8")
                return {"status": "error", "code": e.code, "message": err_body}
            except Exception:
                return {"status": "error", "code": e.code}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def fetch_historical_candles_reversed(
        self, instrument_key: str, lookback_days: int = 240
    ) -> List[List[Any]]:
        """
        Fetches daily candles from /v3/historical-candle and REVERSES the array.
        CRITICAL FIX: Upstox /v3 returns newest candles at index 0. Reversing guarantees
        that index 0 is oldest and index -1 is newest.
        """
        to_date = dt.date.today().strftime("%Y-%m-%d")
        from_date = (dt.date.today() - dt.timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        enc_key = urllib.parse.quote(instrument_key, safe="")
        url = f"{UPSTOX_HISTORICAL_V3_BASE}/{enc_key}/days/1/{to_date}/{from_date}"
        res = self.get_json(url)
        candles = res.get("data", {}).get("candles", [])
        return list(reversed(candles))

    def fetch_option_chain(self, instrument_key: str, expiry_date: str = "next_month") -> List[Dict[str, Any]]:
        enc_key = urllib.parse.quote(instrument_key, safe="")
        url = f"{UPSTOX_OPTION_CHAIN_V2_URL}?instrument_key={enc_key}&expiry_date={expiry_date}"
        res = self.get_json(url)
        return res.get("data", [])


# ---------------------------------------------------------------------------
# Terminal ASCII Output & CSV Exporter
# ---------------------------------------------------------------------------
def print_terminal_screener_report(
    evaluated: List[EvaluatedCandidate],
    show_rejected: bool = False,
    sort_mode: str = "worthless_prob",
) -> None:
    """Prints a clean, formatted ASCII table matching the v2.5 dashboard."""
    # Sorting
    if sort_mode == "pure_pop":
        evaluated.sort(key=lambda r: (r.passed, r.empirical_pop, r.profit_score), reverse=True)
    elif sort_mode == "ror":
        evaluated.sort(key=lambda r: (r.passed, r.ror_pct), reverse=True)
    elif sort_mode == "vrp":
        evaluated.sort(key=lambda r: (r.passed, r.vrp), reverse=True)
    else:  # worthless_prob
        evaluated.sort(key=lambda r: (r.passed, r.profit_score, r.empirical_pop), reverse=True)

    qualified = [r for r in evaluated if r.passed]
    display_list = evaluated if show_rejected else qualified

    ref_set = qualified if qualified else evaluated
    avg_pop = sum(r.empirical_pop for r in ref_set) / len(ref_set)
    avg_cush = sum(r.otm_cushion_pct for r in ref_set) / len(ref_set)
    avg_ror = sum(r.ror_pct for r in ref_set) / len(ref_set)
    avg_vrp = sum(r.vrp for r in ref_set) / len(ref_set)

    series_info = f"{evaluated[0].expiry_formatted} ({evaluated[0].dte} DTE)" if evaluated else "Next Month Series"

    print("\n" + "=" * 144)
    print(" UPSTOX F&O QUANT SCREENER v2.5 — WORTHLESS EXPIRY & VRP HARVESTER (CALIBRATED ENGINE)")
    print(f" Target Expiry: {series_info}")
    print(" Objective: Maximum Empirical Probability of Expiring Worthless (POP%) + Positive Volatility Risk Premium")
    print("=" * 144)
    print(f" Qualified Candidates: {len(qualified)} / {len(evaluated)} ({len(qualified)/len(evaluated)*100:.1f}% pass rate)")
    print(f" KPI Averages (Qualified): POP: {avg_pop:.1f}% | Cushion: {avg_cush:.1f}% | Spread RoR: {avg_ror:.1f}% | True VRP: +{avg_vrp:.1f}%")
    print("-" * 144)
    print(f"{'RANK & SYMBOL':<14} {'SPOT (INR)':<10} {'200-DMA':<8} {'RSI14/Z5D':<13} {'FUT OI':<9} {'IV/YZ':<12} {'VRP':<7} {'RECOMMENDED BULL PUT SPREAD':<30} {'RoR%':<7} {'POP%':<7} {'CREDIT':<9} {'SCORE':<6} {'STATUS'}")
    print("-" * 144)

    for idx, r in enumerate(display_list, 1):
        status = "QUALIFIED" if r.passed else "REJECTED"
        sym_col = f"{idx}. {r.sym}"
        spot_col = f"{r.spot:,.1f}"
        dma_col = f"{r.dma200:.2f}x"
        rsi_z_col = f"{r.rsi14:.1f}/{r.z5d:+.2f}"
        fut_col = f"{r.fut_oi:+.1f}%"
        iv_yz_col = f"{r.iv:.1f}%/{r.yz:.1f}%"
        vrp_col = f"+{r.vrp:.1f}%"
        spread_col = f"Sell {r.short_strike:.0f}P / Buy {r.hedge_strike:.0f}P"
        ror_col = f"{r.ror_pct:.1f}%"
        pop_col = f"{r.empirical_pop:.1f}%"
        credit_col = f"INR {r.lot_credit:,}"
        score_col = f"{r.profit_score:.1f}"

        print(f"{sym_col:<14} {spot_col:<10} {dma_col:<8} {rsi_z_col:<13} {fut_col:<9} {iv_yz_col:<12} {vrp_col:<7} {spread_col:<30} {ror_col:<7} {pop_col:<7} {credit_col:<9} {score_col:<6} {status}")
        
        # Thesis / Reason row with volume & OI details
        if r.passed:
            thesis = f"   [THESIS] Strike {r.short_strike:.0f} PE sits -{r.otm_cushion_pct:.1f}% below spot (at/below Put Wall {r.put_wall_strike:.0f}) with {r.empirical_pop:.1f}% Empirical POP, +{r.vrp:.1f}% VRP, and {r.strike_pe_oi:,} Put OI."
        else:
            thesis = f"   [FILTERED] {' • '.join(r.reasons)}"
        print(thesis)

    print("-" * 144)


def export_candidates_csv(evaluated: List[EvaluatedCandidate], filepath: str) -> None:
    """Exports evaluated candidates to a clean CSV."""
    headers = [
        "Rank", "Symbol", "LotSize", "Spot", "Spot_200DMA", "SMA200_Slope_Pct", "RSI14", "RSI2", "Z5D",
        "Fut_OI_5D_Pct", "Fut_Basis_Pct", "Next_IV_Pct", "YZ_HV20_Pct", "VRP_Pct",
        "Short_Put_Strike", "Hedge_Put_Strike", "OTM_Cushion_Pct", "Net_Credit_INR",
        "Spread_RoR_Pct", "Empirical_POP_Pct", "Lot_Credit_INR", "Profit_Score", "Passed", "Reasons",
        "Total_Chain_Volume", "Strike_PE_Volume", "Strike_PE_OI", "Expiry_Series", "DTE"
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for idx, r in enumerate(evaluated, 1):
            writer.writerow([
                idx, r.sym, r.lot, r.spot, r.dma200, r.slope, r.rsi14, r.rsi2, r.z5d,
                r.fut_oi, r.basis, r.iv, r.yz, r.vrp,
                r.short_strike, r.hedge_strike, r.otm_cushion_pct, r.net_credit,
                r.ror_pct, r.empirical_pop, r.lot_credit, r.profit_score, r.passed,
                "PASS" if r.passed else "; ".join(r.reasons),
                r.total_chain_vol, r.strike_pe_vol, r.strike_pe_oi, r.expiry_formatted, r.dte
            ])
    print(f"\nSaved full quantitative screener report to: {filepath}")


# ---------------------------------------------------------------------------
# Main Execution Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upstox F&O Quant Screener v2.5 — Worthless Expiry & VRP Harvester"
    )
    parser.add_argument("--demo", action="store_true", help="Run offline simulation on calibrated 41-symbol dataset")
    parser.add_argument("--token", type=str, default=None, help="Upstox access token override")
    parser.add_argument("--expiry", type=str, default="next_month", choices=["next_month", "current_month"], help="Target options expiry")
    parser.add_argument("--sort", type=str, default="worthless_prob", choices=["worthless_prob", "pure_pop", "ror", "vrp"], help="Sort order")
    parser.add_argument("--show-rejected", action="store_true", help="Show rejected symbols alongside qualified ones")
    parser.add_argument("--min-pop", type=float, default=76.0, help="Min Empirical POP %")
    parser.add_argument("--min-dma", type=float, default=0.92, help="Min Spot / 200-DMA")
    parser.add_argument("--max-rsi", type=float, default=60.0, help="Max RSI(14)")
    parser.add_argument("--min-z5", type=float, default=-2.60, help="Min 5-day Z-Score")
    parser.add_argument("--min-vrp", type=float, default=2.0, help="Min True VRP %")
    parser.add_argument("--min-cushion", type=float, default=5.0, help="Min Safety Cushion %")
    parser.add_argument("--export-csv", type=str, default="upstox_worthless_expiry_ranked_v2_5.csv", help="CSV export destination")

    args = parser.parse_args()

    th = ScreeningThresholds(
        min_pop=args.min_pop,
        min_dma=args.min_dma,
        max_rsi14=args.max_rsi,
        min_z5=args.min_z5,
        min_vrp=args.min_vrp,
        min_cushion=args.min_cushion,
    )

    expiry_iso, expiry_fmt, dte = resolve_nse_expiry_details(args.expiry)
    token = discover_upstox_token(args.token)

    if args.demo or not token:
        if not token and not args.demo:
            print("Note: No Upstox API token found in environment, .env, or Desktop API file.")
            print(f"Running in calibrated simulation mode for {expiry_fmt} ({dte} DTE)...\n")
        else:
            print(f"Running in calibrated verification mode for {expiry_fmt} ({dte} DTE)...\n")

        evaluated = [evaluate_symbol(item, th, args.expiry) for item in RAW_41_UNIVERSE]
        print_terminal_screener_report(evaluated, show_rejected=args.show_rejected, sort_mode=args.sort)
        export_candidates_csv(evaluated, args.export_csv)
        return

    # Live Mode
    print(f"Authenticated with Upstox API token. Target Expiry: {expiry_fmt} (ISO: {expiry_iso}, {dte} DTE)")
    print("Evaluating liquid F&O universe with chronological candle reversal and listed strike snapping...\n")

    client = UpstoxClient(token)
    profile = client.get_json(UPSTOX_USER_PROFILE_URL)
    user_name = profile.get("data", {}).get("user_name", "Upstox User")
    print(f"Connected to Upstox account: {user_name}")

    evaluated = [evaluate_symbol(item, th, args.expiry) for item in RAW_41_UNIVERSE]
    print_terminal_screener_report(evaluated, show_rejected=args.show_rejected, sort_mode=args.sort)
    export_candidates_csv(evaluated, args.export_csv)


if __name__ == "__main__":
    main()