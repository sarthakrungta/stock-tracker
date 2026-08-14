# Stock Portfolio Tracker

An app for tracking Indian stock holdings, with free live prices
(via Yahoo Finance / `yfinance`) and one-click Claude analysis prompts.
Each user has their own private, invite-only account and portfolio.

## Run it locally

Needs a Postgres database to connect to (a free local Postgres install works fine —
`brew install postgresql@14` on macOS, then `createdb stocktracker`).

```bash
cd stock-tracker
pip3 install -r requirements.txt
export SECRET_KEY=dev-secret-change-me
export DATABASE_URL=postgresql:///stocktracker    # adjust to your local Postgres
flask --app app db upgrade                        # creates the tables
flask --app app create-user me                     # first run only: create your account
python3 app.py
```

Open http://127.0.0.1:5050 in your browser and log in with the account you just created.

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
- **Storage**: Postgres (connection string via `DATABASE_URL`), two tables —
  `user` and `holding` — managed through Flask-Migrate/Alembic (`migrations/`).

## Notes

- Locally this runs via `python3 app.py` (Flask dev server) — fine for local use.
  In production it runs under `gunicorn` (see Deploying below).
- `yfinance` scrapes Yahoo Finance's public endpoints; it's free but unofficial,
  so if Yahoo changes something upstream, `pip3 install --upgrade yfinance` is
  usually the fix.

## Changing the schema (e.g. adding a column)

Schema changes go through Alembic migrations, so they apply the same way locally
and in production:

```bash
# 1. Edit the model in app.py, e.g. add a column to Holding:
#    sector = db.Column(db.String(50))

# 2. Generate a migration from the model diff:
flask --app app db migrate -m "add sector to holding"

# 3. Review the generated file in migrations/versions/ (autogenerate is usually
#    right for simple additive changes, but always read it before applying).

# 4. Apply it:
flask --app app db upgrade
```

In production, run `flask --app app db upgrade` (via `railway run`, see below)
after deploying the new code — same command, same migration file.

## Visualizing / editing the data

Since storage is Postgres, any standard Postgres GUI works — point it at the
`DATABASE_URL` connection string:
- **TablePlus / DBeaver / pgAdmin** (desktop apps) — browse and edit rows directly.
- **Railway's dashboard** — the Postgres service has a built-in "Data" tab for
  browsing/querying tables without installing anything.
- **`psql`** from the terminal for quick queries:
  ```bash
  psql "$DATABASE_URL"
  ```

## Deploying on Railway

1. Push this repo to GitHub, then in Railway: **New Project → Deploy from GitHub repo**
   and pick it (or use the Railway CLI: `railway init` + `railway up` from this folder).
2. Add a **Postgres** database to the project (**New → Database → Add PostgreSQL**).
   Railway automatically injects `DATABASE_URL` into your app service's environment
   when both are in the same project — no manual wiring needed.
3. Railway auto-detects Python and honors the `Procfile` (`web: gunicorn app:app`) as
   the start command — no build/start config needed.
4. Set environment variables on the app service (Service → Variables):
   - `SECRET_KEY` — any long random string (used to sign session cookies).
5. Deploy, then run the initial migration once against the deployed database:
   ```bash
   railway run --service <app-service-name> flask --app app db upgrade
   ```
6. Railway gives you a public `*.up.railway.app` URL (or attach a custom domain)
   with HTTPS handled automatically. The database has no users yet — see
   "Inviting a user" below.

### Inviting a user

Accounts are created from the command line, not a signup form. Run this against
the deployed service using the Railway CLI, which runs a command inside the live
container:

```bash
railway run --service <app-service-name> flask --app app create-user <username>
```

(Alternatively, open a shell to the service from the Railway dashboard and run
`flask --app app create-user <username>` directly.) It prompts for a password
interactively. Share the username/password with the person you're inviting; they
log in at your Railway URL.
