import re
import base64
import json
import os
import requests
import time
from datetime import datetime
from typing import Optional, Generator

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

def decode_email_body(payload: dict) -> str:
    body = ""
    if "parts" in payload:
        for part in payload["parts"]:
            body += decode_email_body(part)
    elif "body" in payload and "data" in payload["body"]:
        try:
            data = payload["body"]["data"]
            body = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        except Exception:
            pass
    return body

def clean_html(text: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_with_groq(subject: str, sender: str, body: str) -> Optional[dict]:
    try:
        prompt = f"""You are a financial transaction parser for Indian emails.

Analyze this email and extract transaction details if it contains a payment/transaction.

Subject: {subject}
From: {sender}
Body: {body[:1000]}

If this is a transaction email (payment, debit, credit, UPI, wallet payment etc), return ONLY this JSON:
{{
  "amount": <number>,
  "type": "debit" or "credit",
  "merchant": "<who was paid or who paid - use real name not email>",
  "date": "<YYYY-MM-DD>",
  "bank": "<bank or wallet name>",
  "payment_mode": "UPI" or "NEFT" or "IMPS" or "Wallet" or "Other"
}}

Rules:
- amount must be positive number
- type is debit if money left, credit if money came in
- merchant should be the person/shop name, NOT an email address
- date in YYYY-MM-DD format
- If NOT a transaction email, return exactly: null

Return ONLY the JSON or null. No explanation."""

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "llama-3.1-8b-instant",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 200,
                "temperature": 0
            },
            timeout=15
        )

        data = response.json()
        print(f"Groq response: {data}")
        text = data["choices"][0]["message"]["content"].strip()

        if text.lower() == "null" or not text:
            return None

        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        if not result or not result.get("amount"):
            return None

        return result

    except Exception as e:
        print(f"Groq parse error: {e}")
        return None

def stream_bank_emails(gmail_service, max_results: int = 25) -> Generator:
    query = "subject:(debit OR credit OR credited OR debited OR transaction OR payment OR transferred OR withdrawn OR UPI OR NEFT OR IMPS OR alert OR successful)"

    results = gmail_service.users().messages().list(
        userId="me",
        q=query,
        maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    print(f"Found {len(messages)} potential transaction emails")

    skip_subjects = ["otp", "one time password", "login", "password reset",
                     "verify", "verification", "newsletter", "promo", "offer",
                     "streak", "lesson", "play", "security alert", "data export"]

    for msg in messages:
        try:
            full_msg = gmail_service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="full"
            ).execute()

            headers = {
                h["name"].lower(): h["value"]
                for h in full_msg.get("payload", {}).get("headers", [])
            }

            sender = headers.get("from", "")
            subject = headers.get("subject", "")

            if any(skip in subject.lower() for skip in skip_subjects):
                continue

            body = decode_email_body(full_msg.get("payload", {}))
            if not body or len(body.strip()) < 20:
                continue

            body_clean = clean_html(body)

            parsed = parse_with_groq(subject, sender, body_clean)

            if parsed:
                parsed["gmail_id"] = msg["id"]
                parsed["raw_text"] = body_clean[:300]
                parsed["source"] = "gmail"
                print(f"✓ {parsed.get('bank','?')} | {parsed.get('merchant','?')} | ₹{parsed.get('amount')} | {parsed.get('type')}")
                yield parsed

            time.sleep(1)
            del full_msg, body, body_clean

        except Exception as e:
            print(f"Error processing email {msg.get('id')}: {e}")
            continue