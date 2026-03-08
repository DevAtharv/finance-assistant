import re
import base64
import json
from datetime import datetime
from typing import Optional
from openai import OpenAI
import os

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

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
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_with_openai(email_text: str, subject: str, sender: str) -> Optional[dict]:
    """Use OpenAI to extract transaction data from any bank email."""
    try:
        prompt = f"""You are a financial data extractor for Indian bank emails.

Analyze this email and extract transaction details if it contains a bank transaction alert.

Email Subject: {subject}
Email From: {sender}
Email Body: {email_text[:1500]}

If this email contains a bank transaction (debit, credit, UPI, NEFT, IMPS, ATM withdrawal, etc.), extract the details.
If it is NOT a transaction email (OTP, login alert, offers, newsletter, statement), return null.

Return ONLY a JSON object with these exact fields, or null if not a transaction:
{{
  "amount": <number>,
  "type": "debit" or "credit",
  "merchant": "<merchant or recipient name>",
  "date": "<YYYY-MM-DD format>",
  "bank": "<bank name>",
  "payment_mode": "UPI" or "NEFT" or "IMPS" or "RTGS" or "Cash/ATM" or "EMI" or "Other"
}}

Rules:
- amount must be a positive number
- type is "debit" if money left account, "credit" if money came in
- date must be in YYYY-MM-DD format, use today if not found
- merchant is who you paid or who paid you
- Return ONLY the JSON, no explanation, no markdown"""

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0,
        )

        text = response.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()

        if text.lower() == "null" or text == "":
            return None

        result = json.loads(text)
        if not result or not result.get("amount"):
            return None

        return result

    except Exception as e:
        print(f"OpenAI extraction error: {e}")
        return None

def fetch_bank_emails(gmail_service, max_results: int = 200) -> list:
    """
    Fetch ALL emails and use OpenAI to identify and parse transactions.
    No hardcoded sender addresses needed.
    """
    transactions = []

    # Search broadly for any financial emails
    query = "subject:(debit OR credit OR credited OR debited OR transaction OR payment OR transferred OR withdrawn OR UPI OR NEFT OR IMPS OR alert OR statement)"

    try:
        results = gmail_service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        print(f"Found {len(messages)} potential transaction emails")

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

                # Skip obvious non-transaction emails
                skip_subjects = ["otp", "one time password", "login", "password reset",
                                  "verify", "verification", "newsletter", "offer", "cashback promo"]
                if any(skip in subject.lower() for skip in skip_subjects):
                    continue

                # Decode body
                body = decode_email_body(full_msg.get("payload", {}))
                if not body or len(body.strip()) < 30:
                    continue

                body_clean = clean_html(body)

                # Use OpenAI to extract transaction
                parsed = extract_with_openai(body_clean, subject, sender)

                if parsed:
                    parsed["gmail_id"] = msg["id"]
                    parsed["raw_text"] = body_clean[:500]
                    parsed["source"] = "gmail"
                    transactions.append(parsed)
                    print(f"✓ Extracted: {parsed['merchant']} ₹{parsed['amount']} ({parsed['type']})")

            except Exception as e:
                print(f"Error processing email {msg.get('id')}: {e}")
                continue

    except Exception as e:
        raise Exception(f"Failed to fetch Gmail: {str(e)}")

    print(f"Total transactions extracted: {len(transactions)}")
    return transactions
