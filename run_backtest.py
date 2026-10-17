#!/usr/bin/env python3
"""
Upstox F&O Quant Strategy Backtester — Runner CLI
=================================================
Executes historical backtest using authentic Upstox API v3 daily candle data
across 2021–2026 (~70 monthly expiry cycles).
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List

from backtest.performance_metrics import (
    export_backtest_dataset_json,
    export_trades_to_csv,
    print_performance_report,
)
from backtest.portfolio_simulator import BacktestSummary, PortfolioSimulator
from backtest.strategy_screener import HistoricalScreener, generate_nse_monthly_cycles
from backtest.upstox_data_provider import UpstoxDataProvider


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upstox F&O Quant Strategy Backtester (Worthless Expiry Harvester)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=500000.0,
        help="Initial capital in INR (default: 500000 = 5 Lakhs)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=3,
        choices=[1, 2, 3, 4, 5],
        help="Number of top candidates to trade per cycle (default: 3)",
    )
    parser.add_argument(
        "--preset",
        type=str,
        default="all",
        choices=["all", "default", "fortress", "oversold_dip", "vrp_crush"],
        help="Strategy preset to backtest (or 'all' for comparative study)",
    )
    parser.add_argument(
        "--spread",
        action="store_true",
        help="Execute as Defined-Risk Bull Put Spreads (hedging with OTM long put)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=None,
        help="Stop loss multiplier on entry credit (e.g. 2.0 for 2x stop loss)",
    )
    parser.add_argument(
        "--export-csv",
        type=str,
        default="backtest_trades.csv",
        help="Filepath to export trade log CSV",
    )
    parser.add_argument(
        "--export-json",
        type=str,
        default="backtest_results.json",
        help="Filepath to export dashboard JSON data",
    )

    args = parser.parse_args()

    print("=" * 100)
    print(" 🚀 INITIALIZING UPSTOX QUANT STRATEGY BACKTESTING ENGINE")
    print(f" Initial Capital: INR {args.capital:,.0f} • Top Picks/Cycle: {args.top}")
    print(f" Mode: {'Defined-Risk Bull Put Spread' if args.spread else 'Single-Leg Naked Short OTM Put'}")
    if args.stop_loss:
        print(f" Stop-Loss: {args.stop_loss}x Entry Premium")
    else:
        print(" Stop-Loss: None (Hold to Expiry — Pure Worthless Harvester)")
    print("=" * 100)

    # 1. Initialize Upstox Data Provider & Preload
    provider = UpstoxDataProvider()
    trading_dates_sample = [c["date"] for c in provider.load_or_fetch_symbol("SBIN")]
    print(f"Loaded {len(trading_dates_sample)} trading dates from Upstox API.")

    # 2. Generate Authentic Monthly Expiry Cycles
    cycles = generate_nse_monthly_cycles(trading_dates_sample, start_year=2021, end_year=2026, end_month=10)
    print(f"Generated {len(cycles)} monthly expiry cycles from {cycles[0].cycle_label} to {cycles[-1].cycle_label}.\n")

    screener = HistoricalScreener(provider)
    simulator = PortfolioSimulator(provider, screener)

    if args.preset == "all":
        # Comparative Multi-Preset Run
        presets_to_test = ["default", "fortress", "oversold_dip"]
        all_summaries: Dict[str, BacktestSummary] = {}
        all_datasets: Dict[str, Any] = {}

        for p in presets_to_test:
            print(f"\n>>> Running Backtest for Preset: [{p.upper()}] with INR {args.capital:,.0f} Capital...")
            summary, cycle_perf, trades = simulator.run_simulation(
                cycles=cycles,
                initial_capital=args.capital,
                preset=p,
                top_n=args.top,
                use_spread=args.spread,
                stop_loss_mult=args.stop_loss,
            )
            all_summaries[p] = summary
            all_datasets[p] = {
                "summary": summary.__dict__,
                "cycles": [c.__dict__ for c in cycle_perf],
                "trades": [t.__dict__ for t in trades],
            }
            print_performance_report(summary, cycle_perf, trades, title=f"UPSTOX BACKTEST: [{p.upper()}] PRESET")

        # Also run Defined-Risk Spread variant for Default preset to compare side-by-side
        print(f"\n>>> Running Comparative Variant: [DEFAULT PRESET — DEFINED-RISK BULL PUT SPREAD]...")
        spread_summary, spread_cycles, spread_trades = simulator.run_simulation(
            cycles=cycles,
            initial_capital=args.capital,
            preset="default",
            top_n=args.top,
            use_spread=True,
            stop_loss_mult=args.stop_loss,
        )
        all_summaries["default_spread"] = spread_summary
        all_datasets["default_spread"] = {
            "summary": spread_summary.__dict__,
            "cycles": [c.__dict__ for c in spread_cycles],
            "trades": [t.__dict__ for t in spread_trades],
        }

        # Comparative Summary Table
        print("\n" + "=" * 125)
        print(" 🏆 INSTITUTIONAL MULTI-PRESET COMPARATIVE SCORECARD (CAPITAL: INR 5,00,000)")
        print("=" * 125)
        print(f"{'PRESET / VARIANT':<30} {'NET PnL (INR)':<18} {'TOTAL RET %':<14} {'CAGR %':<10} {'WIN RATE %':<12} {'MAX DD %':<12} {'PROFIT FACTOR':<14} {'SHARPE'}")
        print("-" * 125)

        for label, s in all_summaries.items():
            disp_label = {
                "default": "1. Default Harvester (Naked)",
                "fortress": "2. Fortress 84%+ POP (Naked)",
                "oversold_dip": "3. Oversold Dip (Naked)",
                "default_spread": "4. Default Spread (Defined-Risk)",
            }.get(label, label)
            sign = "+" if s.total_net_pnl >= 0 else "-"
            pnl_s = f"{sign}INR {abs(s.total_net_pnl):,.0f}"
            ret_s = f"{s.total_return_pct:+.1f}%"
            cagr_s = f"{s.cagr_pct:+.1f}%"
            wr_s = f"{s.trade_win_rate_pct:.1f}% ({s.cycle_win_rate_pct:.0f}% cycle)"
            dd_s = f"-{s.max_drawdown_pct:.1f}%"
            pf_s = f"{s.profit_factor:.2f}"
            sh_s = f"{s.sharpe_ratio:.2f}"
            print(f"{disp_label:<30} {pnl_s:<18} {ret_s:<14} {cagr_s:<10} {wr_s:<12} {dd_s:<12} {pf_s:<14} {sh_s}")
        print("=" * 125)

        # Export primary default trades to CSV
        export_trades_to_csv(all_datasets["default"]["trades"], args.export_csv)

        # Export multi-preset dataset for the dashboard
        export_backtest_dataset_json(all_datasets, [], [], args.export_json)

    else:
        # Single Preset Run
        summary, cycle_perf, trades = simulator.run_simulation(
            cycles=cycles,
            initial_capital=args.capital,
            preset=args.preset,
            top_n=args.top,
            use_spread=args.spread,
            stop_loss_mult=args.stop_loss,
        )
        print_performance_report(summary, cycle_perf, trades)
        export_trades_to_csv(trades, args.export_csv)
        export_backtest_dataset_json(summary.__dict__, cycle_perf, trades, args.export_json)


if __name__ == "__main__":
    main()
