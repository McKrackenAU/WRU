"""Shared Ventia / VenInspect-style PDF branding for WRU exports.

Colour tokens and header/footer layout mirror McKrackenAU/VenInspect
``src/lib/report-pdf.ts`` so client-facing PDFs feel like one family.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

# VenInspect report-pdf.ts tokens
GREEN = colors.HexColor("#004825")
GREEN_MID = colors.HexColor("#00994d")
INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5c6670")
RULE = colors.HexColor("#c5cdd4")
ROW_ALT = colors.HexColor("#f6faef")
HEADER_FILL = colors.HexColor("#004825")
WARN_TINT = colors.HexColor("#FDE8D8")

BRAND_DIR = Path(__file__).resolve().parent / "static" / "brand"
VENTIA_LOGO = BRAND_DIR / "ventia-logo.png"


def draw_branded_page(canvas: Canvas, doc) -> None:
    """Header + footer chrome drawn on every page (VenInspect-style).

    Compatible with ``SimpleDocTemplate`` ``onFirstPage`` / ``onLaterPages``.
    Optional attributes on ``doc``:
      brand_eyebrow, brand_title, brand_subtitle,
      brand_doc_kind, brand_product, brand_footer_meta
    """
    canvas.saveState()
    page_w, page_h = doc.pagesize
    margin = doc.leftMargin

    eyebrow = getattr(doc, "brand_eyebrow", None) or "WRU TGS TRACKER"
    title = getattr(doc, "brand_title", None) or "Priority List"
    subtitle = getattr(doc, "brand_subtitle", None) or ""
    doc_kind = getattr(doc, "brand_doc_kind", None) or "Priority List"
    product = getattr(doc, "brand_product", None) or "WRU TGS TRACKER"
    footer_meta = getattr(doc, "brand_footer_meta", None) or ""

    # Top brand bar (VenInspect: rect 0,0,PAGE_W,8)
    canvas.setFillColor(GREEN)
    canvas.rect(0, page_h - 8, page_w, 8, fill=1, stroke=0)

    # Ventia wordmark (top-right)
    logo_h = 10 * mm
    logo_w = 31 * mm
    if VENTIA_LOGO.is_file():
        try:
            canvas.drawImage(
                str(VENTIA_LOGO),
                page_w - margin - logo_w,
                page_h - 8 - 3 * mm - logo_h,
                width=logo_w,
                height=logo_h,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(margin, page_h - 8 - 7 * mm, str(eyebrow).upper())

    canvas.setFillColor(GREEN)
    canvas.setFont("Helvetica-Bold", 13)
    canvas.drawString(margin, page_h - 8 - 13 * mm, title[:90])

    if subtitle:
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(margin, page_h - 8 - 18 * mm, subtitle[:120])

    # Rule under header
    rule_y = page_h - 8 - 22 * mm
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.8)
    canvas.line(margin, rule_y, page_w - margin, rule_y)

    # Footer
    footer_y = 10 * mm
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.6)
    canvas.line(margin, footer_y + 6 * mm, page_w - margin, footer_y + 6 * mm)

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(margin, footer_y, doc_kind)

    canvas.setFillColor(GREEN)
    canvas.setFont("Helvetica-Bold", 7)
    canvas.drawString(margin + 28 * mm, footer_y, product)

    canvas.setFillColor(MUTED)
    canvas.setFont("Helvetica", 7)
    generated = datetime.now().strftime("%d/%m/%Y %H:%M")
    mid = f"{footer_meta} · {generated}" if footer_meta else generated
    canvas.drawString(margin + 62 * mm, footer_y, mid)

    page_label = f"{canvas.getPageNumber()}"
    canvas.drawRightString(page_w - margin, footer_y, page_label)

    canvas.restoreState()


def branded_margins(*, landscape_mode: bool = True) -> dict[str, float]:
    """Margins that clear the drawn header/footer bands."""
    if landscape_mode:
        return {
            "leftMargin": 12 * mm,
            "rightMargin": 12 * mm,
            "topMargin": 34 * mm,
            "bottomMargin": 16 * mm,
        }
    return {
        "leftMargin": 16 * mm,
        "rightMargin": 16 * mm,
        "topMargin": 36 * mm,
        "bottomMargin": 18 * mm,
    }
