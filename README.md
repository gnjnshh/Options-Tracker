# 📈 Upstox F&O Quant Screener — Worthless Expiry & VRP Harvester (v2.5)

Institutional-grade quantitative options screener powered by the **Upstox Developer API (v2 & v3)**.
Ranks liquid NSE F&O Short Puts and Bull Put Credit Spreads by **Empirical Probability of Expiring Worthless (POP% via Yang-Zhang Volatility)**, **True Volatility Risk Premium (VRP)**, and **Put OI Support Wall Cushion**.

🌐 **Live Web Dashboard:** [https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)

*(Note: The original v1.0 2024 Multi-Year Low screener is preserved on branch **[`v1`](https://github.com/gnjnshh/Options-Tracker/tree/v1)**).*

---

## 🔒 Security Architecture (Public Repo + Private API)

This repository is **completely public**, but your personal Upstox API credentials remain **100% private and secure**:

1. **Browser `localStorage` Client-Side Persistence**:
   - When you open the hosted GitHub Page ([https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)), enter or load your Upstox Bearer token **once**.
   - The token is saved in your browser's isolated `localStorage` on your device.
   - **Whenever you reopen this GitHub page on your laptop or phone, it automatically retrieves your saved token so you don't have to input it every time!**
   - Because `localStorage` stays strictly within your client-side browser, your token is **never transmitted to GitHub or any third-party server**, and is never visible to anyone else visiting your public repository.
   - You can also click **"📁 Load API File"** to instantly import your token file (`Upstox API.txt` or `.env`) with a single click.

2. **Local Python Execution via `.env`**:
   - For running the Python CLI tool locally, your credentials are saved in `.env` (or automatically discovered from your desktop token file `Upstox API.txt`).
   - `.gitignore` strictly prevents `.env`, `*.token`, `*.txt` credentials, and output datasets from ever being committed to git.

---

## 🏛️ Calibrated Quantitative Pillars & Bug Fixes

The v2.5 engine addresses and resolves common quantitative options screening pitfalls:

1. **Reversed V3 Candle Chronology Fix**:
   - Upstox `/v3/historical-candle` returns newest candles at index `0`. The engine reverses the candle series so that 5-day Z-scores ($Z_{5D}$) and momentum indicators have the correct sign.
2. **Strict Listed NSE Strike Snapping**:
   - Snaps short and hedge legs to actual listed NSE strike intervals (e.g. ₹10, ₹20, ₹50, ₹100). No fractional strikes (e.g. 1881.6 PE) and no negative RoR spreads.
3. **Empirical Probability of Expiring Worthless ($P_{\text{worthless}}$)**:
   - Evaluates exact lognormal survival probability $N(d_2)$ using 20-day **Yang-Zhang (2000) minimum-variance OHLC volatility ($\sigma_{\text{YZ}}$)**. Avoids inverted broker delta fields.
4. **True Volatility Risk Premium (VRP)**:
   - Requires $\text{Option IV} - \sigma_{\text{YZ}} \ge +2.0\%$ so you are statistically paid excess premium above realized market movement.
5. **Calibrated 5-Pillar Regime Guard**:
   - **Pillar I — Empirical POP & Safety Cushion:** Empirical $\text{POP} \ge 76\%$ and OTM cushion $\ge 5.0\%$ at or below Put OI Support Wall.
   - **Pillar II — Structural Floor:** $\text{Spot} / 200\text{-DMA} \ge 0.92\text{x}$ (captures pullbacks in secular compounders).
   - **Pillar III — Exhaustion / Non-Blowoff Regime:** $\text{RSI}(14) \le 60$ and $-2.60 \le Z_{5D} \le +1.10$ (rejects blowoffs and active crash waterfalls).
   - **Pillar IV — Futures Flow Guard:** Rejects stocks with 5-day Futures OI surge $> +3.0\%$ during price drops (aggressive short buildup).
   - **Pillar V — Positive VRP:** Excess premium harvest $\ge +2.0\%$.

---

## 🚀 Quick Start

### Option A: Use the Hosted Web Dashboard (GitHub Pages)

1. Open **[https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)**.
2. Paste your Upstox Bearer token (or click **"📁 Load API File"**).
3. Click **"🚀 Scan Live via Upstox API"**.
4. Your token is now remembered on that browser—every time you revisit the link, your credentials are already loaded!

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
Edit `.env`:
```env
UPSTOX_ACCESS_TOKEN=your_upstox_bearer_token_here
```
*(The screener also automatically detects `Upstox API.txt` on your Desktop if `.env` is omitted.)*

#### 3. Run the Screener

- **Offline Simulation / Verification Mode (Instant 41-symbol scan, no API token required):**
  ```bash
  python upstox_fno_option_screener.py --demo
  ```

- **Live Next-Month Expiry Rebound Scan:**
  ```bash
  python upstox_fno_option_screener.py --expiry next_month
  ```

- **Show Both Qualified and Filtered Stocks:**
  ```bash
  python upstox_fno_option_screener.py --demo --show-rejected
  ```

- **Sort by Pure Empirical POP %:**
  ```bash
  python upstox_fno_option_screener.py --demo --sort pure_pop
  ```

---

## 📊 Sample Screener Output

```text
==============================================================================================================================================
 UPSTOX F&O QUANT SCREENER v2.5 — WORTHLESS EXPIRY & VRP HARVESTER (CALIBRATED ENGINE)
 Objective: Maximum Empirical Probability of Expiring Worthless (POP%) + Positive Volatility Risk Premium
==============================================================================================================================================
 Qualified Candidates: 16 / 41 (39.0% pass rate)
 KPI Averages (Qualified): POP: 91.7% | Cushion: 5.8% | Spread RoR: 38.2% | True VRP: +6.5%
----------------------------------------------------------------------------------------------------------------------------------------------
RANK & SYMBOL  SPOT (INR) 200-DMA  RSI14/Z5D     FUT OI    IV/YZ        VRP     RECOMMENDED BULL PUT SPREAD    RoR%    POP%    CREDIT    SCORE  STATUS
----------------------------------------------------------------------------------------------------------------------------------------------
1. SIEMENS     3,624.0    1.03x    43.5/-0.95    -3.8%     22.9%/16.0%  +6.9%   Sell 3400P / Buy 3300P         35.4%   92.6%   INR 4,576 93.2   QUALIFIED
   [THESIS] Strike 3400 PE sits -6.2% below spot (at/below Put Wall 3400) with 92.6% Empirical POP and +6.9% VRP.
2. ABB         6,801.0    1.03x    41.2/-1.18    -2.9%     23.4%/16.2%  +7.2%   Sell 6400P / Buy 6200P         33.5%   91.4%   INR 6,268 92.9   QUALIFIED
   [THESIS] Strike 6400 PE sits -5.9% below spot (at/below Put Wall 6300) with 91.4% Empirical POP and +7.2% VRP.
3. DRREDDY     1,233.0    0.99x    38.4/-1.42    -3.4%     21.8%/14.9%  +6.9%   Sell 1160P / Buy 1120P         26.9%   93.3%   INR 5,294 91.8   QUALIFIED
   [THESIS] Strike 1160 PE sits -5.9% below spot (at/below Put Wall 1140) with 93.3% Empirical POP and +6.9% VRP.
----------------------------------------------------------------------------------------------------------------------------------------------
Saved full quantitative screener report to: upstox_worthless_expiry_ranked_v2_5.csv
```

---

## 🛠️ Project Structure

```text
Options-Tracker/
├── .env.example                     # Safe configuration template (git-tracked)
├── .env                             # Your private API token (git-ignored, never pushed)
├── .gitignore                       # Ensures all secrets and tokens remain private
├── index.html                       # Web Dashboard v2.5 (Worthless Expiry & VRP Harvester)
├── upstox_fno_option_screener.py    # Python CLI screener v2.5 (Reversed candles & listed strikes)
├── upstox_fno_option_screener_v2.py # Entry point alias to latest screener
└── README.md                        # Documentation & methodology guide
```

---

## 🗂️ Branches

- **`main`**: Latest v2.5 Worthless Expiry & VRP Harvester (Dashboard & CLI).
- **`v1`**: Original v1.0 2024 Multi-Year Low screener code.

---

## 📄 License
MIT License.
