# Stock Portfolio Tracker

A simple local app for tracking Indian stock holdings, with free live prices
(via Yahoo Finance / `yfinance`) and one-click Claude analysis prompts.

## Run it

```bash
cd stock-tracker
pip3 install -r requirements.txt
python3 app.py
```

Open http://127.0.0.1:5050 in your browser.

## How it works

- **Add holdings**: symbol, company name, exchange (NSE/BSE), quantity, buy price, buy date.
  - For NSE, use the normal trading symbol (RELIANCE, TCS, INFY, HDFCBANK, ...).
  - For BSE, use the numeric scrip code (e.g. 500325).
- **Live prices**: fetched from Yahoo Finance for free, no API key. Prices are cached
  for 30 seconds; click "Refresh Prices" to force an update. Yahoo occasionally
  rate-limits or hiccups — if a price shows `—`, just refresh again in a moment.
- **P/L and weights**: computed automatically per holding and for the portfolio total.
- **Analysis prompts**: click "Analyze Full Portfolio" (top bar) or "Analyze" on any
  row. Each opens a modal with a ready-made prompt built from your live data —
  copy it and paste into Claude (or any AI chat) yourself. The app never calls an
  AI API itself; it only generates the prompt text.
- **Storage**: holdings live in `data/portfolio.json` on your machine. No cloud,
  no accounts.

## Notes

- This is a Flask dev server, meant for local personal use only.
- `yfinance` scrapes Yahoo Finance's public endpoints; it's free but unofficial,
  so if Yahoo changes something upstream, `pip3 install --upgrade yfinance` is
  usually the fix.
