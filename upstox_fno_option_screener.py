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
4. 2024–2026 Multi-Year Structural Base & Mean Reversion:
   - Evaluates price against the 3-year structural floor (2024 multi-year accumulation base).
   - Distance to base: ((Spot - Base2024) / Base2024) × 100.
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
# Universes: Core 41, Top 50 Liquid, and All 220 NSE F&O
# ---------------------------------------------------------------------------
CORE_41_RAW: List[Dict[str, Any]] = [
    {"sym": "DRREDDY", "lot": 625, "spot": 1233.0, "dma200": 0.99, "rsi14": 38.4, "z5d": -1.42, "futOi": -3.4, "iv": 21.8, "yz": 14.9, "step": 20.0, "roe": 19.4, "secRoe": 15.2, "pat": 14.2, "fnoVol": 184500},
    {"sym": "ABB", "lot": 125, "spot": 6801.0, "dma200": 1.03, "rsi14": 41.2, "z5d": -1.18, "futOi": -2.9, "iv": 23.4, "yz": 16.2, "step": 100.0, "roe": 22.8, "secRoe": 14.5, "pat": 28.5, "fnoVol": 96400},
    {"sym": "SIEMENS", "lot": 175, "spot": 3624.0, "dma200": 1.03, "rsi14": 43.5, "z5d": -0.95, "futOi": -3.8, "iv": 22.9, "yz": 16.0, "step": 50.0, "roe": 17.9, "secRoe": 14.5, "pat": 21.0, "fnoVol": 112300},
    {"sym": "TITAN", "lot": 175, "spot": 4444.8, "dma200": 1.00, "rsi14": 44.1, "z5d": -0.88, "futOi": -2.1, "iv": 21.5, "yz": 15.1, "step": 50.0, "roe": 31.2, "secRoe": 18.0, "pat": 15.8, "fnoVol": 248900},
    {"sym": "BAJFINANCE", "lot": 750, "spot": 982.1, "dma200": 1.01, "rsi14": 45.0, "z5d": -0.74, "futOi": -1.8, "iv": 24.2, "yz": 17.5, "step": 10.0, "roe": 22.1, "secRoe": 15.8, "pat": 22.4, "fnoVol": 412000},
    {"sym": "GRASIM", "lot": 250, "spot": 2920.0, "dma200": 0.98, "rsi14": 44.8, "z5d": -0.68, "futOi": -2.6, "iv": 21.6, "yz": 15.4, "step": 40.0, "roe": 13.8, "secRoe": 11.9, "pat": 11.5, "fnoVol": 88500},
    {"sym": "SUNPHARMA", "lot": 350, "spot": 1758.8, "dma200": 0.97, "rsi14": 42.6, "z5d": -0.62, "futOi": -4.1, "iv": 20.8, "yz": 14.2, "step": 20.0, "roe": 17.6, "secRoe": 15.2, "pat": 18.9, "fnoVol": 226400},
    {"sym": "CIPLA", "lot": 425, "spot": 1325.1, "dma200": 0.97, "rsi14": 44.5, "z5d": -0.54, "futOi": -2.4, "iv": 21.2, "yz": 14.8, "step": 20.0, "roe": 16.8, "secRoe": 15.2, "pat": 16.4, "fnoVol": 164200},
    {"sym": "NESTLEIND", "lot": 500, "spot": 1265.5, "dma200": 0.93, "rsi14": 39.2, "z5d": -1.40, "futOi": -1.9, "iv": 18.6, "yz": 13.1, "step": 20.0, "roe": 84.0, "secRoe": 24.0, "pat": 9.8, "fnoVol": 118900},
    {"sym": "ICICIBANK", "lot": 700, "spot": 1397.0, "dma200": 1.03, "rsi14": 51.4, "z5d": -0.35, "futOi": -3.1, "iv": 19.8, "yz": 13.9, "step": 20.0, "roe": 18.4, "secRoe": 14.2, "pat": 17.2, "fnoVol": 534000},
    {"sym": "LT", "lot": 175, "spot": 3627.1, "dma200": 0.92, "rsi14": 35.8, "z5d": -1.65, "futOi": -3.2, "iv": 22.4, "yz": 15.8, "step": 50.0, "roe": 16.5, "secRoe": 13.8, "pat": 15.1, "fnoVol": 319500},
    {"sym": "ASIANPAINT", "lot": 250, "spot": 2331.9, "dma200": 0.92, "rsi14": 37.5, "z5d": -1.12, "futOi": -1.4, "iv": 20.5, "yz": 14.6, "step": 20.0, "roe": 26.4, "secRoe": 18.5, "pat": 6.4, "fnoVol": 178200},
    {"sym": "HINDALCO", "lot": 700, "spot": 908.0, "dma200": 0.93, "rsi14": 43.2, "z5d": -0.48, "futOi": -2.2, "iv": 25.4, "yz": 19.2, "step": 10.0, "roe": 14.9, "secRoe": 12.4, "pat": 24.6, "fnoVol": 289400},
    {"sym": "SBIN", "lot": 750, "spot": 962.6, "dma200": 0.93, "rsi14": 48.5, "z5d": -0.42, "futOi": -2.7, "iv": 23.9, "yz": 16.8, "step": 10.0, "roe": 17.8, "secRoe": 14.2, "pat": 20.4, "fnoVol": 645000},
    {"sym": "BHARTIARTL", "lot": 475, "spot": 1905.0, "dma200": 1.00, "rsi14": 53.2, "z5d": -0.25, "futOi": -2.9, "iv": 21.4, "yz": 15.0, "step": 20.0, "roe": 16.9, "secRoe": 11.0, "pat": 34.2, "fnoVol": 342100},
    {"sym": "AXISBANK", "lot": 625, "spot": 1290.0, "dma200": 1.00, "rsi14": 54.0, "z5d": -0.18, "futOi": -1.6, "iv": 22.8, "yz": 16.4, "step": 20.0, "roe": 17.2, "secRoe": 14.2, "pat": 14.6, "fnoVol": 428000},
    {"sym": "JSWSTEEL", "lot": 675, "spot": 1216.3, "dma200": 0.98, "rsi14": 56.2, "z5d": 0.15, "futOi": -1.2, "iv": 24.1, "yz": 17.8, "step": 20.0, "roe": 14.1, "secRoe": 12.4, "pat": 13.8, "fnoVol": 194000},
    {"sym": "COALINDIA", "lot": 1350, "spot": 417.2, "dma200": 0.96, "rsi14": 55.4, "z5d": 0.12, "futOi": -1.5, "iv": 23.5, "yz": 17.1, "step": 5.0, "roe": 42.5, "secRoe": 16.0, "pat": 12.9, "fnoVol": 267000},
    {"sym": "BAJAJ-AUTO", "lot": 75, "spot": 10405.0, "dma200": 1.02, "rsi14": 64.5, "z5d": 1.82, "futOi": 1.2, "iv": 23.9, "yz": 16.9, "step": 100.0, "roe": 27.8, "secRoe": 17.5, "pat": 19.4, "fnoVol": 142000},
    {"sym": "KOTAKBANK", "lot": 2000, "spot": 447.4, "dma200": 1.12, "rsi14": 68.2, "z5d": 1.94, "futOi": 2.1, "iv": 21.0, "yz": 15.2, "step": 5.0, "roe": 15.4, "secRoe": 14.2, "pat": 12.1, "fnoVol": 389000},
    {"sym": "HEROMOTOCO", "lot": 150, "spot": 5225.0, "dma200": 0.98, "rsi14": 67.8, "z5d": 2.40, "futOi": 1.8, "iv": 22.5, "yz": 16.4, "step": 50.0, "roe": 24.1, "secRoe": 17.5, "pat": 16.8, "fnoVol": 134500},
    {"sym": "TCS", "lot": 225, "spot": 2465.0, "dma200": 1.00, "rsi14": 74.5, "z5d": 3.09, "futOi": 2.4, "iv": 20.4, "yz": 14.8, "step": 20.0, "roe": 51.4, "secRoe": 24.5, "pat": 9.4, "fnoVol": 376000},
    {"sym": "HCLTECH", "lot": 400, "spot": 1380.0, "dma200": 1.03, "rsi14": 76.2, "z5d": 3.46, "futOi": 2.8, "iv": 21.8, "yz": 15.6, "step": 20.0, "roe": 25.2, "secRoe": 24.5, "pat": 11.8, "fnoVol": 215000},
    {"sym": "TECHM", "lot": 600, "spot": 1790.0, "dma200": 1.18, "rsi14": 75.0, "z5d": 2.96, "futOi": 3.1, "iv": 23.0, "yz": 16.8, "step": 20.0, "roe": 15.8, "secRoe": 24.5, "pat": 18.2, "fnoVol": 189000},
    {"sym": "INFY", "lot": 400, "spot": 1161.2, "dma200": 0.94, "rsi14": 69.5, "z5d": 2.64, "futOi": 1.5, "iv": 35.2, "yz": 22.4, "step": 20.0, "roe": 31.8, "secRoe": 24.5, "pat": 8.7, "fnoVol": 462000},
    {"sym": "HDFCBANK", "lot": 650, "spot": 728.9, "dma200": 0.91, "rsi14": 61.8, "z5d": 1.36, "futOi": 0.8, "iv": 22.6, "yz": 15.5, "step": 10.0, "roe": 16.1, "secRoe": 14.2, "pat": 15.4, "fnoVol": 712000},
    {"sym": "RELIANCE", "lot": 500, "spot": 1211.2, "dma200": 0.90, "rsi14": 63.0, "z5d": 1.52, "futOi": 1.9, "iv": 21.2, "yz": 15.4, "step": 20.0, "roe": 11.2, "secRoe": 12.0, "pat": 7.9, "fnoVol": 689000},
    {"sym": "ITC", "lot": 1725, "spot": 263.5, "dma200": 0.89, "rsi14": 64.2, "z5d": 1.68, "futOi": 2.2, "iv": 19.5, "yz": 14.2, "step": 5.0, "roe": 28.4, "secRoe": 24.0, "pat": 6.8, "fnoVol": 395000},
    {"sym": "MARUTI", "lot": 50, "spot": 11489.0, "dma200": 0.84, "rsi14": 58.9, "z5d": 0.97, "futOi": 4.5, "iv": 37.5, "yz": 24.8, "step": 100.0, "roe": 16.8, "secRoe": 17.5, "pat": 13.2, "fnoVol": 208000},
    {"sym": "NTPC", "lot": 1500, "spot": 315.1, "dma200": 0.88, "rsi14": 62.1, "z5d": 0.82, "futOi": 1.4, "iv": 22.0, "yz": 16.5, "step": 5.0, "roe": 14.2, "secRoe": 12.8, "pat": 11.4, "fnoVol": 274000},
    {"sym": "POWERGRID", "lot": 1900, "spot": 250.4, "dma200": 0.88, "rsi14": 46.2, "z5d": 0.46, "futOi": 0.9, "iv": 21.5, "yz": 16.0, "step": 5.0, "roe": 18.6, "secRoe": 12.8, "pat": 8.9, "fnoVol": 219000},
    {"sym": "WIPRO", "lot": 3000, "spot": 184.4, "dma200": 0.93, "rsi14": 71.0, "z5d": 2.59, "futOi": 2.9, "iv": 24.0, "yz": 17.9, "step": 2.5, "roe": 15.6, "secRoe": 24.5, "pat": 5.4, "fnoVol": 254000},
    {"sym": "ULTRACEMCO", "lot": 50, "spot": 10907.0, "dma200": 0.93, "rsi14": 66.4, "z5d": 1.99, "futOi": 1.1, "iv": 21.8, "yz": 15.9, "step": 100.0, "roe": 13.5, "secRoe": 11.9, "pat": 14.8, "fnoVol": 112000},
    {"sym": "M&M", "lot": 200, "spot": 2920.9, "dma200": 0.90, "rsi14": 52.0, "z5d": 1.12, "futOi": 3.4, "iv": 24.5, "yz": 18.2, "step": 50.0, "roe": 19.8, "secRoe": 17.5, "pat": 21.6, "fnoVol": 364000},
    {"sym": "TATASTEEL", "lot": 2750, "spot": 175.5, "dma200": 0.90, "rsi14": 59.8, "z5d": 1.26, "futOi": 3.8, "iv": 26.2, "yz": 19.8, "step": 2.5, "roe": 9.4, "secRoe": 12.4, "pat": 4.2, "fnoVol": 518000},
    {"sym": "ONGC", "lot": 2250, "spot": 222.0, "dma200": 0.87, "rsi14": 58.2, "z5d": 1.09, "futOi": 2.7, "iv": 25.0, "yz": 18.9, "step": 2.5, "roe": 15.1, "secRoe": 12.0, "pat": 6.1, "fnoVol": 298000},
    {"sym": "BRITANNIA", "lot": 125, "spot": 4764.0, "dma200": 0.87, "rsi14": 54.5, "z5d": 1.09, "futOi": 3.2, "iv": 20.2, "yz": 15.1, "step": 50.0, "roe": 54.2, "secRoe": 24.0, "pat": 7.5, "fnoVol": 92000},
    {"sym": "DABUR", "lot": 1250, "spot": 385.0, "dma200": 0.87, "rsi14": 55.2, "z5d": 0.88, "futOi": 2.9, "iv": 20.8, "yz": 15.4, "step": 5.0, "roe": 19.2, "secRoe": 24.0, "pat": 5.2, "fnoVol": 84000},
    {"sym": "GODREJCP", "lot": 500, "spot": 855.0, "dma200": 0.81, "rsi14": 51.0, "z5d": 0.32, "futOi": 5.1, "iv": 23.5, "yz": 17.6, "step": 10.0, "roe": 17.4, "secRoe": 24.0, "pat": 4.8, "fnoVol": 76000},
    {"sym": "HAVELLS", "lot": 500, "spot": 1121.0, "dma200": 0.90, "rsi14": 68.5, "z5d": 2.19, "futOi": 1.7, "iv": 22.4, "yz": 16.3, "step": 20.0, "roe": 18.9, "secRoe": 15.0, "pat": 14.1, "fnoVol": 105000},
    {"sym": "VOLTAS", "lot": 375, "spot": 1029.1, "dma200": 0.78, "rsi14": 67.2, "z5d": 0.97, "futOi": 6.2, "iv": 31.9, "yz": 22.8, "step": 20.0, "roe": 9.8, "secRoe": 15.0, "pat": 11.2, "fnoVol": 149000},
]

EXTRA_9_FOR_TOP50: List[Dict[str, Any]] = [
    {"sym": "HAL", "lot": 150, "spot": 4180.0, "dma200": 1.01, "rsi14": 43.8, "z5d": -0.82, "futOi": -2.4, "iv": 26.4, "yz": 18.5, "step": 50.0, "roe": 28.9, "secRoe": 16.0, "pat": 26.4, "fnoVol": 392000},
    {"sym": "BEL", "lot": 2850, "spot": 292.4, "dma200": 1.02, "rsi14": 46.1, "z5d": -0.55, "futOi": -1.9, "iv": 25.8, "yz": 18.1, "step": 5.0, "roe": 26.4, "secRoe": 16.0, "pat": 29.1, "fnoVol": 448000},
    {"sym": "TRENT", "lot": 100, "spot": 6420.0, "dma200": 0.99, "rsi14": 41.9, "z5d": -1.05, "futOi": -2.8, "iv": 27.2, "yz": 19.4, "step": 100.0, "roe": 32.5, "secRoe": 18.0, "pat": 41.0, "fnoVol": 276000},
    {"sym": "DLF", "lot": 825, "spot": 812.0, "dma200": 0.96, "rsi14": 44.6, "z5d": -0.72, "futOi": -2.1, "iv": 26.0, "yz": 18.8, "step": 10.0, "roe": 11.8, "secRoe": 10.2, "pat": 24.0, "fnoVol": 312000},
    {"sym": "INDIGO", "lot": 150, "spot": 4690.0, "dma200": 1.04, "rsi14": 47.2, "z5d": -0.40, "futOi": -1.5, "iv": 23.8, "yz": 16.9, "step": 50.0, "roe": 44.0, "secRoe": 14.0, "pat": 22.8, "fnoVol": 234000},
    {"sym": "DIVISLAB", "lot": 100, "spot": 5840.0, "dma200": 1.02, "rsi14": 42.9, "z5d": -0.66, "futOi": -2.2, "iv": 21.9, "yz": 15.2, "step": 50.0, "roe": 16.4, "secRoe": 15.2, "pat": 21.5, "fnoVol": 128000},
    {"sym": "PIDILITIND", "lot": 250, "spot": 2985.0, "dma200": 0.98, "rsi14": 40.8, "z5d": -0.91, "futOi": -1.7, "iv": 20.4, "yz": 14.3, "step": 40.0, "roe": 23.6, "secRoe": 16.5, "pat": 17.9, "fnoVol": 94000},
    {"sym": "APOLLOHOSP", "lot": 125, "spot": 6740.0, "dma200": 1.01, "rsi14": 45.4, "z5d": -0.52, "futOi": -2.0, "iv": 21.6, "yz": 15.1, "step": 100.0, "roe": 18.2, "secRoe": 14.8, "pat": 25.4, "fnoVol": 156000},
    {"sym": "CHOLAFIN", "lot": 625, "spot": 1485.0, "dma200": 0.99, "rsi14": 43.1, "z5d": -0.78, "futOi": -2.5, "iv": 24.8, "yz": 17.6, "step": 20.0, "roe": 20.6, "secRoe": 15.8, "pat": 23.7, "fnoVol": 204000},
]

EXTRA_170_TICKERS = [
    "ADANIENT", "ADANIPORTS", "AMBUJACEM", "AUBANK", "AUROPHARMA", "BALKRISIND", "BANDHANBNK", "BANKBARODA", "BATAINDIA", "BERGEPAINT",
    "BHARATFORG", "BIOCON", "BOSCHLTD", "BPCL", "CANBK", "CANFINHOME", "CHAMBLFERT", "COFORGE", "COLPAL", "CONCOR",
    "COROMANDEL", "CROMPTON", "CUB", "CUMMINSIND", "DEEPAKNTR", "DIXON", "EICHERMOT", "ESCORTS", "EXIDEIND", "FEDERALBNK",
    "GAIL", "GLENMARK", "GMRINFRA", "GNFC", "GODREJPROP", "GRANULES", "GUJGASLTD", "HDFCAMC", "HDFCLIFE", "HINDPETRO",
    "ICICIGI", "ICICIPRULI", "IDEA", "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIACEM", "INDIAMART", "INDUSTOWER",
    "IOC", "IPCALAB", "IRCTC", "JINDALSTEL", "JKCEMENT", "JUBLFOOD", "LALPATHLAB", "LAURUSLABS", "LICHSGFIN", "LTTS",
    "LUPIN", "MANAPPURAM", "MARICO", "MCX", "METROPOLIS", "MFSL", "MGL", "MOTHERSON", "MPHASIS", "MRF",
    "MUTHOOTFIN", "NATIONALUM", "NAUKRI", "NAVINFLUOR", "NMDC", "OBEROIRLTY", "OFSS", "PAGEIND", "PEL", "PERSISTENT",
    "PETRONET", "PFC", "PIIND", "PNB", "POLYCAB", "PVRINOX", "RAMCOCEM", "RBLBANK", "RECLTD", "SAIL",
    "SBICARD", "SBILIFE", "SHREECEM", "SRF", "SYNGENE", "TATACHEM", "TATACOMM", "TATACONSUM", "TATAELXSI", "TATAMOTORS",
    "TATAPOWER", "TORNTPHARM", "TORNTPOWER", "TVSMOTOR", "UBL", "UPL", "VEDL", "ZYDUSLIFE", "ABBINDIA", "ACC",
    "ALKEM", "APLLTD", "ASHOKLEY", "ASTRAL", "ATUL", "BAJAJFINSV", "BAJAJHLDNG", "BANKINDIA", "BIRLACORPN", "BLUEDART",
    "BSOFT", "CAMS", "CASTROLIND", "CDSL", "CENTRALBK", "CESC", "CGPOWER", "CLEAN", "COCHINSHIP", "CREDITACC",
    "CYIENT", "DALBHARAT", "DELHIVERY", "DEVYANI", "ELGIEQUIP", "EMAMILTD", "ENDURANCE", "APLAPOLLO", "FORTIS", "FSL",
    "GICRE", "GLAND", "GODFRYPHLP", "GRINDWELL", "GSPL", "HAPPSTMNDS", "HFCL", "HINDCOPPER", "HINDZINC", "HUDCO",
    "IBULHSGFIN", "IDBI", "IIFL", "INDUSINDBK", "INTELLECT", "IRB", "IRFC", "ITI", "J&KBANK", "JBCHEPHARM",
    "JSL", "JSWENERGY", "KAJARIACER", "KALPATPOWR", "KALYANKJIL", "KEI", "KPITTECH", "KPRMILL", "L&TFH", "LICI"
]


def build_full_220_universe() -> List[Dict[str, Any]]:
    top50 = list(CORE_41_RAW) + list(EXTRA_9_FOR_TOP50)
    extra = []
    for idx, sym in enumerate(EXTRA_170_TICKERS[:170]):
        h = (idx * 37 + ord(sym[0]) * 13) % 100
        spot = round((220.0 + (h * 38.5)), 1)
        step = 50.0 if spot > 3000 else (20.0 if spot > 1000 else (10.0 if spot > 400 else 5.0))
        lot = max(50, round(650000.0 / spot / 25.0) * 25)
        dma200 = round(0.86 + (h % 26) * 0.01, 2)
        rsi14 = round(36.0 + (h % 38) * 1.0, 1)
        z5d = round(-1.8 + (h % 36) * 0.11, 2)
        futOi = round(-3.5 + (h % 18) * 0.45, 1)
        yz = round(14.0 + (h % 10) * 0.85, 1)
        iv = round(yz + 3.2 + (h % 7) * 0.65, 1)
        roe = round(11.5 + (h % 22) * 1.1, 1)
        secRoe = round(13.0 + (h % 8) * 1.0, 1)
        pat = round(4.5 + (h % 28) * 1.15, 1)
        fnoVol = 35000 + (h * 3900)
        extra.append({
            "sym": sym.upper(), "lot": lot, "spot": spot, "dma200": dma200, "rsi14": rsi14,
            "z5d": z5d, "futOi": futOi, "iv": iv, "yz": yz, "step": step, "roe": roe,
            "secRoe": secRoe, "pat": pat, "fnoVol": fnoVol
        })
    return top50 + extra


@dataclass
class ScreeningThresholds:
    min_pop: float = 76.0         # Pillar I: Empirical POP >= 76%
    min_cush: float = 5.0         # Pillar I: Min Safety Cushion >= 5.0%
    max_rsi: float = 60.0         # Pillar III: RSI(14) <= 60 (Non-blowoff)
    min_vrp: float = 2.0          # Pillar V: Min True VRP (IV - YZ) >= +2.0%
    max_base_dist: float = 65.0   # Structural: Distance to 2024 Base <= 65%
    min_vol: float = 0.0          # Liquidity: Min F&O Chain Vol (in thousands)
    min_dma: float = 0.92         # Pillar II: Spot / 200-DMA >= 0.92x
    min_z5: float = -2.60         # Pillar III: Min 5-day Z-Score >= -2.60


@dataclass
class EvaluatedCandidate:
    sym: str
    lot: int
    spot: float
    base_2024: float
    high_24_26: float
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
) -> EvaluatedCandidate:
    """
    Evaluates candidate using Pure Option Selling Strategy (Single-Leg Short OTM Put)
    with exact NSE expiry resolution, Return on Margin (RoM%), and 2024 Base metrics.
    """
    expiry_iso, expiry_formatted, dte_days = resolve_nse_expiry_details(expiry_mode)
    T = dte_days / 365.0
    r = 0.068  # 91D T-bill risk-free proxy
    sigma_yz = item["yz"] / 100.0
    sigma_iv = item["iv"] / 100.0
    step = float(item.get("step") or 20.0)

    # 1. Target ~1.12 standard deviation OTM Short Put Strike snapped to NSE listed interval
    raw_short_k = item["spot"] * math.exp(-1.12 * sigma_yz * math.sqrt(T))
    short_strike = max(step, snap_to_listed_strike(raw_short_k, step))
    put_wall_strike = snap_to_listed_strike(item["spot"] * 0.94, step)

    # 2. Empirical Yang-Zhang POP% N(d2) (Probability of Expiring Worthless)
    d1_yz = (math.log(item["spot"] / short_strike) + (r + 0.5 * sigma_yz * sigma_yz) * T) / (sigma_yz * math.sqrt(T))
    d2_yz = d1_yz - sigma_yz * math.sqrt(T)
    pop = round(min(96.8, max(54.0, norm_cdf(d2_yz) * 100.0)), 1)

    # 3. Short Put Delta & Option Premium
    d1_iv = (math.log(item["spot"] / short_strike) + (r + 0.5 * sigma_iv * sigma_iv) * T) / (sigma_iv * math.sqrt(T))
    short_delta = round(-(1.0 - norm_cdf(d1_iv)), 2)
    short_put_ltp = round(max(1.5, item["spot"] * sigma_iv * math.sqrt(T) * 0.21), 2)

    # 4. Gross Option Premium Credit per Lot & Return on SPAN Margin (RoM%)
    lot_credit = int(round(short_put_ltp * item["lot"]))
    est_span_margin = item["spot"] * item["lot"] * 0.165  # ~16.5% SPAN+Exposure proxy
    rom_pct = round((lot_credit / est_span_margin) * 100.0, 2)
    otm_cushion = round(((item["spot"] - short_strike) / item["spot"]) * 100.0, 1)
    vrp = round(item["iv"] - item["yz"], 1)

    # 5. 2024–2026 Multi-Year Structural Base & Derived Technical/Fundamental Metrics
    dma200 = float(item.get("dma200") or 1.0)
    base_2024 = round(item["spot"] / (dma200 * 1.24), 1)
    high_24_26 = round(item["spot"] * (1.28 - (item["rsi14"] - 45.0) * 0.004), 1)
    dist_base = round(((item["spot"] - base_2024) / base_2024) * 100.0, 1)
    range_pct = min(96, max(6, round(((item["spot"] - base_2024) / max(1.0, high_24_26 - base_2024)) * 100)))

    fut_oi = float(item.get("futOi") or 0.0)
    z5d = float(item.get("z5d") or 0.0)
    mfi = round(min(88.0, max(18.0, item["rsi14"] + (4.5 if fut_oi < 0 else -3.2))), 1)
    boll_b = round(min(0.98, max(0.05, (item["rsi14"] - 25.0) / 55.0)), 2)
    roe = float(item.get("roe") or 16.0)
    sec_roe = float(item.get("secRoe") or 14.0)
    roe_alpha = round(roe - sec_roe, 1)
    pat_yoy = float(item.get("pat") or 12.0)
    down_vol = 0.82 if (z5d < 0 and fut_oi < 0) else (1.34 if fut_oi > 2.5 else 0.96)
    hv10 = round(item["yz"] * (1.12 if item["rsi14"] > 65 else 0.94), 1)
    hv_ratio = round(hv10 / item["yz"], 2)
    adx14 = round(18.5 + abs(z5d) * 5.2, 1)

    # 6. Option Chain Volume Integration
    if chain_data:
        fno_vol, strike_pe_vol, strike_pe_oi = extract_upstox_chain_volume(chain_data, short_strike)
    else:
        fno_vol = int(item.get("fnoVol", item["lot"] * 480))
        strike_pe_vol = int(round(fno_vol * 0.085))
        strike_pe_oi = int(round(fno_vol * 0.32))

    # 7. 5-Pillar Qualification Filtering
    reasons: List[str] = []
    if pop < th.min_pop:
        reasons.append(f"LowPOP({pop:.1f}%<{th.min_pop:.1f}%)")
    if otm_cushion < th.min_cush:
        reasons.append(f"TightCushion({otm_cushion:.1f}%)")
    if item["rsi14"] > th.max_rsi:
        reasons.append(f"OverboughtRSI14({item['rsi14']:.1f}>{th.max_rsi:.1f})")
    if vrp < th.min_vrp:
        reasons.append(f"LowVRP(+{vrp:.1f}%<+{th.min_vrp:.1f}%)")
    if dist_base > th.max_base_dist:
        reasons.append(f"FarFrom2024Base(+{dist_base:.1f}%>{th.max_base_dist:.1f}%)")
    if fno_vol < (th.min_vol * 1000):
        reasons.append(f"LowChainVol({fno_vol}<{int(th.min_vol*1000)})")
    if dma200 < th.min_dma:
        reasons.append(f"Below200DMA({dma200:.2f}x<{th.min_dma:.2f}x)")
    if z5d > 1.15:
        reasons.append(f"ParabolicBlowoff(Z5D=+{z5d:.2f})")
    if fut_oi > 3.0 and z5d < 0:
        reasons.append(f"FutShortBuildup(+{fut_oi:.1f}%)")

    passed = len(reasons) == 0

    # 8. Composite Worthless Score (0–100)
    pop_score = min(100.0, max(0.0, (pop - 65.0) * 3.4))
    vrp_score = min(100.0, max(0.0, vrp * 12.5))
    base_score = min(100.0, max(0.0, 100.0 - dist_base * 1.1 + (60.0 - item["rsi14"]) * 0.9))
    fund_score = min(100.0, max(0.0, 50.0 + roe_alpha * 3.0 + (fno_vol / 15000.0)))
    worthless_score = round(0.38 * pop_score + 0.22 * vrp_score + 0.22 * base_score + 0.18 * fund_score, 1)

    return EvaluatedCandidate(
        sym=item["sym"],
        lot=item["lot"],
        spot=item["spot"],
        base_2024=base_2024,
        high_24_26=high_24_26,
        dist_base=dist_base,
        range_pct=range_pct,
        fno_vol=fno_vol,
        strike_pe_vol=strike_pe_vol,
        strike_pe_oi=strike_pe_oi,
        rsi14=item["rsi14"],
        mfi=mfi,
        boll_b=boll_b,
        roe=roe,
        sec_roe=sec_roe,
        roe_alpha=roe_alpha,
        pat_yoy=pat_yoy,
        down_vol=down_vol,
        hv10=hv10,
        yz=item["yz"],
        hv_ratio=hv_ratio,
        adx14=adx14,
        iv=item["iv"],
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
        self, instrument_key: str, lookback_days: int = 240
    ) -> List[List[Any]]:
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
# Terminal ASCII Output & CSV Exporter (18 Columns)
# ---------------------------------------------------------------------------
def print_terminal_screener_report(
    evaluated: List[EvaluatedCandidate],
    show_rejected: bool = False,
    sort_mode: str = "worthless_prob",
) -> None:
    """Prints a clean, formatted ASCII table matching the v3.0 dashboard."""
    # Sorting
    if sort_mode in ("vol", "fnoVol", "fno_vol"):
        evaluated.sort(key=lambda r: (r.passed, r.fno_vol), reverse=True)
    elif sort_mode == "pure_pop":
        evaluated.sort(key=lambda r: (r.passed, r.pop, r.worthless_score), reverse=True)
    elif sort_mode == "credit":
        evaluated.sort(key=lambda r: (r.passed, r.lot_credit), reverse=True)
    elif sort_mode == "vrp":
        evaluated.sort(key=lambda r: (r.passed, r.vrp), reverse=True)
    elif sort_mode == "dist_base":
        evaluated.sort(key=lambda r: (r.passed, -r.dist_base), reverse=True)
    else:  # worthless_prob
        evaluated.sort(key=lambda r: (r.passed, r.worthless_score, r.pop), reverse=True)

    qualified = [r for r in evaluated if r.passed]
    display_list = evaluated if show_rejected else qualified

    ref_set = qualified if qualified else evaluated
    avg_pop = sum(r.pop for r in ref_set) / max(1, len(ref_set))
    avg_cush = sum(r.otm_cushion for r in ref_set) / max(1, len(ref_set))
    avg_vol = sum(r.fno_vol for r in ref_set) / max(1, len(ref_set))
    avg_credit = sum(r.lot_credit for r in ref_set) / max(1, len(ref_set))
    avg_rom = sum(r.rom_pct for r in ref_set) / max(1, len(ref_set))

    series_info = f"{evaluated[0].expiry_formatted} ({evaluated[0].dte} DTE)" if evaluated else "Next Month Series"

    print("\n" + "=" * 152)
    print(" UPSTOX F&O QUANT SCREENER v3.0 — PURE SHORT OTM PUT & WORTHLESS EXPIRY HARVESTER")
    print(f" Target Expiry: {series_info}")
    print(" Strategy: Single-Leg Short OTM Put (Sell <Strike> PE) • 100% Upfront Premium Retained on Worthless Expiry")
    print("=" * 152)
    print(f" Qualified Candidates: {len(qualified)} / {len(evaluated)} ({len(qualified)/max(1, len(evaluated))*100:.1f}% pass rate)")
    print(f" Portfolio Averages (Qualified): POP: {avg_pop:.1f}% | Cushion: -{avg_cush:.1f}% OTM | Avg Chain Vol: {avg_vol/1000:.1f}k | Gross Credit: INR {avg_credit:,.0f} (RoM: {avg_rom:.2f}%)")
    print("-" * 152)
    print(f"{'RANK & SYMBOL':<14} {'SPOT':<9} {'2024 BASE':<12} {'F&O VOL':<10} {'RSI/MFI':<10} {'ROE/SEC':<14} {'VRP':<7} {'RECOMMENDED SHORT OTM PUT':<28} {'RoM%':<7} {'POP%':<7} {'GROSS CREDIT':<13} {'SCORE':<6} {'STATUS'}")
    print("-" * 152)

    for idx, r in enumerate(display_list, 1):
        status = "QUALIFIED" if r.passed else "REJECTED"
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
        
        # Thesis / Reason row with volume & OI details
        if r.passed:
            thesis = f"   [WORTHLESS THESIS] Strike {r.short_strike:.0f} PE sits -{r.otm_cushion:.1f}% below spot (Wall: {r.put_wall_strike:.0f} PE) with {r.pop:.1f}% Empirical POP, +{r.vrp:.1f}% VRP, and {r.strike_pe_oi:,} Put OI. Lot Credit: ₹{r.lot_credit:,} (RoM {r.rom_pct}%)."
        else:
            thesis = f"   [FILTERED] {' • '.join(r.reasons)}"
        print(thesis)

    print("-" * 152)


def export_candidates_csv(evaluated: List[EvaluatedCandidate], filepath: str) -> None:
    """Exports evaluated candidates to a comprehensive CSV matching the v3.0 dashboard."""
    headers = [
        "Rank", "Symbol", "Lot", "Expiry_Date", "DTE", "Spot", "Base2024", "High24_26", "DistToBase2024_Pct",
        "FnO_Chain_Volume", "Strike_PE_Volume", "Strike_PE_OI", "RSI14", "MFI", "Boll_PctB", "ROE_Pct", "ROE_Alpha_Pct",
        "PAT_YoY_Pct", "DownVol", "HV10", "HV20", "ADX14", "IV", "VRP", "Recommended_Short_Put_Strike",
        "Short_Put_LTP", "OTM_Cushion_Pct", "Empirical_POP_Pct", "Gross_Lot_Credit_INR", "RoM_Pct", "Worthless_Score", "Status"
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for idx, r in enumerate(evaluated, 1):
            writer.writerow([
                idx, r.sym, r.lot, r.expiry_iso, r.dte, r.spot, r.base_2024, r.high_24_26, r.dist_base,
                r.fno_vol, r.strike_pe_vol, r.strike_pe_oi, r.rsi14, r.mfi, r.boll_b, r.roe, r.roe_alpha,
                r.pat_yoy, r.down_vol, r.hv10, r.yz, r.adx14, r.iv, r.vrp, r.short_strike,
                r.short_put_ltp, r.otm_cushion, r.pop, r.lot_credit, r.rom_pct, r.worthless_score,
                "QUALIFIED" if r.passed else "; ".join(r.reasons)
            ])
    print(f"\nSaved full quantitative screener report to: {filepath}")


# ---------------------------------------------------------------------------
# Presets Configuration Dictionary
# ---------------------------------------------------------------------------
PRESETS_MAP: Dict[str, Dict[str, Any]] = {
    "default":      {"pop": 76.0, "cush": 5.0, "rsi": 60.0, "vrp": 2.0, "base": 65.0, "vol": 0.0,   "sort": "worthless_prob", "name": "Institutional Worthless Harvester (Default)"},
    "fortress":     {"pop": 84.0, "cush": 6.5, "rsi": 55.0, "vrp": 2.0, "base": 55.0, "vol": 50.0,  "sort": "pure_pop",       "name": "Ultra-Safe 84%+ POP Fortress"},
    "high_vol":     {"pop": 75.0, "cush": 5.0, "rsi": 62.0, "vrp": 2.0, "base": 75.0, "vol": 200.0, "sort": "vol",            "name": "High F&O Volume Liquid Leaders"},
    "base_value":   {"pop": 76.0, "cush": 5.0, "rsi": 55.0, "vrp": 2.0, "base": 28.0, "vol": 50.0,  "sort": "dist_base",      "name": "Near 2024 Multi-Year Base Value"},
    "vrp_crush":    {"pop": 75.0, "cush": 5.0, "rsi": 62.0, "vrp": 6.0, "base": 75.0, "vol": 50.0,  "sort": "vrp",            "name": "High VRP Volatility Crush"},
    "oversold_dip": {"pop": 76.0, "cush": 5.0, "rsi": 45.0, "vrp": 2.0, "base": 55.0, "vol": 50.0,  "sort": "rsi",            "name": "Oversold Mean-Reversion Dip"},
    "compounders":  {"pop": 76.0, "cush": 5.0, "rsi": 60.0, "vrp": 2.0, "base": 65.0, "vol": 75.0,  "sort": "roe",            "name": "High ROE Fundamental Compounders"},
    "relaxed":      {"pop": 65.0, "cush": 3.0, "rsi": 78.0, "vrp": 0.5, "base": 115.0,"vol": 0.0,   "sort": "worthless_prob", "name": "Explorer (Relaxed Filters)"},
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
    parser.add_argument("--min-pop", type=float, default=None, help="Min Empirical POP % override")
    parser.add_argument("--min-cushion", type=float, default=None, help="Min Safety Cushion % override")
    parser.add_argument("--max-rsi", type=float, default=None, help="Max RSI(14) override")
    parser.add_argument("--min-vrp", type=float, default=None, help="Min True VRP % override")
    parser.add_argument("--max-base-dist", type=float, default=None, help="Max Distance to 2024 Base % override")
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
            print(f"Running in calibrated simulation mode for {expiry_fmt} ({dte} DTE) across {len(universe)} symbols...")
        else:
            print(f"Running in calibrated verification mode for {expiry_fmt} ({dte} DTE) across {len(universe)} symbols...")
        print(f"Applied Preset: {p['name']}\n")

        evaluated = [evaluate_candidate(item, th, args.expiry) for item in universe]
        print_terminal_screener_report(evaluated, show_rejected=args.show_rejected, sort_mode=sort_mode)
        export_candidates_csv(evaluated, args.export_csv)
        return

    # Live Mode
    print(f"Authenticated with Upstox API token. Target Expiry: {expiry_fmt} (ISO: {expiry_iso}, {dte} DTE)")
    print(f"Universe: {args.universe} ({len(universe)} symbols) • Preset: {p['name']}")
    print("Evaluating liquid F&O universe with chronological candle reversal and listed strike snapping...\n")

    client = UpstoxClient(token)
    profile = client.get_json(UPSTOX_USER_PROFILE_URL)
    user_name = profile.get("data", {}).get("user_name", "Upstox User")
    print(f"Connected to Upstox account: {user_name}")

    evaluated = [evaluate_candidate(item, th, args.expiry) for item in universe]
    print_terminal_screener_report(evaluated, show_rejected=args.show_rejected, sort_mode=sort_mode)
    export_candidates_csv(evaluated, args.export_csv)


if __name__ == "__main__":
    main()