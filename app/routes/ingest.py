from flask import Blueprint, render_template, request, redirect, url_for, session, jsonify
import os
from app.services.sms_parser import parse_bulk_sms
from app.services.pdf_csv_parser import parse_pdf, parse_csv
from app.services.categorize_transaction import categorize_transactions

ingest_bp = Blueprint("ingest", __name__)

def get_supabase():
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    access_token = session.get("access_token")
    if access_token:
        sb.postgrest.auth(access_token)
    return sb

@ingest_bp.route("/ingest")
def index():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))
    return render_template("ingest.html")

@ingest_bp.route("/ingest/sms", methods=["POST"])
def ingest_sms():
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    sms_text = request.form.get("sms_text", "").strip()
    if not sms_text:
        return jsonify({"error": "No SMS text provided"}), 400
    transactions = parse_bulk_sms(sms_text)
    if not transactions:
        return jsonify({"error": "No transactions found in SMS text"}), 400
    transactions = categorize_transactions(transactions)
    saved = save_transactions(transactions)
    return jsonify({"success": True, "count": len(saved), "transactions": saved[:5]})

@ingest_bp.route("/ingest/file", methods=["POST"])
def ingest_file():
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400
    filename = file.filename.lower()
    content = file.read()
    if len(content) > 10 * 1024 * 1024:
        return jsonify({"error": "File too large (max 10MB)"}), 400
    try:
        if filename.endswith(".pdf"):
            transactions = parse_pdf(content)
        elif filename.endswith(".csv"):
            transactions = parse_csv(content)
        else:
            return jsonify({"error": "Only PDF and CSV files are supported"}), 400
        if not transactions:
            return jsonify({"error": "No transactions found in file"}), 400
        transactions = categorize_transactions(transactions)
        saved = save_transactions(transactions)
        return jsonify({"success": True, "count": len(saved), "transactions": saved[:5]})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Failed to process file"}), 500

def save_transactions(transactions: list) -> list:
    user_id = session.get("user_id")
    sb = get_supabase()
    rows = []
    for tx in transactions:
        row = {
            "user_id": user_id,
            "date": tx.get("date"),
            "amount": tx.get("amount"),
            "type": tx.get("type"),
            "merchant": tx.get("merchant", "Unknown"),
            "merchant_clean": tx.get("merchant_clean", tx.get("merchant", "Unknown")),
            "category": tx.get("category", "Other"),
            "subcategory": tx.get("subcategory", "Uncategorized"),
            "payment_mode": tx.get("payment_mode", "Other"),
            "bank": tx.get("bank", "Unknown"),
            "raw_text": tx.get("raw_text", ""),
        }
        rows.append(row)
    if rows:
        sb.table("transactions").insert(rows).execute()
    return rows