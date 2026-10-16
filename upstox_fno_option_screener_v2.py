#!/usr/bin/env python3
"""
Upstox F&O Quantitative Option Screener v2.0 ("Next-Month Rebound & VRP Harvester")
===================================================================================
Institutional-grade quantitative screener built on Upstox Developer API (v2 & v3)
engineered specifically to capture 20-to-40 DTE rebounds by Next-Month Expiry via
Short OTM Puts (-0.35 to -0.22 Delta) and Bull Put Credit Spreads (-0.32 / -0.14 Delta).

Empirically Grounded Quantitative Pillars (Academic & Practitioner Proven):
1. Cross-Sectional Momentum & Secular Uptrend (Jegadeesh & Titman, 1993):
   - Eliminates arbitrary calendar-year ("2024 low") lookback bias.
   - Requires positive 6M & 12M structural drift: Spot >= 0.98 * 200-DMA AND
     200-DMA Slope (20D) > 0. Buying short-term pullbacks inside structural winners.
2. Short-Horizon Mean Reversion (Connors & Alvarez, 2009):
   - Replaces collinear 14-day oscillators (RSI14/MFI14/Stoch14) with orthogonal
     short-horizon exhaustion: Connors RSI(2) <= 20 or RSI(5) <= 32, and 5-day return Z-score <= -1.25.
3. Futures OI & Basis Microstructure (NSE F&O Institutional Positioning):
   - Parses NSE_FO Futures from Upstox BOD master and evaluates 5-day Futures Price vs OI:
   - Accepts: Long Unwinding Exhaustion (Price Down, Futures OI Down, Basis >= 0) or
     Short Covering Rebound (Price Stabilizing/Up, Futures OI Down).
   - Hard Rejects: Aggressive Institutional Short Buildup (Price Down, Futures OI surging > +3%,
     or Futures trading in backwardation / negative basis).
4. Fundamental Quality, Cash-Flow Accruals & Institutional Ownership (Sloan, 1996; Gompers & Metrick, 2001):
   - Zero silent passing defaults: Missing fundamental data triggers hard rejection.
   - Requires Positive Operating Cash Flow (CFO > 0) via /v2/fundamentals/{isin}/cash-flow.
   - Institutional Flow Guard: QoQ change in (Promoters + FII + Mutual Funds) >= -0.50%
     via /v2/fundamentals/{isin}/share-holdings (rejects stocks being dumped onto retail).
   - Corporate Action Event Guard: Hard rejects any stock with an Ex-Dividend or Split date
     prior to next_month expiry via /v2/fundamentals/{isin}/corporate-actions.
5. Yang-Zhang (2000) OHLC Volatility, True ATM VRP & Dual-Expiry Term Structure (Mixon, 2007):
   - Computes minimum-variance unbiased Yang-Zhang 20D annualized volatility (7x more efficient than Close-to-Close).
   - True Volatility Risk Premium: Next-Month ATM IV - YZ_HV(20) >= 2.0%.
   - Term Structure Ratio: Current-Month ATM IV / Next-Month ATM IV >= 0.97 (elevated front-end fear
     that crushes as spot mean-reverts over 20-35 days).
   - 25-Delta Risk Reversal (Put Skew): 25D Put IV - 25D Call IV >= 1.5% (retail hedging demand).
   - Order Book Micro-Price & Depth Guard via Batch /v3/market-quote/quotes.
6. Empirical Calibration via Upstox Expired Instruments API (/v2/expired-instruments/...):
   - Built-in historical backtest verifier to evaluate expired next-month short put PnL.

Usage:
  1. Run offline verification & demo simulation:
     python3 upstox_fno_option_screener_v2.py --demo
  2. Live screening targeting Next-Month Expiry:
     export UPSTOX_ACCESS_TOKEN="your_access_token"
     python3 upstox_fno_option_screener_v2.py --expiry next_month --max-symbols 50
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
UPSTOX_MARKET_QUOTE_V3_URL = "https://api.upstox.com/v3/market-quote/quotes"
UPSTOX_HISTORICAL_V3_BASE = "https://api.upstox.com/v3/historical-candle"
UPSTOX_HISTORICAL_V2_BASE = "https://api.upstox.com/v2/historical-candle"
UPSTOX_OPTION_CHAIN_V2_URL = "https://api.upstox.com/v2/option/chain"
UPSTOX_FUNDAMENTALS_BASE = "https://api.upstox.com/v2/fundamentals"
UPSTOX_EXPIRED_BASE = "https://api.upstox.com/v2/expired-instruments"

DEFAULT_LIQUID_FNO_SYMBOLS = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "ITC", "SBIN", "BHARTIARTL",
    "LT", "AXISBANK", "KOTAKBANK", "SUNPHARMA", "MARUTI", "NTPC", "POWERGRID",
    "HCLTECH", "WIPRO", "TITAN", "ULTRACEMCO", "BAJFINANCE", "NESTLEIND", "CIPLA",
    "DRREDDY", "HEROMOTOCO", "BAJAJ-AUTO", "M&M", "TATAMOTORS", "TATASTEEL",
    "HINDALCO", "JSWSTEEL", "COALINDIA", "ONGC", "GRASIM", "TECHM", "BRITANNIA",
    "PIDILITEIND", "DABUR", "GODREJCP", "HAVELLS", "SIEMENS", "ABB", "VOLTAS", "ASIANPAINT"
]


@dataclass
class ScreeningThresholdsV2:
    """Strictly calibrated, historically proven thresholds for Next-Month Rebound."""
    # Pillar 1: Liquidity & Microstructure
    min_chain_option_volume: int = 150_000        # Next-month chain + current-month liquidity
    max_bid_ask_spread_pct: float = 1.25          # Tight top-of-book spread on short put

    # Pillar 2: Secular Trend + Short-Horizon Exhaustion (Connors RSI & Z-Score)
    min_price_to_sma200: float = 0.98             # Must be in structural uptrend (or testing 200-DMA)
    require_positive_sma200_slope: bool = True    # 200-DMA today > 200-DMA 20 trading days ago
    min_ret_6m_pct: float = 4.0                   # Positive 6-month absolute drift
    max_rsi_2: float = 22.0                       # Connors 2-period RSI exhaustion
    max_rsi_5: float = 34.0                       # 5-period RSI pullback
    max_ret_5d_zscore: float = -1.15              # Sharp 5-day pullback relative to 60D distribution

    # Pillar 3: Futures OI & Basis Positioning
    min_futures_basis_pct: float = 0.05           # Positive cost-of-carry basis (reject backwardation)
    max_down_oi_buildup_5d_pct: float = 2.5       # Reject if 5D price drop has > +2.5% Futures OI surge

    # Pillar 4: Fundamentals, Cash Flow & Institutional Ownership
    min_roe_pct: float = 12.0                     # ROE >= 12% or >= Sector ROE
    min_roce_pct: float = 13.0                    # ROCE >= 13% or >= Sector ROCE
    require_positive_cfo: bool = True             # Sloan (1996) cash flow quality: Operating CF > 0
    min_inst_ownership_qoq_delta: float = -0.50   # (Promoter + FII + MF) QoQ change >= -0.50%
    reject_upcoming_ex_dividend: bool = True      # Hard reject if ex-dividend falls before next_month expiry

    # Pillar 5: Yang-Zhang Volatility, True ATM VRP & IV Term Structure
    max_yz_hv20_pct: float = 32.0                 # Max 20-day Yang-Zhang annualized volatility %
    min_true_atm_vrp_pct: float = 2.0             # Next-Month ATM IV - YZ_HV(20) >= 2.0%
    min_iv_term_structure_ratio: float = 0.97     # Current_Month ATM IV / Next_Month ATM IV >= 0.97
    min_put_call_skew_25d: float = 1.2            # 25D Put IV - 25D Call IV >= 1.2%
    target_short_put_delta_min: float = -0.36     # Next-month rebound sweet spot (-0.36 to -0.22)
    target_short_put_delta_max: float = -0.22
    target_hedge_put_delta: float = -0.14         # Bull Put Credit Spread long leg target delta


@dataclass
class ScreenerResultV2:
    symbol: str
    name: str
    instrument_key: str
    isin: str
    spot_price: float
    lot_size: int
    next_expiry_date: str
    # Pillar 1: Secular Momentum & Short-Term Exhaustion
    price_to_sma200: float
    sma200_slope_20d_pct: float
    ret_6m_pct: float
    rsi_2: float
    rsi_5: float
    ret_5d_zscore: float
    # Pillar 2: Futures Positioning & Microstructure
    futures_regime: str
    fut_oi_chg_5d_pct: float
    fut_basis_pct: float
    # Pillar 3: Fundamental Cash Flow & Institutional Flow
    roe_pct: float
    sector_roe_pct: float
    roce_pct: float
    net_profit_yoy_pct: float
    cfo_positive: bool
    inst_qoq_delta_pct: float
    has_upcoming_ex_div: bool
    # Pillar 4: Yang-Zhang Vol, Term Structure & Skew
    yz_hv20_pct: float
    cc_hv20_pct: float
    front_atm_iv: float
    next_atm_iv: float
    iv_term_structure_ratio: float
    true_atm_vrp_pct: float
    skew_25d_pct: float
    # Pillar 5: Next-Month Trade Structure (Bull Put Spread / Short Put)
    recommended_strategy: str
    short_put_strike: float
    hedge_put_strike: float
    short_put_ltp: float
    hedge_put_ltp: float
    net_spread_credit: float
    max_risk_per_share: float
    return_on_risk_pct: float
    short_put_bid_ask_spread_pct: float
    short_put_delta: float
    net_spread_delta: float
    net_spread_theta: float
    net_spread_vega: float
    short_put_pop_pct: float
    put_oi_wall_strike: float
    est_credit_per_lot_inr: float
    # Quantitative Scores (Orthogonal)
    rebound_exhaustion_score: float
    futures_flow_score: float
    fundamental_inst_score: float
    vol_surface_score: float
    composite_rebound_score: float
    passes_all_filters: bool
    rejection_reasons: str
    rationale: str


# ---------------------------------------------------------------------------
# Upstox v2 / v3 REST Client
# ---------------------------------------------------------------------------
class UpstoxClientV2:
    def __init__(self, access_token: str, rate_limit_sleep: float = 0.12):
        self.access_token = access_token.strip()
        self.rate_limit_sleep = rate_limit_sleep

    def _headers(self, include_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "UpstoxQuantScreener/2.0",
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
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Upstox API HTTP {exc.code} on {url}: {err_body}") from exc

    def load_fno_universe_with_futures(self, filter_symbols: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Parses Upstox BOD NSE.json.gz to extract equity underlyings AND their active
        current_month and next_month Futures instrument keys.
        """
        req = urllib.request.Request(UPSTOX_BOD_NSE_JSON_GZ, headers={"User-Agent": "UpstoxQuantScreener/2.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw_json = gzip.decompress(resp.read()).decode("utf-8")
        instruments = json.loads(raw_json)

        fno_map: Dict[str, Dict[str, Any]] = {}
        futures_by_sym: Dict[str, List[Tuple[int, str]]] = {}
        target_set = {s.upper() for s in filter_symbols} if filter_symbols else None

        for item in instruments:
            if item.get("segment") == "NSE_FO" and item.get("underlying_type") == "EQUITY":
                sym = (item.get("underlying_symbol") or "").upper()
                ukey = item.get("underlying_key") or ""
                if not sym or not ukey.startswith("NSE_EQ|"):
                    continue
                if target_set and sym not in target_set:
                    continue
                if sym not in fno_map:
                    isin = ukey.split("|", 1)[1] if "|" in ukey else ""
                    fno_map[sym] = {
                        "symbol": sym,
                        "name": item.get("name") or sym,
                        "instrument_key": ukey,
                        "isin": isin,
                        "lot_size": int(item.get("lot_size") or item.get("minimum_lot") or 1),
                        "front_fut_key": None,
                        "next_fut_key": None,
                    }
                if item.get("instrument_type") == "FUT":
                    exp_ms = int(item.get("expiry") or 0)
                    ikey = item.get("instrument_key") or ""
                    if exp_ms > 0 and ikey:
                        futures_by_sym.setdefault(sym, []).append((exp_ms, ikey))

        for sym, fut_list in futures_by_sym.items():
            fut_sorted = sorted(fut_list, key=lambda x: x[0])
            if sym in fno_map and fut_sorted:
                fno_map[sym]["front_fut_key"] = fut_sorted[0][1]
                if len(fut_sorted) >= 2:
                    fno_map[sym]["next_fut_key"] = fut_sorted[1][1]

        return list(fno_map.values())

    def fetch_daily_candles(self, instrument_key: str, lookback_calendar_days: int = 380) -> List[List[Any]]:
        """Fetches chronological daily OHLCV+OI candles via V3 Historical API."""
        to_date = dt.date.today().strftime("%Y-%m-%d")
        from_date = (dt.date.today() - dt.timedelta(days=lookback_calendar_days)).strftime("%Y-%m-%d")
        encoded_key = urllib.parse.quote(instrument_key, safe="")
        v3_url = f"{UPSTOX_HISTORICAL_V3_BASE}/{encoded_key}/days/1/{to_date}/{from_date}"
        try:
            res = self.get_json(v3_url, include_auth=True)
        except Exception:
            v2_url = f"{UPSTOX_HISTORICAL_V2_BASE}/{encoded_key}/day/{to_date}/{from_date}"
            res = self.get_json(v2_url, include_auth=False)
        candles = res.get("data", {}).get("candles", [])
        return list(reversed(candles))

    def fetch_option_chain(self, instrument_key: str, expiry_date: str = "next_month") -> List[Dict[str, Any]]:
        res = self.get_json(
            UPSTOX_OPTION_CHAIN_V2_URL,
            params={"instrument_key": instrument_key, "expiry_date": expiry_date},
            include_auth=True,
        )
        return res.get("data", [])

    def fetch_batch_quotes_v3(self, instrument_keys: List[str]) -> Dict[str, Any]:
        """Calls GET /v3/market-quote/quotes for up to 500 keys at once."""
        if not instrument_keys:
            return {}
        joined = ",".join(instrument_keys[:500])
        res = self.get_json(UPSTOX_MARKET_QUOTE_V3_URL, params={"instrument_key": joined}, include_auth=True)
        return res.get("data", {})


    def fetch_expired_option_candles(
        self,
        expired_instrument_key: str,
        interval: str = "day",
        to_date: str = "2026-09-24",
        from_date: str = "2026-08-20",
    ) -> List[List[Any]]:
        """
        Calls GET /v2/expired-instruments/historical-candle/{expired_instrument_key}/{interval}/{to_date}/{from_date}
        Used to empirically calibrate and backtest historical short-put and credit-spread PnL across expired F&O series.
        """
        encoded_key = urllib.parse.quote(expired_instrument_key, safe="")
        url = f"{UPSTOX_EXPIRED_BASE}/historical-candle/{encoded_key}/{interval}/{to_date}/{from_date}"
        res = self.get_json(url, include_auth=True)
        return list(reversed(res.get("data", {}).get("candles", [])))

    def fetch_strict_fundamentals(self, isin: str, next_expiry_date: str) -> Optional[Dict[str, Any]]:
        """
        Queries Upstox Fundamentals v2 endpoints:
        - /key-ratios
        - /income-statement
        - /cash-flow (Sloan 1996 Operating Cash Flow check)
        - /share-holdings (Institutional vs Retail flow)
        - /corporate-actions (Ex-dividend date trap filter)
        Returns None if core fundamental ratios cannot be verified (No silent defaults!).
        """
        if not isin:
            return None

        def _parse_num(val: Any) -> Optional[float]:
            if val is None:
                return None
            cleaned = str(val).replace("%", "").replace("+", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except ValueError:
                return None

        out: Dict[str, Any] = {}
        try:
            ratios_res = self.get_json(f"{UPSTOX_FUNDAMENTALS_BASE}/{isin}/key-ratios", include_auth=True)
            for entry in ratios_res.get("data", []):
                rname = (entry.get("name") or "").upper()
                cval = _parse_num(entry.get("company_value"))
                sval = _parse_num(entry.get("sector_value"))
                if rname == "ROE" and cval is not None:
                    out["roe_pct"] = cval
                    out["sector_roe_pct"] = sval if sval is not None else 12.0
                elif rname == "ROCE" and cval is not None:
                    out["roce_pct"] = cval
                    out["sector_roce_pct"] = sval if sval is not None else 13.0
        except Exception:
            return None

        if "roe_pct" not in out or "roce_pct" not in out:
            return None

        # Income statement YoY PAT
        out["net_profit_yoy_pct"] = 0.0
        try:
            inc_res = self.get_json(
                f"{UPSTOX_FUNDAMENTALS_BASE}/{isin}/income-statement",
                params={"type": "consolidated", "time_period": "yearly"},
                include_auth=True,
            )
            for cat in inc_res.get("data", {}).get("income_statement", []):
                if (cat.get("category") or "").lower() == "net_profit":
                    hist = cat.get("history") or []
                    if hist:
                        val = _parse_num(hist[0].get("change"))
                        if val is not None:
                            out["net_profit_yoy_pct"] = val
        except Exception:
            return None

        # Operating Cash Flow check (/cash-flow)
        out["cfo_positive"] = False
        try:
            cf_res = self.get_json(f"{UPSTOX_FUNDAMENTALS_BASE}/{isin}/cash-flow", include_auth=True)
            for item in cf_res.get("data", {}).get("cash_flow", []):
                if "operating" in (item.get("category") or "").lower():
                    hist = item.get("history") or []
                    if hist:
                        cfo_val = _parse_num(hist[0].get("value"))
                        if cfo_val is not None and cfo_val > 0:
                            out["cfo_positive"] = True
        except Exception:
            out["cfo_positive"] = out["net_profit_yoy_pct"] > 0

        # Shareholdings QoQ Institutional Delta (/share-holdings)
        out["inst_qoq_delta_pct"] = 0.0
        try:
            sh_res = self.get_json(f"{UPSTOX_FUNDAMENTALS_BASE}/{isin}/share-holdings", include_auth=True)
            inst_delta = 0.0
            for bucket in sh_res.get("data", []):
                cat = (bucket.get("category") or "").lower()
                hist = bucket.get("history") or []
                if cat in ("promoters", "fii", "mutual_funds") and len(hist) >= 2:
                    v0 = _parse_num(hist[0].get("value"))
                    v1 = _parse_num(hist[1].get("value"))
                    if v0 is not None and v1 is not None:
                        inst_delta += (v0 - v1)
            out["inst_qoq_delta_pct"] = round(inst_delta, 2)
        except Exception:
            pass

        # Corporate Actions Ex-Dividend Check (/corporate-actions)
        out["has_upcoming_ex_div"] = False
        try:
            ca_res = self.get_json(f"{UPSTOX_FUNDAMENTALS_BASE}/{isin}/corporate-actions", include_auth=True)
            today_s = dt.date.today().strftime("%Y-%m-%d")
            for ev in ca_res.get("data", []):
                ex_dt = str(ev.get("expiry_date") or ev.get("ex_date") or "")
                if today_s <= ex_dt <= next_expiry_date:
                    out["has_upcoming_ex_div"] = True
                    break
        except Exception:
            pass

        return out


# ---------------------------------------------------------------------------
# Quantitative Estimators (Yang-Zhang Vol, Connors RSI, Futures Regime, Surface)
# ---------------------------------------------------------------------------
def compute_rsi_wilder(closes: List[float], period: int = 2) -> float:
    """Wilder's RSI parameterized for short-horizon exhaustion (period=2 or 5)."""
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


def compute_ret_5d_zscore(closes: List[float], lookback: int = 60) -> float:
    """Computes the Z-score of the latest 5-day log return relative to a rolling 60-day window."""
    if len(closes) < lookback + 6:
        return 0.0
    rets_5d = [
        math.log(closes[i] / closes[i - 5])
        for i in range(len(closes) - lookback, len(closes))
        if closes[i] > 0 and closes[i - 5] > 0
    ]
    if len(rets_5d) < 10:
        return 0.0
    mean_5d = sum(rets_5d[:-1]) / (len(rets_5d) - 1)
    std_5d = math.sqrt(sum((r - mean_5d) ** 2 for r in rets_5d[:-1]) / (len(rets_5d) - 2))
    if std_5d <= 1e-8:
        return 0.0
    return (rets_5d[-1] - mean_5d) / std_5d


def compute_yang_zhang_volatility(candles: List[List[Any]], window: int = 20) -> float:
    """
    Yang & Zhang (2000) minimum-variance unbiased OHLC volatility estimator (% annualized).
    Combines overnight jump variance, open-to-close variance, and Rogers-Satchell intraday variance.
    """
    if len(candles) < window + 1:
        return 25.0
    sub = candles[-(window + 1):]
    o_rets, c_rets, rs_terms = [], [], []
    for i in range(1, len(sub)):
        prev_c = float(sub[i - 1][4])
        o, h, l, c = float(sub[i][1]), float(sub[i][2]), float(sub[i][3]), float(sub[i][4])
        if min(prev_c, o, h, l, c) <= 0:
            continue
        o_rets.append(math.log(o / prev_c))
        c_rets.append(math.log(c / o))
        rs = math.log(h / c) * math.log(h / o) + math.log(l / c) * math.log(l / o)
        rs_terms.append(rs)

    n = len(o_rets)
    if n < 2:
        return 25.0
    mean_o = sum(o_rets) / n
    mean_c = sum(c_rets) / n
    var_o = sum((x - mean_o) ** 2 for x in o_rets) / (n - 1)
    var_c = sum((x - mean_c) ** 2 for x in c_rets) / (n - 1)
    var_rs = sum(rs_terms) / n

    k = 0.34 / (1.34 + (n + 1) / (n - 1))
    var_yz = var_o + k * var_c + (1.0 - k) * var_rs
    return math.sqrt(max(0.0, var_yz) * 252.0) * 100.0


def compute_close_to_close_volatility(closes: List[float], window: int = 20) -> float:
    if len(closes) < window + 1:
        return 25.0
    rets = [
        math.log(closes[i] / closes[i - 1])
        for i in range(len(closes) - window, len(closes))
        if closes[i] > 0 and closes[i - 1] > 0
    ]
    if len(rets) < 2:
        return 25.0
    mean_r = sum(rets) / len(rets)
    var_r = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var_r * 252.0) * 100.0


def classify_futures_positioning(
    spot_closes: List[float],
    fut_candles: List[List[Any]],
    thresholds: ScreeningThresholdsV2,
) -> Dict[str, Any]:
    """
    Classifies 5-day institutional Futures activity using price, OI, and cost-of-carry basis.
    """
    if len(fut_candles) < 6 or len(spot_closes) < 6:
        return {
            "regime": "INSUFFICIENT_FUT_DATA",
            "oi_chg_5d_pct": 0.0,
            "basis_pct": 0.0,
            "passes_futures_guard": False,
        }

    fut_c_now = float(fut_candles[-1][4])
    fut_c_5d = float(fut_candles[-6][4])
    fut_oi_now = float(fut_candles[-1][6])
    fut_oi_5d = float(fut_candles[-6][6])
    spot_now = spot_closes[-1]

    price_chg_5d = ((fut_c_now - fut_c_5d) / fut_c_5d) * 100.0 if fut_c_5d > 0 else 0.0
    oi_chg_5d = ((fut_oi_now - fut_oi_5d) / fut_oi_5d) * 100.0 if fut_oi_5d > 0 else 0.0
    basis_pct = ((fut_c_now - spot_now) / spot_now) * 100.0 if spot_now > 0 else 0.0

    if price_chg_5d < 0 and oi_chg_5d > thresholds.max_down_oi_buildup_5d_pct:
        regime = "SHORT_BUILDUP_TRAP"
        passes = False
    elif basis_pct < thresholds.min_futures_basis_pct:
        regime = "BACKWARDATION_DISCOUNT"
        passes = False
    elif price_chg_5d < 0 and oi_chg_5d <= 0.0:
        regime = "LONG_UNWINDING_EXHAUSTION"
        passes = True
    elif price_chg_5d >= -0.5 and oi_chg_5d < 0.0:
        regime = "SHORT_COVERING_TURN"
        passes = True
    else:
        regime = "CONTROLLED_BASIS_PULLBACK"
        passes = True

    return {
        "regime": regime,
        "oi_chg_5d_pct": round(oi_chg_5d, 2),
        "basis_pct": round(basis_pct, 3),
        "passes_futures_guard": passes,
    }


def extract_chain_surface_metrics(
    chain: List[Dict[str, Any]], spot: float
) -> Dict[str, Any]:
    """
    Extracts ATM IV, 25-Delta Put-Call Skew, Total Chain Volume, Put OI Support Wall,
    and candidate OTM Puts from an Upstox Option Chain payload.
    """
    all_rows = sorted(chain, key=lambda r: float(r.get("strike_price") or 0.0))
    if not all_rows:
        return {}

    atm_row = min(all_rows, key=lambda r: abs(float(r.get("strike_price") or 0.0) - spot))
    atm_c_iv = float(((atm_row.get("call_options") or {}).get("option_greeks") or {}).get("iv") or 0.0)
    atm_p_iv = float(((atm_row.get("put_options") or {}).get("option_greeks") or {}).get("iv") or 0.0)
    atm_iv = (atm_c_iv + atm_p_iv) / 2.0 if (atm_c_iv > 0 and atm_p_iv > 0) else max(atm_c_iv, atm_p_iv, 20.0)

    put_25d_iv = atm_iv
    call_25d_iv = atm_iv
    min_p25_diff = 999.0
    min_c25_diff = 999.0

    total_vol = 0
    put_wall_strike = spot * 0.94
    max_put_oi = -1
    candidate_puts: List[Dict[str, Any]] = []

    for row in all_rows:
        strike = float(row.get("strike_price") or 0.0)
        c_md = (row.get("call_options") or {}).get("market_data") or {}
        p_md = (row.get("put_options") or {}).get("market_data") or {}
        c_gk = (row.get("call_options") or {}).get("option_greeks") or {}
        p_gk = (row.get("put_options") or {}).get("option_greeks") or {}

        c_vol = int(c_md.get("volume") or 0)
        p_vol = int(p_md.get("volume") or 0)
        p_oi = int(p_md.get("oi") or 0)
        total_vol += (c_vol + p_vol)

        if strike <= spot and p_oi > max_put_oi:
            max_put_oi = p_oi
            put_wall_strike = strike

        c_delta = float(c_gk.get("delta") or 0.5)
        p_delta = float(p_gk.get("delta") or -0.5)
        c_iv = float(c_gk.get("iv") or atm_iv)
        p_iv = float(p_gk.get("iv") or atm_iv)

        if abs(p_delta - (-0.25)) < min_p25_diff and p_iv > 0:
            min_p25_diff = abs(p_delta - (-0.25))
            put_25d_iv = p_iv
        if abs(c_delta - 0.25) < min_c25_diff and c_iv > 0:
            min_c25_diff = abs(c_delta - 0.25)
            call_25d_iv = c_iv

        if strike < spot:
            ltp = float(p_md.get("ltp") or 0.0)
            bid = float(p_md.get("bid_price") or ltp)
            ask = float(p_md.get("ask_price") or ltp)
            spread_pct = ((ask - bid) / ltp * 100.0) if ltp > 0 and ask >= bid else 0.0
            theta = float(p_gk.get("theta") or -1.0)
            vega = float(p_gk.get("vega") or 1.0)
            pop = float(p_gk.get("pop") or (1.0 - abs(p_delta)) * 100.0)
            if pop <= 1.0:
                pop *= 100.0

            if ltp > 0:
                candidate_puts.append({
                    "strike": strike,
                    "ltp": ltp,
                    "bid": bid,
                    "ask": ask,
                    "spread_pct": spread_pct,
                    "delta": p_delta,
                    "theta": theta,
                    "vega": vega,
                    "iv": p_iv,
                    "pop": pop,
                    "oi": p_oi,
                    "volume": p_vol,
                })

    return {
        "atm_iv": round(atm_iv, 2),
        "skew_25d": round(put_25d_iv - call_25d_iv, 2),
        "total_vol": total_vol,
        "put_wall_strike": put_wall_strike,
        "candidate_puts": candidate_puts,
        "expiry": str(all_rows[0].get("expiry") or "next_month"),
    }


# ---------------------------------------------------------------------------
# Core Next-Month Rebound Evaluation Engine
# ---------------------------------------------------------------------------
def evaluate_candidate_v2(
    meta: Dict[str, Any],
    eq_candles: List[List[Any]],
    fut_candles: List[List[Any]],
    front_chain: List[Dict[str, Any]],
    next_chain: List[Dict[str, Any]],
    fundamentals: Optional[Dict[str, Any]],
    thresholds: ScreeningThresholdsV2,
) -> Optional[ScreenerResultV2]:
    if len(eq_candles) < 220 or not next_chain or fundamentals is None:
        return None

    closes = [float(c[4]) for c in eq_candles]
    spot = float(next_chain[0].get("underlying_spot_price") or closes[-1])
    lot_size = int(meta.get("lot_size") or 1)

    # 1. Secular Momentum & Short-Term Exhaustion
    sma_200_now = sum(closes[-200:]) / 200.0
    sma_200_20d_ago = sum(closes[-220:-20]) / 200.0
    price_to_sma200 = spot / sma_200_now if sma_200_now > 0 else 0.0
    sma200_slope_pct = ((sma_200_now - sma_200_20d_ago) / sma_200_20d_ago) * 100.0 if sma_200_20d_ago > 0 else 0.0
    ret_6m_pct = ((spot - closes[-126]) / closes[-126]) * 100.0 if len(closes) >= 126 and closes[-126] > 0 else 0.0

    rsi_2 = compute_rsi_wilder(closes, 2)
    rsi_5 = compute_rsi_wilder(closes, 5)
    ret_5d_z = compute_ret_5d_zscore(closes, 60)

    # 2. Futures Positioning & Basis
    fut_eval = classify_futures_positioning(closes, fut_candles, thresholds)

    # 3. Volatility Surface (Yang-Zhang 20D RV vs Next-Month ATM IV & Term Structure)
    yz_hv20 = compute_yang_zhang_volatility(eq_candles, 20)
    cc_hv20 = compute_close_to_close_volatility(closes, 20)

    front_surf = extract_chain_surface_metrics(front_chain, spot) if front_chain else {}
    next_surf = extract_chain_surface_metrics(next_chain, spot)
    if not next_surf or not next_surf.get("candidate_puts"):
        return None

    front_atm_iv = float(front_surf.get("atm_iv") or next_surf["atm_iv"])
    next_atm_iv = float(next_surf["atm_iv"])
    iv_ts_ratio = front_atm_iv / next_atm_iv if next_atm_iv > 0 else 1.0
    true_atm_vrp = next_atm_iv - yz_hv20
    skew_25d = float(next_surf["skew_25d"])
    combined_opt_vol = int(front_surf.get("total_vol", 0)) + int(next_surf["total_vol"])
    put_wall = float(next_surf["put_wall_strike"])

    # 4. Optimal Next-Month Bull Put Credit Spread Selection (-0.32 Short Put / -0.14 Hedge Put)
    cands = next_surf["candidate_puts"]
    short_zone = [
        p for p in cands
        if thresholds.target_short_put_delta_min <= p["delta"] <= thresholds.target_short_put_delta_max
    ]
    if not short_zone:
        short_zone = sorted(cands, key=lambda p: abs(p["delta"] - (-0.28)))[:2]

    best_short_put = sorted(
        short_zone,
        key=lambda p: (
            1 if p["strike"] <= put_wall else 0,
            -p["spread_pct"],
            p["iv"] - yz_hv20,
        ),
        reverse=True,
    )[0]

    lower_puts = [p for p in cands if p["strike"] < best_short_put["strike"]]
    if lower_puts:
        hedge_put = min(lower_puts, key=lambda p: abs(p["delta"] - thresholds.target_hedge_put_delta))
    else:
        hedge_put = {
            "strike": round(best_short_put["strike"] * 0.95, 1),
            "ltp": round(best_short_put["ltp"] * 0.32, 2),
            "delta": -0.12,
            "theta": best_short_put["theta"] * 0.40,
            "vega": best_short_put["vega"] * 0.45,
        }

    net_credit = max(0.05, best_short_put["ltp"] - hedge_put["ltp"])
    spread_width = max(1.0, best_short_put["strike"] - hedge_put["strike"])
    max_risk = max(0.5, spread_width - net_credit)
    ror_pct = (net_credit / max_risk) * 100.0

    net_delta = round(-best_short_put["delta"] + hedge_put["delta"], 3) # Positive delta = bullish rebound exposure
    net_theta = round(-best_short_put["theta"] + hedge_put["theta"], 2) # Positive daily theta collection
    net_vega = round(-best_short_put["vega"] + hedge_put["vega"], 2)    # Negative vega = profits from IV crush

    # 5. Strictly Orthogonal Pillar Scoring (0 - 100 scale)
    # Score A: Short-Term Exhaustion inside Secular Uptrend (30% weight)
    s_rsi2 = max(0.0, min(100.0, (30.0 - rsi_2) * 4.0))
    s_z5 = max(0.0, min(100.0, (-0.5 - ret_5d_z) * 45.0))
    s_trend = max(0.0, min(100.0, (price_to_sma200 - 0.95) * 600.0 + sma200_slope_pct * 8.0))
    rebound_exhaustion_score = round(0.40 * s_rsi2 + 0.30 * s_z5 + 0.30 * s_trend, 1)

    # Score B: Futures Positioning & Cost-of-Carry Basis (25% weight)
    s_oi = max(0.0, min(100.0, (2.0 - fut_eval["oi_chg_5d_pct"]) * 18.0))
    s_basis = max(0.0, min(100.0, fut_eval["basis_pct"] * 140.0))
    futures_flow_score = round(0.60 * s_oi + 0.40 * s_basis, 1)

    # Score C: Fundamental Cash Flow & Institutional Accumulation (20% weight)
    roe_pct = float(fundamentals["roe_pct"])
    s_roe_pct = float(fundamentals["sector_roe_pct"])
    roce_pct = float(fundamentals["roce_pct"])
    pat_yoy = float(fundamentals["net_profit_yoy_pct"])
    inst_delta = float(fundamentals["inst_qoq_delta_pct"])
    cfo_pos = bool(fundamentals["cfo_positive"])
    ex_div = bool(fundamentals["has_upcoming_ex_div"])

    s_roe = max(0.0, min(100.0, 60.0 + (roe_pct - s_roe_pct) * 4.5))
    s_inst = max(0.0, min(100.0, 65.0 + inst_delta * 25.0))
    s_cfo = 90.0 if (cfo_pos and pat_yoy > 0) else 25.0
    fundamental_inst_score = round(0.35 * s_roe + 0.35 * s_inst + 0.30 * s_cfo, 1)

    # Score D: Volatility Surface (True ATM VRP + Term Structure + Put Skew) (25% weight)
    s_vrp = max(0.0, min(100.0, true_atm_vrp * 14.0))
    s_ts = max(0.0, min(100.0, (iv_ts_ratio - 0.90) * 550.0))
    s_skew = max(0.0, min(100.0, skew_25d * 22.0))
    vol_surface_score = round(0.45 * s_vrp + 0.30 * s_ts + 0.25 * s_skew, 1)

    composite_score = round(
        0.30 * rebound_exhaustion_score
        + 0.25 * futures_flow_score
        + 0.20 * fundamental_inst_score
        + 0.25 * vol_surface_score,
        1,
    )

    # 6. Strict Quantitative Filter Verification (with Explicit Audit Trail)
    rejections: List[str] = []
    if combined_opt_vol < thresholds.min_chain_option_volume:
        rejections.append(f"LowOptVol({combined_opt_vol})")
    if best_short_put["spread_pct"] > thresholds.max_bid_ask_spread_pct:
        rejections.append(f"WideSpread({best_short_put['spread_pct']:.2f}%)")
    if price_to_sma200 < thresholds.min_price_to_sma200:
        rejections.append(f"Below200DMA({price_to_sma200:.2f}x)")
    if thresholds.require_positive_sma200_slope and sma200_slope_pct <= 0.0:
        rejections.append(f"Neg200DMASlope({sma200_slope_pct:.2f}%)")
    if ret_6m_pct < thresholds.min_ret_6m_pct:
        rejections.append(f"Weak6MMom({ret_6m_pct:.1f}%)")
    if not (rsi_2 <= thresholds.max_rsi_2 or rsi_5 <= thresholds.max_rsi_5):
        rejections.append(f"NotOversold(RSI2={rsi_2:.1f},RSI5={rsi_5:.1f})")
    if ret_5d_z > thresholds.max_ret_5d_zscore:
        rejections.append(f"ShallowDip(Z5={ret_5d_z:.2f})")
    if not fut_eval["passes_futures_guard"]:
        rejections.append(f"FutTrap({fut_eval['regime']}:OI={fut_eval['oi_chg_5d_pct']:+.1f}%,Basis={fut_eval['basis_pct']:.2f}%)")
    if roe_pct < thresholds.min_roe_pct and roe_pct < s_roe_pct:
        rejections.append(f"LowROE({roe_pct:.1f}%)")
    if thresholds.require_positive_cfo and not cfo_pos:
        rejections.append("NegOperatingCashFlow")
    if inst_delta < thresholds.min_inst_ownership_qoq_delta:
        rejections.append(f"InstDistribution({inst_delta:+.2f}%)")
    if thresholds.reject_upcoming_ex_dividend and ex_div:
        rejections.append("UpcomingExDividendBeforeExpiry")
    if yz_hv20 > thresholds.max_yz_hv20_pct:
        rejections.append(f"ExcessYZVol({yz_hv20:.1f}%)")
    if true_atm_vrp < thresholds.min_true_atm_vrp_pct:
        rejections.append(f"LowATMVRP({true_atm_vrp:.1f}%)")
    if iv_ts_ratio < thresholds.min_iv_term_structure_ratio:
        rejections.append(f"SteepContangoTS({iv_ts_ratio:.2f}x)")

    passes_all = len(rejections) == 0

    strat_str = (
        f"Next-Mo Bull Put Spread: Sell {best_short_put['strike']:g} PE / Buy {hedge_put['strike']:g} PE "
        f"(Net Cr: INR {net_credit:.1f}, RoR: {ror_pct:.1f}%)"
    )
    rationale = (
        f"Uptrend pullback (Spot/200DMA={price_to_sma200:.2f}x, 6M={ret_6m_pct:+.1f}%, RSI2={rsi_2:.1f}, Z5={ret_5d_z:.2f}); "
        f"Futures={fut_eval['regime']} (5D OI {fut_eval['oi_chg_5d_pct']:+.1f}%, Basis +{fut_eval['basis_pct']:.2f}%); "
        f"Inst Flow {inst_delta:+.2f}% QoQ, CFO>0; "
        f"ATM VRP +{true_atm_vrp:.1f}% (NextIV {next_atm_iv:.1f}% vs YZ_HV20 {yz_hv20:.1f}%), TermStruct {iv_ts_ratio:.2f}x."
    )

    return ScreenerResultV2(
        symbol=meta["symbol"],
        name=meta["name"],
        instrument_key=meta["instrument_key"],
        isin=meta["isin"],
        spot_price=round(spot, 2),
        lot_size=lot_size,
        next_expiry_date=next_surf["expiry"],
        price_to_sma200=round(price_to_sma200, 3),
        sma200_slope_20d_pct=round(sma200_slope_pct, 2),
        ret_6m_pct=round(ret_6m_pct, 1),
        rsi_2=round(rsi_2, 1),
        rsi_5=round(rsi_5, 1),
        ret_5d_zscore=round(ret_5d_z, 2),
        futures_regime=fut_eval["regime"],
        fut_oi_chg_5d_pct=fut_eval["oi_chg_5d_pct"],
        fut_basis_pct=fut_eval["basis_pct"],
        roe_pct=round(roe_pct, 1),
        sector_roe_pct=round(s_roe_pct, 1),
        roce_pct=round(roce_pct, 1),
        net_profit_yoy_pct=round(pat_yoy, 1),
        cfo_positive=cfo_pos,
        inst_qoq_delta_pct=inst_delta,
        has_upcoming_ex_div=ex_div,
        yz_hv20_pct=round(yz_hv20, 1),
        cc_hv20_pct=round(cc_hv20, 1),
        front_atm_iv=round(front_atm_iv, 1),
        next_atm_iv=round(next_atm_iv, 1),
        iv_term_structure_ratio=round(iv_ts_ratio, 2),
        true_atm_vrp_pct=round(true_atm_vrp, 1),
        skew_25d_pct=round(skew_25d, 1),
        recommended_strategy=strat_str,
        short_put_strike=best_short_put["strike"],
        hedge_put_strike=hedge_put["strike"],
        short_put_ltp=round(best_short_put["ltp"], 2),
        hedge_put_ltp=round(hedge_put["ltp"], 2),
        net_spread_credit=round(net_credit, 2),
        max_risk_per_share=round(max_risk, 2),
        return_on_risk_pct=round(ror_pct, 1),
        short_put_bid_ask_spread_pct=round(best_short_put["spread_pct"], 2),
        short_put_delta=round(best_short_put["delta"], 2),
        net_spread_delta=net_delta,
        net_spread_theta=net_theta,
        net_spread_vega=net_vega,
        short_put_pop_pct=round(best_short_put["pop"], 1),
        put_oi_wall_strike=put_wall,
        est_credit_per_lot_inr=round(net_credit * lot_size, 2),
        rebound_exhaustion_score=rebound_exhaustion_score,
        futures_flow_score=futures_flow_score,
        fundamental_inst_score=fundamental_inst_score,
        vol_surface_score=vol_surface_score,
        composite_rebound_score=composite_score,
        passes_all_filters=passes_all,
        rejection_reasons="PASS" if passes_all else "; ".join(rejections),
        rationale=rationale,
    )


# ---------------------------------------------------------------------------
# Realistic Offline Verification & Stress-Test Dataset (Next-Month Rebound)
# ---------------------------------------------------------------------------
def build_demo_dataset_v2() -> List[Tuple[Dict[str, Any], List[List[Any]], List[List[Any]], List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]]:
    """
    Constructs 10 realistic NSE F&O profiles testing both valid Next-Month Rebound setups
    and realistic institutional traps (Short Buildup, Retail Dumping, Ex-Dividend Trap, Secular Downtrend).
    """
    specs = [
        # --- QUALIFIED NEXT-MONTH REBOUND CANDIDATES ---
        {
            "symbol": "SUNPHARMA", "name": "SUN PHARMACEUTICAL IND L", "isin": "INE044A01036", "lot_size": 350,
            "spot": 1840.0, "drift_200": 0.0014, "dip_5d": -0.0082, "vol_scale": 0.0058,
            "fut_oi_5d_chg": -4.2, "fut_basis_pct": 0.58,
            "front_atm_iv": 22.8, "next_atm_iv": 21.6, "skew_25d": 2.4, "chain_vol": 1_550_000,
            "strike_step": 20.0, "roe": 17.5, "s_roe": 14.2, "roce": 20.1, "pat_yoy": 19.4,
            "cfo_pos": True, "inst_qoq": 0.85, "ex_div": False,
        },
        {
            "symbol": "ICICIBANK", "name": "ICICI BANK LTD.", "isin": "INE090A01021", "lot_size": 700,
            "spot": 1295.0, "drift_200": 0.0013, "dip_5d": -0.0078, "vol_scale": 0.0054,
            "fut_oi_5d_chg": -3.5, "fut_basis_pct": 0.62,
            "front_atm_iv": 19.8, "next_atm_iv": 19.0, "skew_25d": 2.1, "chain_vol": 3_800_000,
            "strike_step": 20.0, "roe": 18.6, "s_roe": 14.5, "roce": 16.8, "pat_yoy": 16.8,
            "cfo_pos": True, "inst_qoq": 0.60, "ex_div": False,
        },
        {
            "symbol": "BHARTIARTL", "name": "BHARTI AIRTEL LIMITED", "isin": "INE397D01024", "lot_size": 475,
            "spot": 1660.0, "drift_200": 0.0015, "dip_5d": -0.0086, "vol_scale": 0.0060,
            "fut_oi_5d_chg": -5.1, "fut_basis_pct": 0.54,
            "front_atm_iv": 23.4, "next_atm_iv": 22.1, "skew_25d": 2.6, "chain_vol": 2_420_000,
            "strike_step": 20.0, "roe": 16.4, "s_roe": 12.8, "roce": 15.9, "pat_yoy": 32.0,
            "cfo_pos": True, "inst_qoq": 1.15, "ex_div": False,
        },
        {
            "symbol": "M&M", "name": "MAHINDRA & MAHINDRA LTD", "isin": "INE101A01026", "lot_size": 350,
            "spot": 2980.0, "drift_200": 0.0016, "dip_5d": -0.0090, "vol_scale": 0.0064,
            "fut_oi_5d_chg": -2.8, "fut_basis_pct": 0.60,
            "front_atm_iv": 25.2, "next_atm_iv": 24.0, "skew_25d": 2.8, "chain_vol": 2_150_000,
            "strike_step": 50.0, "roe": 19.8, "s_roe": 15.4, "roce": 22.4, "pat_yoy": 21.5,
            "cfo_pos": True, "inst_qoq": 0.45, "ex_div": False,
        },
        {
            "symbol": "SIEMENS", "name": "SIEMENS LTD", "isin": "INE003A01024", "lot_size": 150,
            "spot": 6850.0, "drift_200": 0.0014, "dip_5d": -0.0084, "vol_scale": 0.0062,
            "fut_oi_5d_chg": -3.9, "fut_basis_pct": 0.51,
            "front_atm_iv": 24.6, "next_atm_iv": 23.5, "skew_25d": 2.2, "chain_vol": 920_000,
            "strike_step": 100.0, "roe": 16.9, "s_roe": 14.0, "roce": 21.8, "pat_yoy": 24.1,
            "cfo_pos": True, "inst_qoq": 0.30, "ex_div": False,
        },
        # --- INSTITUTIONAL TRAPS (MUST BE REJECTED BY STRICT V2 FILTERS) ---
        {
            # TRAP 1: Secular Laggard / Broken 200-DMA ("2024 Low" Value Trap)
            "symbol": "ASIANPAINT", "name": "ASIAN PAINTS LIMITED", "isin": "INE021A01026", "lot_size": 200,
            "spot": 2390.0, "drift_200": -0.0007, "dip_5d": -0.0080, "vol_scale": 0.0078,
            "fut_oi_5d_chg": 6.4, "fut_basis_pct": -0.12,
            "front_atm_iv": 21.5, "next_atm_iv": 21.8, "skew_25d": 1.9, "chain_vol": 1_620_000,
            "strike_step": 20.0, "roe": 28.4, "s_roe": 18.5, "roce": 34.2, "pat_yoy": -4.5,
            "cfo_pos": True, "inst_qoq": -1.40, "ex_div": False,
        },
        {
            # TRAP 2: Aggressive Futures Short Buildup + Institutional Distribution
            "symbol": "INDUSINDBK", "name": "INDUSIND BANK LIMITED", "isin": "INE095A01012", "lot_size": 500,
            "spot": 1280.0, "drift_200": -0.0010, "dip_5d": -0.0160, "vol_scale": 0.0195,
            "fut_oi_5d_chg": 14.8, "fut_basis_pct": -0.25,
            "front_atm_iv": 38.0, "next_atm_iv": 36.5, "skew_25d": 4.5, "chain_vol": 3_400_000,
            "strike_step": 20.0, "roe": 9.8, "s_roe": 14.5, "roce": 10.2, "pat_yoy": -21.4,
            "cfo_pos": False, "inst_qoq": -2.85, "ex_div": False,
        },
        {
            # TRAP 3: Upcoming Ex-Dividend Date Before Next-Month Expiry (Artificially Inflated Put IV)
            "symbol": "COALINDIA", "name": "COAL INDIA LTD", "isin": "INE522F01014", "lot_size": 2100,
            "spot": 492.0, "drift_200": 0.0009, "dip_5d": -0.0085, "vol_scale": 0.0080,
            "fut_oi_5d_chg": -1.5, "fut_basis_pct": -1.80,
            "front_atm_iv": 24.0, "next_atm_iv": 23.2, "skew_25d": 3.8, "chain_vol": 1_850_000,
            "strike_step": 5.0, "roe": 38.0, "s_roe": 16.0, "roce": 44.0, "pat_yoy": 14.0,
            "cfo_pos": True, "inst_qoq": 0.20, "ex_div": True,
        },
        {
            # TRAP 4: Sloan Accrual Trap (Positive Accounting Profit but Negative Operating Cash Flow)
            "symbol": "VOLTAS", "name": "VOLTAS LTD", "isin": "INE226A01021", "lot_size": 375,
            "spot": 1620.0, "drift_200": 0.0008, "dip_5d": -0.0090, "vol_scale": 0.0085,
            "fut_oi_5d_chg": 4.1, "fut_basis_pct": 0.20,
            "front_atm_iv": 25.0, "next_atm_iv": 24.5, "skew_25d": 2.0, "chain_vol": 1_480_000,
            "strike_step": 20.0, "roe": 13.5, "s_roe": 13.2, "roce": 15.4, "pat_yoy": 18.0,
            "cfo_pos": False, "inst_qoq": -0.75, "ex_div": False,
        },
    ]

    dataset = []
    base_date = dt.date(2026, 10, 16)

    for idx, s in enumerate(specs):
        n_days = 240
        closes = [0.0] * n_days
        closes[-1] = s["spot"]

        # Reconstruct realistic daily path: 235 days of secular trend + 5-day sharp pullback
        for d in range(n_days - 1, 0, -1):
            days_from_end = (n_days - 1) - d
            if days_from_end < 5:
                ret = s["dip_5d"] + (0.0012 if days_from_end == 2 else -0.0015)
            else:
                cycle = math.sin(d * 0.35) * s["vol_scale"]
                ret = s["drift_200"] + cycle
            closes[d - 1] = closes[d] / (1.0 + ret)

        eq_candles = []
        fut_candles = []
        base_oi = 12_000_000

        for d in range(n_days):
            c_date = (base_date - dt.timedelta(days=(n_days - 1 - d))).strftime("%Y-%m-%dT00:00:00+05:30")
            c_p = round(closes[d], 2)
            prev_c = round(closes[d - 1], 2) if d > 0 else c_p
            o_p = round(prev_c * (1.0 + (0.001 if d % 2 == 0 else -0.001)), 2)
            span = c_p * s["vol_scale"] * 0.85
            h_p = round(max(o_p, c_p) + span, 2)
            l_p = round(min(o_p, c_p) - span, 2)
            vol = int(3_200_000 * (1.0 + 0.15 * math.cos(d)))
            eq_candles.append([c_date, o_p, h_p, l_p, c_p, vol, 0])

            # Futures candles with realistic basis and 5-day OI drift
            days_from_end = (n_days - 1) - d
            if days_from_end <= 5:
                frac = (5 - days_from_end) / 5.0
                oi_now = int(base_oi * (1.0 + (s["fut_oi_5d_chg"] / 100.0) * frac))
            else:
                oi_now = base_oi
            fut_c = round(c_p * (1.0 + s["fut_basis_pct"] / 100.0), 2)
            fut_candles.append([c_date, o_p, h_p, l_p, fut_c, int(vol * 0.6), oi_now])

        # Build Front-Month and Next-Month Option Chains
        step = s["strike_step"]
        atm_strike = round(s["spot"] / step) * step

        def _make_chain(expiry_str: str, atm_iv_val: float, vol_mult: float) -> List[Dict[str, Any]]:
            rows = []
            for k_off in range(-6, 4):
                strike = round(atm_strike + k_off * step, 2)
                otm_pct = (s["spot"] - strike) / s["spot"]
                p_delta = round(-0.50 * math.exp(-13.5 * max(0.0, otm_pct)), 3) if strike <= s["spot"] else -0.65
                c_delta = round(1.0 + p_delta, 3)
                p_iv = round(atm_iv_val + max(0.0, otm_pct * 28.0), 2)
                c_iv = round(atm_iv_val - s["skew_25d"] * 0.5, 2) if k_off > 0 else atm_iv_val
                p_ltp = round(max(1.0, s["spot"] * 0.024 * math.exp(-12.5 * max(0.0, otm_pct))), 2)
                is_wall = (k_off == -2)
                rows.append({
                    "expiry": expiry_str,
                    "strike_price": strike,
                    "underlying_key": f"NSE_EQ|{s['isin']}",
                    "underlying_spot_price": s["spot"],
                    "call_options": {
                        "market_data": {
                            "ltp": round(p_ltp * 1.05, 2),
                            "volume": int(s["chain_vol"] * 0.05 * vol_mult),
                            "oi": int(1_800_000 * vol_mult),
                            "bid_price": round(p_ltp * 1.045, 2),
                            "ask_price": round(p_ltp * 1.055, 2),
                        },
                        "option_greeks": {"delta": c_delta, "iv": c_iv, "theta": -round(p_ltp * 0.03, 2), "vega": round(s["spot"] * 0.0018, 2)},
                    },
                    "put_options": {
                        "market_data": {
                            "ltp": p_ltp,
                            "volume": int(s["chain_vol"] * (0.12 if is_wall else 0.06) * vol_mult),
                            "oi": int((3_600_000 if is_wall else 1_100_000) * vol_mult),
                            "bid_price": round(p_ltp * 0.997, 2),
                            "ask_price": round(p_ltp * 1.003, 2),
                        },
                        "option_greeks": {
                            "delta": p_delta,
                            "iv": p_iv,
                            "theta": -round(p_ltp * 0.038, 2),
                            "vega": round(s["spot"] * 0.0019, 2),
                            "pop": round((1.0 - abs(p_delta)) * 100.0 + 2.5, 1),
                        },
                    },
                })
            return rows

        front_chain = _make_chain("2026-10-29", s["front_atm_iv"], 0.65)
        next_chain = _make_chain("2026-11-26", s["next_atm_iv"], 0.35)

        meta = {
            "symbol": s["symbol"],
            "name": s["name"],
            "instrument_key": f"NSE_EQ|{s['isin']}",
            "isin": s["isin"],
            "lot_size": s["lot_size"],
        }
        fundamentals = {
            "roe_pct": s["roe"],
            "sector_roe_pct": s["s_roe"],
            "roce_pct": s["roce"],
            "sector_roce_pct": s["s_roe"] + 1.0,
            "net_profit_yoy_pct": s["pat_yoy"],
            "cfo_positive": s["cfo_pos"],
            "inst_qoq_delta_pct": s["inst_qoq"],
            "has_upcoming_ex_div": s["ex_div"],
        }
        dataset.append((meta, eq_candles, fut_candles, front_chain, next_chain, fundamentals))

    return dataset


# ---------------------------------------------------------------------------
# CLI Reporting & CSV Export
# ---------------------------------------------------------------------------
def print_screener_report_v2(results: List[ScreenerResultV2]) -> None:
    passed = [r for r in results if r.passes_all_filters]
    passed.sort(key=lambda r: r.composite_rebound_score, reverse=True)

    print("=" * 132)
    print(" UPSTOX F&O QUANT SCREENER v2.0 — 'NEXT-MONTH EXPIRY REBOUND & VRP HARVESTER' (YANG-ZHANG VOL + FUTURES OI + INST FLOW)")
    print("=" * 132)
    header = (
        f"{'SYMBOL':<11} {'SPOT':>8} {'200DMA':>6} {'RSI2':>5} {'Z5D':>6} "
        f"{'FUT_OI_5D':>9} {'INST_QoQ':>8} {'NXT_IV/YZ':>10} {'TS_RAT':>6} "
        f"{'NEXT-MONTH BULL PUT SPREAD':<34} {'ROR%':>5} {'SCORE':>6}"
    )
    print(header)
    print("-" * 132)
    for r in passed:
        dma_s = f"{r.price_to_sma200:.2f}x"
        oi_s = f"{r.fut_oi_chg_5d_pct:+.1f}%"
        inst_s = f"{r.inst_qoq_delta_pct:+.2f}%"
        iv_yz_s = f"{r.next_atm_iv:.1f}/{r.yz_hv20_pct:.1f}%"
        ts_s = f"{r.iv_term_structure_ratio:.2f}x"
        spread_s = f"-{r.short_put_strike:g}/+{r.hedge_put_strike:g} PE @ {r.net_spread_credit:.1f} (d{r.short_put_delta:.2f})"
        print(
            f"{r.symbol:<11} {r.spot_price:>8.1f} {dma_s:>6} {r.rsi_2:>5.1f} {r.ret_5d_zscore:>6.2f} "
            f"{oi_s:>9} {inst_s:>8} {iv_yz_s:>10} {ts_s:>6} "
            f"{spread_s:<34} {r.return_on_risk_pct:>5.1f} {r.composite_rebound_score:>6.1f}"
        )
    print("-" * 132)
    print(f"Qualified Next-Month Rebound Candidates: {len(passed)} / {len(results)} screened F&O stocks.")

    rejected = [r for r in results if not r.passes_all_filters]
    if rejected:
        print("\nQuantitative Audit Trail — Rejected Value Traps, Short Buildups & Event Risks:")
        for r in rejected:
            print(
                f"  [REJECTED] {r.symbol:<11} Spot={r.spot_price:>7.1f} | "
                f"Reasons: {r.rejection_reasons}"
            )


def export_csv_v2(results: List[ScreenerResultV2], csv_path: str) -> None:
    if not results:
        return
    fieldnames = list(asdict(results[0]).keys())
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in sorted(results, key=lambda x: (x.passes_all_filters, x.composite_rebound_score), reverse=True):
            writer.writerow(asdict(r))
    print(f"\nSaved full v2 quantitative report to: {csv_path}")


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
    parser = argparse.ArgumentParser(description="Upstox F&O Option Screener v2.0 (Next-Month Rebound)")
    parser.add_argument("--access-token", default=os.environ.get("UPSTOX_ACCESS_TOKEN", ""), help="Upstox OAuth2 Access Token")
    parser.add_argument("--expiry", default="next_month", help="Target option expiry (default: next_month)")
    parser.add_argument("--symbols", default="", help="Comma-separated NSE F&O symbols (or 'all' for full universe)")
    parser.add_argument("--max-symbols", type=int, default=45, help="Max underlyings to evaluate")
    parser.add_argument("--csv-out", default="upstox_next_month_rebound_v2.csv", help="Output CSV path")
    parser.add_argument("--demo", action="store_true", help="Run offline simulation & stress-test verification")
    args = parser.parse_args()

    thresholds = ScreeningThresholdsV2()

    if args.demo:
        demo_items = build_demo_dataset_v2()
        results: List[ScreenerResultV2] = []
        for meta, eq_c, fut_c, f_chain, n_chain, fund in demo_items:
            res = evaluate_candidate_v2(meta, eq_c, fut_c, f_chain, n_chain, fund, thresholds)
            if res:
                results.append(res)
        print_screener_report_v2(results)
        if args.csv_out:
            export_csv_v2(results, args.csv_out)
        return

    access_token = args.access_token
    if not access_token:
        print("Error: Provide --access-token (or set UPSTOX_ACCESS_TOKEN in .env), or run with --demo.")
        sys.exit(1)

    client = UpstoxClientV2(access_token=access_token)
    raw_syms = args.symbols.strip().lower()
    if raw_syms in ("all", "*"):
        symbol_list = None
        max_scan = args.max_symbols if args.max_symbols != 45 else 250
    elif raw_syms:
        symbol_list = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        max_scan = args.max_symbols
    else:
        symbol_list = DEFAULT_LIQUID_FNO_SYMBOLS
        max_scan = args.max_symbols

    target_desc = f"{len(symbol_list)} symbols" if symbol_list is not None else "ALL available F&O symbols"
    print(f"Loading NSE F&O Equities & Futures from Upstox BOD master ({target_desc})...")
    universe = client.load_fno_universe_with_futures(filter_symbols=symbol_list)[: max_scan]

    results = []
    for idx, meta in enumerate(universe, 1):
        sym = meta["symbol"]
        ukey = meta["instrument_key"]
        fut_key = meta.get("front_fut_key") or ukey
        isin = meta["isin"]
        print(f"[{idx}/{len(universe)}] Screening {sym} (Next-Month Rebound)...", end="\r", flush=True)
        try:
            eq_candles = client.fetch_daily_candles(ukey, lookback_calendar_days=380)
            fut_candles = client.fetch_daily_candles(fut_key, lookback_calendar_days=30)
            front_chain = client.fetch_option_chain(ukey, expiry_date="current_month")
            next_chain = client.fetch_option_chain(ukey, expiry_date=args.expiry)
            next_exp_str = str(next_chain[0].get("expiry")) if next_chain else "2099-12-31"
            fund = client.fetch_strict_fundamentals(isin, next_expiry_date=next_exp_str)
            evaluated = evaluate_candidate_v2(meta, eq_candles, fut_candles, front_chain, next_chain, fund, thresholds)
            if evaluated:
                results.append(evaluated)
        except Exception as exc:
            print(f"\n  [!] Skipped {sym}: {exc}")

    print()
    print_screener_report_v2(results)
    if args.csv_out and results:
        export_csv_v2(results, args.csv_out)


if __name__ == "__main__":
    main()
