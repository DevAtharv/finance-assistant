from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify
import os
from app.services.analyzer import analyze_transactions
from datetime import datetime

dashboard_bp = Blueprint("dashboard", __name__)

def get_supabase():
    from supabase import create_client
    from app.routes.auth import refresh_session_if_needed
    refresh_session_if_needed()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    access_token = session.get("access_token")
    if access_token:
        sb.postgrest.auth(access_token)
    return sb

@dashboard_bp.route("/dashboard")
def index():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))

    month = request.args.get("month", datetime.today().strftime("%Y-%m"))
    user_id = session.get("user_id")

    # Defaults
    summary = {
        "total_income": 0, "total_expenses": 0,
        "income_trend": 0, "expense_trend": 0,
        "savings_trend": 0, "total_count": 0, "new_this_month": 0
    }
    transactions = []
    categories = []
    top_merchants = []
    chart_data = {"labels": [], "income": [], "expense": []}
    gmail_connected = False

    try:
        sb = get_supabase()

        # Check Gmail connection
        try:
            gres = sb.table("gmail_tokens").select("gmail_connected") \
                .eq("user_id", user_id).limit(1).execute()
            if gres.data:
                gmail_connected = gres.data[0].get("gmail_connected", False)
        except Exception:
            pass

        # Fetch all transactions
        res = sb.table("transactions").select("*").eq("user_id", user_id).execute()
        all_txns = res.data or []

        # Filter to current month
        month_txns = [t for t in all_txns if str(t.get("date", "")).startswith(month)]

        transactions = sorted(month_txns, key=lambda t: t.get("date", ""), reverse=True)

        # Summary
        income_txns  = [t for t in month_txns if t.get("type") == "credit"]
        expense_txns = [t for t in month_txns if t.get("type") == "debit"]
        total_income   = sum(float(t.get("amount", 0)) for t in income_txns)
        total_expenses = sum(float(t.get("amount", 0)) for t in expense_txns)

        summary = {
            "total_income":    round(total_income, 2),
            "total_expenses":  round(total_expenses, 2),
            "income_trend":    0,
            "expense_trend":   0,
            "savings_trend":   0,
            "total_count":     len(month_txns),
            "new_this_month":  len(month_txns),
        }

        # Categories (expenses only, sorted by total)
        cat_map = {}
        for t in expense_txns:
            cat = t.get("category") or "Uncategorized"
            cat_map[cat] = cat_map.get(cat, 0) + float(t.get("amount", 0))
        categories = sorted(
            [{"category": k, "total": round(v, 2)} for k, v in cat_map.items()],
            key=lambda x: x["total"], reverse=True
        )

        # Top merchants
        merch_map = {}
        for t in expense_txns:
            name = t.get("merchant_clean") or t.get("merchant") or "Unknown"
            if name not in merch_map:
                merch_map[name] = {"merchant": name, "merchant_clean": name, "count": 0, "total": 0}
            merch_map[name]["count"] += 1
            merch_map[name]["total"] += float(t.get("amount", 0))
        top_merchants = sorted(merch_map.values(), key=lambda x: x["total"], reverse=True)[:5]
        for m in top_merchants:
            m["total"] = round(m["total"], 2)

        # Chart data — daily buckets for the month
        from collections import defaultdict
        daily_income  = defaultdict(float)
        daily_expense = defaultdict(float)
        for t in month_txns:
            day = str(t.get("date", ""))[-2:]  # last 2 chars = day
            if t.get("type") == "credit":
                daily_income[day]  += float(t.get("amount", 0))
            else:
                daily_expense[day] += float(t.get("amount", 0))

        all_days = sorted(set(list(daily_income.keys()) + list(daily_expense.keys())))
        if all_days:
            chart_data = {
                "labels":  [f"{month}-{d}" for d in all_days],
                "income":  [round(daily_income.get(d, 0), 2)  for d in all_days],
                "expense": [round(daily_expense.get(d, 0), 2) for d in all_days],
            }
        else:
            # Placeholder so chart renders empty gracefully
            chart_data = {"labels": ["No data"], "income": [0], "expense": [0]}

    except Exception as e:
        # Don't crash the page — just show empty state
        print(f"Dashboard error: {e}")

    return render_template(
        "dashboard.html",
        month=month,
        summary=summary,
        transactions=transactions,
        categories=categories,
        top_merchants=top_merchants,
        chart_data=chart_data,
        gmail_connected=gmail_connected,
    )


@dashboard_bp.route("/api/dashboard")
def api_data():
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    month = request.args.get("month", datetime.today().strftime("%Y-%m"))
    user_id = session.get("user_id")
    try:
        sb = get_supabase()
        res = sb.table("transactions").select("*").eq("user_id", user_id).execute()
        transactions = res.data or []
        analysis = analyze_transactions(transactions, month)
        return jsonify(analysis)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@dashboard_bp.route("/api/transactions")
def api_transactions():
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    month = request.args.get("month", datetime.today().strftime("%Y-%m"))
    user_id = session.get("user_id")
    sb = get_supabase()
    res = sb.table("transactions").select("*").eq("user_id", user_id)\
        .gte("date", f"{month}-01").lte("date", f"{month}-31")\
        .order("date", desc=True).execute()
    return jsonify(res.data or [])