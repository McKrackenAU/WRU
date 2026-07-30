# WRU TGS Tracker

Linux-hosted PostgreSQL web app for traffic guidance / MoA workflow tracking. Same Ventia styling and logos as [VenInspect](https://github.com/McKrackenAU/VenInspect).

## Features

- **Site register** with program, multi-council attribution, TGS reference, MoA fields, workflow stages
- **Sheet-style calculations** — priority (&lt;21 days), must-have bands (0–14 / 14+), progress %, permits priority list (TRIMS rule)
- **Dashboard** — program health, stage funnel, councils, permits priority count
- **Tracking page** — filter whole program by stage / council / priority / permits list
- **Priority list export** — CSV for the approvals client (`/api/export/priority-list.csv`)
- **MoA document library** — emails, TGS, plans, MoAs attached per site/MoA; searchable library page
- **Archive by financial year** (AU FY Jul–Jun) instead of delete; restore supported
- **Map** — import prior-year KML, click polygons to open linked TGS/MoA
- **Traffic cost calculator** — day/night shifts, configurable OT threshold, crew rates, VMS lead/delivery/collection/day hire; 24h closure compares 3×8 vs 2×12
- **Rates backend** — `/rates` to edit OT, VMS defaults, and labour/plant categories
- **Custom columns**, tracking notes, Ventia/VenInspect styling

## Stack

- Python 3.12 + FastAPI
- **PostgreSQL** via SQLAlchemy + psycopg2
- Static HTML/CSS/JS frontend with **VenInspect / Ventia** brand tokens, logos, Geist fonts, and light/dark theme
- Proxmox helper-script installer and Docker Compose

## Proxmox Helper Script install (recommended)

Helper-script style installer with a **whiptail GUI** (same pattern as VenInspect / community-scripts): creates a Debian LXC, installs PostgreSQL + WRU, enables `wru.service`, seeds sample data.

### On the Proxmox host

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

The GUI prompts for:

- Container ID, hostname, CPU / RAM / disk
- Storage and network bridge
- **DHCP or static IPv4** (CIDR + gateway)
- App HTTP port, git source, and root password

When finished it prints the CTID, root password, network summary, and `http://<ip>:<port>`.

Noninteractive / automation (skip whiptail; use env defaults):

```bash
NONINTERACTIVE=1 CTID=230 HN=wru STORAGE=local-lvm WRU_PORT=8000 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

Static IP without the GUI:

```bash
NONINTERACTIVE=1 NET=static IP_CIDR=192.168.1.50/24 GW=192.168.1.1 \
  CTID=230 HN=wru STORAGE=local-lvm \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

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
| `NET` | `dhcp` | Proxmox LXC network mode (`dhcp` or `static`) |
| `IP_CIDR` | — | Static IPv4 CIDR when `NET=static` (e.g. `192.168.1.50/24`) |
| `GW` | — | Gateway IP when `NET=static` |
| `NONINTERACTIVE` | `0` | Set `1` to skip the whiptail GUI on the Proxmox host |

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
