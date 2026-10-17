# 📈 Upstox F&O Quant Screener v3.0 — Short OTM Put & Worthless Expiry Harvester

Institutional-grade quantitative options screener powered by the **Upstox Developer API (v2 & v3)**.
Engineered specifically for **Pure Option Selling (Single-Leg Short OTM Puts)** that expire 100% worthless, harvesting upfront gross premium and **Volatility Risk Premium (VRP)** while calculating **Return on SPAN Margin (RoM %)**.

🌐 **Live Web Dashboards:**
- 📊 **Main Quantitative Screener (Single-Screen 100% Fit):** [https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)
- 📖 **Quantitative Thesis, Criteria & Terminology FAQs:** [https://gnjnshh.github.io/Options-Tracker/thesis.html](https://gnjnshh.github.io/Options-Tracker/thesis.html)

*(Note: The original v1.0 2024 Multi-Year Low screener is preserved on branch **[`v1`](https://github.com/gnjnshh/Options-Tracker/tree/v1)**).*

---

## 🚀 What's New in v3.0

1. **Pure Option Selling Strategy (Single-Leg Short OTM Put)**:
   - Replaced 2-leg spread with high-conviction Short OTM Put (`SELL <Strike> PE`) snapped to listed NSE strike intervals.
   - **100% Gross Option Premium Retained** (`Short Put LTP × Lot Size`) upon worthless expiry ($S_T \ge K_{\text{short}}$).
   - Computes estimated **Return on SPAN Margin (RoM %)** based on exchange margin requirements (~16.5% contract value proxy).
2. **Exact Target Expiry Month & Date Display**:
   - Dynamically resolves and displays the exact NSE monthly expiration series:
     - **Oct Series:** Tue, 27 Oct 2026 (10 DTE)
     - **Nov Series:** Mon, 23 Nov 2026 (37 DTE)
     - **Dec Series:** Tue, 29 Dec 2026 (73 DTE)
   - Synchronizes directly with Upstox API `GET /v2/option/contract` and `GET /v2/option/chain`.
3. **Upstox API Option Chain Volume Integration & 1-Click Sort by Volume**:
   - Pulls live total option chain volume (`Σ Call Vol + Put Vol`) and strike-specific volume & open interest (`OI`).
   - Dedicated quick-sort toolbar directly above the table with 1-click **🔥 Sort by F&O Chain Volume** (`--sort vol`).
4. **Interactive (i) Hover Tooltips Across All 18 Columns**:
   - Comprehensive tooltip guide explaining the mathematical formula, Upstox API source endpoint, and ideal range for option selling.
5. **Expanded Universes & 8 Strategy Presets**:
   - **Universes:** Core 41 Calibrated Symbols, Top 50 Liquid F&O, and All 220 NSE F&O Underlyings.
   - **8 Strategy Presets:**
     1. Institutional Worthless Harvester (Default)
     2. Ultra-Safe 84%+ POP Fortress
     3. High F&O Volume Liquid Leaders
     4. Near 2020 Multi-Year Base (<140% Dist)
     5. High VRP Volatility Crush (VRP ≥ +6%)
     6. Oversold Mean-Reversion Dip (RSI ≤ 45)
     7. High ROE Fundamental Compounders
     8. Explorer (Relaxed Filters)

---

## 🔒 Security Architecture (Public Repo + Private API)

This repository is **completely public**, but your personal Upstox API credentials remain **100% private and secure**:

1. **Browser `localStorage` Client-Side Persistence**:
   - When you open the hosted GitHub Page ([https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)), enter or load your Upstox Bearer token **once**.
   - The token is saved in your browser's isolated `localStorage` on your device.
   - **Whenever you reopen this GitHub page on your laptop or phone, it automatically retrieves your saved token so you don't have to input it every time!**
   - Because `localStorage` stays strictly within your client-side browser, your token is **never transmitted to GitHub or any third-party server**, and is never visible to anyone else visiting your public repository.
   - You can also click **"📁 Load File"** to instantly import your token file (`Upstox API.txt` or `.env`) with a single click.

2. **Local Python Execution via `.env`**:
   - For running the Python CLI tool locally, your credentials are saved in `.env` (or automatically discovered from your desktop token file `Upstox API.txt`).
   - `.gitignore` strictly prevents `.env`, `*.token`, `*.txt` credentials, and output datasets from ever being committed to git.

---

## 🏛️ Calibrated Quantitative Pillars

1. **Reversed V3 Candle Chronology Fix**:
   - Upstox `/v3/historical-candle` returns newest candles at index `0`. The engine reverses the candle series so that 5-day Z-scores ($Z_{5D}$) and momentum indicators have the correct sign.
2. **Strict Listed NSE Strike Snapping**:
   - Snaps short strike to actual listed NSE strike intervals (e.g. ₹10, ₹20, ₹50, ₹100). No fractional strikes.
3. **Empirical Probability of Expiring Worthless ($P_{\text{worthless}}$)**:
   - Evaluates exact lognormal survival probability $N(d_2)$ using 20-day **Yang-Zhang (2000) minimum-variance OHLC volatility ($\sigma_{\text{YZ}}$)** over actual DTE.
4. **True Volatility Risk Premium (VRP)**:
   - Requires $\text{Option IV} - \sigma_{\text{YZ}} \ge +2.0\%$ so you are statistically paid excess premium above realized market movement.
5. **Calibrated 5-Pillar Regime Guard**:
   - **Pillar I — Empirical POP & Safety Cushion:** Empirical $\text{POP} \ge 76\%$ and OTM cushion $\ge 5.0\%$ at or below Put OI Support Wall.
   - **Pillar II — Structural Floor:** $\text{Spot} / 200\text{-DMA} \ge 0.92\text{x}$ and 2020–2026 Base tracking.
   - **Pillar III — Exhaustion / Non-Blowoff Regime:** $\text{RSI}(14) \le 60$ and $-2.60 \le Z_{5D} \le +1.10$.
   - **Pillar IV — Futures Flow Guard:** Rejects stocks with 5-day Futures OI surge $> +3.0\%$ during price drops.
   - **Pillar V — Positive VRP:** Excess premium harvest $\ge +2.0\%$.

---

## 🚀 Quick Start

### Option A: Use the Hosted Web Dashboard (GitHub Pages)

1. Open **[https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)**.
2. Paste your Upstox Bearer token (or click **"📁 Load File"**).
3. Click **"⚡ SCAN LIVE UPSTOX API"**.
4. Your token is remembered on that browser—every time you revisit the link, your credentials are automatically loaded!

---

### Option B: Run the Python CLI Tool Locally

#### 1. Setup Environment
```bash
git clone https://github.com/gnjnshh/Options-Tracker.git
cd Options-Tracker
```

#### 2. Configure Your API Token (One Time)
Copy `.env.example` to `.env` and paste your Upstox access token:
```bash
cp .env.example .env
```
*(The screener also automatically detects `Upstox API.txt` on your Desktop if `.env` is omitted.)*

#### 3. Run the Screener

- **Offline Simulation / Verification Mode (Instant Core 41 scan):**
  ```bash
  python upstox_fno_option_screener.py --demo
  ```

- **Sort by F&O Chain Volume:**
  ```bash
  python upstox_fno_option_screener.py --demo --sort vol
  ```

- **Scan Top 50 Liquid F&O with Ultra-Safe Fortress Preset:**
  ```bash
  python upstox_fno_option_screener.py --demo --universe top50 --preset fortress
  ```

- **Scan All 220 NSE F&O Universe:**
  ```bash
  python upstox_fno_option_screener.py --demo --universe all220
  ```

- **Live Upstox API Scan:**
  ```bash
  python upstox_fno_option_screener.py --expiry next_month
  ```

---

## 🧪 Quantitative Backtesting Engine (2021–2026)

The project includes an institutional-grade backtesting engine powered by **Upstox API v3 daily candle data** across **69 monthly expiry cycles (Jan 2021 – Sep 2026)** for the Top 50 liquid F&O universe.

### 🏆 5L Capital Multi-Preset Performance Scorecard (Top 3 Picks)

| Strategy Preset / Structure | Net Profit (INR) | Total Return % | CAGR % | Win Rate % | Max Drawdown % | Profit Factor |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **🔥 Oversold Dip (2.0x Stop-Loss)** | **+₹2,57,737** | **+51.55%** | **7.50%** | **89.0%** (137W / 17L) | **-2.54%** | **3.49** |
| **Oversold Dip (Hold to Expiry)** | +₹2,25,310 | +45.06% | 6.68% | 93.5% (144W / 10L) | -7.00% | 2.45 |
| **Defined-Risk Bull Put Spread** | +₹1,00,810 | +20.16% | 3.22% | 89.7% (157W / 18L) | -4.61% | 2.06 |
| **Default Harvester (Naked)** | +₹80,451 | +16.09% | 2.61% | 90.7% (166W / 17L) | -20.69% | 1.29 |
| **Fortress 84%+ POP (Naked)** | +₹22,998 | +4.60% | 0.79% | 91.0% (162W / 16L) | -19.27% | 1.08 |

### Running the Backtester Locally:

- **Run Multi-Preset Comparison (INR 5,00,000 Capital, Top 3 Picks):**
  ```bash
  python run_backtest.py --capital 500000 --top 3
  ```

- **Run Top Alpha Strategy with 2.0x Premium Stop-Loss:**
  ```bash
  python run_backtest.py --capital 500000 --top 3 --preset oversold_dip --stop-loss 2.0
  ```

- **Run with INR 2,00,000 Capital:**
  ```bash
  python run_backtest.py --capital 200000 --top 3 --preset oversold_dip --stop-loss 2.0
  ```

- **Run Automated Test Suite:**
  ```bash
  python test_backtest.py
  ```

### Interactive Web Dashboard with Variable Capital:
Open **[`backtest_dashboard.html`](file:///c:/Options%20Tracker/backtest_dashboard.html)** in any browser. It allows adjusting Capital dynamically (e.g. ₹2L, ₹3L, ₹5L, ₹10L, custom) and instantly recalculates equity curves, monthly heatmaps, drawdowns, and trade logs!

---

## 🛠️ Project Structure

```text
Options-Tracker/
├── .env.example                     # Safe configuration template (git-tracked)
├── .env                             # Your private API token (git-ignored, never pushed)
├── .gitignore                       # Ensures all secrets and tokens remain private
├── index.html                       # Web Dashboard v3.0 (Pure Short Put & Volume Harvester)
├── backtest_dashboard.html          # Interactive Backtesting Dashboard with variable capital input
├── backtest_data.js                 # Browser-bundled backtest dataset (zero-CORS)
├── upstox_fno_option_screener.py    # Python CLI screener v3.0 (Pure Option Selling Engine)
├── run_backtest.py                  # CLI runner for quantitative backtesting engine
├── test_backtest.py                 # Automated unit tests for math, indicators & simulator
├── backtest/                        # Modular Backtesting Engine Package
│   ├── upstox_data_provider.py      # Upstox API v3 daily candle client & cache
│   ├── indicators.py                # 200-DMA, RSI, Z5D, Yang-Zhang vol & options pricing
│   ├── strategy_screener.py         # Historical monthly expiry screener & 5-Pillar Regime
│   ├── portfolio_simulator.py       # SPAN margin tracking, greedy allocation & settlement
│   └── performance_metrics.py       # Institutional CAGR, Drawdown, Win Rate & exporters
└── README.md                        # Documentation & methodology guide
```

---

## 🗂️ Branches

- **`main`**: Latest v3.0 Short OTM Put & Worthless Expiry Harvester (Dashboard & CLI).
- **`v1`**: Original v1.0 2024 Multi-Year Low screener code.

---

## 📄 License
MIT License.
