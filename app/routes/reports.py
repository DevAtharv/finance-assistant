from flask import Blueprint, session, redirect, url_for, send_file, request
import os, io
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
from reportlab.lib.enums import TA_CENTER
from app.services.analyzer import analyze_transactions, get_ai_summary

reports_bp = Blueprint("reports", __name__)

def get_supabase():
    from supabase import create_client
    from app.routes.auth import refresh_session_if_needed
    refresh_session_if_needed()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    access_token = session.get("access_token")
    if access_token:
        sb.postgrest.auth(access_token)
    return sb

BRAND_GREEN = colors.HexColor("#10B981")
BRAND_DARK  = colors.HexColor("#0D1117")
BRAND_GRAY  = colors.HexColor("#6B7280")
BRAND_RED   = colors.HexColor("#EF4444")

@reports_bp.route("/report")
def generate_report():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))

    month   = request.args.get("month", datetime.today().strftime("%Y-%m"))
    user_id = session.get("user_id")

    try:
        sb  = get_supabase()
        res = sb.table("transactions").select("*").eq("user_id", user_id).execute()
        transactions = res.data or []
        print(f"Report: {len(transactions)} transactions for {user_id}")
    except Exception as e:
        print(f"Report fetch error: {e}")
        transactions = []

    analysis   = analyze_transactions(transactions, month)
    ai_summary = get_ai_summary(transactions, analysis)
    pdf_buffer = build_pdf(analysis, ai_summary, month, session.get("email", ""))

    return send_file(
        pdf_buffer,
        as_attachment=True,
        download_name=f"getsync_report_{month}.pdf",
        mimetype="application/pdf"
    )


def build_pdf(analysis, ai_summary, month, email):
    buffer   = io.BytesIO()
    doc      = SimpleDocTemplate(buffer, pagesize=A4,
                                 leftMargin=2*cm, rightMargin=2*cm,
                                 topMargin=2*cm, bottomMargin=2*cm)
    month_label = datetime.strptime(month, "%Y-%m").strftime("%B %Y")

    title_style = ParagraphStyle("title", fontSize=24, textColor=BRAND_DARK,
                                 spaceAfter=4, fontName="Helvetica-Bold")
    subtitle_style = ParagraphStyle("subtitle", fontSize=11, textColor=BRAND_GRAY, spaceAfter=20)
    section_style  = ParagraphStyle("section", fontSize=13, textColor=BRAND_DARK,
                                    fontName="Helvetica-Bold", spaceBefore=16, spaceAfter=8)
    body_style     = ParagraphStyle("body", fontSize=10, textColor=BRAND_GRAY, leading=16, spaceAfter=12)
    footer_style   = ParagraphStyle("footer", fontSize=8, textColor=BRAND_GRAY,
                                    alignment=TA_CENTER, spaceBefore=8)

    story = []
    s = analysis.get("summary", {})

    # Header
    story.append(Paragraph("GetSync — Finance Report", title_style))
    story.append(Paragraph(f"{month_label} · {email}", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=2, color=BRAND_GREEN))
    story.append(Spacer(1, 0.4*cm))

    # AI Summary
    story.append(Paragraph("Monthly Summary", section_style))
    summary_text = ai_summary if ai_summary else "No summary available."
    story.append(Paragraph(summary_text, body_style))
    story.append(Spacer(1, 0.3*cm))

    # At a Glance
    story.append(Paragraph("At a Glance", section_style))
    summary_data = [
        ["Metric", "Amount"],
        ["Total Income",    f"Rs. {s.get('total_income', 0):,.0f}"],
        ["Total Expenses",  f"Rs. {s.get('total_expense', 0):,.0f}"],
        ["Net Savings",     f"Rs. {s.get('savings', 0):,.0f}"],
        ["Savings Rate",    f"{s.get('savings_rate', 0)}%"],
        ["Transactions",    str(s.get('transaction_count', 0))],
    ]
    t = Table(summary_data, colWidths=[9*cm, 8*cm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), BRAND_DARK),
        ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
        ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTSIZE",   (0,0), (-1,-1), 10),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("GRID",    (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
        ("PADDING", (0,0), (-1,-1), 8),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.4*cm))

    # Category breakdown
    cat_breakdown = analysis.get("category_breakdown", [])
    if cat_breakdown:
        story.append(Paragraph("Spending by Category", section_style))
        cat_data = [["Category", "Amount", "% of Spend"]]
        for cat in cat_breakdown:
            cat_data.append([
                cat.get("category", "Other"),
                f"Rs. {cat.get('amount', 0):,.0f}",
                f"{cat.get('percentage', 0)}%"
            ])
        ct = Table(cat_data, colWidths=[9*cm, 5*cm, 4*cm])
        ct.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), BRAND_DARK),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,-1), 10),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("GRID",    (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
            ("PADDING", (0,0), (-1,-1), 8),
        ]))
        story.append(ct)
        story.append(Spacer(1, 0.4*cm))

    # Recent transactions table
    story.append(Paragraph("Recent Transactions", section_style))
    txn_list = analysis.get("recent_transactions", [])
    if txn_list:
        txn_data = [["Date", "Merchant", "Category", "Type", "Amount"]]
        for tx in txn_list[:20]:
            txn_data.append([
                str(tx.get("date", ""))[:10],
                str(tx.get("merchant_clean") or tx.get("merchant") or "Unknown")[:30],
                str(tx.get("category", "Other"))[:20],
                tx.get("type", "debit"),
                f"Rs. {float(tx.get('amount', 0)):,.0f}",
            ])
        tt = Table(txn_data, colWidths=[3*cm, 5.5*cm, 3.5*cm, 2.5*cm, 3.5*cm])
        tt.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), BRAND_DARK),
            ("TEXTCOLOR",  (0,0), (-1,0), colors.white),
            ("FONTNAME",   (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE",   (0,0), (-1,-1), 9),
            ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F9FAFB")]),
            ("GRID",    (0,0), (-1,-1), 0.5, colors.HexColor("#E5E7EB")),
            ("PADDING", (0,0), (-1,-1), 6),
        ]))
        story.append(tt)
    else:
        story.append(Paragraph("No transactions found for this month.", body_style))

    # Footer
    story.append(Spacer(1, 0.5*cm))
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_GRAY))
    story.append(Paragraph(
        f"Generated by GetSync · {datetime.today().strftime('%d %b %Y')}",
        footer_style
    ))

    doc.build(story)
    buffer.seek(0)
    return buffer
