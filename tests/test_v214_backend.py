"""Backend helpers for v2.14 prefs, MSP import, and weather labels."""

from app.msp_import import parse_msp_xml
from app.user_prefs import normalize_prefs
from app.weather import weather_label


def test_normalize_prefs_defaults_and_theme():
    prefs = normalize_prefs(None)
    assert prefs["theme"] == "system"
    assert prefs["quick_links"]
    assert "costs" in prefs["home_widgets"]
    merged = normalize_prefs({"theme": "dark", "comms_sort": "date", "quick_links": ["/shifts", "/bogus"]})
    assert merged["theme"] == "dark"
    assert merged["comms_sort"] == "date"
    assert merged["quick_links"] == ["/shifts"]


def test_weather_label_thunderstorm():
    assert weather_label(95) == "Thunderstorm"
    assert weather_label("nope") == "Unknown"


def test_parse_msp_xml_tasks():
    xml = b"""<?xml version="1.0"?>
    <Project xmlns="http://schemas.microsoft.com/project">
      <Tasks>
        <Task>
          <UID>1</UID>
          <ID>1</ID>
          <Name>S28 Lifecycle</Name>
          <Start>2026-03-02T08:00:00</Start>
          <Finish>2026-03-06T17:00:00</Finish>
          <Duration>PT40H0M0S</Duration>
          <Summary>0</Summary>
        </Task>
      </Tasks>
    </Project>"""
    tasks = parse_msp_xml(xml)
    assert tasks
    assert tasks[0]["name"] == "S28 Lifecycle"
    assert tasks[0]["start"] == "2026-03-02"
