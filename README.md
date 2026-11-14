# Strava local dashboard

A small Flask application that reads the local MySQL `strava` database. It includes
a dashboard, activity feed, route directory, athlete directory, and individual
athlete profiles. Empty tables display friendly empty states.

## Requirements

- Python 3.10 or later
- MySQL Server 8.0 with the `strava` database and tables created from `strava_schema.sql`

## Run on Windows

Open PowerShell in this project folder and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `DB_PASSWORD` to your local MySQL password. Keep `.env` private;
it is excluded from Git by `.gitignore`.

Then start the dashboard:

```powershell
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The sidebar links to the
activity feed (`/activities`), route directory (`/routes`), and athlete directory
(`/users`). Select an athlete to view their profile, activities, routes, and stats.
To check database connectivity, visit [http://127.0.0.1:5000/healthz](http://127.0.0.1:5000/healthz).

The app is read-only. Add data to MySQL and refresh a page to see it; forms or data
import can be added later to match the desired workflows.
