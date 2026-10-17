"""
Portfolio Simulator & Execution Engine
======================================
Simulates monthly multi-candidate portfolio execution with configurable capital (2L, 5L, etc.),
margin tracking, naked short puts vs defined-risk spreads, and stop-loss logic.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Tuple

from backtest.indicators import black_scholes_put_price
from backtest.strategy_screener import CycleCandidate, ExpiryCycle, HistoricalScreener
from backtest.upstox_data_provider import UpstoxDataProvider


@dataclass
class TradeRecord:
    cycle_label: str
    sym: str
    rank: int
    entry_date: str
    expiry_date: str
    dte_days: int
    lot: int
    spot_entry: float
    short_strike: float
    long_strike: Optional[float]
    otm_cushion_pct: float
    put_premium: float
    gross_credit: float
    net_credit: float
    span_margin: float
    is_spread: bool
    spot_exit: float
    exit_date: str
    exit_reason: str  # "WORTHLESS_EXPIRY", "ITM_EXPIRY", "STOP_LOSS"
    exit_put_price: float
    pnl_inr: float
    rom_pct: float
    is_win: bool


@dataclass
class CyclePerformance:
    year: int
    month: int
    cycle_label: str
    entry_date: str
    expiry_date: str
    starting_capital: float
    total_margin_used: float
    margin_utilization_pct: float
    trades_count: int
    wins_count: int
    cycle_pnl_inr: float
    cycle_return_pct: float
    ending_capital: float
    trade_symbols: List[str]


@dataclass
class BacktestSummary:
    initial_capital: float
    ending_capital: float
    total_net_pnl: float
    total_return_pct: float
    cagr_pct: float
    total_cycles: int
    profitable_cycles: int
    cycle_win_rate_pct: float
    total_trades: int
    winning_trades: int
    trade_win_rate_pct: float
    gross_profit: float
    gross_loss: float
    profit_factor: float
    max_drawdown_inr: float
    max_drawdown_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    avg_trade_pnl: float
    avg_win: float
    avg_loss: float
    win_loss_ratio: float
    preset: str
    top_n: int
    is_spread: bool
    stop_loss_mult: Optional[float]


class PortfolioSimulator:
    """Simulates monthly execution of the option selling strategy."""

    def __init__(self, data_provider: UpstoxDataProvider, screener: HistoricalScreener):
        self.provider = data_provider
        self.screener = screener

    def run_simulation(
        self,
        cycles: List[ExpiryCycle],
        initial_capital: float = 500000.0,
        preset: str = "default",
        top_n: int = 3,
        use_spread: bool = False,
        stop_loss_mult: Optional[float] = None,  # e.g. 2.0 for 2x stop-loss
        compounding: bool = True,
    ) -> Tuple[BacktestSummary, List[CyclePerformance], List[TradeRecord]]:
        """
        Executes backtest across all given monthly cycles.
        """
        capital = float(initial_capital)
        trades: List[TradeRecord] = []
        cycle_records: List[CyclePerformance] = []

        peak_capital = capital
        max_dd_inr = 0.0
        max_dd_pct = 0.0
        cycle_returns: List[float] = []

        for cycle in cycles:
            cycle_start_capital = capital
            available_cash = capital
            total_cycle_margin = 0.0

            # 1. Screen candidates on cycle entry date
            screened = self.screener.screen_cycle(cycle, preset=preset)
            qualified = [c for c in screened if c.passed]

            # Select top N qualified candidates
            selected = qualified[:top_n]
            cycle_trades: List[TradeRecord] = []

            for rank, cand in enumerate(selected, 1):
                # Calculate margin required
                if use_spread:
                    # Bull Put Spread: sell short_strike, buy long_strike (2 steps lower)
                    spread_width = 2.0 * cand.step
                    long_strike = max(cand.step, cand.short_strike - spread_width)
                    # Long put price
                    long_put_price, _, _ = black_scholes_put_price(
                        spot=cand.spot_entry,
                        strike=long_strike,
                        dte_days=cand.dte_days,
                        iv_pct=cand.iv_pct,
                    )
                    net_premium = max(0.2, cand.put_premium - long_put_price)
                    net_credit = round(net_premium * cand.lot, 2)
                    gross_credit = cand.lot_credit
                    # Max spread risk = (width - net_premium) * lot
                    required_margin = round((cand.short_strike - long_strike) * cand.lot, 2)
                else:
                    long_strike = None
                    net_premium = cand.put_premium
                    net_credit = cand.lot_credit
                    gross_credit = cand.lot_credit
                    required_margin = cand.est_span_margin

                # Strict Margin Check against available cash
                if required_margin > available_cash:
                    # Insufficient margin to take this position
                    continue

                available_cash -= required_margin
                total_cycle_margin += required_margin

                # 2. Simulate Trade Life from entry_date to expiry_date
                all_candles = self.provider.load_or_fetch_symbol(cand.sym)
                holding_candles = [
                    c for c in all_candles if c["date"] >= cycle.entry_date and c["date"] <= cycle.expiry_date
                ]

                if not holding_candles:
                    continue

                final_spot = holding_candles[-1]["close"]
                exit_date = holding_candles[-1]["date"]
                exit_reason = "WORTHLESS_EXPIRY"
                exit_put_price = 0.0
                stopped_out = False

                # Stop Loss check (if enabled)
                if stop_loss_mult is not None and len(holding_candles) > 1:
                    stop_threshold = cand.put_premium * stop_loss_mult
                    for h_day in holding_candles[1:-1]:
                        d_spot = h_day["close"]
                        # Approximate intraday/daily put price
                        d_days_left = max(1, (dt.datetime.strptime(cycle.expiry_date, "%Y-%m-%d") - dt.datetime.strptime(h_day["date"], "%Y-%m-%d")).days)
                        curr_put, _, _ = black_scholes_put_price(
                            spot=d_spot, strike=cand.short_strike, dte_days=d_days_left, iv_pct=cand.iv_pct
                        )
                        if curr_put >= stop_threshold:
                            stopped_out = True
                            exit_reason = "STOP_LOSS"
                            exit_date = h_day["date"]
                            final_spot = d_spot
                            exit_put_price = curr_put
                            break

                # 3. Calculate PnL & Settlement
                friction = 120.0  # ₹120 round-trip taxes/charges per lot

                if stopped_out:
                    # Loss = (entry_premium - exit_put_price) * lot - friction
                    pnl = (cand.put_premium - exit_put_price) * cand.lot - friction
                elif use_spread:
                    # Spread settlement at expiry
                    if final_spot >= cand.short_strike:
                        # Both options expire worthless -> retain 100% net credit
                        exit_reason = "WORTHLESS_EXPIRY"
                        exit_put_price = 0.0
                        pnl = net_credit - friction
                    elif final_spot <= long_strike:
                        # Max loss on spread
                        exit_reason = "MAX_SPREAD_LOSS"
                        spread_loss = (cand.short_strike - long_strike) * cand.lot
                        pnl = (net_credit - spread_loss) - friction
                        exit_put_price = cand.short_strike - final_spot
                    else:
                        # Short ITM, Long OTM
                        short_intrinsic = (cand.short_strike - final_spot) * cand.lot
                        pnl = (net_credit - short_intrinsic) - friction
                        exit_reason = "PARTIAL_ITM_LOSS"
                        exit_put_price = cand.short_strike - final_spot
                else:
                    # Single-Leg Naked Put Settlement
                    if final_spot >= cand.short_strike:
                        exit_reason = "WORTHLESS_EXPIRY"
                        exit_put_price = 0.0
                        pnl = cand.lot_credit - friction
                    else:
                        exit_reason = "ITM_EXPIRY"
                        intrinsic_loss = (cand.short_strike - final_spot) * cand.lot
                        exit_put_price = cand.short_strike - final_spot
                        pnl = (cand.lot_credit - intrinsic_loss) - friction

                is_win = pnl > 0.0
                rom_pct = round((pnl / max(1.0, required_margin)) * 100.0, 2)

                tr = TradeRecord(
                    cycle_label=cycle.cycle_label,
                    sym=cand.sym,
                    rank=rank,
                    entry_date=cycle.entry_date,
                    expiry_date=exit_date,
                    dte_days=cand.dte_days,
                    lot=cand.lot,
                    spot_entry=cand.spot_entry,
                    short_strike=cand.short_strike,
                    long_strike=long_strike,
                    otm_cushion_pct=cand.otm_cushion_pct,
                    put_premium=cand.put_premium,
                    gross_credit=gross_credit,
                    net_credit=net_credit,
                    span_margin=required_margin,
                    is_spread=use_spread,
                    spot_exit=final_spot,
                    exit_date=exit_date,
                    exit_reason=exit_reason,
                    exit_put_price=round(exit_put_price, 2),
                    pnl_inr=round(pnl, 2),
                    rom_pct=rom_pct,
                    is_win=is_win,
                )
                cycle_trades.append(tr)
                trades.append(tr)

            # Cycle Performance Aggregation
            cycle_pnl = sum(t.pnl_inr for t in cycle_trades)
            cycle_return = (cycle_pnl / cycle_start_capital) * 100.0
            cycle_returns.append(cycle_return)

            if compounding:
                capital += cycle_pnl
            ending_capital = capital

            # Drawdown update
            if ending_capital > peak_capital:
                peak_capital = ending_capital
            dd_inr = peak_capital - ending_capital
            dd_pct = (dd_inr / peak_capital) * 100.0 if peak_capital > 0 else 0.0
            if dd_inr > max_dd_inr:
                max_dd_inr = dd_inr
            if dd_pct > max_dd_pct:
                max_dd_pct = dd_pct

            margin_util_pct = (
                (total_cycle_margin / cycle_start_capital) * 100.0
                if cycle_start_capital > 0
                else 0.0
            )

            cycle_records.append(
                CyclePerformance(
                    year=cycle.year,
                    month=cycle.month,
                    cycle_label=cycle.cycle_label,
                    entry_date=cycle.entry_date,
                    expiry_date=cycle.expiry_date,
                    starting_capital=round(cycle_start_capital, 2),
                    total_margin_used=round(total_cycle_margin, 2),
                    margin_utilization_pct=round(margin_util_pct, 1),
                    trades_count=len(cycle_trades),
                    wins_count=sum(1 for t in cycle_trades if t.is_win),
                    cycle_pnl_inr=round(cycle_pnl, 2),
                    cycle_return_pct=round(cycle_return, 2),
                    ending_capital=round(ending_capital, 2),
                    trade_symbols=[t.sym for t in cycle_trades],
                )
            )

        # 4. Overall Backtest Summary Analytics
        total_pnl = ending_capital - initial_capital
        total_ret_pct = (total_pnl / initial_capital) * 100.0
        n_years = max(0.5, len(cycles) / 12.0)
        cagr = (
            ((ending_capital / initial_capital) ** (1.0 / n_years) - 1.0) * 100.0
            if ending_capital > 0
            else -100.0
        )

        n_trades = len(trades)
        wins = [t for t in trades if t.is_win]
        losses = [t for t in trades if not t.is_win]
        trade_win_rate = (len(wins) / max(1, n_trades)) * 100.0

        n_cycles = len(cycle_records)
        prof_cycles = sum(1 for c in cycle_records if c.cycle_pnl_inr > 0)
        cycle_win_rate = (prof_cycles / max(1, n_cycles)) * 100.0

        gross_profit = sum(t.pnl_inr for t in wins)
        gross_loss = abs(sum(t.pnl_inr for t in losses))
        profit_factor = (gross_profit / max(1.0, gross_loss)) if gross_loss > 0 else (99.9 if gross_profit > 0 else 0.0)

        avg_trade_pnl = (total_pnl / max(1, n_trades))
        avg_win = (gross_profit / max(1, len(wins))) if wins else 0.0
        avg_loss = (gross_loss / max(1, len(losses))) if losses else 0.0
        win_loss_ratio = (avg_win / max(1.0, avg_loss)) if avg_loss > 0 else 99.9

        # Sharpe and Sortino
        if len(cycle_returns) > 1:
            mean_ret = sum(cycle_returns) / len(cycle_returns)
            var_ret = sum((r - mean_ret) ** 2 for r in cycle_returns) / (len(cycle_returns) - 1)
            std_ret = math.sqrt(var_ret) if var_ret > 1e-8 else 1e-4

            # Monthly risk-free rate proxy ~ 6.8% / 12 = 0.567%
            rf_monthly = 6.8 / 12.0
            sharpe = (mean_ret - rf_monthly) / std_ret * math.sqrt(12.0)

            downside_sq = [min(0.0, r - rf_monthly) ** 2 for r in cycle_returns]
            downside_std = math.sqrt(sum(downside_sq) / max(1, len(downside_sq)))
            sortino = (mean_ret - rf_monthly) / (downside_std if downside_std > 1e-8 else 1e-4) * math.sqrt(12.0)
        else:
            sharpe = 0.0
            sortino = 0.0

        summary = BacktestSummary(
            initial_capital=initial_capital,
            ending_capital=round(ending_capital, 2),
            total_net_pnl=round(total_pnl, 2),
            total_return_pct=round(total_ret_pct, 2),
            cagr_pct=round(cagr, 2),
            total_cycles=n_cycles,
            profitable_cycles=prof_cycles,
            cycle_win_rate_pct=round(cycle_win_rate, 1),
            total_trades=n_trades,
            winning_trades=len(wins),
            trade_win_rate_pct=round(trade_win_rate, 1),
            gross_profit=round(gross_profit, 2),
            gross_loss=round(gross_loss, 2),
            profit_factor=round(profit_factor, 2),
            max_drawdown_inr=round(max_dd_inr, 2),
            max_drawdown_pct=round(max_dd_pct, 2),
            sharpe_ratio=round(sharpe, 2),
            sortino_ratio=round(sortino, 2),
            avg_trade_pnl=round(avg_trade_pnl, 2),
            avg_win=round(avg_win, 2),
            avg_loss=round(avg_loss, 2),
            win_loss_ratio=round(win_loss_ratio, 2),
            preset=preset,
            top_n=top_n,
            is_spread=use_spread,
            stop_loss_mult=stop_loss_mult,
        )

        return summary, cycle_records, trades
