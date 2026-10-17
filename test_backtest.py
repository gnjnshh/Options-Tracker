"""
Automated Unit Tests for Backtesting Engine
"""

import math
from backtest.indicators import (
    black_scholes_put_price,
    compute_200_dma,
    compute_rsi14,
    compute_yang_zhang_vol,
    compute_z5d,
    norm_cdf,
    snap_to_listed_strike,
)
from backtest.strategy_screener import HistoricalScreener, generate_nse_monthly_cycles
from backtest.portfolio_simulator import PortfolioSimulator
from backtest.upstox_data_provider import UpstoxDataProvider


def test_strike_snapping():
    assert snap_to_listed_strike(962.6, 10.0) == 960.0
    assert snap_to_listed_strike(1290.0, 20.0) == 1280.0
    assert snap_to_listed_strike(4444.8, 50.0) == 4400.0
    assert snap_to_listed_strike(6801.0, 100.0) == 6800.0
    print("test_strike_snapping: PASS")


def test_indicators():
    closes = [100.0 + i for i in range(250)]
    dma = compute_200_dma(closes)
    assert dma is not None
    assert abs(dma - (closes[-1] + closes[-200]) / 2.0) < 1.0

    rsi = compute_rsi14(closes)
    assert rsi is not None
    assert rsi == 100.0  # Monotonic gain

    z5 = compute_z5d(closes)
    assert z5 is not None
    assert z5 > 1.0  # Strong uptrend

    # Standard normal cdf
    assert abs(norm_cdf(0.0) - 0.5) < 1e-4
    assert abs(norm_cdf(1.96) - 0.975) < 1e-2

    # Black-Scholes put
    put_p, delta, pop = black_scholes_put_price(spot=1000.0, strike=900.0, dte_days=30, iv_pct=20.0)
    assert put_p > 0
    assert delta < 0
    assert pop > 80.0
    print("test_indicators: PASS")


def test_additional_indicators():
    from backtest.indicators import (
        compute_adx14,
        compute_bollinger_pct_b,
        compute_down_volume_ratio,
        compute_mfi14,
        find_multiyear_high,
    )

    # 1. Bollinger %B test: monotonic steady rise
    closes = [100.0 + i * 0.5 for i in range(50)]
    pct_b = compute_bollinger_pct_b(closes, window=20)
    assert pct_b is not None
    # In steady uptrend, close is above middle band, near upper band
    assert 0.7 <= pct_b <= 1.3

    # Boundary: flat line
    flat = [100.0] * 30
    pct_b_flat = compute_bollinger_pct_b(flat, window=20)
    assert pct_b_flat == 0.5

    # Insufficient data
    assert compute_bollinger_pct_b([100.0] * 5, window=20) is None

    # 2. MFI 14 test
    candles = []
    for i in range(30):
        p = 100.0 + i
        candles.append({"open": p - 0.5, "high": p + 1.0, "low": p - 1.0, "close": p, "volume": 10000})
    mfi = compute_mfi14(candles, window=14)
    assert mfi is not None
    assert mfi == 100.0  # Monotonic rise in typical price

    # 3. ADX 14 test
    adx = compute_adx14(candles, window=14)
    assert adx is not None
    assert adx > 20.0  # Strong directional trend

    # 4. Down Volume Ratio test
    # Candles where only 2 of 20 days are down days with half volume
    mixed_candles = []
    for i in range(25):
        p = 100.0 + (i if i % 5 != 0 else i - 2)
        v = 5000 if i % 5 == 0 else 10000
        mixed_candles.append({"open": p, "high": p + 1, "low": p - 1, "close": p, "volume": v})
    d_vol = compute_down_volume_ratio(mixed_candles, window=20)
    assert d_vol > 0

    # 5. Multiyear High
    high = find_multiyear_high(candles)
    assert high == 100.0 + 29 + 1.0
    print("test_additional_indicators: PASS")


def test_screener_candle_evaluation():
    import upstox_fno_option_screener as scr

    provider = UpstoxDataProvider()
    candles = provider.load_or_fetch_symbol("DRREDDY")
    assert len(candles) > 200

    th = scr.ScreeningThresholds()
    cand = scr.evaluate_candidate(scr.CORE_41_RAW[0], th, expiry_mode="next_month", candles=candles)
    assert cand.sym == "DRREDDY"
    assert cand.spot == candles[-1]["close"]
    # Check that real indicators are computed from candles
    assert abs(cand.rsi14 - 57.8) < 1.0
    assert cand.base_2020 == 499.0
    assert cand.high_20_26 > 1300.0
    assert cand.pop > 70.0
    assert cand.short_strike > 0
    assert cand.short_put_ltp > 0
    assert cand.lot_credit > 0
    print("test_screener_candle_evaluation: PASS")


def test_simulation_runs():
    provider = UpstoxDataProvider()
    dates = [c["date"] for c in provider.load_or_fetch_symbol("SBIN")]
    cycles = generate_nse_monthly_cycles(dates, start_year=2025, end_year=2026, end_month=5)
    assert len(cycles) > 0

    screener = HistoricalScreener(provider)
    sim = PortfolioSimulator(provider, screener)

    summary_5l, _, trades_5l = sim.run_simulation(cycles, initial_capital=500000.0, preset="default", top_n=2)
    assert summary_5l.total_trades > 0
    assert summary_5l.ending_capital > 0

    summary_2l, _, trades_2l = sim.run_simulation(cycles, initial_capital=200000.0, preset="default", top_n=2)
    assert summary_2l.total_trades > 0
    assert summary_2l.ending_capital > 0
    print("test_simulation_runs: PASS")


def test_live_option_chain_and_quote_integration():
    import upstox_fno_option_screener as scr

    provider = UpstoxDataProvider()
    candles = provider.load_or_fetch_symbol("DRREDDY")

    th = scr.ScreeningThresholds()

    # Create mock option chain
    mock_chain = [
        {
            "strike_price": 1100.0,
            "underlying_spot_price": 1250.0,
            "call_options": {"market_data": {"volume": 2000, "oi": 5000}},
            "put_options": {
                "market_data": {"volume": 8000, "oi": 95000, "ltp": 4.50, "close_price": 4.20},
                "option_greeks": {"iv": 24.5, "delta": -0.09, "pop": 91.5},
            },
        },
        {
            "strike_price": 1120.0,
            "underlying_spot_price": 1250.0,
            "call_options": {"market_data": {"volume": 3000, "oi": 12000}},
            "put_options": {
                "market_data": {"volume": 12000, "oi": 62000, "ltp": 6.80, "close_price": 6.50},
                "option_greeks": {"iv": 25.0, "delta": -0.13, "pop": 88.0},
            },
        },
        {
            "strike_price": 1140.0,
            "underlying_spot_price": 1250.0,
            "call_options": {"market_data": {"volume": 4000, "oi": 25000}},
            "put_options": {
                "market_data": {"volume": 15000, "oi": 40000, "ltp": 9.20, "close_price": 9.00},
                "option_greeks": {"iv": 25.8, "delta": -0.18, "pop": 83.0},
            },
        },
    ]

    mock_quote = {
        "last_price": 1255.0,
        "volume": 850000,
    }

    cand = scr.evaluate_candidate(
        scr.CORE_41_RAW[0], th, expiry_mode="next_month", chain_data=mock_chain, candles=candles, quote_data=mock_quote
    )

    # 1. Spot priority: quote price (1255.0) takes precedence over chain spot (1250.0) and candle close (1233.0)
    assert cand.spot == 1255.0

    # 2. Max Put OI Wall: strike 1100.0 has 95,000 Put OI (highest in chain)
    assert cand.put_wall_strike == 1100.0

    # 3. Short strike matched and snapped from chain
    assert cand.short_strike in (1120.0, 1140.0, 1100.0)

    # 4. Chain Greeks & prices wired correctly
    assert cand.iv > 0
    assert cand.short_put_ltp in (4.50, 6.80, 9.20)
    assert cand.short_delta < 0
    assert cand.pop in (91.5, 88.0, 83.0)
    assert cand.fno_vol == (2000 + 8000 + 3000 + 12000 + 4000 + 15000)

    # 5. Consistency: cushion and distance are computed from resolved spot (1255.0)
    expected_cushion = round(((1255.0 - cand.short_strike) / 1255.0) * 100.0, 1)
    assert cand.otm_cushion == expected_cushion

    # 6. Test fallback when LTP is 0 but close_price is positive
    mock_chain_zero_ltp = [
        {
            "strike_price": 1120.0,
            "underlying_spot_price": 1233.0,
            "call_options": {"market_data": {"volume": 0, "oi": 1000}},
            "put_options": {
                "market_data": {"volume": 0, "oi": 30000, "ltp": 0.0, "close_price": 5.40},
                "option_greeks": {"iv": 24.0, "delta": -0.11, "pop": 89.0},
            },
        }
    ]
    cand_zero_ltp = scr.evaluate_candidate(
        scr.CORE_41_RAW[0], th, expiry_mode="next_month", chain_data=mock_chain_zero_ltp, candles=candles
    )
    assert cand_zero_ltp.short_put_ltp == 5.40
    print("test_live_option_chain_and_quote_integration: PASS")


def test_data_provider_caching_and_fallback():
    provider = UpstoxDataProvider()

    # 1. Loading cached symbol
    candles = provider.load_or_fetch_symbol("DRREDDY", force_refresh=False)
    assert len(candles) > 100

    # 2. Instrument key resolution for symbol outside TOP_50
    # Should safely fallback to cache or report missing without crash
    try:
        provider.load_or_fetch_symbol("NONEXISTENT_XYZ", instrument_key="NSE_EQ|NONEXISTENT")
        assert False, "Expected ValueError for nonexistent symbol"
    except ValueError as e:
        assert "Failed to fetch candles" in str(e) or "No candle data available" in str(e)

    print("test_data_provider_caching_and_fallback: PASS")


if __name__ == "__main__":
    test_strike_snapping()
    test_indicators()
    test_additional_indicators()
    test_screener_candle_evaluation()
    test_live_option_chain_and_quote_integration()
    test_data_provider_caching_and_fallback()
    test_simulation_runs()
    print("\nALL UNIT TESTS PASSED SUCCESSFULLY!")

