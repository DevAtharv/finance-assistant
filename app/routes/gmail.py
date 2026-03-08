from flask import Blueprint, redirect, url_for, session, request, jsonify
import os

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
    redirect_uri = os.environ.get("GMAIL_REDIRECT_URI", "http://localhost:5000/gmail/callback")
    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": os.environ["GMAIL_CLIENT_ID"],
                "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        },
        scopes=["https://www.googleapis.com/auth/gmail.readonly"]
    )
    flow.redirect_uri = redirect_uri
    return flow

def get_gmail_service(token_data):
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials(
        token=token_data["gmail_token"],
        refresh_token=token_data["gmail_refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.environ["GMAIL_CLIENT_ID"],
        client_secret=os.environ["GMAIL_CLIENT_SECRET"],
    )

    if creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            sb = get_supabase()
            sb.table("gmail_tokens").update({
                "gmail_token": creds.token,
            }).eq("user_id", session["user_id"]).execute()
        except Exception as e:
            raise Exception(f"Token refresh failed: {str(e)}")

    return build("gmail", "v1", credentials=creds)

@gmail_bp.route("/gmail/connect")
def connect():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))

    if "localhost" in os.environ.get("GMAIL_REDIRECT_URI", ""):
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

    if "localhost" in os.environ.get("GMAIL_REDIRECT_URI", ""):
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

    try:
        flow = get_google_flow()

        auth_response = request.url
        if auth_response.startswith("http://") and "localhost" not in auth_response:
            auth_response = auth_response.replace("http://", "https://", 1)

        flow.fetch_token(authorization_response=auth_response)
        credentials = flow.credentials

        sb = get_supabase()
        token_data = {
            "user_id": session["user_id"],
            "gmail_token": credentials.token,
            "gmail_refresh_token": credentials.refresh_token,
            "gmail_connected": True,
        }

        existing = sb.table("gmail_tokens").select("*").eq("user_id", session["user_id"]).execute()
        if existing.data:
            sb.table("gmail_tokens").update(token_data).eq("user_id", session["user_id"]).execute()
        else:
            sb.table("gmail_tokens").insert(token_data).execute()

        session["gmail_connected"] = True
        return redirect("/dashboard?syncing=1")

    except Exception as e:
        print(f"Gmail callback error: {e}")
        return redirect(f"/dashboard?error=gmail_failed")

@gmail_bp.route("/gmail/sync")
def sync():
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401

    try:
        from app.services.gmail_parser import stream_bank_emails
        from app.services.categorizer import categorize_transactions

        sb = get_supabase()

        token_row = sb.table("gmail_tokens").select("*").eq("user_id", session["user_id"]).execute()
        if not token_row.data:
            return jsonify({"error": "Gmail not connected. Please reconnect."}), 400

        token_data = token_row.data[0]

        if not token_data.get("gmail_refresh_token"):
            return jsonify({"error": "Missing refresh token. Please reconnect Gmail."}), 400

        gmail_service = get_gmail_service(token_data)
        transactions = stream_bank_emails(gmail_service, max_results=25)

        if not transactions:
            return jsonify({"success": True, "count": 0, "message": "No bank transaction emails found"})

        # Get existing gmail IDs to avoid duplicates
        existing = sb.table("transactions").select("raw_text").eq("user_id", session["user_id"]).execute()
        existing_ids = set()
        for row in (existing.data or []):
            raw = row.get("raw_text", "")
            if "gmail_id:" in raw:
                gid = raw.split("gmail_id:")[-1].split("|")[0].strip()
                existing_ids.add(gid)

        # Categorize
        transactions = categorize_transactions(transactions)

        # Insert one by one to avoid memory crash
        saved = 0
        skipped = 0
        for tx in transactions:
            try:
                gmail_id = tx.get("gmail_id", "")
                if gmail_id and gmail_id in existing_ids:
                    skipped += 1
                    continue

                raw_text = f"gmail_id:{gmail_id} | {tx.get('raw_text', '')}"

                sb.table("transactions").insert({
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
                    "raw_text": raw_text[:500],
                }).execute()
                saved += 1

            except Exception as e:
                print(f"Error saving transaction: {e}")
                continue

        return jsonify({
            "success": True,
            "count": saved,
            "message": f"Imported {saved} new transactions from Gmail"
        })

    except Exception as e:
        print(f"Gmail sync error: {e}")
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