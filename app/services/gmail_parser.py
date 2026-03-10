import re, base64, json, os, requests, time
from datetime import datetime
from typing import Optional, Generator

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def decode_email_body(payload: dict, max_chars: int = 2000) -> str:
    text = ""
    mime = payload.get("mimeType", "")
    if mime == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
    elif mime.startswith("multipart/"):
        for part in payload.get("parts", []):
            text += decode_email_body(part, max_chars=max_chars - len(text))
            if len(text) >= max_chars:
                break
    return text[:max_chars]

def clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text

def parse_with_groq(subject: str, sender: str, body: str) -> Optional[dict]:
    if not GROQ_API_KEY:
        return None

    prompt = f"""Extract transaction details from this bank/payment email. 
Return ONLY valid JSON with these fields: amount (number), type ("debit" or "credit"), merchant (string), date (YYYY-MM-DD), bank (string), payment_mode (string).
If this is NOT a transaction email, return: {{"not_transaction": true}}

Subject: {subject}
From: {sender}
Body: {body[:800]}"""

    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": "llama-3.1-8b-instant",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0,
                    "max_tokens": 150,
                },
                timeout=20,
            )
            data = resp.json()

            # Rate limit — extract exact wait time and sleep
            if "error" in data:
                err_msg = data["error"].get("message", "")
                print(f"Groq rate limit: {err_msg[:100]}")
                wait_ms = re.search(r"try again in ([0-9.]+)ms", err_msg)
                wait_s  = re.search(r"try again in ([0-9.]+)s", err_msg)
                if wait_ms:
                    wait = float(wait_ms.group(1)) / 1000 + 0.3
                elif wait_s:
                    wait = float(wait_s.group(1)) + 0.5
                else:
                    wait = 5.0
                print(f"Sleeping {wait:.1f}s...")
                time.sleep(wait)
                continue

            content = data["choices"][0]["message"]["content"].strip()
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)

            parsed = json.loads(content)
            if parsed.get("not_transaction"):
                return None
            return parsed

        except (KeyError, json.JSONDecodeError) as e:
            print(f"Groq parse error: {e}")
            return None
        except Exception as e:
            print(f"Groq request error: {e}")
            if attempt < max_retries - 1:
                time.sleep(3)
            return None

    print("Groq: max retries reached, skipping")
    return None


SKIP_SUBJECTS = [
    "otp", "one time password", "verify", "verification",
    "password reset", "login", "sign in", "unsubscribe",
    "newsletter", "offer", "sale", "discount", "cashback offer",
    "welcome", "thank you for registering"
]

def stream_bank_emails(gmail_service, max_results: int = 50) -> Generator:
    query = (
        "from:(alerts OR noreply OR no-reply OR donotreply OR notification OR support) "
        "(debit OR credit OR UPI OR NEFT OR IMPS OR transaction OR payment OR debited OR credited) "
        "newer_than:3m"
    )

    fetched = 0
    page_token = None

    while fetched < max_results:
        batch = min(10, max_results - fetched)
        kwargs = {"userId": "me", "q": query, "maxResults": batch}
        if page_token:
            kwargs["pageToken"] = page_token

        try:
            result = gmail_service.users().messages().list(**kwargs).execute()
        except Exception as e:
            print(f"Gmail list error: {e}")
            break

        messages = result.get("messages", [])
        if not messages:
            break

        page_token = result.get("nextPageToken")

        for msg in messages:
            if fetched >= max_results:
                break
            fetched += 1

            try:
                full = gmail_service.users().messages().get(
                    userId="me", id=msg["id"], format="full"
                ).execute()

                headers = {h["name"].lower(): h["value"] for h in full.get("payload", {}).get("headers", [])}
                subject = headers.get("subject", "")
                sender  = headers.get("from", "")

                subj_lower = subject.lower()
                if any(kw in subj_lower for kw in SKIP_SUBJECTS):
                    continue

                body = decode_email_body(full.get("payload", {}))
                body = clean_html(body)

                tx = parse_with_groq(subject, sender, body)
                if not tx:
                    continue

                tx["gmail_id"] = msg["id"]
                tx["raw_text"] = f"{subject[:80]} | {sender[:50]}"

                print(f"✓ {tx.get('bank')} | {tx.get('merchant')} | ₹{tx.get('amount')} | {tx.get('type')}")
                yield tx

            except Exception as e:
                print(f"Error processing email {msg['id']}: {e}")
                continue

            time.sleep(0.5)

        if not page_token:
            break