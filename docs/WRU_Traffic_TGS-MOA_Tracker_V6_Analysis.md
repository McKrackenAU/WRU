# WRU Traffic TGS-MOA Tracker V6 — Workbook Analysis

**Source file:** `WRU_Traffic_TGS-MOA_Tracker_V6_WIP_69c5.xlsm` (~1.1 MB, macro-enabled)  
**SharePoint path (embedded):** `https://ventia.sharepoint.com/teams/CT-Transport-3057/023 TRAFFIC MANAGEMENT/09. Trackers/`  
**Author / last editor (doc props):** John Li Rosi · created 2023-05-29 · modified 2026-08-05  
**Purpose of this report:** Drive a full web-app rewrite by documenting sheets, columns, formulas, VBA, validations, formatting rules, and workflow semantics.

---

## 1. Sheet inventory and purpose

| # | Sheet name | CodeName | Purpose |
|---|------------|----------|---------|
| 1 | **ENABLE MACROS** | Sheet2 | Splash / gate sheet (image-only). Forces users to enable macros before using add-row / multi-select council behaviour. |
| 2 | **Dashboard V3 WIP** | Sheet1 | Status overview dashboard (“TM MoA Status Overview”). Mostly visual: drawings + a chart fed from `Dashboard backend` status counts. Almost no cell data (title in A2). Print area `$A$1:$Q$39`. |
| 3 | **TGS-MOA Tracker** | Sheet3 | **Primary operational register.** One row per site/job. Status pipeline, MoA dates, council process, extensions, comments, job completion. VBA lives here. |
| 4 | **Priority List Template** | Sheet10 | Blank export/print template for client lists: **DTP – PERMITS PRIORITY LIST** and **DTP – TRIMS PRIORITY LIST**. Manual fill / copy from tracker. |
| 5 | **Dashboard backend** | Sheet13 | Admin/config + calculation support: `TODAY()`, stage counts for chart, council/Yes-No dropdown sources, road-name list, TGS status list, **template row 29** copied by VBA when adding rows. |

There are **no cost/rates sheets** and **no map/coordinate sheets** in this workbook.

---

## 2. TGS-MOA Tracker — columns, volumes, samples

### 2.1 Column dictionary (row 1 headers)

| Col | Header | Type / role |
|-----|--------|-------------|
| **A** | *(blank header)* | Section include flag. Usually `1` for active jobs counted in totals; rare `10` on special STRUCTURES rows. |
| **B** | Road Name | Dropdown from backend road list. Format typically `ROAD NAME - ####` (asset/route number). |
| **C** | Site Number | Free text (e.g. `S48`, or descriptive like `KERB & CHANNEL`, `GENERICS 26-27 Hazards`). |
| **D** | Indicative Site Start Date | Date. Program start for the site. |
| **E** | MoA - Must Have Received Date `[0-14 days]` / `[14+ days]` | **Calculated.** Deadline = 20 business days before start; or `"Received"` once MoA stage reached. |
| **F** | Today Priority =1 if&lt;21days | **Calculated.** `1` (urgent) or `2` based on must-have date proximity (formula uses **14-day** threshold — header text “21days” is stale). |
| **G** | TGS Markup completed | **Master status dropdown** (misnamed header — this is the single current-stage field). |
| **H** | Submitted to TMD | Derived stage lamp: `0` if not yet reached, blank if passed. |
| **I** | Plan Received | Same pattern. |
| **J** | Ready To Submit MoA | Same pattern. |
| **K** | MoA Submitted | Same pattern. |
| **L** | MoA "WITH TRIMS" - (Remove from Permits Priority List) | Same pattern. Header encodes business rule: TRIMS stage removes job from Permits priority list. |
| **M** | Revision Needed | Same pattern. |
| **N** | MoA Received | Same pattern; also drives must-have `"Received"` logic. |
| **O** | Ready for Works | Same pattern (terminal “works ready” stage). |
| **P** | Comments | Free-text operational notes / correspondence log. |
| **Q** | *(spacer)* | Empty separator column. |
| **R** | MoA Number | MoA / permit reference (e.g. `0093225`). |
| **S** | MoA Submission Date | Date. |
| **T** | MoA Received Date | Date. |
| **U** | MoA Wait Time | **Calculated** business days between submission and received (or today if still waiting). |
| **V** | MOA Start Date | Date (permit validity start). |
| **W** | MOA Expiry Date | Date (permit validity end). |
| **X** | Council | Dropdown; VBA enables **multi-select** (`"A, B"`). |
| **Y** | Council Submission Date | Date. |
| **Z** | Council No Objection Recieved Date | Date (or free text in older/generic rows). |
| **AA** | Council No Objection Assumed Date | **Calculated:** if submitted and no objection yet → `WORKDAY.INTL(Y, 10)` (assume after **10 business days**). |
| **AB** | MoA Extension or Change Requried? | Yes / No / N/A dropdown. Default `No`. |
| **AC** | MoA Extension/Change Submission Date | Date. |
| **AD** | MoA E/C Received Date | Date. |
| **AE** | MoA Wait Time | **Calculated** wait on extension/change (same pattern as U). |
| **AF** | MOA Start Date | Extension/change MoA start. |
| **AG** | MOA Expiry Date | Extension/change MoA expiry. |
| **AH** | JOB COMPLETED DATE | Manual date (often blank). |
| **AI** | JOB COMPLETED | Yes/No. **VBA deletes the row when set to Yes.** |

Columns AJ–AX are unused in practice (filter range extends to AV for historical reasons).

### 2.2 Section layout (programs inside one sheet)

| Rows | Section | Notes |
|------|---------|-------|
| 2 | Header band | `A2:P2` merged = **LCP - FMRP**; `AK2` = **BORAL** (legacy/project label). |
| 3–64 | **LCP – FMRP** main program | **62 site rows** with road + site number. |
| 65 | `ADD NEW LINE ABOVE` | VBA DynamicButton. |
| 66–68 | Totals block | Completed / not completed / **% COMPLETE**. |
| 69–71 | **FMRP Non-Commit** placeholder rows | Status `Not Yet Started`. |
| 72 | `ADD NEW LINE ABOVE` | |
| 73–75 | Totals – FMRP Non-Commit | |
| 76 | Section: **LCP Maintenace - MISC** | Typo in sheet. |
| 77–79 | Misc jobs (+ blanks) | e.g. Gordon St kerb & channel. |
| 80 | `ADD NEW LINE ABOVE` | |
| 81 | Section: **STRUCTURES** | |
| 82–85 | Structures / bridge / gradient jobs | Older Yes/No stage style (not status-dropdown formulas). |
| 86 | `ADD NEW LINE ABOVE` | |
| 87 | Section: **GENERICS MTMP & ITMP** | Generic MoAs spanning councils. |
| 88–90 | Generic / OTHER rows | |
| 91 | `ADD NEW LINE ABOVE` | |
| 92 | Section: **Routine Maintenance** | |
| 93 | Placeholder | |
| 94 | `ADD NEW LINE ABOVE` | |

**Named range `DynamicButtons`** = `B65,B72,B80,B86,B91,B94` — selecting any of these cells inserts a new templated row above.

### 2.3 Data volume (this WIP snapshot)

- Main FMRP block (rows 3–64): **62 sites**
- Of those: MoA number filled ≈ **14**; council submission date ≈ **7**
- Status mix (main block): Submitted to TMD **34**, MoA Submitted **12**, Ready to Submit MoA **10**, Ready For Works **5**, Plan Received **1**
- JOB COMPLETED = Yes: **3** (Structures block; VBA would normally delete — these remain, likely older Yes/No column style)
- Filter database: `'TGS-MOA Tracker'!$A$1:$AV$94`

### 2.4 Sample data rows (abridged)

**Row 3 — mid-pipeline MoA**

| Field | Value |
|-------|-------|
| Road / Site | DYNON RD - 5035 / S48 |
| Start | 2026-09-13 |
| Status (G) | MoA Submitted |
| MoA # / Submitted | 0093225 / 2026-07-03 |
| Council | Maribyrnong (submitted 2026-07-06, no-objection 2026-07-28) |
| Extension | No · Job completed No |
| Comments | TRIMS requested; Ventia/DTP correspondence |

**Row 7 — Ready for Works**

| Field | Value |
|-------|-------|
| Road / Site | DOCKLANDS HWY - 2120 / S52 |
| Start | 2026-09-24 |
| Status | Ready For Works |
| MoA | 0093335 · submitted 2026-07-07 · received 2026-08-03 |
| Validity | 2026-09-01 → 2026-12-23 |
| Comments | TRIMS Submitted; Change Form; Approved 05/08/2026 |

**Row 17 — drafting**

| Field | Value |
|-------|-------|
| Road / Site | SOMERVILLE RD - 5458 / S40 |
| Start | 2026-10-27 |
| Status | Ready to Submit MoA |
| Council | Brimbank |
| Comments | Drafted |

**Row 82 — Structures (legacy Yes/No stages)**

| Field | Value |
|-------|-------|
| Road | PRINCES HWY WEST (GEELONG RD) BRIDGE INSPECTION |
| Start | 2024-10-15 |
| G–O | mostly Yes (not formula lamps) |
| E formula variant | `IF(M82="Yes","Received",WORKDAY.INTL(D82,-20,1))` |
| Job completed | Yes |
| A flag | **10** (excluded from normal `COUNTIF(A,"=1")` totals) |

---

## 3. Named ranges / defined names

| Name | Scope | Refers to | Role |
|------|-------|-----------|------|
| **DynamicButtons** | TGS-MOA Tracker | `$B$65,$B$72,$B$80,$B$86,$B$91,$B$94` | VBA “add row” click targets |
| **JOBCOMPLETED** | Workbook | `TGS-MOA Tracker!$AI:$AI` | Named column for completion flag |
| `_xlnm._FilterDatabase` | Tracker / Priority List | AutoFilter caches | |
| `_xlnm.Print_Area` / `Print_Titles` | Several sheets | Print setup | |
| `_xlcn.WorksheetConnection_WRUTraffic202324.xlsxTable2` | Hidden | Legacy Power Pivot connection to older `WRU Traffic 2023-24.xlsx!Table2` | Stale data-model link |
| `_xleta.AND` / `NETWORKDAYS.INTL` / `RECEIVED` | Hidden XLM stubs | `#NAME?` | Excel LAMBDA/eta artifacts — ignore |
| Custom view **Cover Page** | Workbook view | Points at older sheet id | Legacy |

Named sheet views: **MoA List**, **View1** (filter presentation presets).

---

## 4. Key formulas and business rules

Weekend parameter `1` on `WORKDAY.INTL` / `NETWORKDAYS.INTL` = Saturday+Sunday weekends (no Victorian public holidays).

### 4.1 Must-have received date (E)

```excel
=IF(N3="","Received",WORKDAY.INTL(D3,-20,1))
```

- While status is **before** MoA Received, column N formula returns `0` → E computes **start date minus 20 business days**.
- Once status reaches MoA Received or later, N returns `""` → E shows **`Received`**.
- Structures/generic legacy rows sometimes use `IF(M="Yes","Received",...)` instead.

**Business rule:** MoA must be in-hand **20 business days before** indicative site start.

### 4.2 Today priority (F)

```excel
=IF(E3="Received","",
IF((E3-TODAY()>14),2,1))
```

| Condition | Priority |
|-----------|----------|
| Must-have already `"Received"` | blank |
| Must-have date more than **14 calendar days** away | **2** (lower) |
| Must-have within 14 days or overdue | **1** (higher / urgent) |

Header claim “if&lt;21days” does **not** match the formula (14). App rewrite should treat **14** as the spreadsheet truth unless product owners confirm 21.

### 4.3 Stage progress lamps (H–O)

Single source of truth is **G** (status). Columns H–O are cumulative “have we reached this stage?” indicators:

- Return **`0`** if current status is still earlier than that column’s stage
- Return **`""` (blank)** if status is at or beyond that stage

Order encoded in formulas:

1. Not Yet Started  
2. TGS Markup Complete  
3. Submitted to TMD  
4. Plan Received  
5. Ready To Submit MoA  
6. MoA Submitted  
7. MoA with TRIMS  
8. Revision Needed  
9. MoA Received  
10. Ready for Works  

**Important casing mismatches** between dropdown list and formulas (see §5) — e.g. list has `Ready to Submit MoA` / `MoA With TRIMS` / `Ready For Works` while formulas check `Ready To Submit MoA` / `MoA with TRIMS` / `Ready for Works`. This can leave lamps stuck at `0` even after status change.

### 4.4 MoA wait time (U) and extension wait (AE)

```excel
=IF(ISBLANK(S3),"Not yet Submitted",
  IF(ISBLANK(T3),
    NETWORKDAYS.INTL(S3,'Dashboard backend'!$E$1,1),
    NETWORKDAYS.INTL(T3,S3,1)))   ' most rows: T then S
```

- No submission → `"Not yet Submitted"`
- Submitted, not received → business days from S to **today** (`Dashboard backend!$E$1` = `TODAY()`)
- Both dates present → business days between them  

**Bug/inconsistency:** ~5 rows use `NETWORKDAYS.INTL(S,T,…)` (S then T) while ~71 use `(T,S)`. Argument order matters for sign/magnitude — normalize in the app.

AE mirrors U using AC/AD (extension/change submission & received).

### 4.5 Council no-objection assumed date (AA)

```excel
=IF(ISBLANK(Y3),"Not yet Submitted",
  IF(ISBLANK(Z3),WORKDAY.INTL(Y3,10,1),""))
```

If council pack submitted and no objection recorded → assume clearance **10 business days** after submission. When Z is filled, AA clears.

### 4.6 Progress % (section totals)

```excel
G66 = COUNTIF(G3:G65,"<>Not Yet Started")-1      ' completed-ish
G67 = COUNTIF(G3:G65,"Not Yet Started")
B68 = COUNTIF(A3:A65,"=1")                        ' job count
G68 = ((100/(B68))*G66)/100                       ' % complete
```

“Completed” here means **status ≠ Not Yet Started** (started anything), not “Ready for Works” / job finished. The `-1` subtracts the totals row interference. Similar block for Non-Commit (rows 69–75).

### 4.7 Dashboard backend aggregates

Legacy Yes/No counts (partially stale vs current status model):

```excel
COUNTIF('TGS-MOA Tracker'!$H$1:$H$167,"Yes")  ' Submitted to TM
COUNTIF(...$I...,"Yes")                        ' Plan Received
COUNTIF(...$K...,"Yes")                        ' MOA Submitted
COUNTIF(...$M...,"Yes")                        ' MOA Received
```

Status histogram for chart (`I44:I53`) counts each G status label across the main block.

---

## 5. Data validation / dropdowns

### 5.1 Sources on Dashboard backend

| Range | Contents |
|-------|----------|
| **Y2:Y8** | Council Dropdown: Brimbank, Melbourne, Hobsons Bay, Melton, Wyndham, Maribynong *(typo — missing ‘r’)*, Multiple |
| **AB2:AB4** | Yes / No / N/A |
| **C44:C46** | Yes / No / N/A (used by VBA for AB) |
| **D44:D95** | Road Name list (~50 roads + `OTHER`) |
| **F44:F53** | **TGS Status List** (canonical stage labels for G) |

**Canonical status list (F44:F53):**

1. Not Yet Started  
2. TGS Markup Complete  
3. Submitted to TMD  
4. Plan Received  
5. Ready to Submit MoA  
6. MoA Submitted  
7. MoA With TRIMS  
8. Revision Needed  
9. MoA Received  
10. Ready For Works  

### 5.2 Validations on TGS-MOA Tracker

| Target | Source | Notes |
|--------|--------|-------|
| **B** (road) | `'Dashboard backend'!$D$44:$D$95` | x14 list validation |
| **G** (status) | `'Dashboard backend'!$F$44:$F$53` | Master workflow status |
| **X** (council) | Inline list *or* `$Y$2:$Y$8` | VBA multi-select toggles values; `ShowError=False` so comma-joined values validate |
| **AB** | `$C$44:$C$46` or Yes/No/N/A | Extension required? |
| **AI** | `"Yes,No"` | Job completed |
| Some H–O / older blocks | `"Yes,No,N/A"` | Legacy Structures/Generics style |

Hardcoded council DV also appears as:  
`"Brimbank,Melbourne,Hobsons Bay,Melton,Wyndham,Maribyrnong"` (note spelling **Maribyrnong** vs backend **Maribynong**).

---

## 6. VBA macros

Extracted with `olevba` from `xl/vbaProject.bin`.

| Module | Sheet | Summary |
|--------|-------|---------|
| **ThisWorkbook** | — | `Workbook_Open` empty stub |
| **Sheet3** | TGS-MOA Tracker | **All real logic** |
| Sheet1 / Sheet2 / Sheet10 / Sheet13 | Other sheets | Empty or empty Activate/SelectionChange |

### Sheet3 behaviour

1. **`AddNewRowAtCell`**
   - Inserts row at selection
   - Copies **formats + formulas + validation** from `'Dashboard Backend'!Row 29` (case-insensitive match to `Dashboard backend`)
   - Re-pastes formulas for U, AA, AB, AE, AH
   - Re-applies dropdowns:
     - B ← road list `$D$44:$D$95`
     - G ← status list `$F$44:$F$53`, default **`Not Yet Started`**
     - X ← council validation from template; `ShowError = False`
     - AB ← Yes/No/N/A, default **`No`**
     - AI ← Yes/No, default **`No`**
   - Uses SpeedUp (manual calc, no screen update)

2. **`Worksheet_SelectionChange`**
   - If selection intersects **`DynamicButtons`** → call `AddNewRowAtCell`

3. **`Worksheet_Change`**
   - **Column X multi-select:** Undo → if new value already in comma list, remove it; else append with `", "`. Toggle semantics.
   - **Column AI = Yes:** **delete the entire row** (archive-by-deletion — no history retained in-sheet)

---

## 7. Conditional formatting (business logic)

Hundreds of per-row rules (duplicated rather than ranged cleanly). Semantic summary:

| Target | Rule | Visual meaning |
|--------|------|----------------|
| **E** must-have | Contains `"Received"` | Green `#00B050` — MoA in hand |
| **E** | Date between TODAY−14 and TODAY−7 | Yellow `#FFFF00` — approaching/overdue window |
| **E** | Date &lt; TODAY−7 | Red `#FF0000` — badly overdue |
| **U / AE** wait | Contains `"Not yet"` | Dark fill — not submitted |
| **U / AE** | Value **&gt; 20** | Pink `#FFC7CE` + dark red bold — DTP wait SLA breach (&gt;20 business days) |
| **AA** | Contains `"Not yet"` | Dark — council not submitted |
| **AB / AI** | `"No"` / `"Yes"` | Red-pink `#FF7C80` / Green `#00B050` |
| **V/W/AF/AG** | Date within today…+10 or +10…+20 | Pink/rose alerts for MoA start/expiry approaching |
| Stage cells (legacy Yes/No blocks) | Yes/No text | Green / red |

**SLA thresholds encoded in formatting:**

- Must-have urgency bands: 7 / 14 calendar days vs today  
- MoA agency wait: **20 business days**  
- Council assumed clearance: **10 business days** (formula)  
- MoA validity approaching: 10 / 20 calendar days  

---

## 8. TGS / MoA workflow — how jobs flow

```text
Not Yet Started
    → TGS Markup Complete          (internal markup done)
    → Submitted to TMD             (sent to traffic management designer / TMD)
    → Plan Received                (plans back)
    → Ready to Submit MoA          (Ventia ready to lodge with DTP)
    → MoA Submitted                ★ appears on DTP Permits Priority List
    → MoA With TRIMS               ★ leave Permits list; on TRIMS Priority List
         ↘ Revision Needed         (loop back toward resubmission / permits)
    → MoA Received                 (approved; must-have shows Received)
    → Ready for Works              (clear to construct)
    → JOB COMPLETED = Yes          (VBA deletes row)
```

**Parallel council track** (not a G status):

- Submit to council(s) → wait for no-objection (or assume after 10 bd) → may involve multiple councils (multi-select / free-text dates on generics)

**Extension / change track** (AB–AG):

- If MoA needs extension or change → submit → wait (AE) → new start/expiry (AF/AG)

**Client-facing lists** (Priority List Template):

- **Permits Priority List** — jobs needing DTP permits attention (MoA Submitted / Revision; **exclude** MoA With TRIMS per column L header)
- **TRIMS Priority List** — jobs with TRIMS  

Template columns: Road Name, Indicative Start, Priority, Comments, MoA Number, MoA Submission Date, MoA Wait Time (+ numbering). Currently empty shells numbered 1–19 / 1–20.

**Program categories in-sheet:** LCP-FMRP, FMRP Non-Commit, LCP Maintenance Misc, Structures, Generics MTMP/ITMP, Routine Maintenance.

---

## 9. Admin-configurable areas

Everything “configurable without VBA edits” lives on **Dashboard backend**:

| Config | Location | Used for |
|--------|----------|----------|
| Road name catalogue | D44:D95 | Column B dropdown |
| Status / stage labels | F44:F53 | Column G dropdown + chart categories |
| Councils | Y2:Y8 | Column X dropdown |
| Yes/No/N/A | C44:C46 / AB2:AB4 | AB and related |
| New-row template | **Row 29** | All formulas/defaults for inserted jobs |
| “Today” anchor | E1 `=TODAY()` | Wait-time calculations |
| Chart series | I44:I53 COUNTIFs | Dashboard status chart |

Not admin-configurable in-sheet (hardcoded in formulas/VBA/CF):

- 20 business-day must-have offset  
- 14-day priority threshold  
- 10-day council assumption  
- 20-day wait SLA highlighting  
- Stage order in H–O formulas  
- Dynamic button cell addresses  
- Row deletion on AI=Yes  

---

## 10. Map / location / coordinates

**None present.**

- Location is encoded only as **road name + route number** (`DYNON RD - 5035`) and **site number** (`S48`).
- No lat/long, easting/northing, KML, or map sheet.
- Keyword scan of package XML found no real geospatial fields (only VML `coordsize` noise and currency number formats).

Implication for rewrite: map features in the web app are **net-new** relative to this workbook (link via site number / MoA / road name).

---

## 11. Cost / rates

**None present.**

- No rate tables, cost sheets, quote columns, or $ amount fields in use.
- Residual `$` hits are Excel accounting format codes only.
- Costing in the web app is likewise **beyond** this spreadsheet’s scope.

---

## 12. Gaps: spreadsheet uniqueness vs typical / existing web tracker

### What this spreadsheet uniquely does (preserve in rewrite)

1. **Must-have MoA date** = start − 20 business days, with Received latch and RAG by calendar proximity.  
2. **Dual priority semantics** tied to must-have (not only to start date).  
3. **Stage lamp columns** as a visual pipeline (derived from one status).  
4. **MoA wait-time SLA** (business days, alert &gt;20) for initial and extension paths.  
5. **Council multi-select + 10bd assumed no-objection.**  
6. **Permits vs TRIMS client lists** with explicit “remove from Permits when With TRIMS”.  
7. **Extension/change sub-process** with its own dates/wait/validity.  
8. **Program sections** on one register (FMRP / Non-Commit / Misc / Structures / Generics / Routine).  
9. **Operational comment log** as the day-to-day system of record for DTP/Ventia correspondence.  
10. **Destructive completion** (row delete) — rewrite should prefer **archive**, not silent delete.  
11. **Generics / multi-council MoAs** with messy free-text objection dates.  
12. **Printable priority list templates** for external DTP circulation.

### What a typical web tracker adds (spreadsheet lacks)

| Capability | Spreadsheet | Notes for app |
|------------|-------------|----------------|
| Auth / audit trail | No | Comments are free text only |
| Document attachments | No | MoA PDFs, emails live outside |
| Map / KML | No | Road string only |
| Cost / rates / quotes | No | Separate concern |
| Public holiday calendars | No | NETWORKDAYS without holidays |
| Normalized multi-council rows | Partial | Multi-select string / free text |
| Historical completed jobs | Destroyed on AI=Yes | Need archive FY model |
| Consistent stage casing | Broken | Normalize labels |
| Automated Permits/TRIMS export from live data | Manual template | App already has CSV/XLSX export hooks |
| Dashboard accuracy | WIP / stale Yes-No COUNTs | Rebuild from status enum |
| Configurable SLAs | Hardcoded | Should be admin settings |

### Known spreadsheet defects to fix in the app (do not clone blindly)

- Priority header says 21 days; formula uses **14**.  
- Status label casing mismatches (`to`/`To`, `With`/`with`, `For`/`for`).  
- Council spelling: Maribyrnong vs Maribynong.  
- U wait `NETWORKDAYS` argument order inconsistent across rows.  
- Dashboard COUNTIFs still look for Yes/No in H/I/K/M while main block uses 0/blank lamps.  
- Structures block uses Yes/No stage cells + different E formula — dual models in one sheet.  
- `JOB COMPLETED = Yes` deletes data.  
- No holiday calendar.  
- Priority List Template not formula-linked to tracker.

### Alignment note vs current web app seed (`app/stage_registry.py` / `calculations.py`)

Web app stages are close but not identical:

| Spreadsheet | App seed |
|-------------|----------|
| TGS Markup Complete | TGS Markup completed |
| Submitted to TMD | Submitted to traffic management (waiting for plans) |
| *(no separate Ventia review status)* | **Ventia review** (extra) |
| Ready to Submit MoA | Waiting to submit to DTP |
| MoA With TRIMS | MoA with TRIMS team |
| Priority from must-have ±14d | Priority from **start date ±21d** (`PRIORITY_THRESHOLD_DAYS = 21`) |
| Council assume **10** bd | App constant `COUNCIL_NO_OBJECTION_BUSINESS_DAYS = 21` |

These deltas should be reconciled with traffic/permits SMEs before locking production rules.

---

## 13. Ancillary package features

- **Chart** on Dashboard V3 WIP: categories `Dashboard backend!$F$44:$F$53`, values `$I$44:$I$53`.  
- **Images:** macro-enable splash + dashboard pictures (`xl/media/image1–3.png`).  
- **Power Pivot / Data Model:** leftover connection to `WRU Traffic 2023-24.xlsx!Table2` — not driving current tracker UI.  
- **Cell comment:** `T83` by John Li Rosi (date notes).  
- **AutoFilter** on tracker and priority list.

---

## 14. Recommended domain model for rewrite (from this workbook)

```text
ProgramCategory (FMRP, Non-Commit, Misc, Structures, Generics, Routine, …)
Site / Job
  road_name, route_no, site_number, indicative_start
  status (enum = G list)
  comments
  moa_number, moa_submitted_at, moa_received_at
  moa_start, moa_expiry
  extension_required, ext_submitted_at, ext_received_at, ext_start, ext_expiry
  job_completed_at, archived
  computed: must_have_date, priority, moa_wait_bd, ext_wait_bd
SiteCouncil[] (council, submitted_at, no_objection_at, assumed_at)
Workflow derived lamps / progress % from status ordinal
ClientList membership: permits | trims | none (from status + list_role)
Config: roads, councils, statuses, SLA numbers (20 / 14 / 10 / 20)
```

---

*Generated by static analysis with openpyxl + oletools (`olevba`) + OOXML inspection of the `.xlsm` package.*
