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
    return render_template("dashboard.html", month=month)

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