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

Same UX as [Proxmox VE Helper Scripts](https://community-scripts.org): whiptail menu on the Proxmox host, then creates a Debian LXC, installs PostgreSQL + WRU, enables `wru.service`, and seeds sample data.

### On the Proxmox host

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

Choose:

1. **Default Install** — app defaults (1 CPU / 2048 MiB / 8G, DHCP, unprivileged) + storage picker
2. **Advanced Install** — full step wizard with Back navigation:
   - Container type, root password, CTID, hostname
   - Disk / CPU / RAM, storage pools
   - Bridge, **DHCP or static IPv4** (+ gateway), IPv6, MTU, VLAN, MAC
   - DNS server / search domain, tags
   - SSH, FUSE, TUN/TAP, nesting, keyctl, timezone, protection
   - WRU app port, verbose mode, confirmation summary
3. **Update existing CT from GitHub** — pick an installed WRU LXC and pull/reinstall the latest code (keeps DB + uploads). Also installs the in-app updater (`/system` and `sudo wru-update`).

When finished it prints CTID, password mode, network, and `http://<ip>:<port>`.

Update an existing CT from the Proxmox host (noninteractive):

```bash
mode=update CTID=230 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

Noninteractive / automation:

```bash
NONINTERACTIVE=1 mode=default CTID=230 STORAGE=local-lvm WRU_PORT=8000 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

Static IP without the GUI (community-scripts style vars):

```bash
NONINTERACTIVE=1 mode=advanced \
  var_net=192.168.1.50/24 var_gateway=192.168.1.1 \
  var_ctid=230 var_hostname=wru var_container_storage=local-lvm \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

### Install into an existing Debian/Ubuntu LXC or VM

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/install/wru-install.sh)"
```

### Update

**Inside the WRU LXC** (as root) — works even if `wru-update` is not installed yet:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/scripts/wru-update.sh)"
```

That installs `/usr/local/sbin/wru-update`. Afterward you can use:

```bash
sudo wru-update
```

**From the Proxmox host** — menu option **Update existing CT from GitHub**:

```bash
bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

Or noninteractive:

```bash
mode=update CTID=230 \
  bash -c "$(curl -fsSL https://raw.githubusercontent.com/McKrackenAU/WRU/main/ct/wru.sh)"
```

**In the web UI:** open **System** → **Pull & install update** (available after the helper is installed).

App code updates; PostgreSQL data and document folders under `/opt/wru-data` are kept.

| Path | Purpose |
|------|---------|
| `/opt/wru` | Application |
| `/opt/wru-data` | App data (can stay on NVMe with the app) |
| `/opt/wru-data/uploads` | Live documents |
| `/opt/wru-data/uploads/archived` | Archived site files |
| `/etc/default/wru` | Env (`DATABASE_URL`, Postgres creds, port) |
| PostgreSQL | Database `wru` / role `wru` — keep the data directory on NVMe |
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
| `WRU_DATA_DIR` | `./data` (Proxmox: `/opt/wru-data`) | App data, live documents, and archived files. |
| `WRU_PORT` | `8000` | HTTP listen port |
| `WRU_BRANCH` | `main` | Git branch used by helper scripts |
| `WRU_REPO` | `https://github.com/McKrackenAU/WRU.git` | Git remote used by helper scripts |
| `mode` | — | `default` or `advanced` (skips main menu when set) |
| `var_net` | `dhcp` | `dhcp` or static IPv4 CIDR (e.g. `192.168.1.50/24`) |
| `var_gateway` | — | Gateway IP for static `var_net` |
| `var_ctid` / `var_hostname` / `var_cpu` / `var_ram` / `var_disk` | app defaults | LXC sizing / identity |
| `var_brg` / `var_vlan` / `var_mtu` / `var_ns` | `vmbr0` / empty | Network extras |
| `NONINTERACTIVE` | `0` | Set `1` to skip whiptail menus (use env defaults) |

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
