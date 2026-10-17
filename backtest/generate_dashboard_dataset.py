"""
Generate Standalone Dashboard Dataset
====================================
Generates the comprehensive historical cycle evaluations, daily candle histories,
and preset rankings for the interactive HTML backtest dashboard.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from backtest.strategy_screener import HistoricalScreener, generate_nse_monthly_cycles
from backtest.upstox_data_provider import TOP_50_UNIVERSE, UpstoxDataProvider


def generate_full_dashboard_data() -> Dict[str, Any]:
    print("Generating complete backtest dataset for interactive web dashboard...")
    provider = UpstoxDataProvider()
    trading_dates_sample = [c["date"] for c in provider.load_or_fetch_symbol("SBIN")]
    cycles = generate_nse_monthly_cycles(trading_dates_sample, start_year=2021, end_year=2026, end_month=10)
    screener = HistoricalScreener(provider)

    presets = ["default", "fortress", "oversold_dip", "vrp_crush"]
    cycles_data = []

    for c_idx, cycle in enumerate(cycles):
        cycle_dict = {
            "year": cycle.year,
            "month": cycle.month,
            "label": cycle.cycle_label,
            "entry_date": cycle.entry_date,
            "expiry_date": cycle.expiry_date,
            "dte": cycle.dte_days,
            "candidates_by_preset": {},
        }

        # Cache holding candle prices for each symbol in this cycle
        holding_spot = {}
        for sym in TOP_50_UNIVERSE.keys():
            all_c = provider.load_or_fetch_symbol(sym)
            hold = [c for c in all_c if c["date"] >= cycle.entry_date and c["date"] <= cycle.expiry_date]
            if hold:
                holding_spot[sym] = {
                    "entry_spot": hold[0]["close"],
                    "exit_spot": hold[-1]["close"],
                    "exit_date": hold[-1]["date"],
                    "min_low": min(c["low"] for c in hold),
                    "daily_closes": [c["close"] for c in hold],
                    "daily_dates": [c["date"] for c in hold],
                }

        cycle_dict["holding_spots"] = holding_spot

        for p in presets:
            screened = screener.screen_cycle(cycle, preset=p)
            # Store top 10 candidates per preset
            cand_list = []
            for rank, cand in enumerate(screened[:10], 1):
                cand_list.append({
                    "rank": rank,
                    "sym": cand.sym,
                    "lot": cand.lot,
                    "step": cand.step,
                    "spot_entry": cand.spot_entry,
                    "short_strike": cand.short_strike,
                    "otm_cushion": cand.otm_cushion_pct,
                    "put_premium": cand.put_premium,
                    "lot_credit": cand.lot_credit,
                    "span_margin": cand.est_span_margin,
                    "rom_pct": cand.rom_pct,
                    "pop_pct": cand.pop_pct,
                    "iv_pct": cand.iv_pct,
                    "yz_vol": cand.yz_vol,
                    "vrp": cand.vrp,
                    "dma_ratio": cand.dma200_ratio,
                    "rsi14": cand.rsi14,
                    "z5d": cand.z5d,
                    "dist_base": cand.dist_base_2020,
                    "worthless_score": cand.worthless_score,
                    "passed": cand.passed,
                    "reasons": cand.rejection_reasons,
                })
            cycle_dict["candidates_by_preset"][p] = cand_list

        cycles_data.append(cycle_dict)

    dataset = {
        "generated_at": "2026-10-17",
        "universe_count": len(TOP_50_UNIVERSE),
        "total_cycles": len(cycles),
        "start_date": cycles[0].entry_date,
        "end_date": cycles[-1].expiry_date,
        "universe_meta": TOP_50_UNIVERSE,
        "cycles": cycles_data,
    }

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    js_path = os.path.join(base_dir, "backtest_data.js")
    json_path = os.path.join(base_dir, "backtest_data.json")

    # Write JS bundle (window.BACKTEST_DATA = ...) for zero-cors local browser opening
    with open(js_path, "w", encoding="utf-8") as f:
        f.write("window.BACKTEST_DATA = ")
        json.dump(dataset, f)
        f.write(";\n")
    print(f"Exported browser dataset: {js_path} ({os.path.getsize(js_path) / 1024:.1f} KB)")

    # Also write JSON
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(dataset, f)
    print(f"Exported JSON dataset: {json_path}")

    return dataset


if __name__ == "__main__":
    generate_full_dashboard_data()
