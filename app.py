"""
Simple Indian stock portfolio tracker.

- Stores holdings in a local JSON file (data/portfolio.json).
- Fetches live prices for free via yfinance (Yahoo Finance), using the
  ".NS" suffix for NSE and ".BO" for BSE.
- Generates Claude-friendly analysis prompts (whole portfolio / single stock)
  that you copy-paste into Claude chat yourself. This app never calls any
  AI API - it just builds the prompt text for you.
"""

import json
import os
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, request, render_template
import yfinance as yf

APP_DIR = Path(__file__).resolve().parent
DATA_FILE = APP_DIR / "data" / "portfolio.json"
PRICE_CACHE_TTL = 30  # seconds

app = Flask(__name__)

_price_cache = {}  # ticker -> (price, fetched_at)


def load_holdings():
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_holdings(holdings):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(holdings, f, indent=2)


def yf_ticker(symbol, exchange):
    suffix = "NS" if exchange.upper() == "NSE" else "BO"
    return f"{symbol.upper()}.{suffix}"


def fetch_prices(tickers, force=False):
    """Fetch last price for a list of yfinance ticker strings, with a short cache."""
    now = time.time()
    to_fetch = [
        t for t in tickers
        if force or t not in _price_cache or now - _price_cache[t][1] > PRICE_CACHE_TTL
    ]
    if to_fetch:
        try:
            data = yf.Tickers(" ".join(to_fetch))
            for t in to_fetch:
                price = None
                try:
                    price = data.tickers[t].fast_info["last_price"]
                except Exception:
                    price = None
                if price is not None:
                    _price_cache[t] = (float(price), now)
        except Exception:
            # Network issue or Yahoo hiccup - leave cache as-is, fall back below.
            pass
    return {t: _price_cache.get(t, (None, 0))[0] for t in tickers}


def enrich(holdings):
    tickers = [yf_ticker(h["symbol"], h["exchange"]) for h in holdings]
    prices = fetch_prices(tickers)

    enriched = []
    total_invested = 0.0
    total_current = 0.0

    for h in holdings:
        t = yf_ticker(h["symbol"], h["exchange"])
        current_price = prices.get(t)
        qty = h["quantity"]
        buy_price = h["buy_price"]
        invested = qty * buy_price
        current_value = qty * current_price if current_price is not None else None
        pl = current_value - invested if current_value is not None else None
        pl_pct = (pl / invested * 100) if pl is not None and invested else None

        total_invested += invested
        if current_value is not None:
            total_current += current_value

        enriched.append({
            **h,
            "ticker": t,
            "current_price": current_price,
            "invested": round(invested, 2),
            "current_value": round(current_value, 2) if current_value is not None else None,
            "pl": round(pl, 2) if pl is not None else None,
            "pl_pct": round(pl_pct, 2) if pl_pct is not None else None,
        })

    for e in enriched:
        e["weight_pct"] = (
            round(e["current_value"] / total_current * 100, 2)
            if e["current_value"] is not None and total_current
            else None
        )

    summary = {
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current, 2),
        "total_pl": round(total_current - total_invested, 2),
        "total_pl_pct": round((total_current - total_invested) / total_invested * 100, 2) if total_invested else 0,
    }
    return enriched, summary


# ---------------------------------------------------------------- routes --

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/holdings", methods=["GET"])
def get_holdings():
    holdings = load_holdings()
    enriched, summary = enrich(holdings)
    return jsonify({"holdings": enriched, "summary": summary})


@app.route("/api/holdings", methods=["POST"])
def add_holding():
    body = request.get_json(force=True)
    required = ["symbol", "name", "exchange", "quantity", "buy_price"]
    missing = [f for f in required if f not in body or body[f] in (None, "")]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    holding = {
        "id": str(uuid.uuid4()),
        "symbol": body["symbol"].strip().upper(),
        "name": body["name"].strip(),
        "exchange": body.get("exchange", "NSE").strip().upper(),
        "quantity": float(body["quantity"]),
        "buy_price": float(body["buy_price"]),
        "buy_date": body.get("buy_date") or None,
    }
    holdings = load_holdings()
    holdings.append(holding)
    save_holdings(holdings)
    return jsonify(holding), 201


@app.route("/api/holdings/<holding_id>", methods=["PUT"])
def update_holding(holding_id):
    body = request.get_json(force=True)
    holdings = load_holdings()
    for h in holdings:
        if h["id"] == holding_id:
            for field in ["symbol", "name", "exchange", "buy_date"]:
                if field in body and body[field] not in (None, ""):
                    h[field] = body[field].strip().upper() if field in ("symbol", "exchange") else body[field]
            for field in ["quantity", "buy_price"]:
                if field in body and body[field] not in (None, ""):
                    h[field] = float(body[field])
            save_holdings(holdings)
            return jsonify(h)
    return jsonify({"error": "Not found"}), 404


@app.route("/api/holdings/<holding_id>", methods=["DELETE"])
def delete_holding(holding_id):
    holdings = load_holdings()
    new_holdings = [h for h in holdings if h["id"] != holding_id]
    if len(new_holdings) == len(holdings):
        return jsonify({"error": "Not found"}), 404
    save_holdings(new_holdings)
    return jsonify({"ok": True})


@app.route("/api/refresh", methods=["POST"])
def refresh_prices():
    holdings = load_holdings()
    tickers = [yf_ticker(h["symbol"], h["exchange"]) for h in holdings]
    fetch_prices(tickers, force=True)
    enriched, summary = enrich(holdings)
    return jsonify({"holdings": enriched, "summary": summary})


# ------------------------------------------------------------- prompts --

def format_row(e):
    price = f"₹{e['current_price']:.2f}" if e["current_price"] is not None else "N/A"
    pl = f"₹{e['pl']:.2f} ({e['pl_pct']:.2f}%)" if e["pl"] is not None else "N/A"
    weight = f"{e['weight_pct']:.2f}%" if e.get("weight_pct") is not None else "N/A"
    return (
        f"- {e['name']} ({e['symbol']}, {e['exchange']}): "
        f"Qty {e['quantity']}, Buy Price ₹{e['buy_price']:.2f}, Current Price {price}, "
        f"Invested ₹{e['invested']:.2f}, Current Value "
        f"{'₹%.2f' % e['current_value'] if e['current_value'] is not None else 'N/A'}, "
        f"P/L {pl}, Portfolio Weight {weight}"
        + (f", Buy Date {e['buy_date']}" if e.get("buy_date") else "")
    )


def build_portfolio_prompt(enriched, summary):
    lines = [format_row(e) for e in enriched]
    holdings_block = "\n".join(lines) if lines else "(no holdings added yet)"

    return f"""
Act as an equity research analyst reviewing my Indian stock portfolio.

IMPORTANT:
- Use CURRENT information available today.
- Research the latest quarterly/annual financial results, management commentary,
  recent company news, sector developments and Indian macro environment.
- Do not rely on stale model knowledge when current information can be searched.
- Keep the response concise and decision-focused. Maximum ~800 words.
- Avoid generic investing advice.

MY PORTFOLIO

{holdings_block}

Portfolio totals:
- Invested: ₹{summary['total_invested']:.2f}
- Current Value: ₹{summary['total_current_value']:.2f}
- P/L: ₹{summary['total_pl']:.2f} ({summary['total_pl_pct']:.2f}%)

Analyse the portfolio using this exact structure:

## Portfolio Verdict

Give me a 3-5 sentence assessment of the portfolio TODAY.

Include:

Overall Portfolio Score: X/10
Confidence in Assessment: XX%

Then tell me whether the portfolio currently looks:
Strong / Reasonable / Mixed / Weak / High Risk

## Holdings Snapshot

For EACH holding, give only:

Company | Outlook | Confidence | Key Reason | Main Risk

Outlook must be one of:
🟢 Positive
🟡 Neutral / Uncertain
🔴 Negative

Confidence: 0-100%.

Base the assessment primarily on:
- latest financial performance
- valuation where relevant
- earnings/business momentum
- balance sheet quality
- sector environment
- recent company developments

## What Matters Most Right Now

Identify the 3-5 MOST IMPORTANT things affecting this portfolio today.

Ignore minor news.

Examples:
- earnings deterioration/improvement
- valuation risk
- government policy
- interest rates
- INR movements
- commodity cycles
- sector demand
- major company-specific developments

Explain each in 1-2 sentences.

## Portfolio Risks

Identify only meaningful risks.

Highlight:
- excessive stock concentration
- sector concentration
- correlated holdings
- weak fundamentals
- expensive valuations
- cyclical exposure

Rate overall portfolio risk:

Low / Moderate / Moderately High / High

## 6-12 Month Outlook

Give three scenarios for the PORTFOLIO:

Bull Case:
- Expected portfolio return range
- What would need to happen

Base Case:
- Expected portfolio return range
- Most likely drivers

Bear Case:
- Expected portfolio return range
- What could cause it

Then state:

Most Likely Scenario: Bull / Base / Bear
Confidence: XX%

These are probability-based estimates, not guarantees.

## Bottom Line

Finish with ONLY 3 bullet points:

1. Strongest part of my portfolio
2. Biggest concern
3. Most important thing I should monitor next

Be opinionated where the evidence supports it. Do not pad the answer with generic disclaimers.
"""


def build_stock_prompt(e):
    price = (
        f"₹{e['current_price']:.2f}"
        if e["current_price"] is not None
        else "N/A"
    )

    invested = f"₹{e['invested']:.2f}"

    current_value = (
        f"₹{e['current_value']:.2f}"
        if e["current_value"] is not None
        else "N/A"
    )

    pl = (
        f"₹{e['pl']:.2f} ({e['pl_pct']:.2f}%)"
        if e["pl"] is not None
        else "N/A"
    )

    return f"""
Act as an equity research analyst analysing {e['name']}
({e['symbol']}, {e['exchange']}) for an existing shareholder.

Use CURRENT information available today.

You MUST research:
- latest quarterly/annual results
- revenue and profit growth
- margins
- debt / balance sheet
- cash flow where important
- management commentary/guidance
- valuation versus its history and relevant peers
- important company news
- current sector conditions
- Indian macro/regulatory developments where relevant

Do NOT rely on stale model knowledge when newer information is available.

MY POSITION

Quantity: {e['quantity']}
Average Buy Price: ₹{e['buy_price']:.2f}
Current Price: {price}
Invested: {invested}
Current Value: {current_value}
P/L: {pl}
{f"Buy Date: {e['buy_date']}" if e.get('buy_date') else ""}

Keep the entire response concise: approximately 500-700 words.

Use this exact structure:

## Verdict

Current View:
🟢 Positive / 🟡 Neutral-Uncertain / 🔴 Negative

Fundamental Score: X/10
Valuation Score: X/10
Risk Score: X/10
Overall Confidence: XX%

Give me the investment thesis in no more than 4 sentences.

## Latest Financial Picture

Show only the important numbers/trends from the latest results:

- Revenue:
- Profit:
- Margins:
- Debt / Balance Sheet:
- Cash Flow:
- Management Guidance:

Compare against the previous relevant period so I can see whether the business is
improving, stable or deteriorating.

Then state:

Financial Momentum:
Improving / Stable / Deteriorating

## What Is Driving the Stock NOW?

Give the 3 most important current factors affecting the stock.

These can include company news, earnings, valuation, regulation,
sector trends, commodity prices, competition or macro conditions.

Do not include insignificant news.

## Valuation

Tell me whether the stock appears:

Cheap / Reasonable / Expensive / Extremely Expensive

Use relevant valuation metrics and peer/historical comparisons where possible.

Explain in maximum 3 sentences.

## Risks & Catalysts

Top 3 Risks:
1.
2.
3.

Top 3 Catalysts:
1.
2.
3.

## 6-12 Month Prediction

Give reasonable scenario ranges based on fundamentals,
valuation, earnings expectations and current market conditions.

Bull Case:
₹X - ₹Y
Probability: XX%

Base Case:
₹X - ₹Y
Probability: XX%

Bear Case:
₹X - ₹Y
Probability: XX%

Most Likely 12-Month Range: ₹X - ₹Y

Expected Direction:
Strongly Up / Moderately Up / Sideways / Moderately Down / Strongly Down

Prediction Confidence: XX%

Explain the prediction in no more than 4 sentences.

Do not manufacture precision. Wider ranges should be used when uncertainty is high.

## My Position

Given my average entry price of ₹{e['buy_price']:.2f}, tell me:

- What has changed in the investment thesis since my entry?
- Is the business currently performing better or worse than what today's valuation implies?
- What 2-3 specific metrics/events should I monitor next?

Do NOT give a generic explanation of the company.
Focus on information that affects the investment case TODAY.
"""

@app.route("/api/prompts/portfolio", methods=["GET"])
def prompt_portfolio():
    holdings = load_holdings()
    enriched, summary = enrich(holdings)
    return jsonify({"prompt": build_portfolio_prompt(enriched, summary)})


@app.route("/api/prompts/holding/<holding_id>", methods=["GET"])
def prompt_holding(holding_id):
    holdings = load_holdings()
    enriched, _ = enrich(holdings)
    for e in enriched:
        if e["id"] == holding_id:
            return jsonify({"prompt": build_stock_prompt(e)})
    return jsonify({"error": "Not found"}), 404


if __name__ == "__main__":
    app.run(debug=True, port=5050)
