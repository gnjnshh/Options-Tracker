# 📈 Upstox F&O Option Selling Screener & Tracker

A quantitative options selling screener and probability engine powered by the **Upstox Developer API (v2 & v3)**. Designed for theta-decay strategies (OTM Short Puts, Bull Put Credit Spreads, Short Strangles) targeting high-probability candidates.

🌐 **Live Web Dashboard:** [https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)

---

## 🔒 Security Architecture (Public Repo + Private API)

This repository is **completely public**, but your personal Upstox API credentials remain **100% private and secure**:

1. **Browser `localStorage` Persistence**:
   - When you open the hosted GitHub Page ([https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)), enter or load your Upstox Bearer token **once**.
   - The token is saved in your browser's isolated `localStorage` on your device.
   - **Whenever you reopen this GitHub page on your laptop or phone, it automatically retrieves your saved token so you don't have to input it every time!**
   - Because `localStorage` stays strictly within your client-side browser, your token is **never transmitted to GitHub or any third-party server**, and is never visible to anyone else visiting your public repository.
   - You can also click **"📁 Load from Upstox API.txt"** to instantly import your token file with a single click.

2. **Local Python Execution via `.env`**:
   - For running the Python CLI tool locally, your credentials are saved in `.env` (or automatically discovered from your desktop token file).
   - `.gitignore` strictly prevents `.env`, `*.token`, `*.txt` credentials, and output datasets from ever being committed to git.

---

## 🏛️ Quantitative Strategy Pillars

The screener filters out speculative traps and targets high-conviction theta decay opportunities:

1. **2024 Multi-Year Historical Low Base**:
   - Compares spot prices against the multi-year support range since 2024-01-01 (e.g. VOLTAS near ₹1,053.40).
   - Identifies structural demand zones and safe institutional floors.
2. **Technically Oversold**:
   - Pullback into oversold territory: Wilder's RSI(14) $\le 40$, Money Flow Index (14) $\le 45$, Bollinger %B(20, 2) $\le 0.28$.
3. **Fundamental Quality ("Doesn't Deserve the Dip")**:
   - Upstox Fundamentals API integration: Company ROE $\ge$ Sector ROE, ROCE $\ge$ Sector ROCE, positive YoY net profit growth, and low down-day distribution volume (DownVol $\le 1.15\times$).
4. **Stagnant Volatility ("Expires Worthless")**:
   - Realized Volatility Compression: $\text{HV}(10) / \text{HV}(20) \le 0.95$ and $\text{HV}(20) \le 28\%$.
   - Non-trending consolidation regime: $\text{ADX}(14) \le 23$.
   - Positive Volatility Risk Premium (VRP): Option $\text{IV} > \text{HV}(20)$.
5. **High F&O Liquidity & OI Floor**:
   - High option chain volume, tight bid-ask spreads ($\le 1.5\%$), and recommended short put strikes at or below the primary Put Open Interest (OI) support wall.

---

## 🚀 Quick Start

### Option A: Use the Hosted Web Dashboard (GitHub Pages)

1. Open **[https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)**.
2. Paste your Upstox Bearer token (or click **"📁 Load from Upstox API.txt"**).
3. Click **"Scan Live via Upstox API"**.
4. Your token is now remembered on that browser—every time you revisit the link, your credentials are already loaded!

> **Viewing on GitHub Pages (Zero build setup required):**
> 1. Go to your repo: **[https://github.com/gnjnshh/Options-Tracker](https://github.com/gnjnshh/Options-Tracker)**
> 2. Click **Settings** > **Pages** (in the left navigation).
> 3. Under **Build and deployment** > **Source**, choose **Deploy from a branch** (`main` / root `/`).
> 4. Click **Save**. Your page is immediately live at **[https://gnjnshh.github.io/Options-Tracker/](https://gnjnshh.github.io/Options-Tracker/)**!

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
- **Scan liquid F&O basket (Top 40):**
  ```bash
  python upstox_fno_option_screener.py
  ```
- **Scan ALL ~200+ NSE F&O equities across the entire market:**
  ```bash
  python upstox_fno_option_screener.py --symbols all --max-symbols 250
  ```
- **Scan specific tickers:**
  ```bash
  python upstox_fno_option_screener.py --symbols VOLTAS,ASIANPAINT,TCS,HDFCBANK --expiry current_month
  ```
- **Offline Simulation / Demo Mode (No API token required):**
  ```bash
  python upstox_fno_option_screener.py --demo
  ```

---

## 📊 Sample Output Table

```text
======================================================================================================================
 UPSTOX F&O OPTION SELLING SCREENER — 'UNDESERVED OVERSOLD + STAGNANT VOLATILITY (THETA DECAY)'
======================================================================================================================
SYMBOL          SPOT  RSI14    %B   ROE/SEC  HV10/20   ADX   IV/HV20 RECOMMENDED SHORT PUT     POP%  SCORE
----------------------------------------------------------------------------------------------------------------------
VOLTAS       1053.40   34.0  0.03    16/13%    0.64x  15.5  26.3/8.3 1000 PE @ INR 5.1 (d-0.16)  87.1   89.0
ASIANPAINT   2390.00   34.0  0.03    28/18%    0.64x  14.9  23.1/7.9 2300 PE @ INR 14.6 (d-0.22)  81.7   87.0
----------------------------------------------------------------------------------------------------------------------
Qualified Candidates: 2 / 10 screened F&O stocks.
Saved full screener report to: upstox_option_selling_candidates.csv
```

---

## 🛠️ Project Structure

```text
Options-Tracker/
├── .env.example                  # Safe configuration template (git-tracked)
├── .env                          # Your private API token (git-ignored, never pushed)
├── .gitignore                    # Ensures all secrets and tokens remain private
├── index.html                    # Single-page dashboard with localStorage persistence
├── upstox_fno_option_screener.py # Python CLI screener with automatic .env loader
└── README.md                     # Documentation & usage instructions
```

---

## 📄 License
MIT License.
