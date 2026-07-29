# WRU · LCP FMRP MoA Tracker

Linux-hosted SQL web app that replaces the LCP–FMRP MoA spreadsheet. Track roadwork sites, MoA workflow stages, custom columns, activity notes, and attached documents.

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
- SQLite (WAL mode) via SQLAlchemy — single-file DB under `data/`
- Static HTML/CSS/JS frontend
- Optional Docker Compose for Linux hosting

## Proxmox Helper Script install (recommended)

Helper-script style installer (same flow as community-scripts): creates a Debian LXC, installs WRU, enables `wru.service`, seeds sample data.

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

Re-run the same `ct/wru.sh` **inside** the WRU container (or re-run `install/wru-install.sh`). App code updates; `/opt/wru-data` is kept.

| Path | Purpose |
|------|---------|
| `/opt/wru` | Application |
| `/opt/wru-data` | SQLite DB + uploads |
| `/etc/default/wru` | Environment (`WRU_PORT`, data dir) |
| `systemctl status wru` | Service |

## Quick start (manual Linux)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 scripts/seed.py
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` (or forward port 8000 from your host).

### Docker

```bash
docker compose up --build -d
```

Data and uploads persist in the `wru_data` volume.

## Environment

| Variable | Default | Purpose |
|----------|---------|---------|
| `WRU_DATA_DIR` | `./data` (Proxmox: `/opt/wru-data`) | SQLite DB + upload storage |
| `DATABASE_URL` | `sqlite:///{WRU_DATA_DIR}/wru.db` | Override DB (e.g. PostgreSQL) |
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
