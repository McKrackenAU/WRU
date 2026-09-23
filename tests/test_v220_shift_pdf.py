"""The lifecycle shift PDF keeps every field from the printed WRU report."""

from pathlib import Path

from app.shift_export import build_shift_report_pdf, pdf_filename, report_reference

ROOT = Path(__file__).resolve().parent.parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
SHIFTS_HTML = (ROOT / "app/static/shifts.html").read_text(encoding="utf-8")
SHIFTS_JS = (ROOT / "app/static/js/shifts.js").read_text(encoding="utf-8")


def _sample():
    report = {
        "work_date": "2026-02-25",
        "shift_type": "night",
        "road_name": "HEATHS RD - 5443",
        "site_number": "030",
        "weather": {"label": "Clear", "temperature_c": 22},
        "polygons": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[144.95, -37.80], [144.955, -37.80], [144.955, -37.802], [144.95, -37.802], [144.95, -37.80]]],
                },
            }
        ],
        "details": {
            "fmrp_year": "FMRP 2025/26",
            "road_number": "5443",
            "work_kind": "hma",
            "lot_number": "20260225-5443-2526-030-HMA-14HP-WM",
            "supervisor": "William McClure",
            "high_risk": "WORKING NEAR LIVE TRAFFIC, WORKING AROUND MOBILE PLANT",
            "chainage": "CH1325R to CH1938R",
            "description": "",
            "road_closed": "2026-02-25T21:11",
            "road_opened": "2026-02-26T03:00",
            "traffic_contractor": "MIEPOL",
            "tgs_number": "TGS-TMR-MIE-5443-412",
            "moa_number": "0085281",
            "moa_start": "2026-02-25T20:00",
            "moa_end": "2026-02-26T05:00",
            "traffic_crew_start": "2026-02-25T19:30",
            "traffic_crew_end": "2026-02-26T04:00",
            "total_tc": 9,
            "arrow_boards": 0,
            "paving_contractor": "Boral",
            "other_contractors": "J&A Bobcats, Sweep Wright, Bitu-mill",
            "asphalt_type": "14HP",
            "other_material": 0,
            "shift_area_m2": 3200,
            "tonnage": 384,
            "pits": 0,
            "valves": 0,
            "loops": 0,
            "prestart_notes": "Prestarts conducted in Werribee Historical Park carpark",
            "profiling_notes": "Profiling of Ramps only",
            "asphalting_notes": "Mix: 14HP\nDepth: 50mm\nTonnes: 384T",
            "observations": "Nil issues observed.",
            "incidents": "",
            "comments": "",
            "prestart_done": True,
            "plant_prestart_done": True,
            "tm_implementation": True,
            "aftercare": True,
            "ncr_raised": False,
            "vensafe_event": "N/A",
            "non_compliance": "",
            "photos_url": "https://ventia.sharepoint.com/sites/HEATHS/2026-02-25",
        },
    }
    site = {"road_name": "HEATHS RD - 5443", "site_number": "030"}
    return report, site


def test_version_is_220():
    assert VERSION == "2.21"


def test_form_has_every_printed_report_field():
    for field_id in (
        "dWeather",
        "dFmrp",
        "dLot",
        "dRoadNo",
        "dWorkKind",
        "dSupervisor",
        "dRisk",
        "dPaver",
        "dTrafficContractor",
        "dOthers",
        "dRoadClosed",
        "dRoadOpened",
        "dCrewStart",
        "dCrewEnd",
        "dTgs",
        "dMoa",
        "dMoaStart",
        "dMoaEnd",
        "dTotalTc",
        "dArrows",
        "dMix",
        "dOtherMaterial",
        "dShiftArea",
        "dTonnes",
        "dChainage",
        "dDescription",
        "dPits",
        "dValves",
        "dLoops",
        "dPrestart",
        "dProfiling",
        "dAsphaltNotes",
        "dObservations",
        "dIncidents",
        "dComments",
        "dPrestartDone",
        "dPlantPrestart",
        "dTmOk",
        "dAftercare",
        "dNcr",
        "dVensafe",
        "dNonCompliance",
        "dPhotos",
    ):
        assert f'id="{field_id}"' in SHIFTS_HTML
    assert "buildLotNumber" in SHIFTS_JS
    assert "weather_condition" in SHIFTS_JS
    assert "vensafe_event" in SHIFTS_JS


def test_report_number_matches_the_old_filename():
    report, site = _sample()
    assert report_reference(report, site) == "20260225-5443-2526-030-HMA-14HP-WM"
    assert pdf_filename(report, site) == "20260225-5443-2526-030-HMA-14HP-WM.pdf"


def _pdf_text(pdf: bytes) -> str:
    import base64
    import re
    import zlib

    chunks: list[bytes] = []
    pos = 0
    while True:
        start = pdf.find(b"stream\n", pos)
        if start < 0:
            break
        end = pdf.find(b"endstream", start)
        data = pdf[start + 7 : end].strip()
        pos = end + 9
        if data.endswith(b"~>"):
            data = base64.a85decode(data, adobe=True)
        try:
            data = zlib.decompress(data)
        except zlib.error:
            pass
        chunks.append(data)
    blob = b"\n".join(chunks)
    parts = re.findall(br"\((?:\\.|[^\\)])*\)", blob)
    lines = []
    for part in parts:
        raw = part[1:-1]
        try:
            lines.append(raw.decode("unicode_escape"))
        except UnicodeDecodeError:
            lines.append(raw.decode("latin-1", errors="ignore"))
    return "\n".join(lines)


def test_pdf_contains_the_printed_report_sections_and_values():
    report, site = _sample()
    pdf = build_shift_report_pdf(report, site)
    assert pdf.count(b"/MediaBox") == 3
    text = _pdf_text(pdf)
    for phrase in (
        "WRU Lifecycle Pavements Shift Report",
        "General Information",
        "Lot Diagram",
        "Subcontractor Information",
        "Traffic Information",
        "Paving Information",
        "Site Observations",
        "TMP Checks",
        "Non Conformance Reports",
        "Photos",
        "HEATHS RD - 5443 Site:030",
        "William McClure",
        "22c Clear",
        "FMRP 2025/26",
        "Night",
        "WORKING NEAR LIVE TRAFFIC",
        "20260225-5443-2526-030-HMA-14HP-WM",
        "Boral",
        "MIEPOL",
        "J&A Bobcats, Sweep Wright, Bitu-mill",
        "TGS-TMR-MIE-5443-412",
        "0085281",
        "CH1325R to CH1938R",
        "3200",
        "384",
        "14HP",
        "Prestarts conducted in Werribee Historical Park carpark",
        "Profiling of Ramps only",
        "Nil issues observed.",
        "TRUE",
        "FALSE",
        "VenSafe Event No.",
        "N/A",
        "SharePoint URL",
        "ventia.sharepoint.com",
        "Uncontrolled when printed or downloaded",
        "Revision 0",
        "Internal",
        "Page 1 of 3",
        "Page 3 of 3",
    ):
        assert phrase in text, phrase
