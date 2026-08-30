"""Comms role, planner UI, and document visibility."""

from pathlib import Path

from app.auth import (
    ADMIN_ROLE,
    COMMS_ROLE,
    USER_ROLE,
    VALID_ROLES,
    can_manage_comms,
    is_comms_path,
)
from app.comms_export import build_comms_pdf, build_comms_xlsx, collect_export_tables
from app.comms_links import normalize_resource_url
from app.routers.documents import document_is_visible

ROOT = Path(__file__).resolve().parent.parent
COMMON = (ROOT / "app/static/js/common.js").read_text(encoding="utf-8")
USERS_JS = (ROOT / "app/static/js/users.js").read_text(encoding="utf-8")
USERS_HTML = (ROOT / "app/static/users.html").read_text(encoding="utf-8")
COMMS_HTML = (ROOT / "app/static/comms.html").read_text(encoding="utf-8")
COMMS_JS = (ROOT / "app/static/js/comms.js").read_text(encoding="utf-8")
COMMS_PY = (ROOT / "app/routers/comms.py").read_text(encoding="utf-8")
AUTH_PY = (ROOT / "app/auth.py").read_text(encoding="utf-8")
MAIN = (ROOT / "app/main.py").read_text(encoding="utf-8")
SEED = ROOT / "app/comms_seed_data.json"


class _User:
    def __init__(self, role):
        self.role = role


class _Doc:
    def __init__(self, visibility):
        self.visibility = visibility


def test_comms_is_a_valid_role():
    assert COMMS_ROLE == "comms"
    assert COMMS_ROLE in VALID_ROLES
    assert USER_ROLE in VALID_ROLES
    assert ADMIN_ROLE in VALID_ROLES


def test_comms_access_matches_user_plus_planner():
    assert can_manage_comms(_User(COMMS_ROLE))
    assert can_manage_comms(_User(ADMIN_ROLE))
    assert not can_manage_comms(_User(USER_ROLE))
    assert not can_manage_comms(None)


def test_comms_paths():
    assert is_comms_path("/comms")
    assert is_comms_path("/api/comms/sheets")
    assert not is_comms_path("/")
    assert not is_comms_path("/api/sites")
    assert not is_comms_path("/admin/users")


def test_comms_nav_is_ops_only_for_comms_and_admin():
    assert 'href: "/comms"' in COMMON
    assert "commsOnly: true" in COMMON
    assert "isCommsUser" in COMMON
    assert "!l.commsOnly || canComms" in COMMON
    assert "role === \"comms\"" in COMMON


def test_admin_users_can_assign_comms_role():
    assert 'value="comms"' in USERS_HTML
    assert 'value="comms"' in USERS_JS
    assert "admin|user|comms" in (ROOT / "app/routers/users.py").read_text(encoding="utf-8")


def test_comms_page_has_two_seeded_planner_tabs():
    assert 'id="sheetTabs"' in COMMS_HTML
    assert 'id="btnColumns"' in COMMS_HTML
    assert 'id="btnAddRow"' in COMMS_HTML
    assert 'id="commsDrawer"' in COMMS_HTML
    assert 'id="commsDrawerTabs"' in COMMS_HTML
    assert "commsDocVis" in COMMS_JS
    assert 'value="users"' in COMMS_JS
    assert 'value="comms"' in COMMS_JS
    assert "data-open-row" in COMMS_JS
    assert "saveGroupColor" in COMMS_JS
    assert "secondaryColumn" in COMMS_JS
    assert "DRAWER_TAB_RULES" in COMMS_JS
    assert "Link / files" not in COMMS_JS
    assert "filterableColumns" in COMMS_JS
    assert 'id="commsFilters"' in COMMS_HTML
    assert 'id="commsResources"' in COMMS_HTML
    assert 'id="exportDialog"' in COMMS_HTML
    assert 'id="btnExport"' in COMMS_HTML
    assert 'data-view="resources"' in COMMS_JS
    assert "Templates" in COMMS_JS
    assert "/api/comms/resources" in COMMS_JS
    assert "/api/comms/export" in COMMS_JS
    assert "apply_all" in COMMS_JS
    assert 'def list_resources' in COMMS_PY
    assert 'def create_resource_section' in COMMS_PY
    assert 'def export_comms' in COMMS_PY
    assert "filter-drop" in COMMS_JS
    assert "comms-swatch" in (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
    assert "/api/comms/sheets" in COMMS_JS
    assert "/api/comms/sites" in COMMS_JS
    assert "visibility" in COMMS_JS
    assert "settings" in COMMS_PY
    assert SEED.is_file()
    text = SEED.read_text(encoding="utf-8")
    assert '"key": "fmrp_26_27"' in text
    assert '"key": "maintenance_26_27"' in text
    assert '"title": "FMRP 26-27"' in text
    assert '"title": "Maintenance"' in text


def test_comms_router_and_page_wired():
    assert 'prefix="/api/comms"' in COMMS_PY
    assert "require_comms" in COMMS_PY
    assert "def create_column" in COMMS_PY
    assert "def delete_column" in COMMS_PY
    assert 'visibility=vis' in COMMS_PY
    assert 'source="comms"' in COMMS_PY
    assert 'def comms_page' in MAIN
    assert "is_comms_path" in MAIN
    assert "COMMS_ROLE" in AUTH_PY


def test_resource_urls_only_allow_web_links():
    assert normalize_resource_url("ventia.sharepoint.com/sites/comms") == "https://ventia.sharepoint.com/sites/comms"
    assert normalize_resource_url("https://ventia.sharepoint.com/teams/CT-Transport-3057") == (
        "https://ventia.sharepoint.com/teams/CT-Transport-3057"
    )
    try:
        normalize_resource_url("javascript:alert(1)")
        assert False
    except ValueError:
        pass
    try:
        normalize_resource_url("https://user:pass@evil.example/x")
        assert False
    except ValueError:
        pass


def test_comms_export_collects_selected_columns():
    tables = collect_export_tables(
        [
            {
                "title": "FMRP",
                "columns": [{"field_key": "workpack", "name": "Workpack"}],
                "rows": [
                    {
                        "id": 1,
                        "values": {"workpack": "27A", "location": "Kororoit Creek Rd"},
                        "site": {"road_name": "BALLARAT RD", "site_number": "S51"},
                        "document_count": 2,
                    }
                ],
            }
        ],
        column_keys=["workpack", "_files"],
        row_ids=None,
        include_job=True,
    )
    assert tables[0]["headers"] == ["Job", "Workpack", "Files"]
    assert tables[0]["rows"][0] == ["Kororoit Creek Rd", "27A", "2"]
    xlsx = build_comms_xlsx(tables, title="WRU comms")
    pdf = build_comms_pdf(tables, title="WRU comms")
    assert xlsx[:2] == b"PK"
    assert pdf.startswith(b"%PDF")


def test_comms_v20_notes_form_and_export_selects():
    assert 'class="comms-page"' in COMMS_HTML
    assert 'id="exportSheetScope"' in COMMS_HTML
    assert 'id="exportRows"' in COMMS_HTML
    assert 'id="exportColScope"' in COMMS_HTML
    assert 'id="commsFormBuilder"' in COMMS_HTML
    assert 'id="formFieldDialog"' in COMMS_HTML
    assert 'id="jobCategory"' in COMMS_JS
    assert 'id="jobPick"' in COMMS_JS
    assert 'id="commsNoteText"' in COMMS_JS
    assert 'id="btnAddNote"' in COMMS_JS
    assert 'id="commsScopeFile"' in COMMS_JS
    assert 'id="btnUploadScope"' in COMMS_JS
    assert "data-form-field" in COMMS_JS
    assert "uploadCommsRowFile" in COMMS_JS
    assert "/api/comms/form-fields" in COMMS_JS
    assert "/api/comms/site-categories" in COMMS_JS
    assert "/api/comms/rows/" in COMMS_JS
    assert "category: \"scoping\"" in COMMS_JS
    assert "def list_row_notes" in COMMS_PY
    assert "def create_row_note" in COMMS_PY
    assert "def list_form_fields" in COMMS_PY
    assert "def list_site_categories" in COMMS_PY
    assert "form_values" in COMMS_PY
    assert "SCOPING_CATEGORY" in COMMS_PY
    css = (ROOT / "app/static/css/style.css").read_text(encoding="utf-8")
    assert "html:has(body.comms-page)" in css
    assert "body.comms-page" in css
    assert ".comms-note-log" in css
    models = (ROOT / "app/models.py").read_text(encoding="utf-8")
    assert "class CommsRowNote" in models
    assert "class CommsTemplateField" in models
    assert '"scoping"' in models


def test_comms_only_docs_hidden_from_normal_users():
    hidden = _Doc("comms")
    shown = _Doc("users")
    assert document_is_visible(shown, _User(USER_ROLE))
    assert not document_is_visible(hidden, _User(USER_ROLE))
    assert document_is_visible(hidden, _User(COMMS_ROLE))
    assert document_is_visible(hidden, _User(ADMIN_ROLE))
