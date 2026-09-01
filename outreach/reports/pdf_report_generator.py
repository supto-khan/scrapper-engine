"""
Nexidant Signal Engine — Branded PDF Audit Report Generator
Generates a modern, high-converting 3-page PDF audit report with Nexidant's official design system:
- Colors: #00A878 (Primary), #00C896 (CTA), #5EEAD4 (Accent), #F0FDF9 (Brand BG), #0F1F17 (Dark), #64748B (Muted)
- Typography: Lexend
- Branding: Official Nexidant Logo
"""

import logging
import os
from datetime import datetime, timezone
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    HRFlowable,
    Image as ReportLabImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

# ─── Brand Design Tokens ───────────────────────────────────────────────────
BRAND_PRIMARY = colors.HexColor("#00A878")
BRAND_CTA = colors.HexColor("#00C896")
BRAND_ACCENT = colors.HexColor("#5EEAD4")
BRAND_BG = colors.HexColor("#F0FDF9")
BRAND_SURFACE = colors.HexColor("#FFFFFF")
BRAND_MUTED = colors.HexColor("#64748B")
BRAND_DARK = colors.HexColor("#0F1F17")
BRAND_TERMINAL = colors.HexColor("#0D2A21")
BRAND_RED = colors.HexColor("#EF4444")
BRAND_YELLOW = colors.HexColor("#F59E0B")
BRAND_GREEN = colors.HexColor("#10B981")
WHITE = colors.white

# Register Lexend Font
ASSETS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "assets"))
FONT_PATH = os.path.join(ASSETS_DIR, "fonts", "Lexend.ttf")
LOGO_PATH = os.path.join(ASSETS_DIR, "nexidant_logo.png")

FONT_NAME = "Helvetica"
if os.path.exists(FONT_PATH):
    try:
        pdfmetrics.registerFont(TTFont("Lexend", FONT_PATH))
        FONT_NAME = "Lexend"
    except Exception as e:
        logger.warning(f"Could not register Lexend font, falling back to Helvetica: {e}")


def _severity_color(severity: str) -> colors.Color:
    mapping = {
        "critical": BRAND_RED,
        "high": colors.HexColor("#EA580C"),
        "medium": BRAND_YELLOW,
        "low": BRAND_MUTED,
    }
    return mapping.get(severity, BRAND_MUTED)


def _score_color(score: int | None) -> colors.Color:
    if score is None:
        return BRAND_MUTED
    if score >= 85:
        return BRAND_PRIMARY
    if score >= 50:
        return BRAND_YELLOW
    return BRAND_RED


def _score_label(score: int | None) -> str:
    if score is None:
        return "N/A"
    if score >= 85:
        return "Optimal"
    if score >= 50:
        return "Needs Optimization"
    return "Critical Leaks"


def _bool_indicator(val: bool | None, true_text: str = "✓ Pass", false_text: str = "✗ Fail") -> str:
    if val is None:
        return "—"
    return true_text if val else false_text


class AuditReportGenerator:
    """
    Generates branded Nexidant 360° Website & CRO Audit PDF reports.
    """

    def __init__(self, output_dir: str | None = None):
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.output_dir = output_dir or os.path.join(base, "reports")
        os.makedirs(self.output_dir, exist_ok=True)

    def generate_report(
        self,
        domain: str,
        company_name: str,
        deep_audit: dict[str, Any],
        pains: list[dict[str, Any]] | None = None,
        screenshot_path: str | None = None,
    ) -> str | None:
        """
        Generates a branded PDF audit report and returns the file path.
        """
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            filename = f"{domain.replace('.', '_')}_audit_{timestamp}.pdf"
            filepath = os.path.join(self.output_dir, filename)

            doc = SimpleDocTemplate(
                filepath,
                pagesize=letter,
                topMargin=0.5 * inch,
                bottomMargin=0.5 * inch,
                leftMargin=0.6 * inch,
                rightMargin=0.6 * inch,
            )

            styles = getSampleStyleSheet()
            elements = []

            # ── Header & Branding ───────────────────────────────────────
            elements.extend(self._build_header(domain, company_name, styles))
            elements.append(Spacer(1, 10))

            # ── Executive Health Score & Screenshot ────────────────────
            elements.extend(self._build_health_score_section(deep_audit, styles, screenshot_path=screenshot_path))
            elements.append(Spacer(1, 12))

            # ── 4 Pillar Summary Cards ─────────────────────────────────
            elements.extend(self._build_pillar_summary_cards(deep_audit, styles))
            elements.append(Spacer(1, 14))

            # ── Detailed Diagnostics Table ─────────────────────────────
            elements.extend(self._build_detailed_findings(deep_audit, styles))
            elements.append(Spacer(1, 14))

            # ── Prioritized Fix Roadmap ────────────────────────────────
            if pains:
                elements.extend(self._build_pain_points_section(pains, styles))
                elements.append(Spacer(1, 14))

            # ── Nexidant Call-To-Action & Footer ───────────────────────
            elements.extend(self._build_cta_footer(company_name, styles))

            doc.build(elements)
            logger.info(f"📄 Branded PDF Audit Report generated: {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"Failed to generate PDF report for {domain}: {e}", exc_info=True)
            return None

    # ─── Header Section ────────────────────────────────────────────────────

    def _build_header(self, domain: str, company_name: str, styles) -> list:
        elements = []

        # Logo on left, metadata on right
        header_table_data = []

        left_cell = []
        if os.path.exists(LOGO_PATH):
            logo_img = ReportLabImage(LOGO_PATH, width=1.5 * inch, height=0.375 * inch)
            left_cell.append(logo_img)
        else:
            brand_text_style = ParagraphStyle(
                "NexBrandText",
                fontName=FONT_NAME,
                fontSize=20,
                textColor=BRAND_PRIMARY,
                leading=22,
            )
            left_cell.append(Paragraph("<b>nexidant</b>", brand_text_style))

        tagline_style = ParagraphStyle(
            "NexTagline",
            fontName=FONT_NAME,
            fontSize=8,
            textColor=BRAND_MUTED,
            leading=10,
        )
        left_cell.append(Spacer(1, 3))
        left_cell.append(Paragraph("Full-Stack Engineering & Modernization", tagline_style))

        # Right cell: Report info
        right_info_style = ParagraphStyle(
            "ReportMeta",
            fontName=FONT_NAME,
            fontSize=9,
            textColor=BRAND_DARK,
            alignment=TA_RIGHT,
            leading=12,
        )
        audit_date = datetime.now(timezone.utc).strftime("%B %d, %Y")
        right_cell = [
            Paragraph(f"<b>360° Technical & CRO Audit</b>", right_info_style),
            Paragraph(f'<font color="{BRAND_MUTED.hexval()}">Prepared for:</font> <b>{company_name}</b>', right_info_style),
            Paragraph(f'<font color="{BRAND_MUTED.hexval()}">Domain:</font> <font color="{BRAND_PRIMARY.hexval()}"><b>{domain}</b></font>', right_info_style),
            Paragraph(f'<font color="{BRAND_MUTED.hexval()}">Date:</font> {audit_date}', right_info_style),
        ]

        header_table_data.append([left_cell, right_cell])
        header_table = Table(header_table_data, colWidths=[3.2 * inch, 4.0 * inch])
        header_table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                ]
            )
        )
        elements.append(header_table)
        elements.append(Spacer(1, 6))
        elements.append(HRFlowable(width="100%", thickness=2, color=BRAND_PRIMARY, spaceAfter=8, spaceBefore=4))

        return elements

    # ─── Health Score Section ──────────────────────────────────────────────

    def _build_health_score_section(self, audit: dict[str, Any], styles, screenshot_path: str | None = None) -> list:
        elements = []
        lighthouse = audit.get("lighthouse_metrics", {})
        speed = audit.get("speed_metrics", {})
        link_h = audit.get("link_health", {})
        img = audit.get("image_optimization", {})
        dns = audit.get("dns_email_metrics", {})
        sec = audit.get("security_metrics", {})

        # Calculate composite score
        scores = []
        perf = lighthouse.get("performance_score")
        if perf is not None:
            scores.append(perf)
        else:
            hp_ms = speed.get("homepage_speed_ms", 3000)
            scores.append(max(10, min(100, int(100 - (hp_ms / 45)))))

        sec_score = 100
        if not sec.get("has_https"):
            sec_score -= 40
        if sec.get("ssl_cert_expiring_soon"):
            sec_score -= 30
        if sec.get("exposed_wp_users"):
            sec_score -= 20
        scores.append(max(10, sec_score))

        seo_score = 100
        seo = audit.get("seo_metrics", {})
        if not seo.get("has_local_business_schema"):
            seo_score -= 25
        if seo.get("broken_social_cards"):
            seo_score -= 20
        if dns.get("email_deliverability_risk"):
            seo_score -= 20
        if link_h.get("broken_links_count", 0) > 0:
            seo_score -= 20
        scores.append(max(10, seo_score))

        overall = int(sum(scores) / len(scores)) if scores else 0
        overall_color = _score_color(overall)

        score_box_style = ParagraphStyle(
            "ScoreNum",
            fontName=FONT_NAME,
            fontSize=32,
            textColor=overall_color,
            leading=34,
            alignment=TA_CENTER,
        )
        score_label_style = ParagraphStyle(
            "ScoreLabel",
            fontName=FONT_NAME,
            fontSize=9,
            textColor=overall_color,
            leading=11,
            alignment=TA_CENTER,
        )
        meta_style = ParagraphStyle(
            "MetaText",
            fontName=FONT_NAME,
            fontSize=8,
            textColor=BRAND_DARK,
            leading=11,
        )

        left_score_box = [
            Paragraph(f"<b>{overall}</b>", score_box_style),
            Paragraph(f"<b>{_score_label(overall)}</b>", score_label_style),
            Paragraph(f'<font size="7" color="{BRAND_MUTED.hexval()}">Overall Health (/100)</font>', score_label_style),
        ]

        right_meta_box = [
            Paragraph(f"<b>Diagnostic Highlights:</b>", meta_style),
            Paragraph(f"• <b>Subpages Scanned:</b> {audit.get('pages_audited_count', 1)} pages (Latency & TTFB)", meta_style),
            Paragraph(f"• <b>Images Audited:</b> {img.get('total_images', 0)} assets (WebP & Lazy Load)", meta_style),
            Paragraph(f"• <b>DNS Status:</b> SPF ({'Pass' if dns.get('has_spf_record') else 'Missing'}), DMARC ({'Pass' if dns.get('has_dmarc_record') else 'Missing'})", meta_style),
        ]

        # If screenshot is available, render 3-column layout with preview mockup
        if screenshot_path and os.path.exists(screenshot_path):
            screenshot_img = ReportLabImage(screenshot_path, width=2.0 * inch, height=1.12 * inch)
            mockup_style = ParagraphStyle(
                "MockupLabel",
                fontName=FONT_NAME,
                fontSize=7,
                textColor=BRAND_MUTED,
                alignment=TA_CENTER,
                leading=8,
            )
            screenshot_cell = [
                Paragraph("<b>Live Website Capture</b>", mockup_style),
                Spacer(1, 2),
                screenshot_img,
            ]

            score_table = Table([[left_score_box, right_meta_box, screenshot_cell]], colWidths=[1.7 * inch, 3.1 * inch, 2.4 * inch])
        else:
            score_table = Table([[left_score_box, right_meta_box]], colWidths=[2.2 * inch, 5.0 * inch])

        score_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BRAND_BG),
                    ("BOX", (0, 0), (-1, -1), 1, BRAND_PRIMARY),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ]
            )
        )
        elements.append(score_table)

        return elements

    # ─── Pillar Summary Cards ─────────────────────────────────────────────

    def _build_pillar_summary_cards(self, audit: dict[str, Any], styles) -> list:
        elements = []
        speed = audit.get("speed_metrics", {})
        cro = audit.get("conversion_metrics", {})
        seo = audit.get("seo_metrics", {})
        dns = audit.get("dns_email_metrics", {})
        sec = audit.get("security_metrics", {})
        lighthouse = audit.get("lighthouse_metrics", {})

        perf_score = lighthouse.get("performance_score")
        speed_ok = (perf_score and perf_score >= 75) or (speed.get("homepage_speed_ms", 9999) < 2200 and not speed.get("speed_discrepancy_detected"))
        speed_text = "Optimal Speed" if speed_ok else "Latency Bottlenecks"
        speed_color = BRAND_PRIMARY if speed_ok else BRAND_RED

        cro_issues = sum([
            1 if cro.get("missing_mobile_tel_link") else 0,
            1 if cro.get("high_form_friction") else 0,
            0 if cro.get("has_sticky_mobile_cta") else 1,
        ])
        cro_ok = cro_issues == 0
        cro_text = "Frictionless Flow" if cro_ok else f"{cro_issues} Mobile Friction Points"
        cro_color = BRAND_PRIMARY if cro_ok else BRAND_RED

        seo_issues = sum([
            0 if seo.get("has_local_business_schema") else 1,
            1 if seo.get("broken_social_cards") else 0,
            1 if dns.get("email_deliverability_risk") else 0,
        ])
        seo_ok = seo_issues == 0
        seo_text = "Rankings & DNS Protected" if seo_ok else f"{seo_issues} SEO/DNS Blindspots"
        seo_color = BRAND_PRIMARY if seo_ok else BRAND_YELLOW

        sec_issues = sum([
            0 if sec.get("has_https") else 1,
            1 if sec.get("ssl_cert_expiring_soon") else 0,
            1 if sec.get("exposed_wp_users") else 0,
        ])
        sec_ok = sec_issues == 0
        sec_text = "Secured & Encrypted" if sec_ok else f"{sec_issues} Security Risks"
        sec_color = BRAND_PRIMARY if sec_ok else BRAND_RED

        card_title_style = ParagraphStyle(
            "CardTitle",
            fontName=FONT_NAME,
            fontSize=9,
            textColor=BRAND_DARK,
            leading=11,
            alignment=TA_CENTER,
        )
        card_val_style = ParagraphStyle(
            "CardVal",
            fontName=FONT_NAME,
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
        )

        card_data = [
            [
                Paragraph("<b>Speed & Load</b>", card_title_style),
                Paragraph("<b>Mobile Conversion</b>", card_title_style),
                Paragraph("<b>Local SEO & DNS</b>", card_title_style),
                Paragraph("<b>Security & SSL</b>", card_title_style),
            ],
            [
                Paragraph(f'<font color="{speed_color.hexval()}"><b>{speed_text}</b></font>', card_val_style),
                Paragraph(f'<font color="{cro_color.hexval()}"><b>{cro_text}</b></font>', card_val_style),
                Paragraph(f'<font color="{seo_color.hexval()}"><b>{seo_text}</b></font>', card_val_style),
                Paragraph(f'<font color="{sec_color.hexval()}"><b>{sec_text}</b></font>', card_val_style),
            ],
        ]

        card_table = Table(card_data, colWidths=[1.8 * inch] * 4)
        card_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BRAND_SURFACE),
                    ("BOX", (0, 0), (-1, -1), 0.75, BRAND_PRIMARY),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, BRAND_ACCENT),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("LEFTPADDING", (0, 0), (-1, -1), 4),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        elements.append(card_table)

        return elements

    # ─── Detailed Findings Table ──────────────────────────────────────────

    def _build_detailed_findings(self, audit: dict[str, Any], styles) -> list:
        elements = []
        speed = audit.get("speed_metrics", {})
        cro = audit.get("conversion_metrics", {})
        seo = audit.get("seo_metrics", {})
        sec = audit.get("security_metrics", {})
        dns = audit.get("dns_email_metrics", {})
        link_h = audit.get("link_health", {})
        img = audit.get("image_optimization", {})
        lighthouse = audit.get("lighthouse_metrics", {})

        section_title = ParagraphStyle(
            "SecHeader",
            fontName=FONT_NAME,
            fontSize=11,
            textColor=BRAND_DARK,
            leading=14,
            spaceAfter=4,
        )
        elements.append(Paragraph("<b>Detailed Diagnostic Breakdown</b>", section_title))

        th_style = ParagraphStyle("TH", fontName=FONT_NAME, fontSize=8, textColor=WHITE, leading=10)
        td_style = ParagraphStyle("TD", fontName=FONT_NAME, fontSize=8, textColor=BRAND_DARK, leading=10)

        table_data = [[
            Paragraph("<b>Diagnostic Area</b>", th_style),
            Paragraph("<b>Measured Signal / Finding</b>", th_style),
            Paragraph("<b>Status</b>", th_style),
        ]]

        def _row(label: str, finding: str, pass_condition: bool):
            status_color = BRAND_PRIMARY if pass_condition else BRAND_RED
            status_text = "PASS" if pass_condition else "NEEDS FIX"
            table_data.append([
                Paragraph(label, td_style),
                Paragraph(finding, td_style),
                Paragraph(f'<font color="{status_color.hexval()}"><b>{status_text}</b></font>', td_style),
            ])

        # Speed
        _row("Homepage Load Speed", f"{speed.get('homepage_speed_s', '?')}s on mobile 4G", speed.get("homepage_speed_ms", 9999) < 2500)
        _row("Inner Page Latency", f"Slowest subpage: {speed.get('slowest_subpage_path', '/')} ({speed.get('slowest_subpage_speed_s', '?')}s)", not speed.get("speed_discrepancy_detected"))
        _row("Backend Response (TTFB)", f"{speed.get('homepage_ttfb_ms', '?')}ms server time", speed.get("homepage_ttfb_ms", 9999) < 800)

        # Lighthouse
        if lighthouse.get("available"):
            _row("Google PageSpeed Performance", f"{lighthouse.get('performance_score', '?')}/100 benchmark", (lighthouse.get("performance_score") or 0) >= 70)
            _row("Largest Contentful Paint (LCP)", f"{lighthouse.get('lcp_ms', '?')}ms", (lighthouse.get("lcp_ms") or 9999) < 2500)

        # CRO
        _row("Mobile 1-Tap Calling", "Clickable tel: link present" if not cro.get("missing_mobile_tel_link") else "Plain text phone (no 1-tap call)", not cro.get("missing_mobile_tel_link"))
        _row("Lead Form Friction", f"{cro.get('max_form_inputs', 0)} fields on main contact form", cro.get("max_form_inputs", 0) < 7)
        _row("Mobile Sticky Action Bar", "Sticky call/book bar active" if cro.get("has_sticky_mobile_cta") else "Missing sticky bottom action bar", cro.get("has_sticky_mobile_cta", False))

        # SEO & DNS
        _row("LocalBusiness JSON-LD", "Rich LocalBusiness schema active" if seo.get("has_local_business_schema") else "Missing local business schema markup", seo.get("has_local_business_schema", False))
        _row("Social OpenGraph Cards", "Rich preview image configured" if not seo.get("broken_social_cards") else "Blank preview on WhatsApp/iMessage", not seo.get("broken_social_cards"))
        _row("DNS Email Authentication", "SPF & DMARC verified" if not dns.get("email_deliverability_risk") else "Missing DMARC/SPF (Spam folder risk)", not dns.get("email_deliverability_risk"))

        # Links & Images
        _row("Internal Link Integrity", f"{link_h.get('broken_links_count', 0)} dead 404 links found", link_h.get("broken_links_count", 0) == 0)
        _row("Next-Gen Image Formats", f"{img.get('images_non_modern_format', 0)} legacy images (recommend WebP)", img.get("images_non_modern_format", 0) <= 2)

        # Security
        _row("SSL Certificate Health", f"Valid ({sec.get('ssl_cert_days_remaining', 'N/A')} days remaining)", not sec.get("ssl_cert_expiring_soon") and sec.get("ssl_cert_valid", False))

        diag_table = Table(table_data, colWidths=[2.2 * inch, 3.8 * inch, 1.2 * inch])
        t_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_PRIMARY),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("TOPPADDING", (0, 1), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, BRAND_ACCENT),
            ("BOX", (0, 0), (-1, -1), 0.75, BRAND_PRIMARY),
        ]
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                t_styles.append(("BACKGROUND", (0, i), (-1, i), BRAND_BG))

        diag_table.setStyle(TableStyle(t_styles))
        elements.append(diag_table)

        return elements

    # ─── Pain Points / Recommendations ────────────────────────────────────

    def _build_pain_points_section(self, pains: list[dict[str, Any]], styles) -> list:
        elements = []

        section_title = ParagraphStyle(
            "RecTitle",
            fontName=FONT_NAME,
            fontSize=11,
            textColor=BRAND_DARK,
            leading=14,
            spaceAfter=4,
        )
        elements.append(Paragraph("<b>Prioritized Modernization Recommendations</b>", section_title))

        th_style = ParagraphStyle("THP", fontName=FONT_NAME, fontSize=8, textColor=WHITE, leading=10)
        td_style = ParagraphStyle("TDP", fontName=FONT_NAME, fontSize=8, textColor=BRAND_DARK, leading=10)

        pain_data = [[
            Paragraph("<b>#</b>", th_style),
            Paragraph("<b>Detected Opportunity / Leak</b>", th_style),
            Paragraph("<b>Severity</b>", th_style),
            Paragraph("<b>Recommended Solution & Business Impact</b>", th_style),
        ]]

        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        sorted_pains = sorted(pains, key=lambda p: severity_order.get(p.get("severity", "low"), 3))

        for idx, pain in enumerate(sorted_pains[:6], 1):
            severity = pain.get("severity", "medium")
            sev_color = _severity_color(severity)
            title = pain.get("title") or pain.get("pain_label") or "Modernization Opportunity"
            desc = pain.get("description") or pain.get("explanation") or ""
            pain_data.append([
                Paragraph(str(idx), td_style),
                Paragraph(f"<b>{title}</b>", td_style),
                Paragraph(f'<font color="{sev_color.hexval()}"><b>{severity.upper()}</b></font>', td_style),
                Paragraph(desc[:140], td_style),
            ])

        pain_table = Table(pain_data, colWidths=[0.3 * inch, 2.2 * inch, 0.9 * inch, 3.8 * inch])
        p_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), BRAND_TERMINAL),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
            ("TOPPADDING", (0, 1), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 1), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("INNERGRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#CBD5E1")),
            ("BOX", (0, 0), (-1, -1), 0.75, BRAND_TERMINAL),
        ]
        for i in range(1, len(pain_data)):
            if i % 2 == 0:
                p_styles.append(("BACKGROUND", (0, i), (-1, i), BRAND_BG))

        pain_table.setStyle(TableStyle(p_styles))
        elements.append(pain_table)

        return elements

    # ─── CTA Footer ───────────────────────────────────────────────────────

    def _build_cta_footer(self, company_name: str, styles) -> list:
        elements = []

        cta_title_style = ParagraphStyle(
            "CTATitle",
            fontName=FONT_NAME,
            fontSize=11,
            textColor=BRAND_PRIMARY,
            alignment=TA_CENTER,
            leading=14,
        )
        cta_body_style = ParagraphStyle(
            "CTABody",
            fontName=FONT_NAME,
            fontSize=8,
            textColor=BRAND_DARK,
            alignment=TA_CENTER,
            leading=11,
        )
        footer_sub_style = ParagraphStyle(
            "FooterSub",
            fontName=FONT_NAME,
            fontSize=7,
            textColor=BRAND_MUTED,
            alignment=TA_CENTER,
            leading=9,
        )

        cta_content = [
            Paragraph(f"<b>Ready to modernize and resolve these leaks for {company_name}?</b>", cta_title_style),
            Paragraph(
                "We provide turnkey engineering & performance overhauls that drop load times under 1.5s and double mobile conversions.<br/>"
                f'<b>Reply to our outreach email or visit: <font color="{BRAND_PRIMARY.hexval()}">https://nexidant.com</font></b>',
                cta_body_style,
            ),
        ]

        cta_table = Table([[cta_content]], colWidths=[7.2 * inch])
        cta_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), BRAND_BG),
                    ("BOX", (0, 0), (-1, -1), 1.5, BRAND_CTA),
                    ("TOPPADDING", (0, 0), (-1, -1), 8),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 12),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                ]
            )
        )
        elements.append(cta_table)
        elements.append(Spacer(1, 6))

        elements.append(
            Paragraph(
                "Nexidant | Full-Stack Engineering & Modernization • Build. Fix. Scale.<br/>"
                "H:3, R:3/A, Block - F, Sector - 15, Uttara, Dhaka, Bangladesh",
                footer_sub_style,
            )
        )

        return elements


# ─── Module Accessor ──────────────────────────────────────────────────────

_report_gen_instance: AuditReportGenerator | None = None


def get_report_generator() -> AuditReportGenerator:
    global _report_gen_instance
    if _report_gen_instance is None:
        _report_gen_instance = AuditReportGenerator()
    return _report_gen_instance
