"""Generic MoA linking is per-site and must not overwrite another site's number."""

from types import SimpleNamespace
from unittest.mock import patch

from app.services import apply_generic_moa_link


def test_link_sets_fk_without_overwriting_existing_moa():
    generic = SimpleNamespace(id=9, is_generic_moa=True, moa_number="GEN-100", tgs_reference="TGS-G")
    site = SimpleNamespace(
        id=1,
        moa_number="OWN-22",
        tgs_reference="TGS-SITE",
        linked_generic_moa_id=None,
    )
    with patch("app.services.mark_ready_for_works"):
        apply_generic_moa_link(site, generic, None)
    assert site.linked_generic_moa_id == 9
    assert site.moa_number == "OWN-22"
    assert site.tgs_reference == "TGS-SITE"


def test_link_fills_blank_moa_from_generic():
    generic = SimpleNamespace(id=9, is_generic_moa=True, moa_number="GEN-100", tgs_reference="TGS-G")
    site = SimpleNamespace(id=2, moa_number=None, tgs_reference=None, linked_generic_moa_id=None)
    with patch("app.services.mark_ready_for_works"):
        apply_generic_moa_link(site, generic, None)
    assert site.linked_generic_moa_id == 9
    assert site.moa_number == "GEN-100"
    assert site.tgs_reference == "TGS-G"


def test_unlink_clears_only_the_fk():
    site = SimpleNamespace(id=3, moa_number="OWN-22", linked_generic_moa_id=9)
    apply_generic_moa_link(site, None, None)
    assert site.linked_generic_moa_id is None
    assert site.moa_number == "OWN-22"
