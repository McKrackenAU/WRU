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

## Quick start (Linux)

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
| `WRU_DATA_DIR` | `./data` | SQLite DB + upload storage |
| `DATABASE_URL` | `sqlite:///{WRU_DATA_DIR}/wru.db` | Override DB (e.g. PostgreSQL) |

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
