from flask import Blueprint, redirect, url_for, session, request, jsonify
import os
import threading

gmail_bp = Blueprint("gmail", __name__)

# Track sync status per user in memory
_sync_status = {}  # user_id -> {"running": bool, "saved": int, "skipped": int, "error": str|None}

def get_supabase():
    from supabase import create_client
    from app.routes.auth import refresh_session_if_needed
    refresh_session_if_needed()
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    access_token = session.get("access_token")
    if access_token:
        sb.postgrest.auth(access_token)
    return sb

def get_supabase_bg(user_id, access_token):
    """Supabase client for background threads (no flask session)."""
    from supabase import create_client
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
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

def get_gmail_service(token_data, user_id=None, sb=None):
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
            if sb and user_id:
                sb.table("gmail_tokens").update({
                    "gmail_token": creds.token,
                }).eq("user_id", user_id).execute()
        except Exception as e:
            raise Exception(f"Token refresh failed: {str(e)}")

    return build("gmail", "v1", credentials=creds)


def _run_sync(user_id, access_token, token_data):
    """Runs in a background thread — no flask session access here."""
    _sync_status[user_id] = {"running": True, "saved": 0, "skipped": 0, "error": None}
    try:
        from app.services.gmail_parser import stream_bank_emails
        from app.services.categorizer import rule_based_categorize_transactions

        sb = get_supabase_bg(user_id, access_token)
        gmail_service = get_gmail_service(token_data, user_id=user_id, sb=sb)

        # Load existing gmail IDs to deduplicate
        existing = sb.table("transactions").select("raw_text").eq("user_id", user_id).execute()
        existing_ids = set()
        for row in (existing.data or []):
            raw = row.get("raw_text", "")
            if "gmail_id:" in raw:
                gid = raw.split("gmail_id:")[-1].split("|")[0].strip()
                existing_ids.add(gid)

        saved = 0
        skipped = 0

        for tx in stream_bank_emails(gmail_service, max_results=50):
            try:
                gmail_id = tx.get("gmail_id", "")
                if gmail_id in existing_ids:
                    skipped += 1
                    continue

                cat = rule_based_categorize_transactions(tx.get("merchant", "Unknown"))

                sb.table("transactions").insert({
                    "user_id": user_id,
                    "date": tx.get("date"),
                    "amount": tx.get("amount"),
                    "type": tx.get("type"),
                    "merchant": tx.get("merchant", "Unknown"),
                    "merchant_clean": tx.get("merchant", "Unknown"),
                    "category": cat.get("category", "Other"),
                    "subcategory": cat.get("subcategory", "Uncategorized"),
                    "payment_mode": tx.get("payment_mode", "Other"),
                    "bank": tx.get("bank", "Unknown"),
                    "raw_text": f"gmail_id:{gmail_id} | {tx.get('raw_text', '')}",
                }).execute()

                existing_ids.add(gmail_id)
                saved += 1
                # Update live progress
                _sync_status[user_id]["saved"] = saved

            except Exception as e:
                print(f"Error saving transaction: {e}")
                continue

        _sync_status[user_id] = {
            "running": False, "saved": saved,
            "skipped": skipped, "error": None
        }
        print(f"Sync done for {user_id}: {saved} saved, {skipped} skipped")

    except Exception as e:
        print(f"Background sync error: {e}")
        _sync_status[user_id] = {
            "running": False, "saved": 0, "skipped": 0, "error": str(e)
        }


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
        import traceback
        print(f"Gmail callback error: {e}")
        print(traceback.format_exc())
        return redirect(f"/dashboard?error=gmail_failed&msg={str(e)}")


@gmail_bp.route("/gmail/sync")
def sync():
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]

    # Don't start a second sync if one is already running
    if _sync_status.get(user_id, {}).get("running"):
        return jsonify({"status": "already_running", "message": "Sync already in progress"}), 200

    try:
        sb = get_supabase()
        token_row = sb.table("gmail_tokens").select("*").eq("user_id", user_id).execute()
        if not token_row.data:
            return jsonify({"error": "Gmail not connected. Please reconnect."}), 400

        token_data = token_row.data[0]
        if not token_data.get("gmail_refresh_token"):
            return jsonify({"error": "Missing refresh token. Please reconnect Gmail."}), 400

        # Capture session values BEFORE spawning thread (thread can't access flask session)
        access_token = session.get("access_token")

        t = threading.Thread(
            target=_run_sync,
            args=(user_id, access_token, token_data),
            daemon=True
        )
        t.start()

        return jsonify({
            "status": "started",
            "message": "Sync started. Poll /gmail/sync_status for progress."
        })

    except Exception as e:
        print(f"Gmail sync error: {e}")
        return jsonify({"error": str(e)}), 500


@gmail_bp.route("/gmail/sync_status")
def sync_status():
    """Poll this endpoint to get live sync progress."""
    if not session.get("user_id"):
        return jsonify({"error": "Unauthorized"}), 401

    user_id = session["user_id"]
    st = _sync_status.get(user_id, {
        "running": False, "saved": 0, "skipped": 0, "error": None
    })
    return jsonify(st)


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