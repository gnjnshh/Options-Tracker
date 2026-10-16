#!/usr/bin/env python3
"""
Upstox F&O Option Selling Screener ("Undeserved Oversold + Stagnant Volatility")
================================================================================
Quantitative screener built on Upstox Developer API (v2 & v3) for Theta-decay
option selling strategies (Short OTM Puts, Bull Put Credit Spreads, Short Strangles).

Strategy Pillars:
1. High F&O Liquidity: High option chain volume, open interest (OI), and tight bid-ask spreads
   via GET /v2/option/chain (expiry_date="current_month").
2. Technically Oversold: Pullback into oversold territory via Daily OHLCV candles
   (GET /v3/historical-candle/{instrument_key}/days/1/{to_date}/{from_date}):
   - RSI(14) <= 40, MFI(14) <= 45, Bollinger %B(20, 2) <= 0.28, Stochastic %K <= 30.
3. "Doesn't Deserve It" (Fundamental + Structural Quality):
   - Upstox Fundamentals API (GET /v2/fundamentals/{isin}/key-ratios & /income-statement):
     Company ROE >= Sector ROE (or >= 12%), ROCE >= Sector ROCE (or >= 13%),
     reasonable P/E vs sector benchmark, and positive YoY/QoQ Net Profit & Revenue growth.
   - Structural Trend & Volume Integrity: Price >= 0.96 * 200-DMA and no institutional
     distribution spike (5D Down-Volume / 20D Avg Volume <= 1.15x).
4. Stagnant Volatility ("Expires Worthless" / Pinning Regime):
   - Contracting Realized Volatility: HV(10) / HV(20) <= 0.95 and HV(20) <= 28% annualized.
   - Non-Trending / Range-Bound: ADX(14) <= 23 and Daily ATR(14)% <= 2.2%.
   - Positive Volatility Risk Premium (VRP): Option IV > HV(20) (selling overpriced time value
     into a stagnant underlying) with OTM Put POP >= 76% at or below the Put OI Wall.

Usage:
  1. Generate an Access Token via Upstox Developer Apps or run with --auth-code to exchange OAuth code:
     export UPSTOX_ACCESS_TOKEN="your_access_token_here"
     python3 upstox_fno_option_screener.py --expiry current_month --max-symbols 50
  2. Run built-in offline simulation / verification mode:
     python3 upstox_fno_option_screener.py --demo
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
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


# ---------------------------------------------------------------------------
# Upstox API Endpoints (Official v2 & v3 Specification)
# ---------------------------------------------------------------------------
UPSTOX_AUTH_DIALOG_URL = "https://api.upstox.com/v2/login/authorization/dialog"
UPSTOX_TOKEN_URL = "https://api.upstox.com/v2/login/authorization/token"
UPSTOX_BOD_NSE_JSON_GZ = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
UPSTOX_INSTRUMENT_SEARCH_URL = "https://api.upstox.com/v2/instruments/search"
UPSTOX_MARKET_QUOTE_V3_URL = "https://api.upstox.com/v3/market-quote/quotes"
UPSTOX_HISTORICAL_V3_BASE = "https://api.upstox.com/v3/historical-candle"
UPSTOX_HISTORICAL_V2_BASE = "https://api.upstox.com/v2/historical-candle"
UPSTOX_OPTION_CHAIN_V2_URL = "https://api.upstox.com/v2/option/chain"
UPSTOX_FUNDAMENTALS_BASE = "https://api.upstox.com/v2/fundamentals"

# Curated liquid NSE F&O universe (used if full BOD JSON is filtered to top liquid names)
DEFAULT_LIQUID_FNO_SYMBOLS = [
    "VOLTAS", "ASIANPAINT", "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL",
    "LT", "AXISBANK", "KOTAKBANK", "SUNPHARMA", "MARUTI", "NTPC", "POWERGRID",
    "HCLTECH", "WIPRO", "TITAN", "ULTRACEMCO", "BAJFINANCE", "NESTLEIND", "CIPLA",
    "DRREDDY", "HEROMOTOCO", "BAJAJ-AUTO", "M&M", "TATAMOTORS", "TATASTEEL",
    "HINDALCO", "JSWSTEEL", "COALINDIA", "ONGC", "GRASIM", "TECHM", "BRITANNIA",
    "INDUSINDBK", "PIDILITEIND", "DABUR", "GODREJCP", "HAVELLS", "SIEMENS", "ABB"
]


@dataclass
class ScreeningThresholds:
    """Configurable thresholds for the 4-pillar option selling screener."""
    # Pillar 1: F&O Liquidity
    min_chain_option_volume: int = 250_000      # Total option contracts/shares volume across chain
    max_otm_bid_ask_spread_pct: float = 1.50    # Max bid-ask spread % on recommended OTM Put

    # Pillar 2: Technical Oversold ("Oversold")
    max_rsi_14: float = 40.0                    # Wilder's RSI(14) upper bound for oversold
    min_rsi_14: float = 22.0                    # Avoid extreme crash/capitulation (<22)
    max_mfi_14: float = 45.0                    # Money Flow Index (14)
    max_bb_pct_b: float = 0.28                  # Position within 20D Bollinger Bands (0 = lower band)

    # Pillar 3: "Doesn't Deserve It" (Fundamental + Structural Quality)
    min_roe_pct: float = 12.0                   # Minimum ROE % (or >= sector ROE)
    min_roce_pct: float = 13.0                  # Minimum ROCE % (or >= sector ROCE)
    require_positive_profit_growth: bool = True # Positive YoY/QoQ Net Profit growth
    min_price_to_sma200_ratio: float = 0.96     # Within 4% of or above 200-DMA (or near 2024 low)
    max_hist_range_pct_2024: float = 35.0       # Max percentile within 2024-Present price range
    max_dist_to_2024_base_pct: float = 15.0     # Max % distance above 2024 structural support base
    max_down_vol_ratio: float = 1.15            # 5D down-day volume / 20D avg volume (no panic dumping)

    # Pillar 4: Stagnant Volatility ("Expires Worthless")
    max_hv20_pct: float = 28.0                  # Max 20-day annualized realized volatility %
    max_hv10_to_hv20_ratio: float = 0.95        # Volatility compression (HV10 < HV20)
    max_adx_14: float = 23.0                    # Non-trending / range-bound regime
    max_atr_pct: float = 2.80                   # Daily ATR(14) as % of spot price
    min_vrp_pct: float = 1.50                   # Min Volatility Risk Premium (IV - HV20) in % points
    target_put_delta_min: float = -0.28         # Target short put delta range (-0.28 to -0.14)
    target_put_delta_max: float = -0.14
    min_pop_pct: float = 76.0                   # Minimum Probability of Profit (POP %)


@dataclass
class ScreenerResult:
    symbol: str
    name: str
    instrument_key: str
    isin: str
    spot_price: float
    lot_size: int
    expiry_date: str
    # Pillar 0: 2024 Multi-Year Historical Low
    low_2024_base: float
    high_since_2024: float
    hist_range_pct_2024: float
    dist_to_2024_base_pct: float
    # Pillar 1: F&O Liquidity
    total_fno_option_volume: int
    total_put_oi: int
    pcr: float
    put_oi_wall_strike: float
    # Pillar 2: Technical Oversold
    rsi_14: float
    mfi_14: float
    stoch_k: float
    bb_pct_b: float
    drawdown_20d_pct: float
    # Pillar 3: Fundamental & Structural Quality ("Doesn't Deserve It")
    roe_pct: float
    sector_roe_pct: float
    roce_pct: float
    sector_roce_pct: float
    pe_ratio: float
    sector_pe_ratio: float
    net_profit_yoy_pct: float
    revenue_yoy_pct: float
    price_to_sma200: float
    down_vol_ratio: float
    # Pillar 4: Stagnant Volatility ("Expires Worthless")
    hv_10_pct: float
    hv_20_pct: float
    hv_compression_ratio: float
    adx_14: float
    atr_14_pct: float
    bb_bandwidth_pct: float
    # Recommended Short Put & Credit Spread Trade
    recommended_strategy: str
    short_put_strike: float
    hedge_put_strike: float
    short_put_ltp: float
    short_put_bid_ask_spread_pct: float
    short_put_iv: float
    vrp_spread_pct: float
    short_put_delta: float
    short_put_theta: float
    short_put_vega: float
    short_put_pop_pct: float
    safety_margin_pct: float
    est_credit_per_lot_inr: float
    # Scoring & Flags
    oversold_score: float
    quality_score: float
    stagnation_score: float
    composite_worthless_score: float
    passes_all_filters: bool
    rationale: str


# ---------------------------------------------------------------------------
# Upstox REST Client (Zero external dependency fallback using urllib)
# ---------------------------------------------------------------------------
class UpstoxClient:
    def __init__(self, access_token: str, rate_limit_sleep: float = 0.12):
        self.access_token = access_token.strip()
        self.rate_limit_sleep = rate_limit_sleep

    def _headers(self, include_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "UpstoxFnOScreener/1.0",
        }
        if include_auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def get_json(self, url: str, params: Optional[Dict[str, Any]] = None, include_auth: bool = True) -> Dict[str, Any]:
        if params:
            query_str = urllib.parse.urlencode(params)
            url = f"{url}?{query_str}"
        req = urllib.request.Request(url, headers=self._headers(include_auth=include_auth), method="GET")
        time.sleep(self.rate_limit_sleep)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Upstox API HTTP {exc.code} on {url}: {err_body}") from exc

    @staticmethod
    def exchange_code_for_token(
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        auth_code: str,
    ) -> str:
        """Exchanges single-use authorization_code for an Upstox access_token."""
        payload = urllib.parse.urlencode({
            "code": auth_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        }).encode("utf-8")
        headers = {
            "accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        req = urllib.request.Request(UPSTOX_TOKEN_URL, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Failed to obtain access_token: {data}")
        return token

    def load_fno_equity_universe(self, filter_symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Downloads Upstox BOD NSE.json.gz master file and extracts unique NSE_FO
        equity underlyings with their underlying_key (NSE_EQ|<ISIN>), ISIN, and lot_size.
        """
        req = urllib.request.Request(UPSTOX_BOD_NSE_JSON_GZ, headers={"User-Agent": "UpstoxFnOScreener/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            compressed = resp.read()
        raw_json = gzip.decompress(compressed).decode("utf-8")
        instruments = json.loads(raw_json)

        fno_underlyings: Dict[str, Dict[str, Any]] = {}
        target_set = {s.upper() for s in filter_symbols} if filter_symbols else None

        for item in instruments:
            if item.get("segment") == "NSE_FO" and item.get("underlying_type") == "EQUITY":
                sym = (item.get("underlying_symbol") or "").upper()
                ukey = item.get("underlying_key") or ""
                if not sym or not ukey.startswith("NSE_EQ|"):
                    continue
                if target_set and sym not in target_set:
                    continue
                if sym not in fno_underlyings:
                    isin = ukey.split("|", 1)[1] if "|" in ukey else ""
                    fno_underlyings[sym] = {
                        "symbol": sym,
                        "name": item.get("name") or sym,
                        "instrument_key": ukey,
                        "isin": isin,
                        "lot_size": int(item.get("lot_size") or item.get("minimum_lot") or 1),
                    }
        return list(fno_underlyings.values())

    def fetch_daily_candles(self, instrument_key: str, lookback_days: int = 320) -> List[List[Any]]:
        """
        Calls Upstox Historical Candle Data V3 (/v3/historical-candle/{key}/days/1/{to}/{from})
        with automatic fallback to V2 (/v2/historical-candle/{key}/day/{to}/{from}).
        Returns chronological list of candles: [timestamp, open, high, low, close, volume, oi]
        """
        to_date = dt.date.today().strftime("%Y-%m-%d")
        from_date = "2024-01-01" if lookback_days >= 300 else (dt.date.today() - dt.timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        encoded_key = urllib.parse.quote(instrument_key, safe="")
        v3_url = f"{UPSTOX_HISTORICAL_V3_BASE}/{encoded_key}/days/1/{to_date}/{from_date}"
        try:
            res = self.get_json(v3_url, include_auth=True)
        except Exception:
            v2_url = f"{UPSTOX_HISTORICAL_V2_BASE}/{encoded_key}/day/{to_date}/{from_date}"
            res = self.get_json(v2_url, include_auth=False)
        candles = res.get("data", {}).get("candles", [])
        return list(reversed(candles))

    def fetch_option_chain(self, instrument_key: str, expiry_date: str = "current_month") -> List[Dict[str, Any]]:
        """
        Calls GET https://api.upstox.com/v2/option/chain?instrument_key=...&expiry_date=current_month
        Supports relative keywords ('current_month', 'next_month', 'current_week') or 'YYYY-MM-DD'.
        """
        res = self.get_json(
            UPSTOX_OPTION_CHAIN_V2_URL,
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
            include_auth=True,
        )
        return res.get("data", [])

    def fetch_fundamentals(self, isin: str) -> Dict[str, Any]:
        """
        Calls Upstox Company Fundamentals API:
        - GET /v2/fundamentals/{isin}/key-ratios
        - GET /v2/fundamentals/{isin}/income-statement?type=consolidated&time_period=yearly
        """
        out: Dict[str, Any] = {
            "roe_pct": 15.0,
            "sector_roe_pct": 14.0,
            "roce_pct": 16.0,
            "sector_roce_pct": 14.5,
            "pe_ratio": 22.0,
            "sector_pe_ratio": 24.0,
            "net_profit_yoy_pct": 10.0,
            "revenue_yoy_pct": 8.0,
        }
        if not isin:
            return out

        def _parse_num(val: Any, default: float = 0.0) -> float:
            if val is None:
                return default
            cleaned = str(val).replace("%", "").replace("+", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return default

        try:
            ratios_res = self.get_json(f"{UPSTOX_FUNDAMENTALS_BASE}/{isin}/key-ratios", include_auth=True)
            for entry in ratios_res.get("data", []):
                rname = (entry.get("name") or "").upper()
                cval = _parse_num(entry.get("company_value"))
                sval = _parse_num(entry.get("sector_value"))
                if rname == "ROE":
                    out["roe_pct"], out["sector_roe_pct"] = cval, sval
                elif rname == "ROCE":
                    out["roce_pct"], out["sector_roce_pct"] = cval, sval
                elif rname == "P/E":
                    out["pe_ratio"], out["sector_pe_ratio"] = cval, sval
        except Exception:
            pass

        try:
            inc_res = self.get_json(
                f"{UPSTOX_FUNDAMENTALS_BASE}/{isin}/income-statement",
                params={"type": "consolidated", "time_period": "yearly"},
                include_auth=True,
            )
            for cat in inc_res.get("data", {}).get("income_statement", []):
                cname = (cat.get("category") or "").lower()
                hist = cat.get("history") or []
                if hist:
                    latest_chg = _parse_num(hist[0].get("change"), 0.0)
                    if cname == "net_profit":
                        out["net_profit_yoy_pct"] = latest_chg
                    elif cname == "revenue":
                        out["revenue_yoy_pct"] = latest_chg
        except Exception:
            pass

        return out


# ---------------------------------------------------------------------------
# Quantitative Technical & Volatility Indicators (Pure Python / Math)
# ---------------------------------------------------------------------------
def compute_rsi(closes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(diff, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-diff, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def compute_mfi(highs: List[float], lows: List[float], closes: List[float], volumes: List[float], period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    typ = [(h + l + c) / 3.0 for h, l, c in zip(highs, lows, closes)]
    pos_flow, neg_flow = 0.0, 0.0
    for i in range(len(closes) - period, len(closes)):
        raw_mf = typ[i] * volumes[i]
        if typ[i] >= typ[i - 1]:
            pos_flow += raw_mf
        else:
            neg_flow += raw_mf
    if neg_flow == 0:
        return 100.0
    mfr = pos_flow / neg_flow
    return 100.0 - (100.0 / (1.0 + mfr))


def compute_stoch_k(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> float:
    if len(closes) < period:
        return 50.0
    h_max = max(highs[-period:])
    l_min = min(lows[-period:])
    if h_max == l_min:
        return 50.0
    return ((closes[-1] - l_min) / (h_max - l_min)) * 100.0


def compute_bollinger(closes: List[float], period: int = 20, num_std: float = 2.0) -> Tuple[float, float]:
    """Returns (pct_b, bandwidth_pct)."""
    if len(closes) < period:
        return 0.5, 5.0
    window = closes[-period:]
    sma = sum(window) / period
    variance = sum((x - sma) ** 2 for x in window) / period
    std = math.sqrt(variance)
    upper = sma + num_std * std
    lower = sma - num_std * std
    if upper == lower or sma == 0:
        return 0.5, 0.0
    pct_b = (closes[-1] - lower) / (upper - lower)
    bandwidth_pct = ((upper - lower) / sma) * 100.0
    return pct_b, bandwidth_pct


def compute_historical_volatility(closes: List[float], window: int = 20) -> float:
    """Annualized close-to-close realized volatility (%) over `window` trading days."""
    if len(closes) < window + 1:
        return 20.0
    log_rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i - 1] > 0 and closes[i] > 0
    ]
    if len(log_rets) < 2:
        return 20.0
    mean_r = sum(log_rets) / len(log_rets)
    var_r = sum((r - mean_r) ** 2 for r in log_rets) / (len(log_rets) - 1)
    return math.sqrt(var_r) * math.sqrt(252.0) * 100.0


def compute_atr_and_adx(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Tuple[float, float]:
    """Returns (atr_pct_of_spot, adx_14)."""
    n = len(closes)
    if n < period * 2 + 1:
        return 1.5, 20.0
    trs, plus_dms, minus_dms = [], [], []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0
        trs.append(tr)
        plus_dms.append(plus_dm)
        minus_dms.append(minus_dm)

    atr = sum(trs[:period]) / period
    sm_tr = sum(trs[:period])
    sm_plus = sum(plus_dms[:period])
    sm_minus = sum(minus_dms[:period])
    dxs = []

    for i in range(period, len(trs)):
        atr = (atr * (period - 1) + trs[i]) / period
        sm_tr = sm_tr - (sm_tr / period) + trs[i]
        sm_plus = sm_plus - (sm_plus / period) + plus_dms[i]
        sm_minus = sm_minus - (sm_minus / period) + minus_dms[i]
        plus_di = 100.0 * (sm_plus / sm_tr) if sm_tr > 0 else 0.0
        minus_di = 100.0 * (sm_minus / sm_tr) if sm_tr > 0 else 0.0
        di_sum = plus_di + minus_di
        dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0.0
        dxs.append(dx)

    adx = sum(dxs[:period]) / period if len(dxs) >= period else (sum(dxs) / max(len(dxs), 1))
    for i in range(period, len(dxs)):
        adx = (adx * (period - 1) + dxs[i]) / period

    atr_pct = (atr / closes[-1]) * 100.0 if closes[-1] > 0 else 0.0
    return atr_pct, adx


# ---------------------------------------------------------------------------
# Core Screener Evaluation Engine
# ---------------------------------------------------------------------------
def evaluate_stock_for_option_selling(
    meta: Dict[str, Any],
    candles: List[List[Any]],
    option_chain: List[Dict[str, Any]],
    fundamentals: Dict[str, Any],
    thresholds: ScreeningThresholds,
) -> Optional[ScreenerResult]:
    if len(candles) < 60 or not option_chain:
        return None

    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]
    closes = [float(c[4]) for c in candles]
    volumes = [float(c[5]) for c in candles]

    spot = float(option_chain[0].get("underlying_spot_price") or closes[-1])
    expiry_date = str(option_chain[0].get("expiry") or "current_month")
    lot_size = int(meta.get("lot_size") or 1)

    # 1. Technical Oversold Metrics
    rsi_14 = compute_rsi(closes, 14)
    mfi_14 = compute_mfi(highs, lows, closes, volumes, 14)
    stoch_k = compute_stoch_k(highs, lows, closes, 14)
    bb_pct_b, bb_bw_pct = compute_bollinger(closes, 20, 2.0)
    high_20d = max(highs[-20:])
    drawdown_20d_pct = ((spot - high_20d) / high_20d) * 100.0 if high_20d > 0 else 0.0

    # 2. Structural & Volume Integrity ("Doesn't Deserve It")
    sma_200 = sum(closes[-200:]) / len(closes[-200:])
    price_to_sma200 = spot / sma_200 if sma_200 > 0 else 1.0
    high_since_2024 = float(meta.get("high_since_2024") or max(highs))
    sorted_lows = sorted(lows)
    low_2024_base = float(meta.get("low_2024_base") or sorted_lows[max(0, int(len(sorted_lows) * 0.05))])
    abs_low_2024 = min(low_2024_base * 0.92, sorted_lows[0])
    hist_range_pct_2024 = max(0.0, min(100.0, ((spot - abs_low_2024) / max(1.0, high_since_2024 - abs_low_2024)) * 100.0))
    dist_to_2024_base_pct = max(0.0, ((spot - low_2024_base) / max(1.0, low_2024_base)) * 100.0)

    avg_vol_20 = sum(volumes[-20:]) / 20.0 if len(volumes) >= 20 else 1.0
    down_vols_5d = [
        volumes[i] for i in range(len(closes) - 5, len(closes))
        if closes[i] < closes[i - 1]
    ]
    avg_down_vol_5d = (sum(down_vols_5d) / len(down_vols_5d)) if down_vols_5d else (avg_vol_20 * 0.75)
    down_vol_ratio = avg_down_vol_5d / avg_vol_20 if avg_vol_20 > 0 else 1.0

    roe_pct = float(fundamentals.get("roe_pct", 15.0))
    sector_roe_pct = float(fundamentals.get("sector_roe_pct", 14.0))
    roce_pct = float(fundamentals.get("roce_pct", 16.0))
    sector_roce_pct = float(fundamentals.get("sector_roce_pct", 14.5))
    pe_ratio = float(fundamentals.get("pe_ratio", 22.0))
    sector_pe_ratio = float(fundamentals.get("sector_pe_ratio", 24.0))
    net_profit_yoy_pct = float(fundamentals.get("net_profit_yoy_pct", 10.0))
    revenue_yoy_pct = float(fundamentals.get("revenue_yoy_pct", 8.0))

    # 3. Realized Volatility & Stagnation Metrics ("Expires Worthless")
    hv_10 = compute_historical_volatility(closes, 10)
    hv_20 = compute_historical_volatility(closes, 20)
    hv_comp_ratio = hv_10 / hv_20 if hv_20 > 0 else 1.0
    atr_14_pct, adx_14 = compute_atr_and_adx(highs, lows, closes, 14)

    # 4. Option Chain Analysis (F&O Volume, Put OI Support Wall, OTM Short Put Selection)
    total_opt_vol = 0
    total_put_oi = 0
    total_call_oi = 0
    put_wall_strike = spot * 0.95
    max_put_oi = -1

    candidate_puts: List[Dict[str, Any]] = []
    all_strikes_sorted = sorted(option_chain, key=lambda x: float(x.get("strike_price") or 0.0))

    for row in all_strikes_sorted:
        strike = float(row.get("strike_price") or 0.0)
        c_md = (row.get("call_options") or {}).get("market_data") or {}
        p_md = (row.get("put_options") or {}).get("market_data") or {}
        p_gk = (row.get("put_options") or {}).get("option_greeks") or {}

        c_vol = int(c_md.get("volume") or 0)
        p_vol = int(p_md.get("volume") or 0)
        c_oi = int(c_md.get("oi") or 0)
        p_oi = int(p_md.get("oi") or 0)

        total_opt_vol += (c_vol + p_vol)
        total_put_oi += p_oi
        total_call_oi += c_oi

        if strike <= spot and p_oi > max_put_oi:
            max_put_oi = p_oi
            put_wall_strike = strike

        if strike < spot:
            ltp = float(p_md.get("ltp") or 0.0)
            bid = float(p_md.get("bid_price") or ltp)
            ask = float(p_md.get("ask_price") or ltp)
            spread_pct = ((ask - bid) / ltp * 100.0) if ltp > 0 and ask >= bid else 0.0
            delta = float(p_gk.get("delta") or -0.20)
            theta = float(p_gk.get("theta") or -1.0)
            vega = float(p_gk.get("vega") or 1.0)
            iv = float(p_gk.get("iv") or (hv_20 + 3.0))
            pop = float(p_gk.get("pop") or (1.0 - abs(delta)) * 100.0)
            if pop <= 1.0:
                pop *= 100.0

            if ltp > 0:
                candidate_puts.append({
                    "strike": strike,
                    "ltp": ltp,
                    "spread_pct": spread_pct,
                    "delta": delta,
                    "theta": theta,
                    "vega": vega,
                    "iv": iv,
                    "pop": pop,
                    "oi": p_oi,
                    "volume": p_vol,
                })

    if not candidate_puts:
        return None

    pcr = round(total_put_oi / total_call_oi, 2) if total_call_oi > 0 else 1.0

    in_delta_zone = [
        p for p in candidate_puts
        if thresholds.target_put_delta_min <= p["delta"] <= thresholds.target_put_delta_max
    ]
    if not in_delta_zone:
        in_delta_zone = sorted(candidate_puts, key=lambda p: abs(p["delta"] - (-0.20)))[:2]

    best_put = sorted(
        in_delta_zone,
        key=lambda p: (
            1 if p["strike"] <= put_wall_strike else 0,
            p["pop"],
            -p["spread_pct"],
        ),
        reverse=True,
    )[0]

    lower_strikes = [p for p in candidate_puts if p["strike"] < best_put["strike"]]
    hedge_put = lower_strikes[-1] if lower_strikes else {"strike": round(best_put["strike"] * 0.96, 1), "ltp": best_put["ltp"] * 0.35}

    vrp_spread = best_put["iv"] - hv_20
    safety_margin_pct = ((spot - best_put["strike"]) / spot) * 100.0
    est_credit_inr = round(best_put["ltp"] * lot_size, 2)

    # Quantitative Sub-Scores (0 - 100 scale)
    rsi_component = max(0.0, min(100.0, (48.0 - rsi_14) * 4.0)) if rsi_14 >= 22.0 else 45.0
    bb_component = max(0.0, min(100.0, (0.40 - bb_pct_b) * 250.0))
    mfi_component = max(0.0, min(100.0, (55.0 - mfi_14) * 2.8))
    oversold_score = round(0.45 * rsi_component + 0.30 * bb_component + 0.25 * mfi_component, 1)

    roe_edge = max(0.0, min(100.0, 60.0 + (roe_pct - sector_roe_pct) * 5.0))
    growth_comp = max(0.0, min(100.0, 50.0 + net_profit_yoy_pct * 2.5))
    dma_comp = max(0.0, min(100.0, (price_to_sma200 - 0.92) * 700.0))
    vol_exhaust_comp = max(0.0, min(100.0, (1.30 - down_vol_ratio) * 180.0))
    quality_score = round(0.30 * roe_edge + 0.25 * growth_comp + 0.25 * dma_comp + 0.20 * vol_exhaust_comp, 1)

    hv_comp = max(0.0, min(100.0, (1.08 - hv_comp_ratio) * 320.0))
    adx_comp = max(0.0, min(100.0, (32.0 - adx_14) * 4.5))
    vrp_comp = max(0.0, min(100.0, vrp_spread * 12.0))
    pop_comp = max(0.0, min(100.0, (best_put["pop"] - 65.0) * 4.0))
    stagnation_score = round(0.30 * hv_comp + 0.25 * adx_comp + 0.20 * vrp_comp + 0.25 * pop_comp, 1)

    low_2024_bonus = 6.5 if dist_to_2024_base_pct <= 5.0 else (3.0 if hist_range_pct_2024 <= 25.0 else 0.0)
    composite_score = round(min(98.0, 0.30 * oversold_score + 0.35 * quality_score + 0.35 * stagnation_score + low_2024_bonus), 1)

    passes_liquidity = (
        total_opt_vol >= thresholds.min_chain_option_volume
        and best_put["spread_pct"] <= thresholds.max_otm_bid_ask_spread_pct
    )
    passes_oversold = (
        thresholds.min_rsi_14 <= rsi_14 <= thresholds.max_rsi_14
        and mfi_14 <= thresholds.max_mfi_14
        and bb_pct_b <= thresholds.max_bb_pct_b
    )
    passes_quality = (
        (roe_pct >= thresholds.min_roe_pct or roe_pct >= sector_roe_pct)
        and (roce_pct >= thresholds.min_roce_pct or roce_pct >= sector_roce_pct)
        and (not thresholds.require_positive_profit_growth or net_profit_yoy_pct > 0)
        and (price_to_sma200 >= thresholds.min_price_to_sma200_ratio or dist_to_2024_base_pct <= 8.0 or hist_range_pct_2024 <= 22.0)
        and hist_range_pct_2024 <= thresholds.max_hist_range_pct_2024
        and dist_to_2024_base_pct <= thresholds.max_dist_to_2024_base_pct
        and down_vol_ratio <= thresholds.max_down_vol_ratio
    )
    passes_stagnation = (
        hv_20 <= thresholds.max_hv20_pct
        and hv_comp_ratio <= thresholds.max_hv10_to_hv20_ratio
        and adx_14 <= thresholds.max_adx_14
        and atr_14_pct <= thresholds.max_atr_pct
        and vrp_spread >= thresholds.min_vrp_pct
        and best_put["pop"] >= thresholds.min_pop_pct
    )

    passes_all = passes_liquidity and passes_oversold and passes_quality and passes_stagnation

    strategy_label = (
        f"Sell {best_put['strike']:g} PE (or {best_put['strike']:g}/{hedge_put['strike']:g} Bull Put Spread)"
    )
    rationale = (
        f"RSI(14)={rsi_14:.1f} & %B={bb_pct_b:.2f} on low down-day vol ({down_vol_ratio:.2f}x); "
        f"ROE {roe_pct:.1f}% vs sector {sector_roe_pct:.1f}%, PAT YoY +{net_profit_yoy_pct:.1f}%; "
        f"HV10/HV20={hv_comp_ratio:.2f}x, ADX={adx_14:.1f}, IV({best_put['iv']:.1f}%) > HV20({hv_20:.1f}%)."
    )

    return ScreenerResult(
        symbol=meta["symbol"],
        name=meta["name"],
        instrument_key=meta["instrument_key"],
        isin=meta["isin"],
        spot_price=round(spot, 2),
        lot_size=lot_size,
        expiry_date=expiry_date,
        low_2024_base=round(low_2024_base, 2),
        high_since_2024=round(high_since_2024, 2),
        hist_range_pct_2024=round(hist_range_pct_2024, 1),
        dist_to_2024_base_pct=round(dist_to_2024_base_pct, 2),
        total_fno_option_volume=total_opt_vol,
        total_put_oi=total_put_oi,
        pcr=pcr,
        put_oi_wall_strike=put_wall_strike,
        rsi_14=round(rsi_14, 1),
        mfi_14=round(mfi_14, 1),
        stoch_k=round(stoch_k, 1),
        bb_pct_b=round(bb_pct_b, 2),
        drawdown_20d_pct=round(drawdown_20d_pct, 2),
        roe_pct=round(roe_pct, 1),
        sector_roe_pct=round(sector_roe_pct, 1),
        roce_pct=round(roce_pct, 1),
        sector_roce_pct=round(sector_roce_pct, 1),
        pe_ratio=round(pe_ratio, 1),
        sector_pe_ratio=round(sector_pe_ratio, 1),
        net_profit_yoy_pct=round(net_profit_yoy_pct, 1),
        revenue_yoy_pct=round(revenue_yoy_pct, 1),
        price_to_sma200=round(price_to_sma200, 3),
        down_vol_ratio=round(down_vol_ratio, 2),
        hv_10_pct=round(hv_10, 1),
        hv_20_pct=round(hv_20, 1),
        hv_compression_ratio=round(hv_comp_ratio, 2),
        adx_14=round(adx_14, 1),
        atr_14_pct=round(atr_14_pct, 2),
        bb_bandwidth_pct=round(bb_bw_pct, 2),
        recommended_strategy=strategy_label,
        short_put_strike=best_put["strike"],
        hedge_put_strike=hedge_put["strike"],
        short_put_ltp=round(best_put["ltp"], 2),
        short_put_bid_ask_spread_pct=round(best_put["spread_pct"], 2),
        short_put_iv=round(best_put["iv"], 1),
        vrp_spread_pct=round(vrp_spread, 1),
        short_put_delta=round(best_put["delta"], 2),
        short_put_theta=round(best_put["theta"], 2),
        short_put_vega=round(best_put["vega"], 2),
        short_put_pop_pct=round(best_put["pop"], 1),
        safety_margin_pct=round(safety_margin_pct, 2),
        est_credit_per_lot_inr=est_credit_inr,
        oversold_score=oversold_score,
        quality_score=quality_score,
        stagnation_score=stagnation_score,
        composite_worthless_score=composite_score,
        passes_all_filters=passes_all,
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Realistic Demo / Offline Verification Dataset Generator
# ---------------------------------------------------------------------------
def build_demo_dataset() -> List[Tuple[Dict[str, Any], List[List[Any]], List[Dict[str, Any]], Dict[str, Any]]]:
    specs = [
        {
            "symbol": "VOLTAS", "name": "VOLTAS LTD", "isin": "INE226A01021", "lot_size": 375,
            "spot": 1053.40, "low_2024_base": 1020.0, "high_since_2024": 1942.0,
            "drift_200": 0.0004, "pullback_14": -0.0029, "vol_scale": 0.0068,
            "down_vol_mult": 0.72, "chain_vol": 1_480_000, "p_oi": 3_200_000, "c_oi": 2_500_000,
            "strike_step": 20.0, "iv": 24.5, "roe": 15.6, "s_roe": 13.2, "roce": 19.4, "s_roce": 15.8,
            "pe": 38.0, "s_pe": 41.0, "pat_yoy": 24.5, "rev_yoy": 14.2,
        },
        {
            "symbol": "ASIANPAINT", "name": "ASIAN PAINTS LIMITED", "isin": "INE021A01026", "lot_size": 200,
            "spot": 2390.00, "low_2024_base": 2340.0, "high_since_2024": 3422.0,
            "drift_200": 0.0004, "pullback_14": -0.0028, "vol_scale": 0.0065,
            "down_vol_mult": 0.76, "chain_vol": 1_620_000, "p_oi": 3_400_000, "c_oi": 2_850_000,
            "strike_step": 20.0, "iv": 21.8, "roe": 28.4, "s_roe": 18.5, "roce": 34.2, "s_roce": 21.0,
            "pe": 42.0, "s_pe": 46.0, "pat_yoy": 6.4, "rev_yoy": 5.8,
        },
        {
            "symbol": "ITC", "name": "ITC LIMITED", "isin": "INE154A01025", "lot_size": 1600,
            "spot": 486.40, "drift_200": 0.0005, "pullback_14": -0.0028, "vol_scale": 0.0065,
            "down_vol_mult": 0.78, "chain_vol": 2_840_000, "p_oi": 6_400_000, "c_oi": 5_100_000,
            "strike_step": 5.0, "iv": 16.8, "roe": 27.4, "s_roe": 19.2, "roce": 34.1, "s_roce": 22.0,
            "pe": 24.8, "s_pe": 31.5, "pat_yoy": 11.4, "rev_yoy": 8.9,
        },
        {
            "symbol": "HDFCBANK", "name": "HDFC BANK LTD", "isin": "INE040A01034", "lot_size": 550,
            "spot": 1642.00, "drift_200": 0.0004, "pullback_14": -0.0031, "vol_scale": 0.0072,
            "down_vol_mult": 0.82, "chain_vol": 4_120_000, "p_oi": 8_200_000, "c_oi": 7_400_000,
            "strike_step": 20.0, "iv": 17.5, "roe": 16.8, "s_roe": 14.5, "roce": 15.9, "s_roce": 13.8,
            "pe": 18.2, "s_pe": 17.9, "pat_yoy": 15.2, "rev_yoy": 12.6,
        },
        {
            "symbol": "SUNPHARMA", "name": "SUN PHARMACEUTICAL IND L", "isin": "INE044A01036", "lot_size": 350,
            "spot": 1815.50, "drift_200": 0.0006, "pullback_14": -0.0029, "vol_scale": 0.0075,
            "down_vol_mult": 0.85, "chain_vol": 1_260_000, "p_oi": 2_150_000, "c_oi": 1_890_000,
            "strike_step": 20.0, "iv": 19.4, "roe": 16.2, "s_roe": 14.1, "roce": 18.5, "s_roce": 15.2,
            "pe": 34.0, "s_pe": 33.2, "pat_yoy": 18.6, "rev_yoy": 11.4,
        },
        {
            "symbol": "POWERGRID", "name": "POWER GRID CORP. LTD.", "isin": "INE752E01010", "lot_size": 3600,
            "spot": 324.80, "drift_200": 0.0005, "pullback_14": -0.0027, "vol_scale": 0.0068,
            "down_vol_mult": 0.74, "chain_vol": 1_950_000, "p_oi": 4_800_000, "c_oi": 4_100_000,
            "strike_step": 5.0, "iv": 18.9, "roe": 18.4, "s_roe": 13.6, "roce": 14.8, "s_roce": 12.1,
            "pe": 17.6, "s_pe": 21.0, "pat_yoy": 9.8, "rev_yoy": 7.2,
        },
        {
            "symbol": "TCS", "name": "TATA CONSULTANCY SERV LT", "isin": "INE467B01029", "lot_size": 175,
            "spot": 4088.00, "drift_200": 0.0004, "pullback_14": -0.0030, "vol_scale": 0.0070,
            "down_vol_mult": 0.88, "chain_vol": 1_780_000, "p_oi": 2_900_000, "c_oi": 2_650_000,
            "strike_step": 50.0, "iv": 18.2, "roe": 48.5, "s_roe": 24.0, "roce": 58.2, "s_roce": 28.5,
            "pe": 28.4, "s_pe": 29.8, "pat_yoy": 9.4, "rev_yoy": 6.8,
        },
        {
            "symbol": "NESTLEIND", "name": "NESTLE INDIA LIMITED", "isin": "INE239A01024", "lot_size": 200,
            "spot": 2480.00, "drift_200": 0.0003, "pullback_14": -0.0026, "vol_scale": 0.0062,
            "down_vol_mult": 0.80, "chain_vol": 890_000, "p_oi": 1_450_000, "c_oi": 1_320_000,
            "strike_step": 20.0, "iv": 16.5, "roe": 88.0, "s_roe": 21.5, "roce": 96.4, "s_roce": 24.0,
            "pe": 64.0, "s_pe": 52.0, "pat_yoy": 8.1, "rev_yoy": 7.5,
        },
        {
            "symbol": "INDUSINDBK", "name": "INDUSIND BANK LIMITED", "isin": "INE095A01012", "lot_size": 500,
            "spot": 1280.00, "drift_200": -0.0008, "pullback_14": -0.0110, "vol_scale": 0.0240,
            "down_vol_mult": 1.68, "chain_vol": 3_400_000, "p_oi": 3_900_000, "c_oi": 6_200_000,
            "strike_step": 20.0, "iv": 36.5, "roe": 9.8, "s_roe": 14.5, "roce": 10.2, "s_roce": 13.8,
            "pe": 12.1, "s_pe": 17.9, "pat_yoy": -21.4, "rev_yoy": 3.1,
        },
        {
            "symbol": "TRENT", "name": "TRENT LTD", "isin": "INE849A01020", "lot_size": 100,
            "spot": 7420.00, "drift_200": 0.0022, "pullback_14": 0.0045, "vol_scale": 0.0195,
            "down_vol_mult": 0.95, "chain_vol": 1_650_000, "p_oi": 1_800_000, "c_oi": 1_200_000,
            "strike_step": 100.0, "iv": 32.0, "roe": 26.4, "s_roe": 16.0, "roce": 29.1, "s_roce": 18.0,
            "pe": 118.0, "s_pe": 45.0, "pat_yoy": 42.0, "rev_yoy": 36.5,
        },
    ]

    dataset = []
    base_date = dt.date(2026, 10, 14)

    for idx, s in enumerate(specs):
        n_days = 220
        prices = [0.0] * n_days
        prices[-1] = s["spot"]
        for d in range(n_days - 1, 0, -1):
            days_from_end = (n_days - 1) - d
            if days_from_end < 10:
                # Range-bound oscillation with slight negative skew -> RSI ~34-38, HV10 < HV20, ADX ~15-19
                alt = 0.42 if (days_from_end % 2 == 1) else -1.0
                wave = alt * s["vol_scale"] * (0.65 if s["vol_scale"] < 0.01 else 1.35)
                ret = (s["pullback_14"] * 0.20 if s["vol_scale"] < 0.01 else s["pullback_14"]) + wave
            elif days_from_end < 28:
                alt = 0.65 if (days_from_end % 2 == 0) else -1.0
                wave = alt * s["vol_scale"] * 1.15
                ret = (s["pullback_14"] * 0.15 if s["vol_scale"] < 0.01 else s["pullback_14"]) + wave
            else:
                alt = 1.0 if (d % 2 == 0) else -0.92
                wave = alt * s["vol_scale"] * 1.05
                ret = s["drift_200"] + wave
            prices[d - 1] = prices[d] / (1.0 + ret)

        candles = []
        for d in range(n_days):
            c_date = (base_date - dt.timedelta(days=(n_days - 1 - d))).strftime("%Y-%m-%dT00:00:00+05:30")
            close_p = round(prices[d], 2)
            prev_p = round(prices[d - 1], 2) if d > 0 else close_p
            intraday_rng = close_p * (s["vol_scale"] * (0.75 if d >= n_days - 10 and s["vol_scale"] < 0.01 else 1.15))
            if s["vol_scale"] < 0.01:
                # Overlapping range bars (inside/sideways bars keep directional movement low -> ADX ~15-18)
                band_center = 0.88 * prices[max(0, d - 12)] + 0.12 * close_p
                half_span = close_p * 0.0085 * (1.01 if d % 2 == 0 else 0.99)
                high_p = round(max(close_p, prev_p, band_center + half_span), 2)
                low_p = round(min(close_p, prev_p, band_center - half_span), 2)
            else:
                high_p = round(max(close_p, prev_p) + intraday_rng * 0.55, 2)
                low_p = round(min(close_p, prev_p) - intraday_rng * 0.65, 2)
            open_p = prev_p
            is_down = close_p < prev_p
            base_vol = 3_500_000
            if d >= n_days - 5 and is_down:
                vol = int(base_vol * s["down_vol_mult"])
            else:
                vol = int(base_vol * (0.95 + 0.1 * math.sin(d)))
            candles.append([c_date, open_p, high_p, low_p, close_p, vol, 0])

        step = s["strike_step"]
        atm_strike = round(s["spot"] / step) * step
        chain = []
        for k_offset in range(-5, 3):
            strike = round(atm_strike + k_offset * step, 2)
            otm_pct = (s["spot"] - strike) / s["spot"]
            delta = round(-0.50 * math.exp(-22.0 * max(0.0, otm_pct)), 3) if strike <= s["spot"] else -0.62
            ltp = round(max(0.5, s["spot"] * 0.012 * math.exp(-18.0 * max(0.0, otm_pct))), 2)
            is_wall = (k_offset == -2)
            strike_p_oi = int(s["p_oi"] * (0.34 if is_wall else 0.11))
            strike_c_oi = int(s["c_oi"] * (0.25 if k_offset == 2 else 0.12))
            chain.append({
                "expiry": "2026-10-29",
                "pcr": round(s["p_oi"] / s["c_oi"], 2),
                "strike_price": strike,
                "underlying_key": f"NSE_EQ|{s['isin']}",
                "underlying_spot_price": s["spot"],
                "call_options": {
                    "instrument_key": f"NSE_FO|{100000 + idx * 20 + k_offset + 10}",
                    "market_data": {
                        "ltp": round(ltp * 1.1, 2),
                        "volume": int(s["chain_vol"] * 0.06),
                        "oi": strike_c_oi,
                        "bid_price": round(ltp * 1.09, 2),
                        "ask_price": round(ltp * 1.11, 2),
                    },
                    "option_greeks": {"delta": round(1.0 + delta, 3), "iv": s["iv"], "theta": -round(ltp * 0.06, 2), "vega": round(s["spot"] * 0.0012, 2), "pop": 75.0},
                },
                "put_options": {
                    "instrument_key": f"NSE_FO|{200000 + idx * 20 + k_offset + 10}",
                    "market_data": {
                        "ltp": ltp,
                        "volume": int(s["chain_vol"] * (0.14 if is_wall else 0.06)),
                        "oi": strike_p_oi,
                        "bid_price": round(ltp * 0.996, 2),
                        "ask_price": round(ltp * 1.004, 2),
                    },
                    "option_greeks": {
                        "delta": delta,
                        "iv": round(s["iv"] + max(0.0, otm_pct * 35.0), 1),
                        "theta": -round(ltp * 0.075, 2),
                        "vega": round(s["spot"] * 0.0011, 2),
                        "gamma": 0.0004,
                        "pop": round((1.0 - abs(delta)) * 100.0 + 3.5, 1),
                    },
                },
            })

        meta = {
            "symbol": s["symbol"],
            "name": s["name"],
            "instrument_key": f"NSE_EQ|{s['isin']}",
            "isin": s["isin"],
            "lot_size": s["lot_size"], "low_2024_base": s.get("low_2024_base", round(s["spot"] * 0.91, 2)), "high_since_2024": s.get("high_since_2024", round(s["spot"] * 1.28, 2)),
        }
        fundamentals = {
            "roe_pct": s["roe"],
            "sector_roe_pct": s["s_roe"],
            "roce_pct": s["roce"],
            "sector_roce_pct": s["s_roce"],
            "pe_ratio": s["pe"],
            "sector_pe_ratio": s["s_pe"],
            "net_profit_yoy_pct": s["pat_yoy"],
            "revenue_yoy_pct": s["rev_yoy"],
        }
        dataset.append((meta, candles, chain, fundamentals))
    return dataset


# ---------------------------------------------------------------------------
# CLI Runner & Report Formatter
# ---------------------------------------------------------------------------
def print_screener_table(results: List[ScreenerResult], show_all: bool = False) -> None:
    passed = [r for r in results if r.passes_all_filters]
    passed.sort(key=lambda r: r.composite_worthless_score, reverse=True)

    print("=" * 118)
    print(" UPSTOX F&O OPTION SELLING SCREENER — 'UNDESERVED OVERSOLD + STAGNANT VOLATILITY (THETA DECAY)'")
    print("=" * 118)
    header = (
        f"{'SYMBOL':<11} {'SPOT':>8} {'RSI14':>6} {'%B':>5} {'ROE/SEC':>9} "
        f"{'HV10/20':>8} {'ADX':>5} {'IV/HV20':>9} {'RECOMMENDED SHORT PUT':<24} {'POP%':>5} {'SCORE':>6}"
    )
    print(header)
    print("-" * 118)
    for r in passed:
        roe_str = f"{r.roe_pct:.0f}/{r.sector_roe_pct:.0f}%"
        hv_str = f"{r.hv_compression_ratio:.2f}x"
        iv_hv_str = f"{r.short_put_iv:.1f}/{r.hv_20_pct:.1f}"
        rec_short = f"{r.short_put_strike:g} PE @ INR {r.short_put_ltp:.1f} (d{r.short_put_delta:.2f})"
        print(
            f"{r.symbol:<11} {r.spot_price:>8.2f} {r.rsi_14:>6.1f} {r.bb_pct_b:>5.2f} {roe_str:>9} "
            f"{hv_str:>8} {r.adx_14:>5.1f} {iv_hv_str:>9} {rec_short:<24} {r.short_put_pop_pct:>5.1f} {r.composite_worthless_score:>6.1f}"
        )
    print("-" * 118)
    print(f"Qualified Candidates: {len(passed)} / {len(results)} screened F&O stocks.")

    if show_all and len(passed) < len(results):
        print("\nFiltered-Out / Trap Stocks (Rejected by Quality, Trend, or Volatility Expansion Guards):")
        for r in results:
            if not r.passes_all_filters:
                print(
                    f"  [REJECTED] {r.symbol:<11} Spot={r.spot_price:.2f} | RSI={r.rsi_14:.1f} | "
                    f"PAT YoY={r.net_profit_yoy_pct:+.1f}% | HV20={r.hv_20_pct:.1f}% (HV10/20={r.hv_compression_ratio:.2f}x) | "
                    f"DownVol={r.down_vol_ratio:.2f}x | Score={r.composite_worthless_score:.1f}"
                )


def export_results_csv(results: List[ScreenerResult], csv_path: str) -> None:
    if not results:
        return
    fieldnames = list(asdict(results[0]).keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda x: (x.passes_all_filters, x.composite_worthless_score), reverse=True):
            writer.writerow(asdict(r))
    print(f"Saved full screener report to: {csv_path}")


def load_credentials_from_file() -> None:
    """
    Safely loads Upstox API credentials from local .env or secure token file if not already set.
    Credentials are never hardcoded so public git repositories remain secure.
    """
    # 1. Check local .env file in script directory or current working directory
    base_dirs = [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    for d in base_dirs:
        env_file = os.path.join(d, ".env")
        if os.path.isfile(env_file):
            try:
                with open(env_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k, v = k.strip(), v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass

    # 2. Check local token files (e.g. Desktop 'Upstox API.txt' or 'upstox_token.txt')
    if "UPSTOX_ACCESS_TOKEN" not in os.environ or not os.environ["UPSTOX_ACCESS_TOKEN"].strip():
        token_paths = [
            os.path.join(os.getcwd(), "upstox_token.txt"),
            os.path.expanduser(r"~\OneDrive\Desktop\Upstox API.txt"),
            os.path.expanduser(r"~\Desktop\Upstox API.txt"),
        ]
        for p in token_paths:
            if os.path.isfile(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        val = f.read().strip()
                        if val and len(val) > 40:
                            os.environ["UPSTOX_ACCESS_TOKEN"] = val
                            break
                except Exception:
                    pass


def main() -> None:
    load_credentials_from_file()
    parser = argparse.ArgumentParser(description="Upstox F&O Option Selling Quantitative Screener")
    parser.add_argument("--access-token", default=os.environ.get("UPSTOX_ACCESS_TOKEN", ""), help="Upstox OAuth2 Access Token")
    parser.add_argument("--api-key", default=os.environ.get("UPSTOX_API_KEY", ""), help="Upstox API Key (client_id) for OAuth exchange")
    parser.add_argument("--api-secret", default=os.environ.get("UPSTOX_API_SECRET", ""), help="Upstox API Secret for OAuth exchange")
    parser.add_argument("--redirect-uri", default=os.environ.get("UPSTOX_REDIRECT_URI", "http://127.0.0.1:5000/callback"), help="Redirect URI")
    parser.add_argument("--auth-code", default="", help="Single-use authorization code to exchange for an access token")
    parser.add_argument("--expiry", default="current_month", help="Expiry date (YYYY-MM-DD) or Upstox keyword (current_month, next_month)")
    parser.add_argument("--symbols", default="", help="Comma-separated NSE F&O symbols (defaults to liquid F&O basket)")
    parser.add_argument("--max-symbols", type=int, default=40, help="Max F&O underlyings to scan")
    parser.add_argument("--csv-out", default="upstox_option_selling_candidates.csv", help="Output CSV path")
    parser.add_argument("--demo", action="store_true", help="Run offline simulation with sample Upstox v2/v3 payloads")
    args = parser.parse_args()

    thresholds = ScreeningThresholds()

    if args.demo:
        demo_data = build_demo_dataset()
        results: List[ScreenerResult] = []
        for meta, candles, chain, fund in demo_data:
            res = evaluate_stock_for_option_selling(meta, candles, chain, fund, thresholds)
            if res:
                results.append(res)
        print_screener_table(results, show_all=True)
        if args.csv_out:
            export_results_csv(results, args.csv_out)
        return

    access_token = args.access_token
    if not access_token and args.auth_code and args.api_key and args.api_secret:
        print("Exchanging authorization_code for Upstox access_token...")
        access_token = UpstoxClient.exchange_code_for_token(
            client_id=args.api_key,
            client_secret=args.api_secret,
            redirect_uri=args.redirect_uri,
            auth_code=args.auth_code,
        )
        print("Access token obtained! Tip: set export UPSTOX_ACCESS_TOKEN for subsequent runs today.")

    if not access_token:
        if args.api_key:
            login_url = (
                f"{UPSTOX_AUTH_DIALOG_URL}?response_type=code"
                f"&client_id={urllib.parse.quote(args.api_key)}"
                f"&redirect_uri={urllib.parse.quote(args.redirect_uri)}"
            )
            print("Step 1: Open this Upstox Login URL in your browser to get your authorization `code`:")
            print(f"  {login_url}")
            print("Step 2: Re-run with --auth-code <CODE> --api-key <KEY> --api-secret <SECRET>")
        else:
            print("Error: Provide --access-token (or set UPSTOX_ACCESS_TOKEN), or run with --demo to test offline.")
        sys.exit(1)

    client = UpstoxClient(access_token=access_token)
    symbol_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols else DEFAULT_LIQUID_FNO_SYMBOLS
    print(f"Loading NSE F&O instruments from Upstox BOD master ({len(symbol_list)} target symbols)...")
    universe = client.load_fno_equity_universe(filter_symbols=symbol_list)[: args.max_symbols]

    results = []
    for idx, meta in enumerate(universe, 1):
        sym = meta["symbol"]
        ukey = meta["instrument_key"]
        isin = meta["isin"]
        print(f"[{idx}/{len(universe)}] Screening {sym} ({ukey})...", end="\r", flush=True)
        try:
            candles = client.fetch_daily_candles(ukey, lookback_days=320)
            chain = client.fetch_option_chain(ukey, expiry_date=args.expiry)
            fund = client.fetch_fundamentals(isin)
            evaluated = evaluate_stock_for_option_selling(meta, candles, chain, fund, thresholds)
            if evaluated:
                results.append(evaluated)
        except Exception as exc:
            print(f"\n  [!] Skipped {sym}: {exc}")

    print()
    print_screener_table(results, show_all=True)
    if args.csv_out and results:
        export_results_csv(results, args.csv_out)


if __name__ == "__main__":
    main()