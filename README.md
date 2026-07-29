# WRU TGS Tracker

Linux-hosted PostgreSQL web app for traffic guidance / MoA workflow tracking. Same Ventia styling and logos as [VenInspect](https://github.com/McKrackenAU/VenInspect).

## Features

- **Site register** matching the spreadsheet: road name, site number, start dates, MoA must-have date, priority, workflow stages, comments, MoA number/submission date
- **Workflow progress** as clickable stage cells (TGS → TMD → Plan → MoA → TRIMS → Ready for Works)
- **Priority** auto-calculated (1 if indicative start is within 21 days)
- **Custom columns** — any user can add or remove columns (text, number, date, checkbox, select)
- **Tracking** — append status/chase/issue notes per site
- **Documents** — upload attachments and download them again
- **Lightweight UI** — dense table, no heavy frontend build step

## Stack

- Python 3.12 + FastAPI
- **PostgreSQL** via SQLAlchemy + psycopg2
- Static HTML/CSS/JS frontend with **VenInspect / Ventia** brand tokens, logos, Geist fonts, and light/dark theme
- Proxmox helper-script installer and Docker Compose

## Proxmox Helper Script install (recommended)

Helper-script style installer (same flow as community-scripts): creates a Debian LXC, installs PostgreSQL + WRU, enables `wru.service`, seeds sample data.

### On the Proxmox host

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

Optional overrides:

```bash
CTID=230 HN=wru STORAGE=local-lvm WRU_PORT=8000 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

When finished it prints the CTID, root password, and `http://<ip>:8000`.

### Install into an existing Debian/Ubuntu LXC or VM

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/install/wru-install.sh)"
```

### Update

Re-run the same `ct/wru.sh` **inside** the WRU container (or re-run `install/wru-install.sh`). App code updates; PostgreSQL data and `/opt/wru-data/uploads` are kept. DB password in `/etc/default/wru` is reused.

| Path | Purpose |
|------|---------|
| `/opt/wru` | Application |
| `/opt/wru-data/uploads` | Uploaded documents |
| `/etc/default/wru` | Env (`DATABASE_URL`, Postgres creds, port) |
| PostgreSQL | Database `wru` / role `wru` |
| `systemctl status wru` | App service |
| `systemctl status postgresql` | Database service |

## Quick start (manual Linux)

Requires a running PostgreSQL instance.

```bash
sudo -u postgres psql -c "CREATE USER wru WITH PASSWORD 'wru';"
sudo -u postgres psql -c "CREATE DATABASE wru OWNER wru;"
sudo -u postgres psql -d wru -c "GRANT ALL ON SCHEMA public TO wru;"

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export POSTGRES_USER=wru POSTGRES_PASSWORD=wru POSTGRES_HOST=127.0.0.1 POSTGRES_DB=wru
# or: export DATABASE_URL=postgresql+psycopg2://wru:wru@127.0.0.1:5432/wru

python3 scripts/seed.py
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` (or forward port 8000 from your host).

### Docker

```bash
docker compose up --build -d
```

Starts Postgres + the app. Uploads persist in the `wru_uploads` volume; DB in `wru_pg`.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | built from `POSTGRES_*` | Full SQLAlchemy URL |
| `POSTGRES_USER` | `wru` | DB user |
| `POSTGRES_PASSWORD` | `wru` | DB password |
| `POSTGRES_HOST` | `127.0.0.1` | DB host |
| `POSTGRES_PORT` | `5432` | DB port |
| `POSTGRES_DB` | `wru` | Database name |
| `WRU_DATA_DIR` | `./data` (Proxmox: `/opt/wru-data`) | Upload storage |
| `WRU_PORT` | `8000` | HTTP listen port |
| `WRU_BRANCH` | `main` | Git branch used by helper scripts |
| `WRU_REPO` | `https://github.com/McKrackenAU/WRU.git` | Git remote used by helper scripts |

## API overview

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sites` | List/search sites |
| POST | `/api/sites` | Create site |
| PATCH | `/api/sites/{id}` | Update site / workflow / custom fields |
| DELETE | `/api/sites/{id}` | Delete site |
| GET/POST/DELETE | `/api/columns` | Manage custom columns |
| GET/POST/DELETE | `/api/sites/{id}/tracking` | Tracking events |
| GET/POST | `/api/sites/{id}/documents` | List / upload documents |
| GET | `/api/documents/{id}/download` | Download document |
| DELETE | `/api/documents/{id}` | Delete document |

Interactive docs: `http://localhost:8000/docs`

## Notes

- Max upload size: 25 MB per file
- Removing a custom column clears that field from all sites
- Seed script is idempotent (skips if sites already exist)
