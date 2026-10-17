"""
Performance Metrics, Formatted Reporting & CSV Exporter
======================================================
Generates institutional summary tables, monthly matrices, and trade log exports.
"""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from typing import Any, Dict, List

from backtest.portfolio_simulator import BacktestSummary, CyclePerformance, TradeRecord


def print_performance_report(
    summary: BacktestSummary,
    cycles: List[CyclePerformance],
    trades: List[TradeRecord],
    title: str = "UPSTOX F&O SHORT OTM PUT STRATEGY BACKTEST REPORT",
) -> None:
    """Prints a beautiful, comprehensive institutional report in terminal."""
    print("\n" + "=" * 120)
    print(f" {title}")
    print(f" Mode: {'DEFINED-RISK BULL PUT SPREAD' if summary.is_spread else 'PURE SINGLE-LEG SHORT OTM PUT'}")
    print(f" Preset: {summary.preset.upper()} • Candidates per Cycle: Top {summary.top_n} • Initial Capital: INR {summary.initial_capital:,.0f}")
    if summary.stop_loss_mult:
        print(f" Risk Management: {summary.stop_loss_mult}x Premium Stop-Loss Enabled")
    else:
        print(" Risk Management: Hold to Expiry (Worthless Expiry Harvester)")
    print("=" * 120)

    # Core Performance Highlights
    sign = "+" if summary.total_net_pnl >= 0 else "-"
    abs_pnl = abs(summary.total_net_pnl)
    print("\n📈 [EXECUTIVE SUMMARY & RETURN METRICS]")
    print(f"   • Initial Capital:        INR {summary.initial_capital:>14,.2f}")
    print(f"   • Ending Capital:         INR {summary.ending_capital:>14,.2f}")
    print(f"   • Total Net Profit/Loss:  {sign}INR {abs_pnl:>13,.2f} ({summary.total_return_pct:+.2f}%)")
    print(f"   • Annualized Return (CAGR):   {summary.cagr_pct:>10.2f}% p.a.")
    print(f"   • Max Portfolio Drawdown:      -{summary.max_drawdown_pct:>9.2f}% (-INR {summary.max_drawdown_inr:,.0f})")
    print(f"   • Profit Factor:               {summary.profit_factor:>10.2f}")
    print(f"   • Sharpe Ratio (Rf=6.8%):      {summary.sharpe_ratio:>10.2f}")
    print(f"   • Sortino Ratio:               {summary.sortino_ratio:>10.2f}")

    print("\n🎯 [TRADE STATS & WIN RATES]")
    print(f"   • Total Expiry Cycles:         {summary.total_cycles:>10d} (Profitable Cycles: {summary.profitable_cycles}/{summary.total_cycles} • {summary.cycle_win_rate_pct:.1f}%)")
    print(f"   • Total Trades Executed:       {summary.total_trades:>10d}")
    print(f"   • Winning Trades:              {summary.winning_trades:>10d} ({summary.trade_win_rate_pct:.1f}% Win Rate)")
    print(f"   • Gross Profit:           INR {summary.gross_profit:>14,.2f}")
    print(f"   • Gross Loss:             INR {summary.gross_loss:>14,.2f}")
    print(f"   • Average Trade PnL:      INR {summary.avg_trade_pnl:>14,.2f}")
    print(f"   • Average Winning Trade:  INR {summary.avg_win:>14,.2f}")
    print(f"   • Average Losing Trade:  -INR {summary.avg_loss:>14,.2f} (Win/Loss Ratio: {summary.win_loss_ratio:.2f}x)")

    # Recent Cycles Breakdown
    print("\n📅 [SAMPLE RECENT MONTHLY EXPIRY CYCLES (LAST 10 CYCLES)]")
    print("-" * 120)
    print(f"{'CYCLE':<16} {'ENTRY':<12} {'EXPIRY':<12} {'MARGIN USED':<16} {'UTIL%':<8} {'TRADES':<8} {'SYMBOLS':<24} {'CYCLE PnL':<15} {'EQUITY'}")
    print("-" * 120)

    for c in cycles[-10:]:
        sym_str = ", ".join(c.trade_symbols) if c.trade_symbols else "NONE (MARGIN/FILTER)"
        pnl_str = f"{c.cycle_pnl_inr:+,.0f} ({c.cycle_return_pct:+.1f}%)"
        print(
            f"{c.cycle_label:<16} {c.entry_date:<12} {c.expiry_date:<12} INR {c.total_margin_used:>10,.0f}   {c.margin_utilization_pct:>5.1f}%  {c.wins_count}/{c.trades_count:<5d} {sym_str:<24} INR {pnl_str:<11} INR {c.ending_capital:,.0f}"
        )
    print("-" * 120)


def export_trades_to_csv(trades: List[Any], filepath: str) -> None:
    """Exports every individual trade to CSV."""
    headers = [
        "Cycle", "Symbol", "Rank", "Entry_Date", "Exit_Date", "DTE", "Lot", "Spot_Entry",
        "Short_Strike", "Long_Strike", "OTM_Cushion_Pct", "Put_Premium", "Gross_Credit",
        "Net_Credit", "SPAN_Margin", "Is_Spread", "Spot_Exit", "Exit_Reason", "Exit_Put_Price",
        "PnL_INR", "RoM_Pct", "Is_Win"
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for t in trades:
            if isinstance(t, dict):
                writer.writerow([
                    t.get("cycle_label"), t.get("sym"), t.get("rank"), t.get("entry_date"), t.get("expiry_date"),
                    t.get("dte_days"), t.get("lot"), t.get("spot_entry"), t.get("short_strike"), t.get("long_strike") or "",
                    t.get("otm_cushion_pct"), t.get("put_premium"), t.get("gross_credit"), t.get("net_credit"),
                    t.get("span_margin"), t.get("is_spread"), t.get("spot_exit"), t.get("exit_reason"),
                    t.get("exit_put_price"), t.get("pnl_inr"), t.get("rom_pct"), "WIN" if t.get("is_win") else "LOSS"
                ])
            else:
                writer.writerow([
                    t.cycle_label, t.sym, t.rank, t.entry_date, t.expiry_date, t.dte_days, t.lot,
                    t.spot_entry, t.short_strike, t.long_strike or "", t.otm_cushion_pct, t.put_premium,
                    t.gross_credit, t.net_credit, t.span_margin, t.is_spread, t.spot_exit,
                    t.exit_reason, t.exit_put_price, t.pnl_inr, t.rom_pct, "WIN" if t.is_win else "LOSS"
                ])
    print(f"Saved complete backtest trade logs to: {filepath}")


def export_backtest_dataset_json(
    summary_dict: Dict[str, Any],
    cycles: List[Any],
    trades: List[Any],
    filepath: str,
) -> None:
    """Exports full backtest dataset as JSON for the web dashboard."""
    def clean_item(x):
        if hasattr(x, "__dict__"):
            return x.__dict__
        elif hasattr(x, "_asdict"):
            return x._asdict()
        return x

    payload = {
        "summary": summary_dict,
        "cycles": [clean_item(c) for c in cycles],
        "trades": [clean_item(t) for t in trades],
    }
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"Saved dashboard dataset to: {filepath}")

