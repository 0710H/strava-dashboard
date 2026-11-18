# Strava local dashboard

A local Flask dashboard for a MySQL `strava` database. It includes a training
dashboard, activity feed with activity CRUD, route and athlete directories, and
individual athlete profiles. This demonstration app has no login; activity
records are associated with an existing athlete selected in the form.

## Requirements

- Python 3.10 or later
- MySQL Server 8.0
- A MySQL database initialized with `strava_schema.sql`

## Database setup

Start MySQL, then run these commands from this project directory in a terminal
with the MySQL command-line client installed:

```sh
mysql -u root -p < strava_schema.sql
mysql -u root -p strava < demo_data.sql
```

The schema script creates the `strava` database and its tables. The demo-data
script inserts sample athletes, routes, activities, kudos, comments, and follows.
Alternatively, open and execute each SQL file in MySQL Workbench.

## Install and configure

### macOS or Linux

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

### Windows PowerShell

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` and set `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD`
for your local MySQL server. Keep `.env` private; it is excluded from Git.

## Run and use the dashboard

Start the app from this directory:

```sh
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The database health endpoint
is [http://127.0.0.1:5000/healthz](http://127.0.0.1:5000/healthz).

- **Read:** The dashboard, activity feed, and athlete profiles display activities.
- **Create:** Open **Activities**, choose **Log activity**, select an existing
  athlete, and enter a title, distance in km, date/time, and duration in seconds.
  A route is optional; routes shared by any athlete can be selected.
- **Update:** Choose **Edit** beside an activity, change its details, and save.
- **Delete:** Choose **Delete**, review the number of related kudos and comments,
  then explicitly confirm. The existing schema cascades activity deletion to
  those related records.

For a focused CRUD regression check, run:

```sh
python -m unittest discover -s tests -v
```

The app is intended for local project demonstration and does not provide
authentication or authorization. Do not expose it to an untrusted network.
