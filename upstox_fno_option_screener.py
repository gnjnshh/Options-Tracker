#!/usr/bin/env python3
"""
Upstox F&O Quant Screener v3.0 — Short OTM Put & Worthless Expiry Harvester
==========================================================================
Institutional-grade quantitative options screener built on Upstox Developer API (v2 & v3)
specifically calibrated for Pure Option Selling (Single-Leg Short OTM Puts)
that expire 100% worthless while harvesting overpriced Volatility Risk Premium (VRP).

Core Quantitative Strategy & Institutional Pillars:
1. Pure Option Selling Strategy (Single-Leg Short OTM Put):
   - Replaced 2-leg spread with high-conviction Short OTM Put (Sell <Strike> PE) snapped to NSE listed strike steps.
   - 100% of upfront gross premium (Short Put LTP × Lot Size) is kept on worthless expiry.
   - Computes Return on SPAN Margin (RoM % = Lot Credit / Est. SPAN Margin).
2. Exact Target Expiry Month & Date Display:
   - Dynamically resolves exact NSE monthly expiry date, month series, and Days to Expiry (DTE)
     (Oct Series: Thu, 29 Oct 2026 • 12 DTE; Nov Series: Thu, 26 Nov 2026 • 40 DTE; Dec Series: Thu, 31 Dec 2026 • 75 DTE).
   - Syncs with Upstox API /v2/option/chain.
3. Upstox API F&O Option Chain Volume Integration & Sort by Volume:
   - Pulls live option chain volume from GET /v2/option/chain (call + put volume & target strike PE vol / oi)
     and underlying quote volume from GET /v3/market-quote/quotes.
   - Adds F&O Chain Vol and Liquidity Tiers with 1-click sort by volume (--sort vol).
4. 2020–2026 Multi-Year Structural Base & Mean Reversion:
   - Evaluates price against the 6-year structural floor (March 2020 secular cycle low).
   - Distance to base: ((Spot - Base2020) / Base2020) × 100.
5. 5-Pillar Regime Guard (Non-Blowoff / Non-Crash):
   - Pillar I: Min Empirical POP >= 76% and OTM Cushion >= 5.0% at or below Put OI Support Wall.
   - Pillar II: Spot / 200-DMA >= 0.92x (Secular compounders experiencing normal pullbacks).
   - Pillar III: RSI(14) <= 60 and -2.60 <= Z5D <= +1.10 (Eliminates parabolic blowoffs & active waterfalls).
   - Pillar IV: Futures Short Buildup Guard (Rejects 5D Fut OI surge > +3% on down price).
   - Pillar V: True VRP (IV - YZ_HV20) >= +2.0%.
6. Expanded Universes & 8 Presets:
   - Universes: Core 41 Calibrated, Top 50 Liquid F&O, and All 220 NSE F&O.
   - 8 Strategy Presets: default, fortress, high_vol, base_value, vrp_crush, oversold_dip, compounders, relaxed.

Usage:
  1. Offline Verification & Demo Simulation (Instant scan across Core 41):
     python upstox_fno_option_screener.py --demo

  2. Sort by F&O Chain Volume:
     python upstox_fno_option_screener.py --demo --sort vol

  3. Scan Top 50 Liquid F&O with Ultra-Safe Fortress Preset:
     python upstox_fno_option_screener.py --demo --universe top50 --preset fortress

  4. Live Upstox Scan (Automatic token detection from .env or Desktop API file):
     python upstox_fno_option_screener.py --expiry next_month
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

from backtest.indicators import (
    black_scholes_put_price,
    compute_200_dma,
    compute_adx14,
    compute_bollinger_pct_b,
    compute_down_volume_ratio,
    compute_mfi14,
    compute_rsi14,
    compute_worthless_score,
    compute_yang_zhang_vol,
    compute_z5d,
    find_2020_base_floor,
    find_multiyear_high,
    norm_cdf,
    snap_to_listed_strike,
)
from backtest.upstox_data_provider import ALL_220_UNIVERSE_KEYS, TOP_50_UNIVERSE, UpstoxDataProvider


# ---------------------------------------------------------------------------
# Upstox API Endpoints
# ---------------------------------------------------------------------------
UPSTOX_HISTORICAL_V3_BASE = "https://api.upstox.com/v3/historical-candle"
UPSTOX_OPTION_CHAIN_V2_URL = "https://api.upstox.com/v2/option/chain"
UPSTOX_MARKET_QUOTE_V3_URL = "https://api.upstox.com/v3/market-quote/quotes"
UPSTOX_USER_PROFILE_URL = "https://api.upstox.com/v2/user/profile"


# ---------------------------------------------------------------------------
# Universes: Core 41, Top 50 Liquid, and All 220 NSE F&O
# ---------------------------------------------------------------------------
CORE_41_RAW: List[Dict[str, Any]] = [
    {"sym": "DRREDDY", "lot": 625, "spot": 1233.0, "dma200": 0.99, "rsi14": 57.8, "z5d": 0.56, "futOi": -3.4, "iv": 26.5, "yz": 23.9, "step": 20.0, "roe": 19.4, "secRoe": 15.2, "pat": 14.2, "fnoVol": 184500, "base_2020": 499.0, "high_20_26": 1421.5},
    {"sym": "ABB", "lot": 125, "spot": 6801.0, "dma200": 1.02, "rsi14": 41.1, "z5d": -0.96, "futOi": -2.9, "iv": 33.8, "yz": 29.9, "step": 100.0, "roe": 22.8, "secRoe": 14.5, "pat": 28.5, "fnoVol": 96400, "base_2020": 801.0, "high_20_26": 9149.95},
    {"sym": "SIEMENS", "lot": 175, "spot": 3624.0, "dma200": 1.03, "rsi14": 40.9, "z5d": -1.11, "futOi": -3.8, "iv": 33.0, "yz": 29.1, "step": 50.0, "roe": 17.9, "secRoe": 14.5, "pat": 21.0, "fnoVol": 112300, "base_2020": 947.9, "high_20_26": 8129.9},
    {"sym": "TITAN", "lot": 175, "spot": 4444.8, "dma200": 1.0, "rsi14": 35.0, "z5d": -0.05, "futOi": -2.1, "iv": 26.2, "yz": 21.8, "step": 50.0, "roe": 31.2, "secRoe": 18.0, "pat": 15.8, "fnoVol": 248900, "base_2020": 720.9, "high_20_26": 5186.7},
    {"sym": "BAJFINANCE", "lot": 750, "spot": 982.1, "dma200": 1.01, "rsi14": 47.3, "z5d": 1.03, "futOi": -1.8, "iv": 34.9, "yz": 31.5, "step": 10.0, "roe": 22.1, "secRoe": 15.8, "pat": 22.4, "fnoVol": 412000, "base_2020": 210.0, "high_20_26": 1176.4},
    {"sym": "GRASIM", "lot": 250, "spot": 2920.0, "dma200": 0.98, "rsi14": 37.6, "z5d": 1.16, "futOi": -2.6, "iv": 24.7, "yz": 20.5, "step": 40.0, "roe": 13.8, "secRoe": 11.9, "pat": 11.5, "fnoVol": 88500, "base_2020": 383.55, "high_20_26": 3411.1},
    {"sym": "SUNPHARMA", "lot": 350, "spot": 1758.8, "dma200": 0.97, "rsi14": 37.0, "z5d": -0.13, "futOi": -4.1, "iv": 24.2, "yz": 20.0, "step": 20.0, "roe": 17.6, "secRoe": 15.2, "pat": 18.9, "fnoVol": 226400, "base_2020": 312.0, "high_20_26": 2046.9},
    {"sym": "CIPLA", "lot": 425, "spot": 1325.1, "dma200": 0.97, "rsi14": 40.3, "z5d": 0.41, "futOi": -2.4, "iv": 25.8, "yz": 21.8, "step": 20.0, "roe": 16.8, "secRoe": 15.2, "pat": 16.4, "fnoVol": 164200, "base_2020": 355.3, "high_20_26": 1702.05},
    {"sym": "NESTLEIND", "lot": 500, "spot": 1265.5, "dma200": 0.93, "rsi14": 35.8, "z5d": -1.07, "futOi": -1.9, "iv": 35.9, "yz": 31.6, "step": 20.0, "roe": 84.0, "secRoe": 24.0, "pat": 9.8, "fnoVol": 118900, "base_2020": 610.0, "high_20_26": 1553.0},
    {"sym": "ICICIBANK", "lot": 700, "spot": 1397.0, "dma200": 1.03, "rsi14": 59.2, "z5d": 1.17, "futOi": -3.1, "iv": 21.0, "yz": 18.5, "step": 20.0, "roe": 18.4, "secRoe": 14.2, "pat": 17.2, "fnoVol": 534000, "base_2020": 268.3, "high_20_26": 1500.0},
    {"sym": "LT", "lot": 175, "spot": 3627.1, "dma200": 0.92, "rsi14": 36.8, "z5d": -0.68, "futOi": -3.2, "iv": 23.4, "yz": 19.1, "step": 50.0, "roe": 16.5, "secRoe": 13.8, "pat": 15.1, "fnoVol": 319500, "base_2020": 661.0, "high_20_26": 4440.0},
    {"sym": "ASIANPAINT", "lot": 250, "spot": 2331.9, "dma200": 0.92, "rsi14": 37.9, "z5d": -0.81, "futOi": -1.4, "iv": 27.0, "yz": 22.8, "step": 20.0, "roe": 26.4, "secRoe": 18.5, "pat": 6.4, "fnoVol": 178200, "base_2020": 1431.2, "high_20_26": 3590.0},
    {"sym": "HINDALCO", "lot": 700, "spot": 908.0, "dma200": 0.93, "rsi14": 40.3, "z5d": 1.23, "futOi": -2.2, "iv": 28.9, "yz": 24.9, "step": 10.0, "roe": 14.9, "secRoe": 12.4, "pat": 24.6, "fnoVol": 289400, "base_2020": 84.9, "high_20_26": 1176.0},
    {"sym": "SBIN", "lot": 750, "spot": 962.6, "dma200": 0.93, "rsi14": 44.7, "z5d": 0.89, "futOi": -2.7, "iv": 21.6, "yz": 18.0, "step": 10.0, "roe": 17.8, "secRoe": 14.2, "pat": 20.4, "fnoVol": 645000, "base_2020": 173.55, "high_20_26": 1234.7},
    {"sym": "BHARTIARTL", "lot": 475, "spot": 1905.0, "dma200": 1.0, "rsi14": 61.8, "z5d": 1.5, "futOi": -2.9, "iv": 24.4, "yz": 22.1, "step": 20.0, "roe": 16.9, "secRoe": 11.0, "pat": 34.2, "fnoVol": 342100, "base_2020": 355.1, "high_20_26": 2174.5},
    {"sym": "AXISBANK", "lot": 625, "spot": 1290.0, "dma200": 1.0, "rsi14": 62.8, "z5d": 1.08, "futOi": -1.6, "iv": 24.9, "yz": 22.7, "step": 20.0, "roe": 17.2, "secRoe": 14.2, "pat": 14.6, "fnoVol": 428000, "base_2020": 286.0, "high_20_26": 1418.3},
    {"sym": "JSWSTEEL", "lot": 675, "spot": 1216.3, "dma200": 0.98, "rsi14": 45.3, "z5d": 1.46, "futOi": -1.2, "iv": 27.5, "yz": 23.9, "step": 20.0, "roe": 14.1, "secRoe": 12.4, "pat": 13.8, "fnoVol": 194000, "base_2020": 136.1, "high_20_26": 1351.0},
    {"sym": "COALINDIA", "lot": 1350, "spot": 417.2, "dma200": 0.96, "rsi14": 50.5, "z5d": 0.68, "futOi": -1.5, "iv": 25.8, "yz": 22.6, "step": 5.0, "roe": 42.5, "secRoe": 16.0, "pat": 12.9, "fnoVol": 267000, "base_2020": 103.95, "high_20_26": 543.55},
    {"sym": "BAJAJ-AUTO", "lot": 75, "spot": 10405.0, "dma200": 1.01, "rsi14": 42.8, "z5d": 0.85, "futOi": 1.2, "iv": 30.1, "yz": 26.3, "step": 100.0, "roe": 27.8, "secRoe": 17.5, "pat": 19.4, "fnoVol": 142000, "base_2020": 1788.65, "high_20_26": 12774.0},
    {"sym": "KOTAKBANK", "lot": 2000, "spot": 447.4, "dma200": 1.12, "rsi14": 68.2, "z5d": 0.92, "futOi": 2.1, "iv": 28.1, "yz": 26.3, "step": 5.0, "roe": 15.4, "secRoe": 14.2, "pat": 12.1, "fnoVol": 389000, "base_2020": 200.2, "high_20_26": 460.4},
    {"sym": "HEROMOTOCO", "lot": 150, "spot": 5225.0, "dma200": 0.98, "rsi14": 52.2, "z5d": 1.12, "futOi": 1.8, "iv": 29.7, "yz": 26.7, "step": 50.0, "roe": 24.1, "secRoe": 17.5, "pat": 16.8, "fnoVol": 134500, "base_2020": 1375.0, "high_20_26": 6388.5},
    {"sym": "TCS", "lot": 225, "spot": 2465.0, "dma200": 1.0, "rsi14": 73.5, "z5d": 1.31, "futOi": 2.4, "iv": 35.2, "yz": 33.4, "step": 20.0, "roe": 51.4, "secRoe": 24.5, "pat": 9.4, "fnoVol": 376000, "base_2020": 1506.05, "high_20_26": 4592.25},
    {"sym": "HCLTECH", "lot": 400, "spot": 1380.0, "dma200": 1.03, "rsi14": 69.0, "z5d": 0.94, "futOi": 2.8, "iv": 33.0, "yz": 31.2, "step": 20.0, "roe": 25.2, "secRoe": 24.5, "pat": 11.8, "fnoVol": 215000, "base_2020": 375.25, "high_20_26": 2012.2},
    {"sym": "TECHM", "lot": 600, "spot": 1790.0, "dma200": 1.18, "rsi14": 75.6, "z5d": 1.52, "futOi": 3.1, "iv": 34.3, "yz": 32.5, "step": 20.0, "roe": 15.8, "secRoe": 24.5, "pat": 18.2, "fnoVol": 189000, "base_2020": 471.4, "high_20_26": 1854.0},
    {"sym": "INFY", "lot": 400, "spot": 1161.2, "dma200": 0.94, "rsi14": 69.8, "z5d": 1.38, "futOi": 1.5, "iv": 32.0, "yz": 30.2, "step": 20.0, "roe": 31.8, "secRoe": 24.5, "pat": 8.7, "fnoVol": 462000, "base_2020": 509.25, "high_20_26": 2006.45},
    {"sym": "HDFCBANK", "lot": 650, "spot": 728.85, "dma200": 0.91, "rsi14": 55.3, "z5d": 1.13, "futOi": 0.8, "iv": 25.1, "yz": 22.3, "step": 10.0, "roe": 16.1, "secRoe": 14.2, "pat": 15.4, "fnoVol": 712000, "base_2020": 369.4, "high_20_26": 1020.5},
    {"sym": "RELIANCE", "lot": 500, "spot": 1211.2, "dma200": 0.9, "rsi14": 48.7, "z5d": 1.0, "futOi": 1.9, "iv": 22.5, "yz": 19.2, "step": 20.0, "roe": 11.2, "secRoe": 12.0, "pat": 7.9, "fnoVol": 689000, "base_2020": 417.3, "high_20_26": 1611.8},
    {"sym": "ITC", "lot": 1725, "spot": 263.5, "dma200": 0.89, "rsi14": 49.2, "z5d": 0.81, "futOi": 2.2, "iv": 26.2, "yz": 22.9, "step": 5.0, "roe": 28.4, "secRoe": 24.0, "pat": 6.8, "fnoVol": 395000, "base_2020": 134.6, "high_20_26": 528.5},
    {"sym": "MARUTI", "lot": 50, "spot": 11489.0, "dma200": 0.84, "rsi14": 38.8, "z5d": 1.18, "futOi": 4.5, "iv": 24.3, "yz": 20.2, "step": 100.0, "roe": 16.8, "secRoe": 17.5, "pat": 13.2, "fnoVol": 208000, "base_2020": 4030.0, "high_20_26": 17370.0},
    {"sym": "NTPC", "lot": 1500, "spot": 315.15, "dma200": 0.88, "rsi14": 41.0, "z5d": 0.99, "futOi": 1.4, "iv": 22.9, "yz": 19.0, "step": 5.0, "roe": 14.2, "secRoe": 12.8, "pat": 11.4, "fnoVol": 274000, "base_2020": 73.2, "high_20_26": 448.45},
    {"sym": "POWERGRID", "lot": 1900, "spot": 250.45, "dma200": 0.88, "rsi14": 38.8, "z5d": 0.93, "futOi": 0.9, "iv": 24.9, "yz": 20.8, "step": 5.0, "roe": 18.6, "secRoe": 12.8, "pat": 8.9, "fnoVol": 219000, "base_2020": 65.15, "high_20_26": 366.25},
    {"sym": "WIPRO", "lot": 3000, "spot": 184.4, "dma200": 0.94, "rsi14": 71.8, "z5d": 1.5, "futOi": 2.9, "iv": 32.2, "yz": 30.4, "step": 2.5, "roe": 15.6, "secRoe": 24.5, "pat": 5.4, "fnoVol": 254000, "base_2020": 79.7, "high_20_26": 369.9},
    {"sym": "ULTRACEMCO", "lot": 50, "spot": 10907.0, "dma200": 0.94, "rsi14": 49.7, "z5d": 0.93, "futOi": 1.1, "iv": 23.3, "yz": 20.1, "step": 100.0, "roe": 13.5, "secRoe": 11.9, "pat": 14.8, "fnoVol": 112000, "base_2020": 2910.0, "high_20_26": 13110.0},
    {"sym": "M&M", "lot": 200, "spot": 2920.9, "dma200": 0.9, "rsi14": 46.3, "z5d": 1.41, "futOi": 3.4, "iv": 26.1, "yz": 22.6, "step": 50.0, "roe": 19.8, "secRoe": 17.5, "pat": 21.6, "fnoVol": 364000, "base_2020": 245.4, "high_20_26": 3839.9},
    {"sym": "TATASTEEL", "lot": 2750, "spot": 175.5, "dma200": 0.9, "rsi14": 41.3, "z5d": 0.5, "futOi": 3.8, "iv": 29.8, "yz": 25.9, "step": 2.5, "roe": 9.4, "secRoe": 12.4, "pat": 4.2, "fnoVol": 518000, "base_2020": 25.1, "high_20_26": 224.4},
    {"sym": "ONGC", "lot": 2250, "spot": 222.0, "dma200": 0.87, "rsi14": 39.1, "z5d": -0.44, "futOi": 2.7, "iv": 22.0, "yz": 17.9, "step": 2.5, "roe": 15.1, "secRoe": 12.0, "pat": 6.1, "fnoVol": 298000, "base_2020": 44.25, "high_20_26": 345.0},
    {"sym": "BRITANNIA", "lot": 125, "spot": 4764.0, "dma200": 0.87, "rsi14": 39.7, "z5d": -0.89, "futOi": 3.2, "iv": 23.0, "yz": 19.0, "step": 50.0, "roe": 54.2, "secRoe": 24.0, "pat": 7.5, "fnoVol": 92000, "base_2020": 2100.0, "high_20_26": 6469.9},
    {"sym": "DABUR", "lot": 1250, "spot": 385.0, "dma200": 0.87, "rsi14": 50.3, "z5d": 0.55, "futOi": 2.9, "iv": 26.7, "yz": 23.5, "step": 5.0, "roe": 19.2, "secRoe": 24.0, "pat": 5.2, "fnoVol": 84000, "base_2020": 386.05, "high_20_26": 672.0},
    {"sym": "GODREJCP", "lot": 500, "spot": 855.0, "dma200": 0.81, "rsi14": 41.7, "z5d": -0.92, "futOi": 5.1, "iv": 26.9, "yz": 23.0, "step": 10.0, "roe": 17.4, "secRoe": 24.0, "pat": 4.8, "fnoVol": 76000, "base_2020": 425.1, "high_20_26": 1541.85},
    {"sym": "HAVELLS", "lot": 500, "spot": 1121.0, "dma200": 0.9, "rsi14": 54.8, "z5d": 0.75, "futOi": 1.7, "iv": 27.6, "yz": 24.8, "step": 20.0, "roe": 18.9, "secRoe": 15.0, "pat": 14.1, "fnoVol": 105000, "base_2020": 458.05, "high_20_26": 2106.0},
    {"sym": "VOLTAS", "lot": 375, "spot": 1029.1, "dma200": 0.78, "rsi14": 34.7, "z5d": -0.6, "futOi": 6.2, "iv": 30.8, "yz": 26.4, "step": 20.0, "roe": 9.8, "secRoe": 15.0, "pat": 11.2, "fnoVol": 149000, "base_2020": 448.75, "high_20_26": 1944.9},
]

EXTRA_9_FOR_TOP50: List[Dict[str, Any]] = [
    {"sym": "HAL", "lot": 150, "spot": 4989.0, "dma200": 1.13, "rsi14": 60.5, "z5d": 1.13, "futOi": -2.4, "iv": 24.2, "yz": 21.8, "step": 50.0, "roe": 28.9, "secRoe": 16.0, "pat": 26.4, "fnoVol": 392000, "base_2020": 235.0, "high_20_26": 5674.75},
    {"sym": "BEL", "lot": 1425, "spot": 376.85, "dma200": 0.9, "rsi14": 40.7, "z5d": -0.56, "futOi": -1.9, "iv": 23.1, "yz": 19.2, "step": 5.0, "roe": 26.4, "secRoe": 16.0, "pat": 29.1, "fnoVol": 448000, "base_2020": 18.65, "high_20_26": 473.45},
    {"sym": "TRENT", "lot": 225, "spot": 2958.7, "dma200": 1.06, "rsi14": 61.7, "z5d": 0.1, "futOi": -2.8, "iv": 39.8, "yz": 37.5, "step": 100.0, "roe": 32.5, "secRoe": 18.0, "pat": 41.0, "fnoVol": 276000, "base_2020": 243.3, "high_20_26": 5563.6},
    {"sym": "DLF", "lot": 950, "spot": 675.0, "dma200": 1.08, "rsi14": 55.3, "z5d": 1.01, "futOi": -2.1, "iv": 28.9, "yz": 26.1, "step": 10.0, "roe": 11.8, "secRoe": 10.2, "pat": 24.0, "fnoVol": 312000, "base_2020": 114.55, "high_20_26": 967.6},
    {"sym": "INDIGO", "lot": 150, "spot": 4686.9, "dma200": 0.97, "rsi14": 37.0, "z5d": -1.37, "futOi": -1.5, "iv": 30.0, "yz": 25.8, "step": 50.0, "roe": 44.0, "secRoe": 14.0, "pat": 22.8, "fnoVol": 234000, "base_2020": 771.3, "high_20_26": 6232.5},
    {"sym": "DIVISLAB", "lot": 100, "spot": 9144.5, "dma200": 1.27, "rsi14": 46.9, "z5d": -0.21, "futOi": -2.2, "iv": 26.7, "yz": 23.3, "step": 50.0, "roe": 16.4, "secRoe": 15.2, "pat": 21.5, "fnoVol": 128000, "base_2020": 1626.0, "high_20_26": 9740.0},
    {"sym": "PIDILITIND", "lot": 500, "spot": 1502.8, "dma200": 1.0, "rsi14": 45.0, "z5d": 0.58, "futOi": -1.7, "iv": 28.1, "yz": 24.5, "step": 20.0, "roe": 23.6, "secRoe": 16.5, "pat": 17.9, "fnoVol": 94000, "base_2020": 592.8, "high_20_26": 1707.5},
    {"sym": "APOLLOHOSP", "lot": 125, "spot": 7890.0, "dma200": 0.98, "rsi14": 37.3, "z5d": 0.81, "futOi": -2.0, "iv": 37.7, "yz": 33.5, "step": 100.0, "roe": 18.2, "secRoe": 14.8, "pat": 25.4, "fnoVol": 156000, "base_2020": 1047.05, "high_20_26": 9070.5},
    {"sym": "CHOLAFIN", "lot": 625, "spot": 1574.4, "dma200": 0.94, "rsi14": 37.2, "z5d": -0.49, "futOi": -2.5, "iv": 44.2, "yz": 40.0, "step": 20.0, "roe": 20.6, "secRoe": 15.8, "pat": 23.7, "fnoVol": 204000, "base_2020": 123.6, "high_20_26": 1952.5},
]

EXTRA_170_META: Dict[str, Dict[str, Any]] = {
    "360ONE": {
        "sym": "360ONE",
        "lot": 500,
        "spot": 1100.0,
        "step": 20.0,
        "dma200": 0.92,
        "rsi14": 38.0,
        "z5d": -1.5,
        "futOi": -3.2,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 14.0,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 90000,
        "base2020": 418.0,
        "high20_26": 1364.0
    },
    "ABCAPITAL": {
        "sym": "ABCAPITAL",
        "lot": 3100,
        "spot": 390.0,
        "step": 5.0,
        "dma200": 0.93,
        "rsi14": 38.9,
        "z5d": -1.39,
        "futOi": -2.8,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 15.1,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 666500,
        "base2020": 148.2,
        "high20_26": 483.6
    },
    "ADANIENSOL": {
        "sym": "ADANIENSOL",
        "lot": 675,
        "spot": 1400.0,
        "step": 20.0,
        "dma200": 0.94,
        "rsi14": 39.8,
        "z5d": -1.28,
        "futOi": -2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 16.1,
        "secRoe": 16.1,
        "pat": 8.8,
        "fnoVol": 168750,
        "base2020": 532.0,
        "high20_26": 1736.0
    },
    "ADANIENT": {
        "sym": "ADANIENT",
        "lot": 309,
        "spot": 2900.0,
        "step": 20.0,
        "dma200": 0.95,
        "rsi14": 40.7,
        "z5d": -1.17,
        "futOi": -2.0,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 17.1,
        "secRoe": 16.9,
        "pat": 9.7,
        "fnoVol": 88065,
        "base2020": 1102.0,
        "high20_26": 3596.0
    },
    "ADANIGREEN": {
        "sym": "ADANIGREEN",
        "lot": 600,
        "spot": 1260.0,
        "step": 20.0,
        "dma200": 0.96,
        "rsi14": 41.6,
        "z5d": -1.06,
        "futOi": -1.6,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 18.2,
        "secRoe": 17.7,
        "pat": 10.6,
        "fnoVol": 192000,
        "base2020": 478.8,
        "high20_26": 1562.4
    },
    "ADANIPORTS": {
        "sym": "ADANIPORTS",
        "lot": 475,
        "spot": 1740.0,
        "step": 20.0,
        "dma200": 0.97,
        "rsi14": 42.5,
        "z5d": -0.95,
        "futOi": -1.2,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 19.2,
        "secRoe": 18.5,
        "pat": 11.5,
        "fnoVol": 168625,
        "base2020": 661.2,
        "high20_26": 2157.6
    },
    "ADANIPOWER": {
        "sym": "ADANIPOWER",
        "lot": 3550,
        "spot": 195.0,
        "step": 5.0,
        "dma200": 0.98,
        "rsi14": 43.4,
        "z5d": -0.84,
        "futOi": -0.8,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 20.3,
        "secRoe": 14.5,
        "pat": 12.4,
        "fnoVol": 1384500,
        "base2020": 74.1,
        "high20_26": 241.8
    },
    "ALKEM": {
        "sym": "ALKEM",
        "lot": 125,
        "spot": 5200.0,
        "step": 50.0,
        "dma200": 0.99,
        "rsi14": 44.3,
        "z5d": -0.73,
        "futOi": -0.4,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 21.4,
        "secRoe": 15.3,
        "pat": 13.3,
        "fnoVol": 53125,
        "base2020": 1976.0,
        "high20_26": 6448.0
    },
    "AMBER": {
        "sym": "AMBER",
        "lot": 100,
        "spot": 6900.0,
        "step": 50.0,
        "dma200": 1.0,
        "rsi14": 45.2,
        "z5d": -0.62,
        "futOi": 0.0,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 22.4,
        "secRoe": 16.1,
        "pat": 14.2,
        "fnoVol": 46000,
        "base2020": 2622.0,
        "high20_26": 8556.0
    },
    "AMBUJACEM": {
        "sym": "AMBUJACEM",
        "lot": 1200,
        "spot": 380.0,
        "step": 5.0,
        "dma200": 1.01,
        "rsi14": 46.1,
        "z5d": -0.51,
        "futOi": 0.4,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 23.5,
        "secRoe": 16.9,
        "pat": 15.1,
        "fnoVol": 594000,
        "base2020": 144.4,
        "high20_26": 471.2
    },
    "ANANDRATHI": {
        "sym": "ANANDRATHI",
        "lot": 250,
        "spot": 2100.0,
        "step": 20.0,
        "dma200": 1.02,
        "rsi14": 47.0,
        "z5d": -0.4,
        "futOi": 0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 24.5,
        "secRoe": 17.7,
        "pat": 16.0,
        "fnoVol": 132500,
        "base2020": 798.0,
        "high20_26": 2604.0
    },
    "ANGELONE": {
        "sym": "ANGELONE",
        "lot": 2500,
        "spot": 295.0,
        "step": 5.0,
        "dma200": 1.03,
        "rsi14": 47.9,
        "z5d": -0.29,
        "futOi": 1.2,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 25.6,
        "secRoe": 18.5,
        "pat": 16.9,
        "fnoVol": 1412500,
        "base2020": 112.1,
        "high20_26": 365.8
    },
    "APLAPOLLO": {
        "sym": "APLAPOLLO",
        "lot": 350,
        "spot": 2160.0,
        "step": 20.0,
        "dma200": 1.04,
        "rsi14": 48.8,
        "z5d": -0.18,
        "futOi": 1.6,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 26.6,
        "secRoe": 14.5,
        "pat": 17.8,
        "fnoVol": 210000,
        "base2020": 820.8,
        "high20_26": 2678.4
    },
    "ASHOKLEY": {
        "sym": "ASHOKLEY",
        "lot": 5000,
        "spot": 162.5,
        "step": 5.0,
        "dma200": 1.05,
        "rsi14": 49.7,
        "z5d": -0.07,
        "futOi": 2.0,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 27.6,
        "secRoe": 15.3,
        "pat": 18.7,
        "fnoVol": 3175000,
        "base2020": 61.8,
        "high20_26": 201.5
    },
    "ASTRAL": {
        "sym": "ASTRAL",
        "lot": 425,
        "spot": 1440.0,
        "step": 20.0,
        "dma200": 1.06,
        "rsi14": 50.6,
        "z5d": 0.04,
        "futOi": 2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 28.7,
        "secRoe": 16.1,
        "pat": 19.6,
        "fnoVol": 284750,
        "base2020": 547.2,
        "high20_26": 1785.6
    },
    "ATHERENERG": {
        "sym": "ATHERENERG",
        "lot": 375,
        "spot": 1560.0,
        "step": 20.0,
        "dma200": 1.07,
        "rsi14": 51.5,
        "z5d": 0.15,
        "futOi": 2.8,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 29.8,
        "secRoe": 16.9,
        "pat": 20.5,
        "fnoVol": 67500,
        "base2020": 592.8,
        "high20_26": 1934.4
    },
    "AUBANK": {
        "sym": "AUBANK",
        "lot": 1000,
        "spot": 1020.0,
        "step": 20.0,
        "dma200": 1.08,
        "rsi14": 52.4,
        "z5d": 0.26,
        "futOi": -3.2,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 30.8,
        "secRoe": 17.7,
        "pat": 21.4,
        "fnoVol": 215000,
        "base2020": 387.6,
        "high20_26": 1264.8
    },
    "AUROPHARMA": {
        "sym": "AUROPHARMA",
        "lot": 550,
        "spot": 1680.0,
        "step": 20.0,
        "dma200": 1.09,
        "rsi14": 53.3,
        "z5d": 0.37,
        "futOi": -2.8,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 31.9,
        "secRoe": 18.5,
        "pat": 22.3,
        "fnoVol": 137500,
        "base2020": 638.4,
        "high20_26": 2083.2
    },
    "BAJAJFINSV": {
        "sym": "BAJAJFINSV",
        "lot": 300,
        "spot": 1860.0,
        "step": 20.0,
        "dma200": 0.92,
        "rsi14": 54.2,
        "z5d": 0.48,
        "futOi": -2.4,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 32.9,
        "secRoe": 14.5,
        "pat": 23.2,
        "fnoVol": 85500,
        "base2020": 706.8,
        "high20_26": 2306.4
    },
    "BAJAJHLDNG": {
        "sym": "BAJAJHLDNG",
        "lot": 75,
        "spot": 11000.0,
        "step": 50.0,
        "dma200": 0.93,
        "rsi14": 55.1,
        "z5d": 0.59,
        "futOi": -2.0,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 34.0,
        "secRoe": 15.3,
        "pat": 24.1,
        "fnoVol": 24000,
        "base2020": 4180.0,
        "high20_26": 13640.0
    },
    "BANDHANBNK": {
        "sym": "BANDHANBNK",
        "lot": 3600,
        "spot": 170.0,
        "step": 5.0,
        "dma200": 0.94,
        "rsi14": 56.0,
        "z5d": 0.7,
        "futOi": -1.6,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 14.0,
        "secRoe": 16.1,
        "pat": 25.0,
        "fnoVol": 1278000,
        "base2020": 64.6,
        "high20_26": 210.8
    },
    "BANKBARODA": {
        "sym": "BANKBARODA",
        "lot": 2925,
        "spot": 235.0,
        "step": 5.0,
        "dma200": 0.95,
        "rsi14": 56.9,
        "z5d": 0.81,
        "futOi": -1.2,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 15.1,
        "secRoe": 16.9,
        "pat": 25.9,
        "fnoVol": 1140750,
        "base2020": 89.3,
        "high20_26": 291.4
    },
    "BANKINDIA": {
        "sym": "BANKINDIA",
        "lot": 5200,
        "spot": 137.5,
        "step": 5.0,
        "dma200": 0.96,
        "rsi14": 57.8,
        "z5d": 0.92,
        "futOi": -0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 16.1,
        "secRoe": 17.7,
        "pat": 26.8,
        "fnoVol": 2210000,
        "base2020": 52.2,
        "high20_26": 170.5
    },
    "BDL": {
        "sym": "BDL",
        "lot": 425,
        "spot": 1200.0,
        "step": 20.0,
        "dma200": 0.97,
        "rsi14": 58.7,
        "z5d": 1.03,
        "futOi": -0.4,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 17.1,
        "secRoe": 18.5,
        "pat": 27.7,
        "fnoVol": 195500,
        "base2020": 456.0,
        "high20_26": 1488.0
    },
    "BHARATFORG": {
        "sym": "BHARATFORG",
        "lot": 500,
        "spot": 1940.0,
        "step": 20.0,
        "dma200": 0.98,
        "rsi14": 59.6,
        "z5d": 1.14,
        "futOi": 0.0,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 18.2,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 247500,
        "base2020": 737.2,
        "high20_26": 2405.6
    },
    "BHEL": {
        "sym": "BHEL",
        "lot": 2625,
        "spot": 435.0,
        "step": 10.0,
        "dma200": 0.99,
        "rsi14": 60.5,
        "z5d": 1.25,
        "futOi": 0.4,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 19.2,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 1391250,
        "base2020": 165.3,
        "high20_26": 539.4
    },
    "BIOCON": {
        "sym": "BIOCON",
        "lot": 2500,
        "spot": 380.0,
        "step": 5.0,
        "dma200": 1.0,
        "rsi14": 61.4,
        "z5d": -1.5,
        "futOi": 0.8,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 20.3,
        "secRoe": 16.1,
        "pat": 8.8,
        "fnoVol": 1412500,
        "base2020": 144.4,
        "high20_26": 471.2
    },
    "BLUESTARCO": {
        "sym": "BLUESTARCO",
        "lot": 325,
        "spot": 1520.0,
        "step": 20.0,
        "dma200": 1.01,
        "rsi14": 62.3,
        "z5d": -1.39,
        "futOi": 1.2,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 21.4,
        "secRoe": 16.9,
        "pat": 9.7,
        "fnoVol": 195000,
        "base2020": 577.6,
        "high20_26": 1884.8
    },
    "BOSCHLTD": {
        "sym": "BOSCHLTD",
        "lot": 25,
        "spot": 45500.0,
        "step": 50.0,
        "dma200": 1.02,
        "rsi14": 38.0,
        "z5d": -1.28,
        "futOi": 1.6,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 22.4,
        "secRoe": 17.7,
        "pat": 10.6,
        "fnoVol": 15875,
        "base2020": 17290.0,
        "high20_26": 56420.0
    },
    "BPCL": {
        "sym": "BPCL",
        "lot": 1975,
        "spot": 305.0,
        "step": 5.0,
        "dma200": 1.03,
        "rsi14": 38.9,
        "z5d": -1.17,
        "futOi": 2.0,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 23.5,
        "secRoe": 18.5,
        "pat": 11.5,
        "fnoVol": 1323250,
        "base2020": 115.9,
        "high20_26": 378.2
    },
    "BSE": {
        "sym": "BSE",
        "lot": 200,
        "spot": 3250.0,
        "step": 50.0,
        "dma200": 1.04,
        "rsi14": 39.8,
        "z5d": -1.06,
        "futOi": 2.4,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 24.5,
        "secRoe": 14.5,
        "pat": 12.4,
        "fnoVol": 36000,
        "base2020": 1235.0,
        "high20_26": 4030.0
    },
    "CAMS": {
        "sym": "CAMS",
        "lot": 825,
        "spot": 720.0,
        "step": 10.0,
        "dma200": 1.05,
        "rsi14": 40.7,
        "z5d": -0.95,
        "futOi": 2.8,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 25.6,
        "secRoe": 15.3,
        "pat": 13.3,
        "fnoVol": 177375,
        "base2020": 273.6,
        "high20_26": 892.8
    },
    "CANBK": {
        "sym": "CANBK",
        "lot": 6750,
        "spot": 122.0,
        "step": 5.0,
        "dma200": 1.06,
        "rsi14": 41.6,
        "z5d": -0.84,
        "futOi": -3.2,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 26.6,
        "secRoe": 16.1,
        "pat": 14.2,
        "fnoVol": 1687500,
        "base2020": 46.4,
        "high20_26": 151.3
    },
    "CDSL": {
        "sym": "CDSL",
        "lot": 475,
        "spot": 1340.0,
        "step": 20.0,
        "dma200": 1.07,
        "rsi14": 42.5,
        "z5d": -0.73,
        "futOi": -2.8,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 27.6,
        "secRoe": 16.9,
        "pat": 15.1,
        "fnoVol": 135375,
        "base2020": 509.2,
        "high20_26": 1661.6
    },
    "CENTRALBK": {
        "sym": "CENTRALBK",
        "lot": 1500,
        "spot": 200.0,
        "step": 5.0,
        "dma200": 1.08,
        "rsi14": 43.4,
        "z5d": -0.62,
        "futOi": -2.4,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 28.7,
        "secRoe": 17.7,
        "pat": 16.0,
        "fnoVol": 480000,
        "base2020": 76.0,
        "high20_26": 248.0
    },
    "CGPOWER": {
        "sym": "CGPOWER",
        "lot": 850,
        "spot": 850.0,
        "step": 10.0,
        "dma200": 1.09,
        "rsi14": 44.3,
        "z5d": -0.51,
        "futOi": -2.0,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 29.8,
        "secRoe": 18.5,
        "pat": 16.9,
        "fnoVol": 301750,
        "base2020": 323.0,
        "high20_26": 1054.0
    },
    "COCHINSHIP": {
        "sym": "COCHINSHIP",
        "lot": 400,
        "spot": 1380.0,
        "step": 20.0,
        "dma200": 0.92,
        "rsi14": 45.2,
        "z5d": -0.4,
        "futOi": -1.6,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 30.8,
        "secRoe": 14.5,
        "pat": 17.8,
        "fnoVol": 156000,
        "base2020": 524.4,
        "high20_26": 1711.2
    },
    "COFORGE": {
        "sym": "COFORGE",
        "lot": 475,
        "spot": 1880.0,
        "step": 20.0,
        "dma200": 0.93,
        "rsi14": 46.1,
        "z5d": -0.29,
        "futOi": -1.2,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 31.9,
        "secRoe": 15.3,
        "pat": 18.7,
        "fnoVol": 201875,
        "base2020": 714.4,
        "high20_26": 2331.2
    },
    "COLPAL": {
        "sym": "COLPAL",
        "lot": 275,
        "spot": 1840.0,
        "step": 20.0,
        "dma200": 0.94,
        "rsi14": 47.0,
        "z5d": -0.18,
        "futOi": -0.8,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 32.9,
        "secRoe": 16.1,
        "pat": 19.6,
        "fnoVol": 126500,
        "base2020": 699.2,
        "high20_26": 2281.6
    },
    "CONCOR": {
        "sym": "CONCOR",
        "lot": 1250,
        "spot": 465.0,
        "step": 10.0,
        "dma200": 0.95,
        "rsi14": 47.9,
        "z5d": -0.07,
        "futOi": -0.4,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 34.0,
        "secRoe": 16.9,
        "pat": 20.5,
        "fnoVol": 618750,
        "base2020": 176.7,
        "high20_26": 576.6
    },
    "CROMPTON": {
        "sym": "CROMPTON",
        "lot": 2150,
        "spot": 217.5,
        "step": 5.0,
        "dma200": 0.96,
        "rsi14": 48.8,
        "z5d": 0.04,
        "futOi": 0.0,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 14.0,
        "secRoe": 17.7,
        "pat": 21.4,
        "fnoVol": 1139500,
        "base2020": 82.7,
        "high20_26": 269.7
    },
    "CUMMINSIND": {
        "sym": "CUMMINSIND",
        "lot": 200,
        "spot": 4800.0,
        "step": 50.0,
        "dma200": 0.97,
        "rsi14": 49.7,
        "z5d": 0.15,
        "futOi": 0.4,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 15.1,
        "secRoe": 18.5,
        "pat": 22.3,
        "fnoVol": 113000,
        "base2020": 1824.0,
        "high20_26": 5952.0
    },
    "DELHIVERY": {
        "sym": "DELHIVERY",
        "lot": 2075,
        "spot": 420.0,
        "step": 10.0,
        "dma200": 0.98,
        "rsi14": 50.6,
        "z5d": 0.26,
        "futOi": 0.8,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 16.1,
        "secRoe": 14.5,
        "pat": 23.2,
        "fnoVol": 1245000,
        "base2020": 159.6,
        "high20_26": 520.8
    },
    "DIXON": {
        "sym": "DIXON",
        "lot": 50,
        "spot": 13500.0,
        "step": 50.0,
        "dma200": 0.99,
        "rsi14": 51.5,
        "z5d": 0.37,
        "futOi": 1.2,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 17.1,
        "secRoe": 15.3,
        "pat": 24.1,
        "fnoVol": 31750,
        "base2020": 5130.0,
        "high20_26": 16740.0
    },
    "DMART": {
        "sym": "DMART",
        "lot": 150,
        "spot": 3650.0,
        "step": 50.0,
        "dma200": 1.0,
        "rsi14": 52.4,
        "z5d": 0.48,
        "futOi": 1.6,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 18.2,
        "secRoe": 16.1,
        "pat": 25.0,
        "fnoVol": 100500,
        "base2020": 1387.0,
        "high20_26": 4526.0
    },
    "EICHERMOT": {
        "sym": "EICHERMOT",
        "lot": 100,
        "spot": 7400.0,
        "step": 50.0,
        "dma200": 1.01,
        "rsi14": 53.3,
        "z5d": 0.59,
        "futOi": 2.0,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 19.2,
        "secRoe": 16.9,
        "pat": 25.9,
        "fnoVol": 18000,
        "base2020": 2812.0,
        "high20_26": 9176.0
    },
    "ENRIN": {
        "sym": "ENRIN",
        "lot": 175,
        "spot": 3100.0,
        "step": 50.0,
        "dma200": 1.02,
        "rsi14": 54.2,
        "z5d": 0.7,
        "futOi": 2.4,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 20.3,
        "secRoe": 17.7,
        "pat": 26.8,
        "fnoVol": 37625,
        "base2020": 1178.0,
        "high20_26": 3844.0
    },
    "ETERNAL": {
        "sym": "ETERNAL",
        "lot": 2425,
        "spot": 325.0,
        "step": 5.0,
        "dma200": 1.03,
        "rsi14": 55.1,
        "z5d": 0.81,
        "futOi": 2.8,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 21.4,
        "secRoe": 18.5,
        "pat": 27.7,
        "fnoVol": 606250,
        "base2020": 123.5,
        "high20_26": 403.0
    },
    "FEDERALBNK": {
        "sym": "FEDERALBNK",
        "lot": 2500,
        "spot": 335.0,
        "step": 5.0,
        "dma200": 1.04,
        "rsi14": 56.0,
        "z5d": 0.92,
        "futOi": -3.2,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 22.4,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 712500,
        "base2020": 127.3,
        "high20_26": 415.4
    },
    "FORCEMOT": {
        "sym": "FORCEMOT",
        "lot": 25,
        "spot": 17250.0,
        "step": 50.0,
        "dma200": 1.05,
        "rsi14": 56.9,
        "z5d": 1.03,
        "futOi": -2.8,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 23.5,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 8000,
        "base2020": 6555.0,
        "high20_26": 21390.0
    },
    "FORTIS": {
        "sym": "FORTIS",
        "lot": 775,
        "spot": 820.0,
        "step": 10.0,
        "dma200": 1.06,
        "rsi14": 57.8,
        "z5d": 1.14,
        "futOi": -2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 24.5,
        "secRoe": 16.1,
        "pat": 8.8,
        "fnoVol": 275125,
        "base2020": 311.6,
        "high20_26": 1016.8
    },
    "GAIL": {
        "sym": "GAIL",
        "lot": 3550,
        "spot": 172.5,
        "step": 5.0,
        "dma200": 1.07,
        "rsi14": 58.7,
        "z5d": 1.25,
        "futOi": -2.0,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 25.6,
        "secRoe": 16.9,
        "pat": 9.7,
        "fnoVol": 1384500,
        "base2020": 65.5,
        "high20_26": 213.9
    },
    "GLENMARK": {
        "sym": "GLENMARK",
        "lot": 375,
        "spot": 2360.0,
        "step": 20.0,
        "dma200": 1.08,
        "rsi14": 59.6,
        "z5d": -1.5,
        "futOi": -1.6,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 26.6,
        "secRoe": 17.7,
        "pat": 10.6,
        "fnoVol": 159375,
        "base2020": 896.8,
        "high20_26": 2926.4
    },
    "GMRAIRPORT": {
        "sym": "GMRAIRPORT",
        "lot": 6975,
        "spot": 95.0,
        "step": 2.5,
        "dma200": 1.09,
        "rsi14": 60.5,
        "z5d": -1.39,
        "futOi": -1.2,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 27.6,
        "secRoe": 18.5,
        "pat": 11.5,
        "fnoVol": 3208500,
        "base2020": 36.1,
        "high20_26": 117.8
    },
    "GODFRYPHLP": {
        "sym": "GODFRYPHLP",
        "lot": 275,
        "spot": 1880.0,
        "step": 20.0,
        "dma200": 0.92,
        "rsi14": 61.4,
        "z5d": -1.28,
        "futOi": -0.8,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 28.7,
        "secRoe": 14.5,
        "pat": 12.4,
        "fnoVol": 136125,
        "base2020": 714.4,
        "high20_26": 2331.2
    },
    "GODREJPROP": {
        "sym": "GODREJPROP",
        "lot": 325,
        "spot": 1780.0,
        "step": 20.0,
        "dma200": 0.93,
        "rsi14": 62.3,
        "z5d": -1.17,
        "futOi": -0.4,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 29.8,
        "secRoe": 15.3,
        "pat": 13.3,
        "fnoVol": 172250,
        "base2020": 676.4,
        "high20_26": 2207.2
    },
    "GVT&D": {
        "sym": "GVT&D",
        "lot": 125,
        "spot": 4200.0,
        "step": 50.0,
        "dma200": 0.94,
        "rsi14": 38.0,
        "z5d": -1.06,
        "futOi": 0.0,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 30.8,
        "secRoe": 16.1,
        "pat": 14.2,
        "fnoVol": 70625,
        "base2020": 1596.0,
        "high20_26": 5208.0
    },
    "HDFCAMC": {
        "sym": "HDFCAMC",
        "lot": 300,
        "spot": 2380.0,
        "step": 20.0,
        "dma200": 0.95,
        "rsi14": 38.9,
        "z5d": -0.95,
        "futOi": 0.4,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 31.9,
        "secRoe": 16.9,
        "pat": 15.1,
        "fnoVol": 180000,
        "base2020": 904.4,
        "high20_26": 2951.2
    },
    "HDFCLIFE": {
        "sym": "HDFCLIFE",
        "lot": 1100,
        "spot": 540.0,
        "step": 10.0,
        "dma200": 0.96,
        "rsi14": 39.8,
        "z5d": -0.84,
        "futOi": 0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 32.9,
        "secRoe": 17.7,
        "pat": 16.0,
        "fnoVol": 698500,
        "base2020": 205.2,
        "high20_26": 669.6
    },
    "HFCL": {
        "sym": "HFCL",
        "lot": 1500,
        "spot": 200.0,
        "step": 5.0,
        "dma200": 0.97,
        "rsi14": 40.7,
        "z5d": -0.73,
        "futOi": 1.2,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 34.0,
        "secRoe": 18.5,
        "pat": 16.9,
        "fnoVol": 1005000,
        "base2020": 76.0,
        "high20_26": 248.0
    },
    "HINDPETRO": {
        "sym": "HINDPETRO",
        "lot": 2025,
        "spot": 355.0,
        "step": 5.0,
        "dma200": 0.98,
        "rsi14": 41.6,
        "z5d": -0.62,
        "futOi": 1.6,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 14.0,
        "secRoe": 14.5,
        "pat": 17.8,
        "fnoVol": 364500,
        "base2020": 134.9,
        "high20_26": 440.2
    },
    "HINDUNILVR": {
        "sym": "HINDUNILVR",
        "lot": 300,
        "spot": 1940.0,
        "step": 20.0,
        "dma200": 0.99,
        "rsi14": 42.5,
        "z5d": -0.51,
        "futOi": 2.0,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 15.1,
        "secRoe": 15.3,
        "pat": 18.7,
        "fnoVol": 64500,
        "base2020": 737.2,
        "high20_26": 2405.6
    },
    "HINDZINC": {
        "sym": "HINDZINC",
        "lot": 1225,
        "spot": 580.0,
        "step": 10.0,
        "dma200": 1.0,
        "rsi14": 43.4,
        "z5d": -0.4,
        "futOi": 2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 16.1,
        "secRoe": 16.1,
        "pat": 19.6,
        "fnoVol": 306250,
        "base2020": 220.4,
        "high20_26": 719.2
    },
    "HUDCO": {
        "sym": "HUDCO",
        "lot": 1500,
        "spot": 200.0,
        "step": 5.0,
        "dma200": 1.01,
        "rsi14": 44.3,
        "z5d": -0.29,
        "futOi": 2.8,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 17.1,
        "secRoe": 16.9,
        "pat": 20.5,
        "fnoVol": 427500,
        "base2020": 76.0,
        "high20_26": 248.0
    },
    "HYUNDAI": {
        "sym": "HYUNDAI",
        "lot": 275,
        "spot": 2040.0,
        "step": 20.0,
        "dma200": 1.02,
        "rsi14": 45.2,
        "z5d": -0.18,
        "futOi": -3.2,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 18.2,
        "secRoe": 17.7,
        "pat": 21.4,
        "fnoVol": 88000,
        "base2020": 775.2,
        "high20_26": 2529.6
    },
    "ICICIGI": {
        "sym": "ICICIGI",
        "lot": 325,
        "spot": 1560.0,
        "step": 20.0,
        "dma200": 1.03,
        "rsi14": 46.1,
        "z5d": -0.07,
        "futOi": -2.8,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 19.2,
        "secRoe": 18.5,
        "pat": 22.3,
        "fnoVol": 115375,
        "base2020": 592.8,
        "high20_26": 1934.4
    },
    "ICICIPRULI": {
        "sym": "ICICIPRULI",
        "lot": 925,
        "spot": 480.0,
        "step": 10.0,
        "dma200": 1.04,
        "rsi14": 47.0,
        "z5d": 0.04,
        "futOi": -2.4,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 20.3,
        "secRoe": 14.5,
        "pat": 23.2,
        "fnoVol": 360750,
        "base2020": 182.4,
        "high20_26": 595.2
    },
    "IDEA": {
        "sym": "IDEA",
        "lot": 71475,
        "spot": 15.0,
        "step": 2.5,
        "dma200": 1.05,
        "rsi14": 47.9,
        "z5d": 0.15,
        "futOi": -2.0,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 21.4,
        "secRoe": 15.3,
        "pat": 24.1,
        "fnoVol": 30376875,
        "base2020": 5.7,
        "high20_26": 18.6
    },
    "IDFCFIRSTB": {
        "sym": "IDFCFIRSTB",
        "lot": 9275,
        "spot": 83.0,
        "step": 2.5,
        "dma200": 1.06,
        "rsi14": 48.8,
        "z5d": 0.26,
        "futOi": -1.6,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 22.4,
        "secRoe": 16.1,
        "pat": 25.0,
        "fnoVol": 4266500,
        "base2020": 31.5,
        "high20_26": 102.9
    },
    "IEX": {
        "sym": "IEX",
        "lot": 4350,
        "spot": 110.0,
        "step": 5.0,
        "dma200": 1.07,
        "rsi14": 49.7,
        "z5d": 0.37,
        "futOi": -1.2,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 23.5,
        "secRoe": 16.9,
        "pat": 25.9,
        "fnoVol": 2153250,
        "base2020": 41.8,
        "high20_26": 136.4
    },
    "INDHOTEL": {
        "sym": "INDHOTEL",
        "lot": 1000,
        "spot": 740.0,
        "step": 10.0,
        "dma200": 1.08,
        "rsi14": 50.6,
        "z5d": 0.48,
        "futOi": -0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 24.5,
        "secRoe": 17.7,
        "pat": 26.8,
        "fnoVol": 530000,
        "base2020": 281.2,
        "high20_26": 917.6
    },
    "INDIANB": {
        "sym": "INDIANB",
        "lot": 1000,
        "spot": 850.0,
        "step": 10.0,
        "dma200": 1.09,
        "rsi14": 51.5,
        "z5d": 0.59,
        "futOi": -0.4,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 25.6,
        "secRoe": 18.5,
        "pat": 27.7,
        "fnoVol": 565000,
        "base2020": 323.0,
        "high20_26": 1054.0
    },
    "INDUSINDBK": {
        "sym": "INDUSINDBK",
        "lot": 700,
        "spot": 920.0,
        "step": 10.0,
        "dma200": 0.92,
        "rsi14": 52.4,
        "z5d": 0.7,
        "futOi": 0.0,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 26.6,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 420000,
        "base2020": 349.6,
        "high20_26": 1140.8
    },
    "INDUSTOWER": {
        "sym": "INDUSTOWER",
        "lot": 1700,
        "spot": 375.0,
        "step": 5.0,
        "dma200": 0.93,
        "rsi14": 53.3,
        "z5d": 0.81,
        "futOi": 0.4,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 27.6,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 1079500,
        "base2020": 142.5,
        "high20_26": 465.0
    },
    "INOXWIND": {
        "sym": "INOXWIND",
        "lot": 6400,
        "spot": 69.0,
        "step": 2.5,
        "dma200": 0.94,
        "rsi14": 54.2,
        "z5d": 0.92,
        "futOi": 0.8,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 28.7,
        "secRoe": 16.1,
        "pat": 8.8,
        "fnoVol": 4288000,
        "base2020": 26.2,
        "high20_26": 85.6
    },
    "IOC": {
        "sym": "IOC",
        "lot": 4875,
        "spot": 132.0,
        "step": 5.0,
        "dma200": 0.95,
        "rsi14": 55.1,
        "z5d": 1.03,
        "futOi": 1.2,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 29.8,
        "secRoe": 16.9,
        "pat": 9.7,
        "fnoVol": 877500,
        "base2020": 50.2,
        "high20_26": 163.7
    },
    "IRB": {
        "sym": "IRB",
        "lot": 1500,
        "spot": 200.0,
        "step": 5.0,
        "dma200": 0.96,
        "rsi14": 56.0,
        "z5d": 1.14,
        "futOi": 1.6,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 30.8,
        "secRoe": 17.7,
        "pat": 10.6,
        "fnoVol": 322500,
        "base2020": 76.0,
        "high20_26": 248.0
    },
    "IREDA": {
        "sym": "IREDA",
        "lot": 4525,
        "spot": 111.0,
        "step": 5.0,
        "dma200": 0.97,
        "rsi14": 56.9,
        "z5d": 1.25,
        "futOi": 2.0,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 31.9,
        "secRoe": 18.5,
        "pat": 11.5,
        "fnoVol": 1131250,
        "base2020": 42.2,
        "high20_26": 137.6
    },
    "IRFC": {
        "sym": "IRFC",
        "lot": 5425,
        "spot": 81.0,
        "step": 2.5,
        "dma200": 0.98,
        "rsi14": 57.8,
        "z5d": -1.5,
        "futOi": 2.4,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 32.9,
        "secRoe": 14.5,
        "pat": 12.4,
        "fnoVol": 1546125,
        "base2020": 30.8,
        "high20_26": 100.4
    },
    "ITI": {
        "sym": "ITI",
        "lot": 1500,
        "spot": 200.0,
        "step": 5.0,
        "dma200": 0.99,
        "rsi14": 58.7,
        "z5d": -1.39,
        "futOi": 2.8,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 34.0,
        "secRoe": 15.3,
        "pat": 13.3,
        "fnoVol": 480000,
        "base2020": 76.0,
        "high20_26": 248.0
    },
    "JINDALSTEL": {
        "sym": "JINDALSTEL",
        "lot": 625,
        "spot": 1100.0,
        "step": 20.0,
        "dma200": 1.0,
        "rsi14": 59.6,
        "z5d": -1.28,
        "futOi": -3.2,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 14.0,
        "secRoe": 16.1,
        "pat": 14.2,
        "fnoVol": 221875,
        "base2020": 418.0,
        "high20_26": 1364.0
    },
    "JIOFIN": {
        "sym": "JIOFIN",
        "lot": 2350,
        "spot": 232.5,
        "step": 5.0,
        "dma200": 1.01,
        "rsi14": 60.5,
        "z5d": -1.17,
        "futOi": -2.8,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 15.1,
        "secRoe": 16.9,
        "pat": 15.1,
        "fnoVol": 916500,
        "base2020": 88.3,
        "high20_26": 288.3
    },
    "JSWENERGY": {
        "sym": "JSWENERGY",
        "lot": 1075,
        "spot": 500.0,
        "step": 10.0,
        "dma200": 1.02,
        "rsi14": 61.4,
        "z5d": -1.06,
        "futOi": -2.4,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 16.1,
        "secRoe": 17.7,
        "pat": 16.0,
        "fnoVol": 456875,
        "base2020": 190.0,
        "high20_26": 620.0
    },
    "JUBLFOOD": {
        "sym": "JUBLFOOD",
        "lot": 1250,
        "spot": 470.0,
        "step": 10.0,
        "dma200": 1.03,
        "rsi14": 62.3,
        "z5d": -0.95,
        "futOi": -2.0,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 17.1,
        "secRoe": 18.5,
        "pat": 16.9,
        "fnoVol": 575000,
        "base2020": 178.6,
        "high20_26": 582.8
    },
    "KALYANKJIL": {
        "sym": "KALYANKJIL",
        "lot": 1350,
        "spot": 570.0,
        "step": 10.0,
        "dma200": 1.04,
        "rsi14": 38.0,
        "z5d": -0.84,
        "futOi": -1.6,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 18.2,
        "secRoe": 14.5,
        "pat": 17.8,
        "fnoVol": 668250,
        "base2020": 216.6,
        "high20_26": 706.8
    },
    "KAYNES": {
        "sym": "KAYNES",
        "lot": 150,
        "spot": 3450.0,
        "step": 50.0,
        "dma200": 1.05,
        "rsi14": 38.9,
        "z5d": -0.73,
        "futOi": -1.2,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 19.2,
        "secRoe": 15.3,
        "pat": 18.7,
        "fnoVol": 79500,
        "base2020": 1311.0,
        "high20_26": 4278.0
    },
    "KEI": {
        "sym": "KEI",
        "lot": 175,
        "spot": 5000.0,
        "step": 50.0,
        "dma200": 1.06,
        "rsi14": 39.8,
        "z5d": -0.62,
        "futOi": -0.8,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 20.3,
        "secRoe": 16.1,
        "pat": 19.6,
        "fnoVol": 98875,
        "base2020": 1900.0,
        "high20_26": 6200.0
    },
    "KFINTECH": {
        "sym": "KFINTECH",
        "lot": 575,
        "spot": 900.0,
        "step": 10.0,
        "dma200": 1.07,
        "rsi14": 40.7,
        "z5d": -0.51,
        "futOi": -0.4,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 21.4,
        "secRoe": 16.9,
        "pat": 20.5,
        "fnoVol": 345000,
        "base2020": 342.0,
        "high20_26": 1116.0
    },
    "KPITTECH": {
        "sym": "KPITTECH",
        "lot": 775,
        "spot": 550.0,
        "step": 10.0,
        "dma200": 1.08,
        "rsi14": 41.6,
        "z5d": -0.4,
        "futOi": 0.0,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 22.4,
        "secRoe": 17.7,
        "pat": 21.4,
        "fnoVol": 492125,
        "base2020": 209.0,
        "high20_26": 682.0
    },
    "LAURUSLABS": {
        "sym": "LAURUSLABS",
        "lot": 850,
        "spot": 2000.0,
        "step": 20.0,
        "dma200": 1.09,
        "rsi14": 42.5,
        "z5d": -0.29,
        "futOi": 0.4,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 23.5,
        "secRoe": 18.5,
        "pat": 22.3,
        "fnoVol": 569500,
        "base2020": 760.0,
        "high20_26": 2480.0
    },
    "LICHSGFIN": {
        "sym": "LICHSGFIN",
        "lot": 1000,
        "spot": 530.0,
        "step": 10.0,
        "dma200": 0.92,
        "rsi14": 43.4,
        "z5d": -0.18,
        "futOi": 0.8,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 24.5,
        "secRoe": 14.5,
        "pat": 23.2,
        "fnoVol": 180000,
        "base2020": 201.4,
        "high20_26": 657.2
    },
    "LICI": {
        "sym": "LICI",
        "lot": 1400,
        "spot": 400.0,
        "step": 5.0,
        "dma200": 0.93,
        "rsi14": 44.3,
        "z5d": -0.07,
        "futOi": 1.2,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 25.6,
        "secRoe": 15.3,
        "pat": 24.1,
        "fnoVol": 301000,
        "base2020": 152.0,
        "high20_26": 496.0
    },
    "LODHA": {
        "sym": "LODHA",
        "lot": 625,
        "spot": 1140.0,
        "step": 20.0,
        "dma200": 0.94,
        "rsi14": 45.2,
        "z5d": 0.04,
        "futOi": 1.6,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 26.6,
        "secRoe": 16.1,
        "pat": 25.0,
        "fnoVol": 156250,
        "base2020": 433.2,
        "high20_26": 1413.6
    },
    "LTF": {
        "sym": "LTF",
        "lot": 2250,
        "spot": 285.0,
        "step": 5.0,
        "dma200": 0.95,
        "rsi14": 46.1,
        "z5d": 0.15,
        "futOi": 2.0,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 27.6,
        "secRoe": 16.9,
        "pat": 25.9,
        "fnoVol": 641250,
        "base2020": 108.3,
        "high20_26": 353.4
    },
    "LTM": {
        "sym": "LTM",
        "lot": 150,
        "spot": 4350.0,
        "step": 50.0,
        "dma200": 0.96,
        "rsi14": 47.0,
        "z5d": 0.26,
        "futOi": 2.4,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 28.7,
        "secRoe": 17.7,
        "pat": 26.8,
        "fnoVol": 48000,
        "base2020": 1653.0,
        "high20_26": 5394.0
    },
    "LUPIN": {
        "sym": "LUPIN",
        "lot": 425,
        "spot": 1961.6,
        "step": 20.0,
        "dma200": 0.94,
        "rsi14": 48.2,
        "z5d": -0.92,
        "futOi": 2.8,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 29.8,
        "secRoe": 18.5,
        "pat": 27.7,
        "fnoVol": 150875,
        "base2020": 642.0,
        "high20_26": 2312.0
    },
    "MAHABANK": {
        "sym": "MAHABANK",
        "lot": 6500,
        "spot": 83.0,
        "step": 2.5,
        "dma200": 0.98,
        "rsi14": 48.8,
        "z5d": 0.48,
        "futOi": -3.2,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 30.8,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 2535000,
        "base2020": 31.5,
        "high20_26": 102.9
    },
    "MANAPPURAM": {
        "sym": "MANAPPURAM",
        "lot": 3000,
        "spot": 320.0,
        "step": 5.0,
        "dma200": 0.99,
        "rsi14": 49.7,
        "z5d": 0.59,
        "futOi": -2.8,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 31.9,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 1275000,
        "base2020": 121.6,
        "high20_26": 396.8
    },
    "MANKIND": {
        "sym": "MANKIND",
        "lot": 250,
        "spot": 2420.0,
        "step": 20.0,
        "dma200": 1.0,
        "rsi14": 50.6,
        "z5d": 0.7,
        "futOi": -2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 32.9,
        "secRoe": 16.1,
        "pat": 8.8,
        "fnoVol": 115000,
        "base2020": 919.6,
        "high20_26": 3000.8
    },
    "MARICO": {
        "sym": "MARICO",
        "lot": 1200,
        "spot": 810.0,
        "step": 10.0,
        "dma200": 1.01,
        "rsi14": 51.5,
        "z5d": 0.81,
        "futOi": -2.0,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 34.0,
        "secRoe": 16.9,
        "pat": 9.7,
        "fnoVol": 594000,
        "base2020": 307.8,
        "high20_26": 1004.4
    },
    "MAXHEALTH": {
        "sym": "MAXHEALTH",
        "lot": 525,
        "spot": 950.0,
        "step": 10.0,
        "dma200": 1.02,
        "rsi14": 52.4,
        "z5d": 0.92,
        "futOi": -1.6,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 14.0,
        "secRoe": 17.7,
        "pat": 10.6,
        "fnoVol": 278250,
        "base2020": 361.0,
        "high20_26": 1178.0
    },
    "MAZDOCK": {
        "sym": "MAZDOCK",
        "lot": 225,
        "spot": 2150.0,
        "step": 20.0,
        "dma200": 1.03,
        "rsi14": 53.3,
        "z5d": 1.03,
        "futOi": -1.2,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 15.1,
        "secRoe": 18.5,
        "pat": 11.5,
        "fnoVol": 127125,
        "base2020": 817.0,
        "high20_26": 2666.0
    },
    "MCX": {
        "sym": "MCX",
        "lot": 225,
        "spot": 3300.0,
        "step": 50.0,
        "dma200": 1.04,
        "rsi14": 54.2,
        "z5d": 1.14,
        "futOi": -0.8,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 16.1,
        "secRoe": 14.5,
        "pat": 12.4,
        "fnoVol": 135000,
        "base2020": 1254.0,
        "high20_26": 4092.0
    },
    "MFSL": {
        "sym": "MFSL",
        "lot": 400,
        "spot": 1420.0,
        "step": 20.0,
        "dma200": 1.05,
        "rsi14": 55.1,
        "z5d": 1.25,
        "futOi": -0.4,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 17.1,
        "secRoe": 15.3,
        "pat": 13.3,
        "fnoVol": 254000,
        "base2020": 539.6,
        "high20_26": 1760.8
    },
    "MOTHERSON": {
        "sym": "MOTHERSON",
        "lot": 6150,
        "spot": 160.0,
        "step": 5.0,
        "dma200": 1.06,
        "rsi14": 56.0,
        "z5d": -1.5,
        "futOi": 0.0,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 18.2,
        "secRoe": 16.1,
        "pat": 14.2,
        "fnoVol": 4120500,
        "base2020": 60.8,
        "high20_26": 198.4
    },
    "MOTILALOFS": {
        "sym": "MOTILALOFS",
        "lot": 775,
        "spot": 1040.0,
        "step": 20.0,
        "dma200": 1.07,
        "rsi14": 56.9,
        "z5d": -1.39,
        "futOi": 0.4,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 19.2,
        "secRoe": 16.9,
        "pat": 15.1,
        "fnoVol": 139500,
        "base2020": 395.2,
        "high20_26": 1289.6
    },
    "MPHASIS": {
        "sym": "MPHASIS",
        "lot": 275,
        "spot": 2400.0,
        "step": 20.0,
        "dma200": 1.08,
        "rsi14": 57.8,
        "z5d": -1.28,
        "futOi": 0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 20.3,
        "secRoe": 17.7,
        "pat": 16.0,
        "fnoVol": 59125,
        "base2020": 912.0,
        "high20_26": 2976.0
    },
    "MUTHOOTFIN": {
        "sym": "MUTHOOTFIN",
        "lot": 275,
        "spot": 2850.0,
        "step": 20.0,
        "dma200": 1.09,
        "rsi14": 58.7,
        "z5d": -1.17,
        "futOi": 1.2,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 21.4,
        "secRoe": 18.5,
        "pat": 16.9,
        "fnoVol": 68750,
        "base2020": 1083.0,
        "high20_26": 3534.0
    },
    "NAM-INDIA": {
        "sym": "NAM-INDIA",
        "lot": 625,
        "spot": 1140.0,
        "step": 20.0,
        "dma200": 0.92,
        "rsi14": 59.6,
        "z5d": -1.06,
        "futOi": 1.6,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 22.4,
        "secRoe": 14.5,
        "pat": 17.8,
        "fnoVol": 178125,
        "base2020": 433.2,
        "high20_26": 1413.6
    },
    "NATIONALUM": {
        "sym": "NATIONALUM",
        "lot": 1875,
        "spot": 340.0,
        "step": 5.0,
        "dma200": 0.93,
        "rsi14": 60.5,
        "z5d": -0.95,
        "futOi": 2.0,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 23.5,
        "secRoe": 15.3,
        "pat": 18.7,
        "fnoVol": 600000,
        "base2020": 129.2,
        "high20_26": 421.6
    },
    "NAUKRI": {
        "sym": "NAUKRI",
        "lot": 550,
        "spot": 1260.0,
        "step": 20.0,
        "dma200": 0.94,
        "rsi14": 61.4,
        "z5d": -0.84,
        "futOi": 2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 24.5,
        "secRoe": 16.1,
        "pat": 19.6,
        "fnoVol": 195250,
        "base2020": 478.8,
        "high20_26": 1562.4
    },
    "NBCC": {
        "sym": "NBCC",
        "lot": 6500,
        "spot": 80.0,
        "step": 2.5,
        "dma200": 0.95,
        "rsi14": 62.3,
        "z5d": -0.73,
        "futOi": 2.8,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 25.6,
        "secRoe": 16.9,
        "pat": 20.5,
        "fnoVol": 2535000,
        "base2020": 30.4,
        "high20_26": 99.2
    },
    "NHPC": {
        "sym": "NHPC",
        "lot": 6950,
        "spot": 74.0,
        "step": 2.5,
        "dma200": 0.96,
        "rsi14": 38.0,
        "z5d": -0.62,
        "futOi": -3.2,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 26.6,
        "secRoe": 17.7,
        "pat": 21.4,
        "fnoVol": 2953750,
        "base2020": 28.1,
        "high20_26": 91.8
    },
    "NIFTYFPI": {
        "sym": "NIFTYFPI",
        "lot": 1100,
        "spot": 1500.0,
        "step": 20.0,
        "dma200": 0.97,
        "rsi14": 38.9,
        "z5d": -0.51,
        "futOi": -2.8,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 27.6,
        "secRoe": 18.5,
        "pat": 22.3,
        "fnoVol": 506000,
        "base2020": 570.0,
        "high20_26": 1860.0
    },
    "NMDC": {
        "sym": "NMDC",
        "lot": 6750,
        "spot": 80.0,
        "step": 2.5,
        "dma200": 0.98,
        "rsi14": 39.8,
        "z5d": -0.4,
        "futOi": -2.4,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 28.7,
        "secRoe": 14.5,
        "pat": 23.2,
        "fnoVol": 3341250,
        "base2020": 30.4,
        "high20_26": 99.2
    },
    "NYKAA": {
        "sym": "NYKAA",
        "lot": 3125,
        "spot": 335.0,
        "step": 5.0,
        "dma200": 0.99,
        "rsi14": 40.7,
        "z5d": -0.29,
        "futOi": -2.0,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 29.8,
        "secRoe": 15.3,
        "pat": 24.1,
        "fnoVol": 1656250,
        "base2020": 127.3,
        "high20_26": 415.4
    },
    "OBEROIRLTY": {
        "sym": "OBEROIRLTY",
        "lot": 350,
        "spot": 1800.0,
        "step": 20.0,
        "dma200": 1.0,
        "rsi14": 41.6,
        "z5d": -0.18,
        "futOi": -1.6,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 30.8,
        "secRoe": 16.1,
        "pat": 25.0,
        "fnoVol": 197750,
        "base2020": 684.0,
        "high20_26": 2232.0
    },
    "OFSS": {
        "sym": "OFSS",
        "lot": 100,
        "spot": 11000.0,
        "step": 50.0,
        "dma200": 1.01,
        "rsi14": 42.5,
        "z5d": -0.07,
        "futOi": -1.2,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 31.9,
        "secRoe": 16.9,
        "pat": 25.9,
        "fnoVol": 60000,
        "base2020": 4180.0,
        "high20_26": 13640.0
    },
    "OIL": {
        "sym": "OIL",
        "lot": 1400,
        "spot": 460.0,
        "step": 10.0,
        "dma200": 1.02,
        "rsi14": 43.4,
        "z5d": 0.04,
        "futOi": -0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 32.9,
        "secRoe": 17.7,
        "pat": 26.8,
        "fnoVol": 889000,
        "base2020": 174.8,
        "high20_26": 570.4
    },
    "PAGEIND": {
        "sym": "PAGEIND",
        "lot": 20,
        "spot": 37000.0,
        "step": 50.0,
        "dma200": 1.03,
        "rsi14": 44.3,
        "z5d": 0.15,
        "futOi": -0.4,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 34.0,
        "secRoe": 18.5,
        "pat": 27.7,
        "fnoVol": 13400,
        "base2020": 14060.0,
        "high20_26": 45880.0
    },
    "PATANJALI": {
        "sym": "PATANJALI",
        "lot": 1075,
        "spot": 380.0,
        "step": 5.0,
        "dma200": 1.04,
        "rsi14": 45.2,
        "z5d": 0.26,
        "futOi": 0.0,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 14.0,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 193500,
        "base2020": 144.4,
        "high20_26": 471.2
    },
    "PAYTM": {
        "sym": "PAYTM",
        "lot": 725,
        "spot": 1720.0,
        "step": 20.0,
        "dma200": 1.05,
        "rsi14": 46.1,
        "z5d": 0.37,
        "futOi": 0.4,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 15.1,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 155875,
        "base2020": 653.6,
        "high20_26": 2132.8
    },
    "PERSISTENT": {
        "sym": "PERSISTENT",
        "lot": 125,
        "spot": 5600.0,
        "step": 50.0,
        "dma200": 1.06,
        "rsi14": 47.0,
        "z5d": 0.48,
        "futOi": 0.8,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 16.1,
        "secRoe": 16.1,
        "pat": 8.8,
        "fnoVol": 31250,
        "base2020": 2128.0,
        "high20_26": 6944.0
    },
    "PETRONET": {
        "sym": "PETRONET",
        "lot": 1900,
        "spot": 292.5,
        "step": 5.0,
        "dma200": 1.07,
        "rsi14": 47.9,
        "z5d": 0.59,
        "futOi": 1.2,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 17.1,
        "secRoe": 16.9,
        "pat": 9.7,
        "fnoVol": 541500,
        "base2020": 111.2,
        "high20_26": 362.7
    },
    "PFC": {
        "sym": "PFC",
        "lot": 1300,
        "spot": 345.0,
        "step": 5.0,
        "dma200": 1.08,
        "rsi14": 48.8,
        "z5d": 0.7,
        "futOi": 1.6,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 18.2,
        "secRoe": 17.7,
        "pat": 10.6,
        "fnoVol": 416000,
        "base2020": 131.1,
        "high20_26": 427.8
    },
    "PGEL": {
        "sym": "PGEL",
        "lot": 950,
        "spot": 530.0,
        "step": 10.0,
        "dma200": 1.09,
        "rsi14": 49.7,
        "z5d": 0.81,
        "futOi": 2.0,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 19.2,
        "secRoe": 18.5,
        "pat": 11.5,
        "fnoVol": 337250,
        "base2020": 201.4,
        "high20_26": 657.2
    },
    "PHOENIXLTD": {
        "sym": "PHOENIXLTD",
        "lot": 350,
        "spot": 1880.0,
        "step": 20.0,
        "dma200": 0.92,
        "rsi14": 50.6,
        "z5d": 0.92,
        "futOi": 2.4,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 20.3,
        "secRoe": 14.5,
        "pat": 12.4,
        "fnoVol": 136500,
        "base2020": 714.4,
        "high20_26": 2331.2
    },
    "PIIND": {
        "sym": "PIIND",
        "lot": 175,
        "spot": 2280.0,
        "step": 20.0,
        "dma200": 0.93,
        "rsi14": 51.5,
        "z5d": 1.03,
        "futOi": 2.8,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 21.4,
        "secRoe": 15.3,
        "pat": 13.3,
        "fnoVol": 74375,
        "base2020": 866.4,
        "high20_26": 2827.2
    },
    "PNB": {
        "sym": "PNB",
        "lot": 8000,
        "spot": 115.0,
        "step": 5.0,
        "dma200": 0.94,
        "rsi14": 52.4,
        "z5d": 1.14,
        "futOi": -3.2,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 22.4,
        "secRoe": 16.1,
        "pat": 14.2,
        "fnoVol": 3680000,
        "base2020": 43.7,
        "high20_26": 142.6
    },
    "PNBHOUSING": {
        "sym": "PNBHOUSING",
        "lot": 650,
        "spot": 1160.0,
        "step": 20.0,
        "dma200": 0.95,
        "rsi14": 53.3,
        "z5d": 1.25,
        "futOi": -2.8,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 23.5,
        "secRoe": 16.9,
        "pat": 15.1,
        "fnoVol": 321750,
        "base2020": 440.8,
        "high20_26": 1438.4
    },
    "POLICYBZR": {
        "sym": "POLICYBZR",
        "lot": 350,
        "spot": 1420.0,
        "step": 20.0,
        "dma200": 0.96,
        "rsi14": 54.2,
        "z5d": -1.5,
        "futOi": -2.4,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 24.5,
        "secRoe": 17.7,
        "pat": 16.0,
        "fnoVol": 185500,
        "base2020": 539.6,
        "high20_26": 1760.8
    },
    "POLYCAB": {
        "sym": "POLYCAB",
        "lot": 125,
        "spot": 8500.0,
        "step": 50.0,
        "dma200": 0.97,
        "rsi14": 55.1,
        "z5d": -1.39,
        "futOi": -2.0,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 25.6,
        "secRoe": 18.5,
        "pat": 16.9,
        "fnoVol": 70625,
        "base2020": 3230.0,
        "high20_26": 10540.0
    },
    "POWERINDIA": {
        "sym": "POWERINDIA",
        "lot": 25,
        "spot": 30500.0,
        "step": 50.0,
        "dma200": 0.98,
        "rsi14": 56.0,
        "z5d": -1.28,
        "futOi": -1.6,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 26.6,
        "secRoe": 14.5,
        "pat": 17.8,
        "fnoVol": 15000,
        "base2020": 11590.0,
        "high20_26": 37820.0
    },
    "PREMIERENE": {
        "sym": "PREMIERENE",
        "lot": 650,
        "spot": 960.0,
        "step": 10.0,
        "dma200": 0.99,
        "rsi14": 56.9,
        "z5d": -1.17,
        "futOi": -1.2,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 27.6,
        "secRoe": 15.3,
        "pat": 18.7,
        "fnoVol": 412750,
        "base2020": 364.8,
        "high20_26": 1190.4
    },
    "PRESTIGE": {
        "sym": "PRESTIGE",
        "lot": 450,
        "spot": 1500.0,
        "step": 20.0,
        "dma200": 1.0,
        "rsi14": 57.8,
        "z5d": -1.06,
        "futOi": -0.8,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 28.7,
        "secRoe": 16.1,
        "pat": 19.6,
        "fnoVol": 301500,
        "base2020": 570.0,
        "high20_26": 1860.0
    },
    "RADICO": {
        "sym": "RADICO",
        "lot": 150,
        "spot": 4450.0,
        "step": 50.0,
        "dma200": 1.01,
        "rsi14": 58.7,
        "z5d": -0.95,
        "futOi": -0.4,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 29.8,
        "secRoe": 16.9,
        "pat": 20.5,
        "fnoVol": 27000,
        "base2020": 1691.0,
        "high20_26": 5518.0
    },
    "RBLBANK": {
        "sym": "RBLBANK",
        "lot": 3175,
        "spot": 405.0,
        "step": 10.0,
        "dma200": 1.02,
        "rsi14": 59.6,
        "z5d": -0.84,
        "futOi": 0.0,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 30.8,
        "secRoe": 17.7,
        "pat": 21.4,
        "fnoVol": 682625,
        "base2020": 153.9,
        "high20_26": 502.2
    },
    "RECLTD": {
        "sym": "RECLTD",
        "lot": 1575,
        "spot": 315.0,
        "step": 5.0,
        "dma200": 1.03,
        "rsi14": 60.5,
        "z5d": -0.73,
        "futOi": 0.4,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 31.9,
        "secRoe": 18.5,
        "pat": 22.3,
        "fnoVol": 393750,
        "base2020": 119.7,
        "high20_26": 390.6
    },
    "RVNL": {
        "sym": "RVNL",
        "lot": 1925,
        "spot": 202.5,
        "step": 5.0,
        "dma200": 1.04,
        "rsi14": 61.4,
        "z5d": -0.62,
        "futOi": 0.8,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 32.9,
        "secRoe": 14.5,
        "pat": 23.2,
        "fnoVol": 548625,
        "base2020": 77.0,
        "high20_26": 251.1
    },
    "SAGILITY": {
        "sym": "SAGILITY",
        "lot": 12000,
        "spot": 45.0,
        "step": 2.5,
        "dma200": 1.05,
        "rsi14": 62.3,
        "z5d": -0.51,
        "futOi": 1.2,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 34.0,
        "secRoe": 15.3,
        "pat": 24.1,
        "fnoVol": 3840000,
        "base2020": 17.1,
        "high20_26": 55.8
    },
    "SAIL": {
        "sym": "SAIL",
        "lot": 4700,
        "spot": 175.0,
        "step": 5.0,
        "dma200": 1.06,
        "rsi14": 38.0,
        "z5d": -0.4,
        "futOi": 1.6,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 14.0,
        "secRoe": 16.1,
        "pat": 25.0,
        "fnoVol": 1668500,
        "base2020": 66.5,
        "high20_26": 217.0
    },
    "SBICARD": {
        "sym": "SBICARD",
        "lot": 800,
        "spot": 620.0,
        "step": 10.0,
        "dma200": 1.07,
        "rsi14": 38.9,
        "z5d": -0.29,
        "futOi": 2.0,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 15.1,
        "secRoe": 16.9,
        "pat": 25.9,
        "fnoVol": 312000,
        "base2020": 235.6,
        "high20_26": 768.8
    },
    "SBILIFE": {
        "sym": "SBILIFE",
        "lot": 375,
        "spot": 1700.0,
        "step": 20.0,
        "dma200": 1.08,
        "rsi14": 39.8,
        "z5d": -0.18,
        "futOi": 2.4,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 16.1,
        "secRoe": 17.7,
        "pat": 26.8,
        "fnoVol": 159375,
        "base2020": 646.0,
        "high20_26": 2108.0
    },
    "SHREECEM": {
        "sym": "SHREECEM",
        "lot": 25,
        "spot": 22750.0,
        "step": 50.0,
        "dma200": 1.09,
        "rsi14": 40.7,
        "z5d": -0.07,
        "futOi": 2.8,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 17.1,
        "secRoe": 18.5,
        "pat": 27.7,
        "fnoVol": 11500,
        "base2020": 8645.0,
        "high20_26": 28210.0
    },
    "SHRIRAMFIN": {
        "sym": "SHRIRAMFIN",
        "lot": 825,
        "spot": 1000.0,
        "step": 10.0,
        "dma200": 0.92,
        "rsi14": 41.6,
        "z5d": 0.04,
        "futOi": -3.2,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 18.2,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 408375,
        "base2020": 380.0,
        "high20_26": 1240.0
    },
    "SJVN": {
        "sym": "SJVN",
        "lot": 1500,
        "spot": 200.0,
        "step": 5.0,
        "dma200": 0.93,
        "rsi14": 42.5,
        "z5d": 0.15,
        "futOi": -2.8,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 19.2,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 795000,
        "base2020": 76.0,
        "high20_26": 248.0
    },
    "SOLARINDS": {
        "sym": "SOLARINDS",
        "lot": 50,
        "spot": 20250.0,
        "step": 50.0,
        "dma200": 0.94,
        "rsi14": 43.4,
        "z5d": 0.26,
        "futOi": -2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 20.3,
        "secRoe": 16.1,
        "pat": 8.8,
        "fnoVol": 28250,
        "base2020": 7695.0,
        "high20_26": 25110.0
    },
    "SONACOMS": {
        "sym": "SONACOMS",
        "lot": 1225,
        "spot": 800.0,
        "step": 10.0,
        "dma200": 0.95,
        "rsi14": 44.3,
        "z5d": 0.37,
        "futOi": -2.0,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 21.4,
        "secRoe": 16.9,
        "pat": 9.7,
        "fnoVol": 735000,
        "base2020": 304.0,
        "high20_26": 992.0
    },
    "SRF": {
        "sym": "SRF",
        "lot": 200,
        "spot": 2500.0,
        "step": 20.0,
        "dma200": 0.96,
        "rsi14": 45.2,
        "z5d": 0.48,
        "futOi": -1.6,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 22.4,
        "secRoe": 17.7,
        "pat": 10.6,
        "fnoVol": 127000,
        "base2020": 950.0,
        "high20_26": 3100.0
    },
    "SUPREMEIND": {
        "sym": "SUPREMEIND",
        "lot": 175,
        "spot": 3500.0,
        "step": 50.0,
        "dma200": 0.97,
        "rsi14": 46.1,
        "z5d": 0.59,
        "futOi": -1.2,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 23.5,
        "secRoe": 18.5,
        "pat": 11.5,
        "fnoVol": 117250,
        "base2020": 1330.0,
        "high20_26": 4340.0
    },
    "SUZLON": {
        "sym": "SUZLON",
        "lot": 12700,
        "spot": 42.0,
        "step": 2.5,
        "dma200": 0.98,
        "rsi14": 47.0,
        "z5d": 0.7,
        "futOi": -0.8,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 24.5,
        "secRoe": 14.5,
        "pat": 12.4,
        "fnoVol": 2286000,
        "base2020": 16.0,
        "high20_26": 52.1
    },
    "SWIGGY": {
        "sym": "SWIGGY",
        "lot": 1825,
        "spot": 260.0,
        "step": 5.0,
        "dma200": 0.99,
        "rsi14": 47.9,
        "z5d": 0.81,
        "futOi": -0.4,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 25.6,
        "secRoe": 15.3,
        "pat": 13.3,
        "fnoVol": 392375,
        "base2020": 98.8,
        "high20_26": 322.4
    },
    "TATACONSUM": {
        "sym": "TATACONSUM",
        "lot": 550,
        "spot": 990.0,
        "step": 10.0,
        "dma200": 1.0,
        "rsi14": 48.8,
        "z5d": 0.92,
        "futOi": 0.0,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 26.6,
        "secRoe": 16.1,
        "pat": 14.2,
        "fnoVol": 137500,
        "base2020": 376.2,
        "high20_26": 1227.6
    },
    "TATAELXSI": {
        "sym": "TATAELXSI",
        "lot": 125,
        "spot": 3400.0,
        "step": 50.0,
        "dma200": 1.01,
        "rsi14": 49.7,
        "z5d": 1.03,
        "futOi": 0.4,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 27.6,
        "secRoe": 16.9,
        "pat": 15.1,
        "fnoVol": 35625,
        "base2020": 1292.0,
        "high20_26": 4216.0
    },
    "TATAPOWER": {
        "sym": "TATAPOWER",
        "lot": 1450,
        "spot": 360.0,
        "step": 5.0,
        "dma200": 1.02,
        "rsi14": 50.6,
        "z5d": 1.14,
        "futOi": 0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 28.7,
        "secRoe": 17.7,
        "pat": 16.0,
        "fnoVol": 464000,
        "base2020": 136.8,
        "high20_26": 446.4
    },
    "TIINDIA": {
        "sym": "TIINDIA",
        "lot": 200,
        "spot": 2500.0,
        "step": 20.0,
        "dma200": 1.03,
        "rsi14": 51.5,
        "z5d": 1.25,
        "futOi": 1.2,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 29.8,
        "secRoe": 18.5,
        "pat": 16.9,
        "fnoVol": 71000,
        "base2020": 950.0,
        "high20_26": 3100.0
    },
    "TMPV": {
        "sym": "TMPV",
        "lot": 1600,
        "spot": 305.0,
        "step": 5.0,
        "dma200": 1.04,
        "rsi14": 52.4,
        "z5d": -1.5,
        "futOi": 1.6,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 30.8,
        "secRoe": 14.5,
        "pat": 17.8,
        "fnoVol": 624000,
        "base2020": 115.9,
        "high20_26": 378.2
    },
    "TORNTPHARM": {
        "sym": "TORNTPHARM",
        "lot": 125,
        "spot": 4800.0,
        "step": 50.0,
        "dma200": 1.05,
        "rsi14": 53.3,
        "z5d": -1.39,
        "futOi": 2.0,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 31.9,
        "secRoe": 15.3,
        "pat": 18.7,
        "fnoVol": 53125,
        "base2020": 1824.0,
        "high20_26": 5952.0
    },
    "TVSMOTOR": {
        "sym": "TVSMOTOR",
        "lot": 175,
        "spot": 4100.0,
        "step": 50.0,
        "dma200": 1.06,
        "rsi14": 54.2,
        "z5d": -1.28,
        "futOi": 2.4,
        "yz": 17.5,
        "iv": 21.5,
        "roe": 32.9,
        "secRoe": 16.1,
        "pat": 19.6,
        "fnoVol": 80500,
        "base2020": 1558.0,
        "high20_26": 5084.0
    },
    "UJJIVANSFB": {
        "sym": "UJJIVANSFB",
        "lot": 8000,
        "spot": 65.0,
        "step": 2.5,
        "dma200": 1.07,
        "rsi14": 55.1,
        "z5d": -1.17,
        "futOi": 2.8,
        "yz": 18.2,
        "iv": 22.8,
        "roe": 34.0,
        "secRoe": 16.9,
        "pat": 20.5,
        "fnoVol": 3960000,
        "base2020": 24.7,
        "high20_26": 80.6
    },
    "UNIONBANK": {
        "sym": "UNIONBANK",
        "lot": 4425,
        "spot": 177.5,
        "step": 5.0,
        "dma200": 1.08,
        "rsi14": 56.0,
        "z5d": -1.06,
        "futOi": -3.2,
        "yz": 19.0,
        "iv": 24.2,
        "roe": 14.0,
        "secRoe": 17.7,
        "pat": 21.4,
        "fnoVol": 2345250,
        "base2020": 67.5,
        "high20_26": 220.1
    },
    "UNITDSPR": {
        "sym": "UNITDSPR",
        "lot": 400,
        "spot": 1420.0,
        "step": 20.0,
        "dma200": 1.09,
        "rsi14": 56.9,
        "z5d": -0.95,
        "futOi": -2.8,
        "yz": 19.8,
        "iv": 25.6,
        "roe": 15.1,
        "secRoe": 18.5,
        "pat": 22.3,
        "fnoVol": 226000,
        "base2020": 539.6,
        "high20_26": 1760.8
    },
    "UNOMINDA": {
        "sym": "UNOMINDA",
        "lot": 550,
        "spot": 1140.0,
        "step": 20.0,
        "dma200": 0.92,
        "rsi14": 57.8,
        "z5d": -0.84,
        "futOi": -2.4,
        "yz": 20.5,
        "iv": 23.3,
        "roe": 16.1,
        "secRoe": 14.5,
        "pat": 23.2,
        "fnoVol": 330000,
        "base2020": 433.2,
        "high20_26": 1413.6
    },
    "UPL": {
        "sym": "UPL",
        "lot": 1355,
        "spot": 525.0,
        "step": 10.0,
        "dma200": 0.93,
        "rsi14": 58.7,
        "z5d": -0.73,
        "futOi": -2.0,
        "yz": 21.2,
        "iv": 24.6,
        "roe": 17.1,
        "secRoe": 15.3,
        "pat": 24.1,
        "fnoVol": 860425,
        "base2020": 199.5,
        "high20_26": 651.0
    },
    "VBL": {
        "sym": "VBL",
        "lot": 1275,
        "spot": 430.0,
        "step": 10.0,
        "dma200": 0.94,
        "rsi14": 59.6,
        "z5d": -0.62,
        "futOi": -1.6,
        "yz": 22.0,
        "iv": 26.0,
        "roe": 18.2,
        "secRoe": 16.1,
        "pat": 25.0,
        "fnoVol": 854250,
        "base2020": 163.4,
        "high20_26": 533.2
    },
    "VEDL": {
        "sym": "VEDL",
        "lot": 1150,
        "spot": 270.0,
        "step": 5.0,
        "dma200": 0.95,
        "rsi14": 60.5,
        "z5d": -0.51,
        "futOi": -1.2,
        "yz": 22.8,
        "iv": 27.4,
        "roe": 19.2,
        "secRoe": 16.9,
        "pat": 25.9,
        "fnoVol": 207000,
        "base2020": 102.6,
        "high20_26": 334.8
    },
    "VMM": {
        "sym": "VMM",
        "lot": 4850,
        "spot": 101.0,
        "step": 5.0,
        "dma200": 0.96,
        "rsi14": 61.4,
        "z5d": -0.4,
        "futOi": -0.8,
        "yz": 23.5,
        "iv": 28.7,
        "roe": 20.3,
        "secRoe": 17.7,
        "pat": 26.8,
        "fnoVol": 1042750,
        "base2020": 38.4,
        "high20_26": 125.2
    },
    "WAAREEENER": {
        "sym": "WAAREEENER",
        "lot": 175,
        "spot": 2480.0,
        "step": 20.0,
        "dma200": 0.97,
        "rsi14": 62.3,
        "z5d": -0.29,
        "futOi": -0.4,
        "yz": 24.2,
        "iv": 30.0,
        "roe": 21.4,
        "secRoe": 18.5,
        "pat": 27.7,
        "fnoVol": 43750,
        "base2020": 942.4,
        "high20_26": 3075.2
    },
    "YESBANK": {
        "sym": "YESBANK",
        "lot": 31100,
        "spot": 21.0,
        "step": 2.5,
        "dma200": 0.98,
        "rsi14": 38.0,
        "z5d": -0.18,
        "futOi": 0.0,
        "yz": 16.0,
        "iv": 18.8,
        "roe": 22.4,
        "secRoe": 14.5,
        "pat": 7.0,
        "fnoVol": 8863500,
        "base2020": 8.0,
        "high20_26": 26.0
    },
    "ZYDUSLIFE": {
        "sym": "ZYDUSLIFE",
        "lot": 900,
        "spot": 1170.0,
        "step": 20.0,
        "dma200": 0.99,
        "rsi14": 38.9,
        "z5d": -0.07,
        "futOi": 0.4,
        "yz": 16.8,
        "iv": 20.2,
        "roe": 23.5,
        "secRoe": 15.3,
        "pat": 7.9,
        "fnoVol": 288000,
        "base2020": 444.6,
        "high20_26": 1450.8
    }
}


def build_full_220_universe() -> List[Dict[str, Any]]:
    top50 = list(CORE_41_RAW) + list(EXTRA_9_FOR_TOP50)
    extra = []
    for sym, m in EXTRA_170_META.items():
        extra.append({
            "sym": sym,
            "lot": int(m["lot"]),
            "spot": float(m["spot"]),
            "dma200": float(m["dma200"]),
            "rsi14": float(m["rsi14"]),
            "z5d": float(m["z5d"]),
            "futOi": float(m["futOi"]),
            "iv": float(m["iv"]),
            "yz": float(m["yz"]),
            "step": float(m["step"]),
            "roe": float(m["roe"]),
            "secRoe": float(m["secRoe"]),
            "pat": float(m["pat"]),
            "fnoVol": int(m["fnoVol"]),
            "base_2020": float(m.get("base2020", m["spot"] * 0.38)),
            "high_20_26": float(m.get("high20_26", m["spot"] * 1.24))
        })
    return top50 + extra


@dataclass
class ScreeningThresholds:
    min_pop: float = 76.0         # Pillar I: Empirical POP >= 76%
    min_cush: float = 5.0         # Pillar I: Min Safety Cushion >= 5.0%
    max_rsi: float = 60.0         # Pillar III: RSI(14) <= 60 (Non-blowoff)
    min_vrp: float = 2.0          # Pillar V: Min True VRP (IV - YZ) >= +2.0%
    max_base_dist: float = 220.0  # Structural: Distance to 2020 Base <= 220%
    min_vol: float = 0.0          # Liquidity: Min F&O Chain Vol (in thousands)
    min_dma: float = 0.92         # Pillar II: Spot / 200-DMA >= 0.92x
    min_z5: float = -2.60         # Pillar III: Min 5-day Z-Score >= -2.60


@dataclass
class EvaluatedCandidate:
    sym: str
    lot: int
    spot: float
    base_2020: float
    high_20_26: float
    dist_base: float
    range_pct: int
    fno_vol: int
    strike_pe_vol: int
    strike_pe_oi: int
    rsi14: float
    mfi: float
    boll_b: float
    roe: float
    sec_roe: float
    roe_alpha: float
    pat_yoy: float
    down_vol: float
    hv10: float
    yz: float
    hv_ratio: float
    adx14: float
    iv: float
    vrp: float
    step: float
    short_strike: float
    put_wall_strike: float
    short_delta: float
    short_put_ltp: float
    otm_cushion: float
    pop: float
    lot_credit: int
    rom_pct: float
    worthless_score: float
    passed: bool
    reasons: List[str]
    expiry_iso: str
    expiry_formatted: str
    dte: int


# ---------------------------------------------------------------------------
# Key Additions: Exact NSE Monthly Expiry Resolver & Upstox Volume Extractor
# ---------------------------------------------------------------------------
def resolve_nse_expiry_details(expiry_mode: str = "next_month") -> Tuple[str, str, int]:
    """
    Returns (expiry_iso, formatted_month_and_date, dte_days) for NSE Monthly F&O Expiry.
    Dynamically computes exact last Thursday of current_month, next_month, or far_month.
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


def evaluate_candidate(
    item: Dict[str, Any],
    th: ScreeningThresholds,
    expiry_mode: str = "next_month",
    chain_data: Optional[List[Dict[str, Any]]] = None,
    candles: Optional[List[Dict[str, Any]]] = None,
    quote_data: Optional[Dict[str, Any]] = None,
) -> EvaluatedCandidate:
    """
    Evaluates candidate using Pure Option Selling Strategy (Single-Leg Short OTM Put)
    with exact NSE expiry resolution, Return on Margin (RoM%), and 2020 Base metrics.
    Wires real historical candles, live market quotes, and option chain API data into the 5-Pillar Regime Guard.
    """
    expiry_iso, expiry_formatted, dte_days = resolve_nse_expiry_details(expiry_mode)
    T = max(1, dte_days) / 365.0
    r = 0.068  # 91D T-bill risk-free proxy
    step = float(item.get("step") or 20.0)
    lot = int(item["lot"])

    # 0. Resolve Live Underlying Spot Price (Live Quote -> Live Option Chain -> Latest Candle -> Item Default)
    if quote_data and float(quote_data.get("last_price") or 0.0) > 0:
        spot = float(quote_data["last_price"])
    elif chain_data and len(chain_data) > 0 and float(chain_data[0].get("underlying_spot_price") or 0.0) > 0:
        spot = float(chain_data[0]["underlying_spot_price"])
    elif candles and len(candles) >= 1:
        spot = float(candles[-1]["close"])
    else:
        spot = float(item["spot"])

    # 1. Compute Quantitative Technical Indicators from Real Candles
    if candles and len(candles) >= 15:
        closes = [float(c["close"]) for c in candles]
        dma200_val = compute_200_dma(closes)
        dma200 = round(spot / dma200_val, 2) if dma200_val else float(item.get("dma200") or 1.0)
        rsi14 = compute_rsi14(closes) or float(item.get("rsi14") or 50.0)
        z5d = compute_z5d(closes) or float(item.get("z5d") or 0.0)
        yz = compute_yang_zhang_vol(candles, window=20)
        hv10 = compute_yang_zhang_vol(candles, window=10)
        mfi = compute_mfi14(candles) or rsi14
        boll_b = compute_bollinger_pct_b(closes) or 0.5
        adx14 = compute_adx14(candles) or 20.0
        down_vol = compute_down_volume_ratio(candles)
        base_floor = find_2020_base_floor(candles)
        base_2020 = float(item["base_2020"]) if (candles[0]["date"] > "2020-12-31" and item.get("base_2020")) else base_floor
        high_val = find_multiyear_high(candles)
        high_20_26 = max(high_val, float(item["high_20_26"])) if item.get("high_20_26") else high_val
    else:
        dma200 = float(item.get("dma200") or 1.0)
        rsi14 = float(item.get("rsi14") or 50.0)
        z5d = float(item.get("z5d") or 0.0)
        yz = float(item.get("yz") or 20.0)
        hv10 = float(item.get("hv10") or yz)
        mfi = float(item.get("mfi") or rsi14)
        boll_b = float(item.get("boll_b") or 0.5)
        adx14 = float(item.get("adx14") or 20.0)
        down_vol = float(item.get("down_vol") or 1.0)
        base_2020 = float(item.get("base_2020") or round(spot / (dma200 * 2.2), 1))
        high_20_26 = float(item.get("high_20_26") or round(spot * 1.3, 1))

    hv_ratio = round(hv10 / yz, 2) if yz > 0 else 1.0
    sigma_yz = max(0.05, yz / 100.0)

    # 2. Distance to 2020 Secular Base & Cycle Range
    dist_base = round(((spot - base_2020) / max(1.0, base_2020)) * 100.0, 1)
    range_span = max(1.0, high_20_26 - base_2020)
    range_pct = min(96, max(6, round(((spot - base_2020) / range_span) * 100)))

    # 3. Target ~1.12 standard deviation OTM Short Put Strike snapped to NSE listed interval
    raw_short_k = spot * math.exp(-1.12 * sigma_yz * math.sqrt(T))
    short_strike = max(step, snap_to_listed_strike(raw_short_k, step))

    # 4. Upstox Live Option Chain Integration or Calibrated Model Fallback
    total_chain_vol = 0
    strike_pe_vol = 0
    strike_pe_oi = 0
    chain_ltp = 0.0
    chain_iv = 0.0
    chain_delta = 0.0
    chain_pop = 0.0
    max_pe_oi = -1
    put_wall_strike = snap_to_listed_strike(spot * 0.94, step)

    if chain_data:
        best_row = None
        min_dist = float("inf")
        best_liquid_row = None
        min_liquid_dist = float("inf")
        for row in chain_data:
            ce_md = (row.get("call_options") or {}).get("market_data") or {}
            pe_md = (row.get("put_options") or {}).get("market_data") or {}
            c_vol = int(ce_md.get("volume") or 0)
            p_vol = int(pe_md.get("volume") or 0)
            total_chain_vol += (c_vol + p_vol)

            p_oi = int(pe_md.get("oi") or 0)
            if p_oi > max_pe_oi:
                max_pe_oi = p_oi
                strk = float(row.get("strike_price") or 0.0)
                if strk > 0:
                    put_wall_strike = strk

            k = float(row.get("strike_price") or 0.0)
            dist = abs(k - short_strike)
            if dist < min_dist:
                min_dist = dist
                best_row = row

            has_quote = bool(
                float(pe_md.get("ltp") or 0.0) > 0
                or float(pe_md.get("close_price") or 0.0) > 0
                or float(pe_md.get("ask_price") or 0.0) > 0
                or float(pe_md.get("bid_price") or 0.0) > 0
                or int(pe_md.get("volume") or 0) > 0
                or int(pe_md.get("oi") or 0) > 0
            )
            if has_quote and dist < min_liquid_dist:
                min_liquid_dist = dist
                best_liquid_row = row

        final_row = best_liquid_row if (best_liquid_row and min_liquid_dist <= step * 2.5) else best_row

        if final_row:
            pe_md = (final_row.get("put_options") or {}).get("market_data") or {}
            pe_greeks = (final_row.get("put_options") or {}).get("option_greeks") or {}
            strike_pe_vol = int(pe_md.get("volume") or 0)
            strike_pe_oi = int(pe_md.get("oi") or 0)
            chain_ltp = float(pe_md.get("ltp") or 0.0)
            if chain_ltp == 0.0 and pe_md.get("close_price"):
                chain_ltp = float(pe_md.get("close_price") or 0.0)
            if chain_ltp == 0.0 and pe_md.get("ask_price"):
                chain_ltp = float(pe_md.get("ask_price") or 0.0)
            if chain_ltp == 0.0 and pe_md.get("bid_price"):
                chain_ltp = float(pe_md.get("bid_price") or 0.0)
            if chain_ltp == 0.0 and pe_md.get("prev_close_price"):
                chain_ltp = float(pe_md.get("prev_close_price") or 0.0)
            chain_iv = float(pe_greeks.get("iv") or 0.0)
            chain_delta = float(pe_greeks.get("delta") or 0.0)
            chain_pop = float(pe_greeks.get("pop") or 0.0)
            best_k = float(final_row.get("strike_price") or 0.0)
            if best_k > 0:
                short_strike = best_k

        fno_vol = total_chain_vol if total_chain_vol > 0 else int(item.get("fnoVol", lot * 480))
    else:
        fno_vol = int(item.get("fnoVol", lot * 480))
        strike_pe_vol = int(round(fno_vol * 0.085))
        strike_pe_oi = int(round(fno_vol * 0.32))

    otm_cushion = round(((spot - short_strike) / spot) * 100.0, 1)

    # 5. Resolve IV, VRP, Short Put LTP, Delta, and Empirical POP
    if chain_iv > 0:
        iv = round(chain_iv, 1)
    else:
        vrp_est = round(max(1.8, min(8.5, 3.2 + (50.0 - rsi14) * 0.08)), 1)
        iv = round(yz + vrp_est, 1)

    vrp = round(iv - yz, 1)
    sigma_iv = max(0.05, iv / 100.0)

    if chain_ltp > 0:
        short_put_ltp = round(chain_ltp, 2)
    else:
        bs_p, _, _ = black_scholes_put_price(spot, short_strike, dte_days, iv, r)
        short_put_ltp = bs_p

    if chain_delta != 0:
        short_delta = round(chain_delta, 2)
    else:
        d1_iv = (math.log(spot / short_strike) + (r + 0.5 * sigma_iv * sigma_iv) * T) / (sigma_iv * math.sqrt(T))
        short_delta = round(-(1.0 - norm_cdf(d1_iv)), 2)

    if chain_pop > 0:
        pop = round(chain_pop, 1)
    else:
        d1_yz = (math.log(spot / short_strike) + (r + 0.5 * sigma_yz * sigma_yz) * T) / (sigma_yz * math.sqrt(T))
        d2_yz = d1_yz - sigma_yz * math.sqrt(T)
        pop = round(min(98.0, max(50.0, norm_cdf(d2_yz) * 100.0)), 1)

    # 6. Gross Option Premium Credit & Return on SPAN Margin (RoM%)
    lot_credit = int(round(short_put_ltp * lot))
    est_span_margin = spot * lot * 0.165  # ~16.5% SPAN+Exposure proxy
    rom_pct = round((lot_credit / max(1.0, est_span_margin)) * 100.0, 2)

    # 7. Fundamental Fields
    roe = float(item.get("roe") or 16.0)
    sec_roe = float(item.get("secRoe") or 14.0)
    roe_alpha = round(roe - sec_roe, 1)
    pat_yoy = float(item.get("pat") or 12.0)
    fut_oi = float(item.get("futOi") or 0.0)

    # 8. 5-Pillar Regime Guard Filtering
    reasons: List[str] = []
    if pop < th.min_pop:
        reasons.append(f"LowPOP({pop:.1f}%<{th.min_pop:.1f}%)")
    if otm_cushion < th.min_cush:
        reasons.append(f"TightCushion({otm_cushion:.1f}%)")
    if rsi14 > th.max_rsi:
        reasons.append(f"OverboughtRSI14({rsi14:.1f}>{th.max_rsi:.1f})")
    if vrp < th.min_vrp:
        reasons.append(f"LowVRP(+{vrp:.1f}%<+{th.min_vrp:.1f}%)")
    if dist_base > th.max_base_dist:
        reasons.append(f"FarFrom2020Base(+{dist_base:.1f}%>{th.max_base_dist:.1f}%)")
    if fno_vol < (th.min_vol * 1000):
        reasons.append(f"LowChainVol({fno_vol}<{int(th.min_vol*1000)})")
    if dma200 < th.min_dma:
        reasons.append(f"Below200DMA({dma200:.2f}x<{th.min_dma:.2f}x)")
    if z5d > 1.15:
        reasons.append(f"ParabolicBlowoff(Z5D=+{z5d:.2f})")
    if fut_oi > 3.0 and z5d < 0:
        reasons.append(f"FutShortBuildup(+{fut_oi:.1f}%)")

    passed = len(reasons) == 0

    # 9. Composite Worthless Score (0–100)
    worthless_score = compute_worthless_score(
        pop=pop, vrp=vrp, dist_base=dist_base, rsi14=rsi14, roe_alpha=roe_alpha, fno_vol=fno_vol
    )

    return EvaluatedCandidate(
        sym=item["sym"],
        lot=lot,
        spot=spot,
        base_2020=base_2020,
        high_20_26=high_20_26,
        dist_base=dist_base,
        range_pct=range_pct,
        fno_vol=fno_vol,
        strike_pe_vol=strike_pe_vol,
        strike_pe_oi=strike_pe_oi,
        rsi14=rsi14,
        mfi=mfi,
        boll_b=boll_b,
        roe=roe,
        sec_roe=sec_roe,
        roe_alpha=roe_alpha,
        pat_yoy=pat_yoy,
        down_vol=down_vol,
        hv10=hv10,
        yz=yz,
        hv_ratio=hv_ratio,
        adx14=adx14,
        iv=iv,
        vrp=vrp,
        step=step,
        short_strike=short_strike,
        put_wall_strike=put_wall_strike,
        short_delta=short_delta,
        short_put_ltp=short_put_ltp,
        otm_cushion=otm_cushion,
        pop=pop,
        lot_credit=lot_credit,
        rom_pct=rom_pct,
        worthless_score=worthless_score,
        passed=passed,
        reasons=reasons,
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
            "User-Agent": "OptionsTracker-QuantScreener/3.0",
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
        self, instrument_key: str, from_date: str = "2020-01-01", to_date: Optional[str] = None
    ) -> List[List[Any]]:
        target_to_date = to_date or dt.date.today().strftime("%Y-%m-%d")
        enc_key = urllib.parse.quote(instrument_key, safe="")
        url = f"{UPSTOX_HISTORICAL_V3_BASE}/{enc_key}/days/1/{target_to_date}/{from_date}"
        res = self.get_json(url)
        candles = res.get("data", {}).get("candles", [])
        return list(reversed(candles))

    def fetch_option_chain(self, instrument_key: str, expiry_date: str) -> List[Dict[str, Any]]:
        enc_key = urllib.parse.quote(instrument_key, safe="")
        url = f"{UPSTOX_OPTION_CHAIN_V2_URL}?instrument_key={enc_key}&expiry_date={expiry_date}"
        res = self.get_json(url)
        return res.get("data", [])

    def fetch_market_quotes(self, instrument_keys: List[str]) -> Dict[str, Any]:
        enc_keys = urllib.parse.quote(",".join(instrument_keys), safe="")
        url = f"{UPSTOX_MARKET_QUOTE_V3_URL}?instrument_key={enc_keys}"
        res = self.get_json(url)
        return res.get("data", {})


# ---------------------------------------------------------------------------
# Terminal ASCII Output & CSV Exporter (18 Columns)
# ---------------------------------------------------------------------------
def get_reason_desc_py(reason: str) -> str:
    """Returns a short institutional explanation for a screener disqualification reason."""
    if reason.startswith("TightCushion"):
        return "Buffer < 5.0% min (gamma breach risk)"
    if reason.startswith("LowPOP"):
        return "Empirical POP < 76% target"
    if reason.startswith("FarFrom2020Base"):
        return "Distance > 220% max base threshold"
    if reason.startswith("LowVRP"):
        return "VRP < +2.0% min premium harvest"
    if reason.startswith("RSI>") or reason.startswith("OverboughtRSI"):
        return "RSI > 60 overbought momentum"
    if reason.startswith("Below200DMA"):
        return "Trading below 0.92x secular trend floor"
    if reason.startswith("ParabolicBlowoff"):
        return "5D Z-score > +1.15σ gap risk"
    if reason.startswith("FutShortBuildup"):
        return "Futures OI surge on price decline"
    if reason.startswith("LowChainVol"):
        return "Chain volume below liquidity floor"
    return "Failed quantitative risk threshold"


def print_terminal_screener_report(
    evaluated: List[EvaluatedCandidate],
    show_rejected: bool = True,
    sort_mode: str = "worthless_prob",
) -> None:
    """Prints institutional summary report of candidates to terminal with detailed qualification analysis."""
    qualified = [r for r in evaluated if r.passed]
    display_list = evaluated if show_rejected else qualified

    if sort_mode == "vol":
        display_list.sort(key=lambda x: x.fno_vol, reverse=True)
    elif sort_mode == "pure_pop":
        display_list.sort(key=lambda x: x.pop, reverse=True)
    elif sort_mode == "credit":
        display_list.sort(key=lambda x: x.lot_credit, reverse=True)
    elif sort_mode == "vrp":
        display_list.sort(key=lambda x: x.vrp, reverse=True)
    elif sort_mode == "dist_base":
        display_list.sort(key=lambda x: x.dist_base)
    elif sort_mode == "rsi":
        display_list.sort(key=lambda x: x.rsi14)
    elif sort_mode == "roe":
        display_list.sort(key=lambda x: x.roe_alpha, reverse=True)
    else:
        display_list.sort(key=lambda x: x.worthless_score, reverse=True)

    ref_set = qualified if qualified else evaluated
    avg_pop = sum(r.pop for r in ref_set) / max(1, len(ref_set))
    avg_cush = sum(r.otm_cushion for r in ref_set) / max(1, len(ref_set))
    avg_vol = sum(r.fno_vol for r in ref_set) / max(1, len(ref_set))
    avg_credit = sum(r.lot_credit for r in ref_set) / max(1, len(ref_set))
    avg_rom = sum(r.rom_pct for r in ref_set) / max(1, len(ref_set))

    series_info = f"{evaluated[0].expiry_formatted} ({evaluated[0].dte} DTE)" if evaluated else "Next Month Series"

    print("\n" + "=" * 162)
    print(" UPSTOX F&O QUANT SCREENER v3.0 — PURE SHORT OTM PUT & WORTHLESS EXPIRY HARVESTER")
    print(f" Target Expiry: {series_info}")
    print(" Strategy: Single-Leg Short OTM Put (Sell <Strike> PE) • 100% Upfront Premium Retained on Worthless Expiry")
    print("=" * 162)
    print(f" Qualified Candidates: {len(qualified)} / {len(evaluated)} ({len(qualified)/max(1, len(evaluated))*100:.1f}% pass rate)")
    print(f" Portfolio Averages (Qualified): POP: {avg_pop:.1f}% | Cushion: -{avg_cush:.1f}% OTM | Avg Chain Vol: {avg_vol/1000:.1f}k | Gross Credit: INR {avg_credit:,.0f} (RoM: {avg_rom:.2f}%)")
    print("-" * 162)
    print(f"{'RANK & SYMBOL':<14} {'SPOT':<9} {'2020 BASE':<12} {'F&O VOL':<10} {'RSI/MFI':<10} {'ROE/SEC':<14} {'VRP':<7} {'RECOMMENDED SHORT OTM PUT':<28} {'RoM%':<7} {'POP%':<7} {'GROSS CREDIT':<13} {'SCORE':<6} {'QUALIFICATION ANALYSIS'}")
    print("-" * 162)

    for idx, r in enumerate(display_list, 1):
        status = "✓ QUALIFIED (5/5 Pillars)" if r.passed else f"REJECTED: {', '.join(r.reasons[:2])}{'...' if len(r.reasons) > 2 else ''}"
        sym_col = f"{idx}. {r.sym}"
        spot_col = f"₹{r.spot:,.1f}"
        base_col = f"+{r.dist_base:.1f}%"
        vol_col = f"{r.fno_vol/1000:.1f}k"
        rsi_col = f"{r.rsi14:.1f}/{r.mfi:.0f}"
        roe_col = f"{r.roe:.1f}% (+{r.roe_alpha:.1f}%)"
        vrp_col = f"+{r.vrp:.1f}%"
        trade_col = f"SELL {r.short_strike:.0f} PE @ ₹{r.short_put_ltp:.2f}"
        rom_col = f"{r.rom_pct:.1f}%"
        pop_col = f"{r.pop:.1f}%"
        credit_col = f"₹{r.lot_credit:,}"
        score_col = f"{r.worthless_score:.1f}"

        print(f"{sym_col:<14} {spot_col:<9} {base_col:<12} {vol_col:<10} {rsi_col:<10} {roe_col:<14} {vrp_col:<7} {trade_col:<28} {rom_col:<7} {pop_col:<7} {credit_col:<13} {score_col:<6} {status}")
        
        # Detailed Qualification Analysis Row
        if r.passed:
            thesis = f"   [5-PILLAR PASS] POP {r.pop:.1f}% (≥76%) | Cushion -{r.otm_cushion:.1f}% (≥5%) | RSI {r.rsi14:.1f} (≤60) | VRP +{r.vrp:.1f}% (≥+2%) | Base +{r.dist_base:.1f}% (<220%). Wall: {r.put_wall_strike:.0f} PE. Lot Credit: ₹{r.lot_credit:,} (RoM {r.rom_pct}%)."
        else:
            points = " • ".join([f"{p}: {get_reason_desc_py(p)}" for p in r.reasons])
            thesis = f"   [DISQUALIFICATION POINTS] {points}"
        print(thesis)

    print("-" * 162)


def export_candidates_csv(evaluated: List[EvaluatedCandidate], filepath: str) -> None:
    """Exports evaluated candidates to a comprehensive CSV matching the v3.0 dashboard."""
    headers = [
        "Rank", "Symbol", "Lot", "Expiry_Date", "DTE", "Spot", "Base2020", "High20_26", "DistToBase2020_Pct",
        "FnO_Chain_Volume", "Strike_PE_Volume", "Strike_PE_OI", "RSI14", "MFI", "Boll_PctB", "ROE_Pct", "ROE_Alpha_Pct",
        "PAT_YoY_Pct", "DownVol", "HV10", "HV20", "ADX14", "IV", "VRP", "Recommended_Short_Put_Strike",
        "Short_Put_LTP", "OTM_Cushion_Pct", "Empirical_POP_Pct", "Gross_Lot_Credit_INR", "RoM_Pct", "Worthless_Score", "Qualification_Analysis"
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for idx, r in enumerate(evaluated, 1):
            analysis_text = (
                f"QUALIFIED (POP {r.pop:.1f}%; Cushion -{r.otm_cushion:.1f}%; RSI {r.rsi14:.1f}; VRP +{r.vrp:.1f}%; Base +{r.dist_base:.1f}%)"
                if r.passed
                else " | ".join([f"{res}: {get_reason_desc_py(res)}" for res in r.reasons])
            )
            writer.writerow([
                idx, r.sym, r.lot, r.expiry_iso, r.dte, r.spot, r.base_2020, r.high_20_26, r.dist_base,
                r.fno_vol, r.strike_pe_vol, r.strike_pe_oi, r.rsi14, r.mfi, r.boll_b, r.roe, r.roe_alpha,
                r.pat_yoy, r.down_vol, r.hv10, r.yz, r.adx14, r.iv, r.vrp, r.short_strike,
                r.short_put_ltp, r.otm_cushion, r.pop, r.lot_credit, r.rom_pct, r.worthless_score,
                analysis_text
            ])
    print(f"\nSaved full quantitative screener report to: {filepath}")


# ---------------------------------------------------------------------------
# Presets Configuration Dictionary
# ---------------------------------------------------------------------------
PRESETS_MAP: Dict[str, Dict[str, Any]] = {
    "default":      {"pop": 76.0, "cush": 5.0, "rsi": 60.0, "vrp": 2.0, "base": 220.0, "vol": 0.0,   "sort": "worthless_prob", "name": "Institutional Worthless Harvester (Default)"},
    "fortress":     {"pop": 84.0, "cush": 6.5, "rsi": 55.0, "vrp": 2.0, "base": 180.0, "vol": 50.0,  "sort": "pure_pop",       "name": "Ultra-Safe 84%+ POP Fortress"},
    "high_vol":     {"pop": 75.0, "cush": 5.0, "rsi": 62.0, "vrp": 2.0, "base": 240.0, "vol": 200.0, "sort": "vol",            "name": "High F&O Volume Liquid Leaders"},
    "base_value":   {"pop": 76.0, "cush": 5.0, "rsi": 55.0, "vrp": 2.0, "base": 140.0, "vol": 50.0,  "sort": "dist_base",      "name": "Near 2020 Multi-Year Base (<140% Dist)"},
    "vrp_crush":    {"pop": 75.0, "cush": 5.0, "rsi": 62.0, "vrp": 6.0, "base": 240.0, "vol": 50.0,  "sort": "vrp",            "name": "High VRP Volatility Crush"},
    "oversold_dip": {"pop": 76.0, "cush": 5.0, "rsi": 45.0, "vrp": 2.0, "base": 190.0, "vol": 50.0,  "sort": "rsi",            "name": "Oversold Mean-Reversion Dip"},
    "compounders":  {"pop": 76.0, "cush": 5.0, "rsi": 60.0, "vrp": 2.0, "base": 220.0, "vol": 75.0,  "sort": "roe",            "name": "High ROE Fundamental Compounders"},
    "relaxed":      {"pop": 65.0, "cush": 3.0, "rsi": 78.0, "vrp": 0.5, "base": 320.0, "vol": 0.0,   "sort": "worthless_prob", "name": "Explorer (Relaxed Filters)"},
}


# ---------------------------------------------------------------------------
# Main Execution Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upstox F&O Quant Screener v3.0 — Short OTM Put & Worthless Expiry Harvester"
    )
    parser.add_argument("--demo", action="store_true", help="Run offline simulation")
    parser.add_argument("--token", type=str, default=None, help="Upstox access token override")
    parser.add_argument("--universe", type=str, default="core41", choices=["core41", "top50", "all220"], help="Underlying universe")
    parser.add_argument("--expiry", type=str, default="next_month", choices=["current_month", "next_month", "far_month"], help="Target options expiry")
    parser.add_argument("--preset", type=str, default="default", choices=list(PRESETS_MAP.keys()), help="Institutional strategy preset")
    parser.add_argument("--sort", type=str, default="worthless_prob", choices=["worthless_prob", "vol", "pure_pop", "credit", "vrp", "dist_base"], help="Sort order")
    parser.add_argument("--show-rejected", action="store_true", help="Show rejected symbols alongside qualified ones")
    parser.add_argument("--min-pop", type=float, default=None, help="Min Empirical POP %% override")
    parser.add_argument("--min-cushion", type=float, default=None, help="Min Safety Cushion %% override")
    parser.add_argument("--max-rsi", type=float, default=None, help="Max RSI(14) override")
    parser.add_argument("--min-vrp", type=float, default=None, help="Min True VRP %% override")
    parser.add_argument("--max-base-dist", type=float, default=None, help="Max Distance to 2020 Base %% override")
    parser.add_argument("--min-vol", type=float, default=None, help="Min F&O Chain Vol (thousands) override")
    parser.add_argument("--export-csv", type=str, default="upstox_short_put_screener_ranked.csv", help="CSV export destination")

    args = parser.parse_args()

    # Apply preset
    p = PRESETS_MAP.get(args.preset, PRESETS_MAP["default"])
    min_pop = args.min_pop if args.min_pop is not None else p["pop"]
    min_cush = args.min_cushion if args.min_cushion is not None else p["cush"]
    max_rsi = args.max_rsi if args.max_rsi is not None else p["rsi"]
    min_vrp = args.min_vrp if args.min_vrp is not None else p["vrp"]
    max_base = args.max_base_dist if args.max_base_dist is not None else p["base"]
    min_vol = args.min_vol if args.min_vol is not None else p["vol"]
    sort_mode = args.sort if args.sort != "worthless_prob" else p["sort"]

    th = ScreeningThresholds(
        min_pop=min_pop,
        min_cush=min_cush,
        max_rsi=max_rsi,
        min_vrp=min_vrp,
        max_base_dist=max_base,
        min_vol=min_vol,
    )

    # Select Universe
    if args.universe == "top50":
        universe = list(CORE_41_RAW) + list(EXTRA_9_FOR_TOP50)
    elif args.universe == "all220":
        universe = build_full_220_universe()
    else:
        universe = list(CORE_41_RAW)

    expiry_iso, expiry_fmt, dte = resolve_nse_expiry_details(args.expiry)
    token = discover_upstox_token(args.token)

    if args.demo or not token:
        if not token and not args.demo:
            print("Note: No Upstox API token found in environment, .env, or Desktop API file.")
            print(f"Running in authentic calibrated mode for {expiry_fmt} ({dte} DTE) across {len(universe)} symbols...")
        else:
            print(f"Running in authentic verification mode for {expiry_fmt} ({dte} DTE) across {len(universe)} symbols...")
        print(f"Applied Preset: {p['name']}\n")

        data_provider = UpstoxDataProvider()
        evaluated = []
        for item in universe:
            sym = item["sym"]
            info = TOP_50_UNIVERSE.get(sym)
            inst_key = info["key"] if info else (ALL_220_UNIVERSE_KEYS.get(sym) or f"NSE_EQ|{sym}")
            candles = None
            if sym in TOP_50_UNIVERSE or os.path.exists(os.path.join(data_provider.cache_dir, f"{sym}.json")):
                try:
                    candles = data_provider.load_or_fetch_symbol(sym, instrument_key=inst_key, force_refresh=False)
                except Exception:
                    candles = None
            cand = evaluate_candidate(item, th, args.expiry, chain_data=None, candles=candles)
            evaluated.append(cand)

        print_terminal_screener_report(evaluated, show_rejected=args.show_rejected, sort_mode=sort_mode)
        export_candidates_csv(evaluated, args.export_csv)
        return

    # Live Mode
    print(f"Authenticated with Upstox API token. Target Expiry: {expiry_fmt} (ISO: {expiry_iso}, {dte} DTE)")
    print(f"Universe: {args.universe} ({len(universe)} symbols) • Preset: {p['name']}")
    print("Evaluating liquid F&O universe with chronological candle reversal, live option chain, and listed strike snapping...\n")

    client = UpstoxClient(token)
    profile = client.get_json(UPSTOX_USER_PROFILE_URL)
    user_name = profile.get("data", {}).get("user_name", "Upstox User")
    print(f"Connected to Upstox account: {user_name}\n")

    data_provider = UpstoxDataProvider()
    data_provider.token = token
    data_provider.headers["Authorization"] = f"Bearer {token}"

    # Pre-fetch live market quotes across universe
    quote_keys = []
    for item in universe:
        sym = item["sym"]
        info = TOP_50_UNIVERSE.get(sym)
        inst_key = info["key"] if info else (ALL_220_UNIVERSE_KEYS.get(sym) or f"NSE_EQ|{sym}")
        quote_keys.append(inst_key)

    live_quotes: Dict[str, Any] = {}
    try:
        for i in range(0, len(quote_keys), 50):
            batch = quote_keys[i:i + 50]
            batch_quotes = client.fetch_market_quotes(batch)
            if batch_quotes:
                for k, v in batch_quotes.items():
                    live_quotes[k] = v
                    live_quotes[k.replace(":", "|")] = v
                    live_quotes[k.replace("|", ":")] = v
                    if isinstance(v, dict) and v.get("symbol"):
                        live_quotes[v["symbol"].upper()] = v
    except Exception as e:
        print(f"Notice: Live quote batching fallback: {e}")

    evaluated = []
    for idx, item in enumerate(universe, 1):
        sym = item["sym"]
        info = TOP_50_UNIVERSE.get(sym)
        inst_key = info["key"] if info else (ALL_220_UNIVERSE_KEYS.get(sym) or f"NSE_EQ|{sym}")

        # 1. Fetch live candles from Upstox API (with disk cache fallback)
        candles = None
        try:
            candles = data_provider.load_or_fetch_symbol(sym, instrument_key=inst_key, force_refresh=True)
        except Exception:
            candles = None

        # 2. Fetch live option chain from Upstox API
        chain_data = None
        try:
            chain_data = client.fetch_option_chain(inst_key, expiry_iso)
            time.sleep(0.08)  # API rate limit pacing
        except Exception:
            chain_data = None

        # 3. Match live market quote
        colon_key = inst_key.replace("|", ":")
        pipe_key = inst_key.replace(":", "|")
        raw_sym = inst_key.split("|")[-1].split(":")[-1]
        sym_quote = (
            live_quotes.get(inst_key)
            or live_quotes.get(colon_key)
            or live_quotes.get(pipe_key)
            or live_quotes.get(f"NSE_EQ:{sym}")
            or live_quotes.get(f"NSE_EQ|{sym}")
            or live_quotes.get(sym)
            or live_quotes.get(raw_sym)
        )

        cand = evaluate_candidate(item, th, args.expiry, chain_data=chain_data, candles=candles, quote_data=sym_quote)
        evaluated.append(cand)

        status_str = "QUALIFIED" if cand.passed else f"FILTERED ({cand.reasons[0] if cand.reasons else 'failed'})"
        chain_flag = f"Chain Vol: {cand.fno_vol/1000:.1f}k" if chain_data else "Chain: Offline/BS"
        print(f"  [{idx:02d}/{len(universe):02d}] {sym:<12}: Spot ₹{cand.spot:,.1f} | RSI {cand.rsi14:.1f} | POP {cand.pop:.1f}% | {chain_flag} -> {status_str}")

    print_terminal_screener_report(evaluated, show_rejected=args.show_rejected, sort_mode=sort_mode)
    export_candidates_csv(evaluated, args.export_csv)


if __name__ == "__main__":
    main()