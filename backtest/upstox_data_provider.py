"""
Upstox API Data Provider and Historical Cache
=============================================
Fetches and caches daily OHLCV candles from the Upstox Developer API (v3)
for the liquid Top 50 NSE F&O universe.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

UPSTOX_HISTORICAL_V3_BASE = "https://api.upstox.com/v3/historical-candle"

# 50 Liquid F&O Underlyings with NSE_EQ Instrument Keys, Lot Sizes, and Strike Steps
TOP_50_UNIVERSE: Dict[str, Dict[str, Any]] = {
    "MARUTI":     {"key": "NSE_EQ|INE585B01010", "lot": 50,   "step": 100.0, "roe": 16.8, "secRoe": 17.5, "pat": 13.2},
    "BAJAJ-AUTO": {"key": "NSE_EQ|INE917I01010", "lot": 75,   "step": 100.0, "roe": 27.8, "secRoe": 17.5, "pat": 19.4},
    "GODREJCP":   {"key": "NSE_EQ|INE102D01028", "lot": 500,  "step": 10.0,  "roe": 17.4, "secRoe": 24.0, "pat": 4.8},
    "INFY":       {"key": "NSE_EQ|INE009A01021", "lot": 400,  "step": 20.0,  "roe": 31.8, "secRoe": 24.5, "pat": 8.7},
    "KOTAKBANK":  {"key": "NSE_EQ|INE237A01036", "lot": 2000, "step": 5.0,   "roe": 15.4, "secRoe": 14.2, "pat": 12.1},
    "DIVISLAB":   {"key": "NSE_EQ|INE361B01024", "lot": 100,  "step": 50.0,  "roe": 16.4, "secRoe": 15.2, "pat": 21.5},
    "HEROMOTOCO": {"key": "NSE_EQ|INE158A01026", "lot": 150,  "step": 50.0,  "roe": 24.1, "secRoe": 17.5, "pat": 16.8},
    "TRENT":      {"key": "NSE_EQ|INE849A01020", "lot": 100,  "step": 100.0, "roe": 32.5, "secRoe": 18.0, "pat": 41.0},
    "TECHM":      {"key": "NSE_EQ|INE669C01036", "lot": 600,  "step": 20.0,  "roe": 15.8, "secRoe": 24.5, "pat": 18.2},
    "BRITANNIA":  {"key": "NSE_EQ|INE216A01030", "lot": 125,  "step": 50.0,  "roe": 54.2, "secRoe": 24.0, "pat": 7.5},
    "SBIN":       {"key": "NSE_EQ|INE062A01020", "lot": 750,  "step": 10.0,  "roe": 17.8, "secRoe": 14.2, "pat": 20.4},
    "TATASTEEL":  {"key": "NSE_EQ|INE081A01020", "lot": 2750, "step": 2.5,   "roe": 9.4,  "secRoe": 12.4, "pat": 4.2},
    "WIPRO":      {"key": "NSE_EQ|INE075A01022", "lot": 3000, "step": 2.5,   "roe": 15.6, "secRoe": 24.5, "pat": 5.4},
    "CHOLAFIN":   {"key": "NSE_EQ|INE121A01024", "lot": 625,  "step": 20.0,  "roe": 20.6, "secRoe": 15.8, "pat": 23.7},
    "VOLTAS":     {"key": "NSE_EQ|INE226A01021", "lot": 375,  "step": 20.0,  "roe": 9.8,  "secRoe": 15.0, "pat": 11.2},
    "GRASIM":     {"key": "NSE_EQ|INE047A01021", "lot": 250,  "step": 40.0,  "roe": 13.8, "secRoe": 11.9, "pat": 11.5},
    "ONGC":       {"key": "NSE_EQ|INE213A01029", "lot": 2250, "step": 2.5,   "roe": 15.1, "secRoe": 12.0, "pat": 6.1},
    "ASIANPAINT": {"key": "NSE_EQ|INE021A01026", "lot": 250,  "step": 20.0,  "roe": 26.4, "secRoe": 18.5, "pat": 6.4},
    "NTPC":       {"key": "NSE_EQ|INE733E01010", "lot": 1500, "step": 5.0,   "roe": 14.2, "secRoe": 12.8, "pat": 11.4},
    "ABB":        {"key": "NSE_EQ|INE117A01022", "lot": 125,  "step": 100.0, "roe": 22.8, "secRoe": 14.5, "pat": 28.5},
    "NESTLEIND":  {"key": "NSE_EQ|INE239A01024", "lot": 500,  "step": 20.0,  "roe": 84.0, "secRoe": 24.0, "pat": 9.8},
    "APOLLOHOSP": {"key": "NSE_EQ|INE437A01024", "lot": 125,  "step": 100.0, "roe": 18.2, "secRoe": 14.8, "pat": 25.4},
    "JSWSTEEL":   {"key": "NSE_EQ|INE019A01038", "lot": 675,  "step": 20.0,  "roe": 14.1, "secRoe": 12.4, "pat": 13.8},
    "COALINDIA":  {"key": "NSE_EQ|INE522F01014", "lot": 1350, "step": 5.0,   "roe": 42.5, "secRoe": 16.0, "pat": 12.9},
    "BAJFINANCE": {"key": "NSE_EQ|INE296A01032", "lot": 750,  "step": 10.0,  "roe": 22.1, "secRoe": 15.8, "pat": 22.4},
    "HAL":        {"key": "NSE_EQ|INE066F01020", "lot": 150,  "step": 50.0,  "roe": 28.9, "secRoe": 16.0, "pat": 26.4},
    "RELIANCE":   {"key": "NSE_EQ|INE002A01018", "lot": 500,  "step": 20.0,  "roe": 11.2, "secRoe": 12.0, "pat": 7.9},
    "TCS":        {"key": "NSE_EQ|INE467B01029", "lot": 225,  "step": 20.0,  "roe": 51.4, "secRoe": 24.5, "pat": 9.4},
    "HDFCBANK":   {"key": "NSE_EQ|INE040A01034", "lot": 650,  "step": 10.0,  "roe": 16.1, "secRoe": 14.2, "pat": 15.4},
    "POWERGRID":  {"key": "NSE_EQ|INE752E01010", "lot": 1900, "step": 5.0,   "roe": 18.6, "secRoe": 12.8, "pat": 8.9},
    "DLF":        {"key": "NSE_EQ|INE271C01023", "lot": 825,  "step": 10.0,  "roe": 11.8, "secRoe": 10.2, "pat": 24.0},
    "PIDILITIND": {"key": "NSE_EQ|INE318A01026", "lot": 250,  "step": 40.0,  "roe": 23.6, "secRoe": 16.5, "pat": 17.9},
    "DRREDDY":    {"key": "NSE_EQ|INE089A01031", "lot": 625,  "step": 20.0,  "roe": 19.4, "secRoe": 15.2, "pat": 14.2},
    "INDIGO":     {"key": "NSE_EQ|INE646L01027", "lot": 150,  "step": 50.0,  "roe": 44.0, "secRoe": 14.0, "pat": 22.8},
    "BHARTIARTL": {"key": "NSE_EQ|INE397D01024", "lot": 475,  "step": 20.0,  "roe": 16.9, "secRoe": 11.0, "pat": 34.2},
    "CIPLA":      {"key": "NSE_EQ|INE059A01026", "lot": 425,  "step": 20.0,  "roe": 16.8, "secRoe": 15.2, "pat": 16.4},
    "TITAN":      {"key": "NSE_EQ|INE280A01028", "lot": 175,  "step": 50.0,  "roe": 31.2, "secRoe": 18.0, "pat": 15.8},
    "AXISBANK":   {"key": "NSE_EQ|INE238A01034", "lot": 625,  "step": 20.0,  "roe": 17.2, "secRoe": 14.2, "pat": 14.6},
    "SUNPHARMA":  {"key": "NSE_EQ|INE044A01036", "lot": 350,  "step": 20.0,  "roe": 17.6, "secRoe": 15.2, "pat": 18.9},
    "HINDALCO":   {"key": "NSE_EQ|INE038A01020", "lot": 700,  "step": 10.0,  "roe": 14.9, "secRoe": 12.4, "pat": 24.6},
    "BEL":        {"key": "NSE_EQ|INE263A01024", "lot": 2850, "step": 5.0,   "roe": 26.4, "secRoe": 16.0, "pat": 29.1},
    "HCLTECH":    {"key": "NSE_EQ|INE860A01027", "lot": 400,  "step": 20.0,  "roe": 25.2, "secRoe": 24.5, "pat": 11.8},
    "HAVELLS":    {"key": "NSE_EQ|INE176B01034", "lot": 500,  "step": 20.0,  "roe": 18.9, "secRoe": 15.0, "pat": 14.1},
    "ITC":        {"key": "NSE_EQ|INE154A01025", "lot": 1725, "step": 5.0,   "roe": 28.4, "secRoe": 24.0, "pat": 6.8},
    "M&M":        {"key": "NSE_EQ|INE101A01026", "lot": 200,  "step": 50.0,  "roe": 19.8, "secRoe": 17.5, "pat": 21.6},
    "ICICIBANK":  {"key": "NSE_EQ|INE090A01021", "lot": 700,  "step": 20.0,  "roe": 18.4, "secRoe": 14.2, "pat": 17.2},
    "LT":         {"key": "NSE_EQ|INE018A01030", "lot": 175,  "step": 50.0,  "roe": 16.5, "secRoe": 13.8, "pat": 15.1},
    "ULTRACEMCO": {"key": "NSE_EQ|INE481G01011", "lot": 50,   "step": 100.0, "roe": 13.5, "secRoe": 11.9, "pat": 14.8},
    "SIEMENS":    {"key": "NSE_EQ|INE003A01024", "lot": 175,  "step": 50.0,  "roe": 17.9, "secRoe": 14.5, "pat": 21.0},
    "DABUR":      {"key": "NSE_EQ|INE016A01026", "lot": 1250, "step": 5.0,   "roe": 19.2, "secRoe": 24.0, "pat": 5.2},
}


def get_upstox_token() -> str:
    """Discovers Upstox API bearer token from .env or environment."""
    env_token = os.environ.get("UPSTOX_ACCESS_TOKEN", "").strip()
    if env_token:
        return env_token

    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("UPSTOX_ACCESS_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


class UpstoxDataProvider:
    """Manages fetching, caching, and chronological ordering of Upstox daily candles."""

    def __init__(self, cache_dir: Optional[str] = None):
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.cache_dir = cache_dir or os.path.join(base_dir, ".data_cache")
        os.makedirs(self.cache_dir, exist_ok=True)
        self.token = get_upstox_token()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        self._in_memory_cache: Dict[str, List[Dict[str, Any]]] = {}

    def fetch_candle_data_from_api(self, instrument_key: str, from_date: str = "2020-01-01", to_date: Optional[str] = None) -> List[List[Any]]:
        """Calls Upstox v3 historical candle API and returns raw candle array."""
        target_to_date = to_date or dt.date.today().strftime("%Y-%m-%d")
        enc_key = urllib.parse.quote(instrument_key, safe="")
        url = f"{UPSTOX_HISTORICAL_V3_BASE}/{enc_key}/days/1/{target_to_date}/{from_date}"
        req = urllib.request.Request(url, headers=self.headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            candles = data.get("data", {}).get("candles", [])
            return candles

    def load_or_fetch_symbol(
        self,
        sym: str,
        instrument_key: Optional[str] = None,
        force_refresh: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Loads candles for `sym` from local cache or fetches from Upstox API.
        If force_refresh is True, attempts to fetch fresh candles from Upstox API first.
        If that fails, falls back to disk cache if available.
        Returns chronologically sorted list of dicts:
        [{date: '2020-01-01', open: 334.7, high: 335.95, low: 332.15, close: 334.45, volume: 17379320}]
        """
        if sym in self._in_memory_cache and not force_refresh:
            return self._in_memory_cache[sym]

        cache_file = os.path.join(self.cache_dir, f"{sym}.json")
        if os.path.exists(cache_file) and not force_refresh:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    candles = json.load(f)
                    self._in_memory_cache[sym] = candles
                    return candles
            except Exception:
                pass

        # Resolve instrument key
        key = instrument_key
        if not key:
            info = TOP_50_UNIVERSE.get(sym)
            if info:
                key = info.get("key")
            else:
                key = f"NSE_EQ|{sym}"

        # Fetch from Upstox API if token is present
        if self.token:
            try:
                raw_candles = self.fetch_candle_data_from_api(key)
                if raw_candles:
                    # Upstox returns candles in reverse chronological order (newest first).
                    # We reverse them to be strictly chronological (oldest first).
                    reversed_candles = list(reversed(raw_candles))

                    formatted: List[Dict[str, Any]] = []
                    for c in reversed_candles:
                        date_str = c[0][:10]
                        formatted.append({
                            "date": date_str,
                            "open": float(c[1]),
                            "high": float(c[2]),
                            "low": float(c[3]),
                            "close": float(c[4]),
                            "volume": int(c[5]),
                            "oi": int(c[6]) if len(c) > 6 else 0,
                        })

                    # Save to disk cache
                    try:
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(formatted, f)
                    except Exception:
                        pass

                    self._in_memory_cache[sym] = formatted
                    return formatted
            except Exception as e:
                # If fetch failed but cache exists, fallback to cache
                if os.path.exists(cache_file):
                    try:
                        with open(cache_file, "r", encoding="utf-8") as f:
                            candles = json.load(f)
                            self._in_memory_cache[sym] = candles
                            return candles
                    except Exception:
                        pass
                raise ValueError(f"Failed to fetch candles for '{sym}' ({key}): {e}") from e

        # If no token, check disk cache fallback
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    candles = json.load(f)
                    self._in_memory_cache[sym] = candles
                    return candles
            except Exception:
                pass

        raise ValueError(f"No candle data available for symbol '{sym}' (no token and not found in cache)")

    def preload_all_universe(self, symbols: Optional[List[str]] = None, verbose: bool = True) -> Dict[str, int]:
        """Preloads all symbols in the universe and returns count of loaded candles."""
        targets = symbols or list(TOP_50_UNIVERSE.keys())
        results = {}
        if verbose:
            print(f"Preloading historical candles from Upstox API for {len(targets)} symbols...")
        for idx, sym in enumerate(targets, 1):
            try:
                t0 = time.time()
                data = self.load_or_fetch_symbol(sym)
                dt_sec = time.time() - t0
                results[sym] = len(data)
                if verbose:
                    cached_flag = "CACHE" if dt_sec < 0.05 else "UPSTOX API"
                    print(f"  [{idx:02d}/{len(targets):02d}] {sym:<12}: {len(data)} candles ({cached_flag}, {dt_sec:.2f}s)")
            except Exception as e:
                print(f"  [{idx:02d}/{len(targets):02d}] {sym:<12}: FAILED ({e})")
                results[sym] = 0
        return results
