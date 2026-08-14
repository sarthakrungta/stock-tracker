"""
Simple Indian stock portfolio tracker.

- Stores holdings in Postgres (connection string via DATABASE_URL), with each
  holding owned by a user account. Schema changes go through Flask-Migrate
  (Alembic) - see migrations/.
- Fetches live prices for free via yfinance (Yahoo Finance), using the
  ".NS" suffix for NSE and ".BO" for BSE.
- Generates Claude-friendly analysis prompts (whole portfolio / single stock)
  that you copy-paste into Claude chat yourself. This app never calls any
  AI API - it just builds the prompt text for you.

Accounts are invite-only: there is no public signup page. Create accounts with
    flask --app app create-user <username>
"""

import os
import time
from pathlib import Path

import click
from flask import Flask, jsonify, request, render_template, redirect, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
import yfinance as yf

APP_DIR = Path(__file__).resolve().parent
PRICE_CACHE_TTL = 30  # seconds


def _database_uri():
    url = os.environ["DATABASE_URL"]
    # Railway/Heroku-style URLs use the "postgres://" scheme; SQLAlchemy needs "postgresql://".
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ["SECRET_KEY"]
app.config["SQLALCHEMY_DATABASE_URI"] = _database_uri()
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
migrate = Migrate(app, db)

login_manager = LoginManager(app)
login_manager.login_view = "login"

_price_cache = {}  # ticker -> (price, fetched_at)


# ----------------------------------------------------------------- models --

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Holding(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    symbol = db.Column(db.String(20), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    exchange = db.Column(db.String(10), nullable=False, default="NSE")
    quantity = db.Column(db.Float, nullable=False)
    buy_price = db.Column(db.Float, nullable=False)
    buy_date = db.Column(db.String(20), nullable=True)

    def to_dict(self):
        return {
            "id": str(self.id),
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "quantity": self.quantity,
            "buy_price": self.buy_price,
            "buy_date": self.buy_date,
        }


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ------------------------------------------------------------------ prices --

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


# --------------------------------------------------------------------- auth --

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("index"))
        error = "Invalid username or password"

    return render_template("login.html", error=error)


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ---------------------------------------------------------------- routes --

@app.route("/")
@login_required
def index():
    return render_template("index.html", username=current_user.username)


@app.route("/api/holdings", methods=["GET"])
@login_required
def get_holdings():
    holdings = [h.to_dict() for h in Holding.query.filter_by(user_id=current_user.id)]
    enriched, summary = enrich(holdings)
    return jsonify({"holdings": enriched, "summary": summary})


@app.route("/api/holdings", methods=["POST"])
@login_required
def add_holding():
    body = request.get_json(force=True)
    required = ["symbol", "name", "exchange", "quantity", "buy_price"]
    missing = [f for f in required if f not in body or body[f] in (None, "")]
    if missing:
        return jsonify({"error": f"Missing fields: {', '.join(missing)}"}), 400

    holding = Holding(
        user_id=current_user.id,
        symbol=body["symbol"].strip().upper(),
        name=body["name"].strip(),
        exchange=body.get("exchange", "NSE").strip().upper(),
        quantity=float(body["quantity"]),
        buy_price=float(body["buy_price"]),
        buy_date=body.get("buy_date") or None,
    )
    db.session.add(holding)
    db.session.commit()
    return jsonify(holding.to_dict()), 201


@app.route("/api/holdings/<holding_id>", methods=["PUT"])
@login_required
def update_holding(holding_id):
    body = request.get_json(force=True)
    holding = Holding.query.filter_by(id=holding_id, user_id=current_user.id).first()
    if not holding:
        return jsonify({"error": "Not found"}), 404

    for field in ["symbol", "name", "exchange", "buy_date"]:
        if field in body and body[field] not in (None, ""):
            value = body[field].strip().upper() if field in ("symbol", "exchange") else body[field]
            setattr(holding, field, value)
    for field in ["quantity", "buy_price"]:
        if field in body and body[field] not in (None, ""):
            setattr(holding, field, float(body[field]))

    db.session.commit()
    return jsonify(holding.to_dict())


@app.route("/api/holdings/<holding_id>", methods=["DELETE"])
@login_required
def delete_holding(holding_id):
    holding = Holding.query.filter_by(id=holding_id, user_id=current_user.id).first()
    if not holding:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(holding)
    db.session.commit()
    return jsonify({"ok": True})


@app.route("/api/refresh", methods=["POST"])
@login_required
def refresh_prices():
    holdings = [h.to_dict() for h in Holding.query.filter_by(user_id=current_user.id)]
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
@login_required
def prompt_portfolio():
    holdings = [h.to_dict() for h in Holding.query.filter_by(user_id=current_user.id)]
    enriched, summary = enrich(holdings)
    return jsonify({"prompt": build_portfolio_prompt(enriched, summary)})


@app.route("/api/prompts/holding/<holding_id>", methods=["GET"])
@login_required
def prompt_holding(holding_id):
    holding = Holding.query.filter_by(id=holding_id, user_id=current_user.id).first()
    if not holding:
        return jsonify({"error": "Not found"}), 404
    enriched, _ = enrich([holding.to_dict()])
    return jsonify({"prompt": build_stock_prompt(enriched[0])})


# --------------------------------------------------------------- CLI --

@app.cli.command("create-user")
@click.argument("username")
def create_user(username):
    """Create a new invite-only account: flask --app app create-user <username>"""
    if User.query.filter_by(username=username).first():
        click.echo(f"User '{username}' already exists.")
        return
    password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
    user = User(username=username, password_hash=generate_password_hash(password))
    db.session.add(user)
    db.session.commit()
    click.echo(f"Created user '{username}'.")


if __name__ == "__main__":
    app.run(debug=True, port=5050)
