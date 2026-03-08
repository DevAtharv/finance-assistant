from flask import Blueprint, redirect, url_for, session, request, jsonify, render_template_string
import os
import json

gmail_bp = Blueprint("gmail", __name__)

def get_supabase():
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    access_token = session.get("access_token")
    if access_token:
        sb.postgrest.auth(access_token)
    return sb

def get_google_flow():
    from google_auth_oauthlib.flow import Flow
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ["GMAIL_CLIENT_ID"],
                "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:5000/gmail/callback")],
            }
        },
        scopes=["https://www.googleapis.com/auth/gmail.readonly"]
    )
    flow.redirect_uri = os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:5000/gmail/callback")
    return flow

@gmail_bp.route("/gmail/connect")
def connect():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    flow = get_google_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    session["gmail_state"] = state
    return redirect(auth_url)

@gmail_bp.route("/gmail/callback")
def callback():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    try:
        flow = get_google_flow()
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials

        # Save tokens to Supabase
        sb = get_supabase()
        token_data = {
            "user_id": session["user_id"],
            "gmail_token": credentials.token,
            "gmail_refresh_token": credentials.refresh_token,
            "gmail_connected": True,
        }

        # Check if record exists
        existing = sb.table("gmail_tokens").select("*").eq("user_id", session["user_id"]).execute()
        if existing.data:
            sb.table("gmail_tokens").update(token_data).eq("user_id", session["user_id"]).execute()
        else:
            sb.table("gmail_tokens").insert(token_data).execute()

        session["gmail_connected"] = True
        return redirect(url_for("gmail.sync") + "?auto=1")

    except Exception as e:
        return redirect(url_for("dashboard.index") + f"?error=gmail_failed")

@gmail_bp.route("/gmail/sync")
def sync():
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from app.services.gmail_parser import fetch_bank_emails
        from app.services.categorizer import categorize_transactions

        sb = get_supabase()

        # Get stored tokens
        token_row = sb.table("gmail_tokens").select("*").eq("user_id", session["user_id"]).execute()
        if not token_row.data:
            return jsonify({"error": "Gmail not connected"}), 400

        token_data = token_row.data[0]

        # Build Gmail service
        creds = Credentials(
            token=token_data["gmail_token"],
            refresh_token=token_data["gmail_refresh_token"],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=os.environ["GMAIL_CLIENT_ID"],
            client_secret=os.environ["GMAIL_CLIENT_SECRET"],
        )

        gmail_service = build("gmail", "v1", credentials=creds)

        # Fetch and parse emails
        transactions = fetch_bank_emails(gmail_service, max_results=100)

        if not transactions:
            return jsonify({"success": True, "count": 0, "message": "No new transactions found"})

        # Get existing gmail_ids to avoid duplicates
        existing = sb.table("transactions").select("raw_text").eq("user_id", session["user_id"]).execute()
        existing_ids = set()
        for row in (existing.data or []):
            raw = row.get("raw_text", "")
            if "gmail_id:" in raw:
                gid = raw.split("gmail_id:")[-1].strip()
                existing_ids.add(gid)

        # Filter duplicates
        new_transactions = []
        for tx in transactions:
            gmail_id = tx.get("gmail_id", "")
            if gmail_id not in existing_ids:
                tx["raw_text"] = f"gmail_id:{gmail_id} | {tx.get('raw_text', '')}"
                new_transactions.append(tx)

        if not new_transactions:
            return jsonify({"success": True, "count": 0, "message": "All transactions already imported"})

        # Categorize
        new_transactions = categorize_transactions(new_transactions)

        # Save to Supabase
        rows = []
        for tx in new_transactions:
            rows.append({
                "user_id": session["user_id"],
                "date": tx.get("date"),
                "amount": tx.get("amount"),
                "type": tx.get("type"),
                "merchant": tx.get("merchant", "Unknown"),
                "merchant_clean": tx.get("merchant_clean", tx.get("merchant", "Unknown")),
                "category": tx.get("category", "Other"),
                "subcategory": tx.get("subcategory", "Uncategorized"),
                "payment_mode": tx.get("payment_mode", "Other"),
                "bank": tx.get("bank", "Unknown"),
                "raw_text": tx.get("raw_text", "")[:500],
            })

        if rows:
            sb.table("transactions").insert(rows).execute()

        return jsonify({
            "success": True,
            "count": len(rows),
            "message": f"Imported {len(rows)} new transactions from Gmail"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@gmail_bp.route("/gmail/status")
def status():
    if not session.get("user_id"):
        return jsonify({"connected": False})
    try:
        sb = get_supabase()
        row = sb.table("gmail_tokens").select("gmail_connected").eq("user_id", session["user_id"]).execute()
        connected = bool(row.data and row.data[0].get("gmail_connected"))
        return jsonify({"connected": connected})
    except Exception:
        return jsonify({"connected": False})

@gmail_bp.route("/gmail/disconnect")
def disconnect():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))
    try:
        sb = get_supabase()
        sb.table("gmail_tokens").delete().eq("user_id", session["user_id"]).execute()
        session.pop("gmail_connected", None)
    except Exception:
        pass
    return redirect(url_for("dashboard.index"))