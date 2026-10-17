"""
Historical Strategy Screener Engine
===================================
Replays the 5-Pillar Regime Guard and Worthless Expiry Harvester
across historical monthly expiry cycles from 2021 through 2026.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backtest.indicators import (
    black_scholes_put_price,
    compute_200_dma,
    compute_rsi14,
    compute_worthless_score,
    compute_yang_zhang_vol,
    compute_z5d,
    find_2020_base_floor,
    snap_to_listed_strike,
)
from backtest.upstox_data_provider import TOP_50_UNIVERSE, UpstoxDataProvider


@dataclass
class CycleCandidate:
    sym: str
    lot: int
    step: float
    entry_date: str
    expiry_date: str
    dte_days: int
    spot_entry: float
    short_strike: float
    otm_cushion_pct: float
    put_premium: float
    lot_credit: float
    est_span_margin: float
    rom_pct: float
    pop_pct: float
    iv_pct: float
    yz_vol: float
    vrp: float
    dma200_ratio: float
    rsi14: float
    z5d: float
    dist_base_2020: float
    worthless_score: float
    passed: bool
    rejection_reasons: List[str]


@dataclass
class ExpiryCycle:
    year: int
    month: int
    cycle_label: str
    entry_date: str
    expiry_date: str
    dte_days: int


def generate_nse_monthly_cycles(
    trading_dates: List[str], start_year: int = 2021, end_year: int = 2026, end_month: int = 10
) -> List[ExpiryCycle]:
    """
    Generates exact historical NSE monthly expiry cycles based on authentic trading dates.
    For each month, finds the last Thursday (or last trading day on/before Thursday).
    Entry date is the next trading day after previous month's expiry.
    """
    date_set = set(trading_dates)
    dt_objs = [dt.datetime.strptime(d, "%Y-%m-%d").date() for d in trading_dates]
    dt_set = set(dt_objs)

    monthly_expiries: List[Tuple[int, int, dt.date]] = []

    for yr in range(2020, end_year + 1):
        for m in range(1, 13):
            if yr == end_year and m > end_month:
                break
            # Find last Thursday of month m
            next_m_yr = yr + (m // 12)
            next_m = (m % 12) + 1
            last_day = dt.date(next_m_yr, next_m, 1) - dt.timedelta(days=1)
            offset = (last_day.weekday() - 3) % 7  # 3 is Thursday
            thursday = last_day - dt.timedelta(days=offset)

            # Check if Thursday is a trading day; if holiday, roll back to Wednesday/Tuesday
            curr_target = thursday
            while curr_target not in dt_set and curr_target > last_day - dt.timedelta(days=7):
                curr_target -= dt.timedelta(days=1)

            if curr_target in dt_set:
                monthly_expiries.append((yr, m, curr_target))

    # Build cycles starting from start_year
    cycles: List[ExpiryCycle] = []
    for i in range(1, len(monthly_expiries)):
        prev_yr, prev_m, prev_exp = monthly_expiries[i - 1]
        curr_yr, curr_m, curr_exp = monthly_expiries[i]

        if curr_yr < start_year:
            continue

        # Entry date is first trading day after prev_exp
        entry_candidates = [d for d in dt_objs if d > prev_exp and d < curr_exp]
        if not entry_candidates:
            continue
        entry_dt = entry_candidates[0]

        dte = (curr_exp - entry_dt).days
        label = f"{curr_exp.strftime('%b %Y')} Expiry"

        cycles.append(
            ExpiryCycle(
                year=curr_yr,
                month=curr_m,
                cycle_label=label,
                entry_date=entry_dt.strftime("%Y-%m-%d"),
                expiry_date=curr_exp.strftime("%Y-%m-%d"),
                dte_days=dte,
            )
        )

    return cycles


class HistoricalScreener:
    """Evaluates the liquid 50 F&O universe on any historical cycle entry date."""

    def __init__(self, data_provider: UpstoxDataProvider):
        self.provider = data_provider
        self.universe = TOP_50_UNIVERSE
        # Precompute 2020 base floors for all symbols
        self.base_floors: Dict[str, float] = {}
        for sym in self.universe.keys():
            candles = self.provider.load_or_fetch_symbol(sym)
            self.base_floors[sym] = find_2020_base_floor(candles)

    def screen_cycle(
        self, cycle: ExpiryCycle, preset: str = "default"
    ) -> List[CycleCandidate]:
        """
        Runs the screener across the universe on cycle.entry_date.
        Returns ranked list of CycleCandidate objects.
        """
        candidates: List[CycleCandidate] = []

        # Presets thresholds (Upgraded with Falling Knife & Tail Protection)
        min_pop = 76.0
        min_cush = 7.5
        max_rsi = 60.0
        min_vrp = 2.0
        max_base_dist = 220.0
        min_dma = 0.95
        max_dma = 1.10

        if preset == "fortress":
            min_pop = 84.0
            min_cush = 8.0
            max_rsi = 55.0
            max_base_dist = 180.0
            min_dma = 0.97
            max_dma = 1.08
        elif preset == "oversold_dip":
            max_rsi = 45.0
            min_cush = 7.5
            min_dma = 0.95
        elif preset == "vrp_crush":
            min_vrp = 5.0
        elif preset == "relaxed":
            min_pop = 65.0
            min_cush = 5.0
            max_rsi = 75.0
            min_vrp = 0.5
            max_base_dist = 300.0
            min_dma = 0.92
            max_dma = 1.25

        for sym, meta in self.universe.items():
            all_candles = self.provider.load_or_fetch_symbol(sym)
            # Slice strictly up to cycle.entry_date (no lookahead!)
            sliced = [c for c in all_candles if c["date"] <= cycle.entry_date]
            if len(sliced) < 205:
                # Need at least 200 days for DMA
                continue

            spot_entry = sliced[-1]["close"]
            step = float(meta["step"])
            lot = int(meta["lot"])
            closes = [c["close"] for c in sliced]

            dma200 = compute_200_dma(closes)
            if not dma200:
                continue
            dma_ratio = round(spot_entry / dma200, 2)

            rsi14 = compute_rsi14(closes) or 50.0
            z5d = compute_z5d(closes) or 0.0
            yz_vol = compute_yang_zhang_vol(sliced, window=20)

            # Volatility Risk Premium (VRP) & Option IV
            vrp = round(max(1.8, min(8.5, 3.2 + (50.0 - rsi14) * 0.08)), 1)
            iv_pct = round(yz_vol + vrp, 1)

            # Target ~1.25 standard deviation OTM Short Put Strike snapped to listed interval
            # Enforce an absolute 8.0% cushion ceiling to prevent quiet-volatility compression
            T = max(1, cycle.dte_days) / 365.0
            sigma_yz = yz_vol / 100.0
            raw_short_k = spot_entry * math.exp(-1.25 * sigma_yz * math.sqrt(T))
            max_strike_allowed = snap_to_listed_strike(spot_entry * 0.92, step)
            short_strike = max(step, min(max_strike_allowed, snap_to_listed_strike(raw_short_k, step)))

            otm_cushion = round(((spot_entry - short_strike) / spot_entry) * 100.0, 1)

            # Option Premium and Empirical POP
            put_price, put_delta, pop = black_scholes_put_price(
                spot=spot_entry, strike=short_strike, dte_days=cycle.dte_days, iv_pct=iv_pct
            )

            lot_credit = round(put_price * lot, 2)
            est_span_margin = round(spot_entry * lot * 0.165, 2)
            rom_pct = round((lot_credit / est_span_margin) * 100.0, 2)

            # Base distance
            base_floor = self.base_floors.get(sym, spot_entry * 0.5)
            dist_base = round(((spot_entry - base_floor) / max(1.0, base_floor)) * 100.0, 1)

            # Worthless Score (penalizes falling knife downward velocity)
            roe_alpha = float(meta.get("roe", 16.0)) - float(meta.get("secRoe", 14.0))
            worthless_score = compute_worthless_score(
                pop=pop, vrp=vrp, dist_base=dist_base, rsi14=rsi14, roe_alpha=roe_alpha, z5d=z5d
            )

            # 5-Pillar Regime Filters
            reasons: List[str] = []
            if pop < min_pop:
                reasons.append(f"LowPOP({pop:.1f}%<{min_pop:.1f}%)")
            if otm_cushion < min_cush:
                reasons.append(f"TightCushion({otm_cushion:.1f}%<{min_cush:.1f}%)")
            if rsi14 > max_rsi:
                reasons.append(f"OverboughtRSI14({rsi14:.1f}>{max_rsi:.1f})")
            if vrp < min_vrp:
                reasons.append(f"LowVRP(+{vrp:.1f}%<+{min_vrp:.1f}%)")
            if dist_base > max_base_dist:
                reasons.append(f"FarFromBase(+{dist_base:.1f}%>{max_base_dist:.1f}%)")
            if dma_ratio < min_dma:
                reasons.append(f"Stage4Downtrend({dma_ratio:.2f}x<{min_dma:.2f}x)")
            if dma_ratio > max_dma:
                reasons.append(f"OverextendedAboveDMA({dma_ratio:.2f}x>{max_dma:.2f}x)")
            if z5d > 1.15:
                reasons.append(f"Blowoff(Z5D=+{z5d:.2f})")
            if z5d < -1.15:
                reasons.append(f"FallingKnifeWaterfall(Z5D={z5d:.2f}<-1.15)")
            if lot_credit < 1200 or put_price < 1.50:
                reasons.append(f"MicroCreditFriction(Credit=₹{lot_credit:.0f}<₹1200)")

            passed = len(reasons) == 0

            candidates.append(
                CycleCandidate(
                    sym=sym,
                    lot=lot,
                    step=step,
                    entry_date=cycle.entry_date,
                    expiry_date=cycle.expiry_date,
                    dte_days=cycle.dte_days,
                    spot_entry=spot_entry,
                    short_strike=short_strike,
                    otm_cushion_pct=otm_cushion,
                    put_premium=put_price,
                    lot_credit=lot_credit,
                    est_span_margin=est_span_margin,
                    rom_pct=rom_pct,
                    pop_pct=pop,
                    iv_pct=iv_pct,
                    yz_vol=yz_vol,
                    vrp=vrp,
                    dma200_ratio=dma_ratio,
                    rsi14=rsi14,
                    z5d=z5d,
                    dist_base_2020=dist_base,
                    worthless_score=worthless_score,
                    passed=passed,
                    rejection_reasons=reasons,
                )
            )

        # Sorting logic based on preset
        if preset == "fortress":
            candidates.sort(key=lambda c: (c.passed, c.pop_pct, c.worthless_score), reverse=True)
        elif preset == "oversold_dip":
            candidates.sort(key=lambda c: (c.passed, -c.rsi14, c.worthless_score), reverse=True)
        elif preset == "vrp_crush":
            candidates.sort(key=lambda c: (c.passed, c.vrp, c.worthless_score), reverse=True)
        else:  # default
            candidates.sort(key=lambda c: (c.passed, c.worthless_score, c.pop_pct), reverse=True)

        return candidates
