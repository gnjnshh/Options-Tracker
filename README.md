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
     4. Near 2024 Multi-Year Base (<25% Dist)
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
   - **Pillar II — Structural Floor:** $\text{Spot} / 200\text{-DMA} \ge 0.92\text{x}$ and 2024–2026 Base tracking.
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

## 🛠️ Project Structure

```text
Options-Tracker/
├── .env.example                     # Safe configuration template (git-tracked)
├── .env                             # Your private API token (git-ignored, never pushed)
├── .gitignore                       # Ensures all secrets and tokens remain private
├── index.html                       # Web Dashboard v3.0 (Pure Short Put & Volume Harvester)
├── upstox_fno_option_screener.py    # Python CLI screener v3.0 (Pure Option Selling Engine)
├── upstox_fno_option_screener_v2.py # Entry point alias to latest screener
└── README.md                        # Documentation & methodology guide
```

---

## 🗂️ Branches

- **`main`**: Latest v3.0 Short OTM Put & Worthless Expiry Harvester (Dashboard & CLI).
- **`v1`**: Original v1.0 2024 Multi-Year Low screener code.

---

## 📄 License
MIT License.
