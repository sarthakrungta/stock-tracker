# Stock Portfolio Tracker

An app for tracking Indian stock holdings, with free live prices
(via Yahoo Finance / `yfinance`) and one-click Claude analysis prompts.
Each user has their own private, invite-only account and portfolio.

## Run it locally

```bash
cd stock-tracker
pip3 install -r requirements.txt
export SECRET_KEY=dev-secret-change-me
flask --app app create-user me        # first run only: create your account
python3 app.py
```

Open http://127.0.0.1:5050 in your browser and log in with the account you just created.

If you have an existing `data/portfolio.json` from before accounts were added, import
it into a user once:

```bash
flask --app app import-json me
```

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
- **Accounts**: invite-only. There's no public signup page — the owner creates an
  account for each person (see below). Every user only ever sees their own holdings.
- **Storage**: holdings live in a SQLite database (`data/portfolio.db` by default,
  or wherever `DATA_DIR` points), one file for all users.

## Notes

- Locally this runs via `python3 app.py` (Flask dev server) — fine for local use.
  In production it runs under `gunicorn` (see Deploying below).
- `yfinance` scrapes Yahoo Finance's public endpoints; it's free but unofficial,
  so if Yahoo changes something upstream, `pip3 install --upgrade yfinance` is
  usually the fix.

## Deploying on Render

1. Push this repo to GitHub (or connect it directly if already pushed) and create
   a new **Web Service** on Render pointing at it.
2. Build command: `pip install -r requirements.txt`
   Start command: `gunicorn app:app` (already declared in the `Procfile`).
3. Add a **Persistent Disk** to the service (e.g. mounted at `/var/data`) so the
   SQLite database survives redeploys and restarts — it's the only thing kept on
   local disk, and Render's default filesystem is otherwise ephemeral.
4. Set environment variables on the service:
   - `SECRET_KEY` — any long random string (used to sign session cookies).
   - `DATA_DIR` — the disk mount path, e.g. `/var/data`.
5. Deploy. On first deploy the database is created automatically but has no
   users yet — see "Inviting a user" below.

### Inviting a user

Accounts are created from the command line, not a signup form. Run this against
the deployed service (Render's dashboard has a "Shell" tab for the service, or
use a one-off job):

```bash
flask --app app create-user <username>
```

It prompts for a password interactively. Share the username/password with the
person you're inviting; they log in at your Render URL.

If you're migrating your own existing local holdings, copy `data/portfolio.json`
onto the instance (or re-add them by hand) and run:

```bash
flask --app app import-json <username>
```
