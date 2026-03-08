import re
import base64
from datetime import datetime
from typing import Optional

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

def detect_bank(sender: str, body: str) -> str:
    text = (sender + " " + body).lower()
    if "hdfc" in text: return "HDFC"
    if "sbi" in text: return "SBI"
    if "icici" in text: return "ICICI"
    if "axis" in text: return "Axis"
    if "kotak" in text: return "Kotak"
    if "paytm" in text: return "Paytm"
    if "phonepe" in text: return "PhonePe"
    if "gpay" in text or "google pay" in text: return "GPay"
    if "bob" in text or "bank of baroda" in text: return "BOB"
    if "pnb" in text or "punjab national" in text: return "PNB"
    if "yes bank" in text: return "Yes Bank"
    if "idfc" in text: return "IDFC"
    if "indusind" in text: return "IndusInd"
    return "Unknown"

def detect_payment_mode(text: str) -> str:
    t = text.lower()
    if "upi" in t: return "UPI"
    if "neft" in t: return "NEFT"
    if "imps" in t: return "IMPS"
    if "rtgs" in t: return "RTGS"
    if "atm" in t or "cash withdrawal" in t: return "Cash/ATM"
    if "emi" in t: return "EMI"
    if "credit card" in t or "cc " in t: return "Credit Card"
    return "Other"

def parse_amount(text: str) -> Optional[float]:
    """Extract amount from Indian bank email — handles Rs., INR, ₹"""
    patterns = [
        r'(?:Rs\.?|INR|₹)\s*([0-9,]+(?:\.[0-9]{1,2})?)',
        r'([0-9,]+(?:\.[0-9]{1,2})?)\s*(?:Rs\.?|INR|₹)',
        r'amount\s*(?:of\s*)?(?:Rs\.?|INR|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)',
        r'debited\s+(?:with\s+)?(?:Rs\.?|INR|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)',
        r'credited\s+(?:with\s+)?(?:Rs\.?|INR|₹)?\s*([0-9,]+(?:\.[0-9]{1,2})?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            amount_str = match.group(1).replace(",", "")
            try:
                amount = float(amount_str)
                if 1 <= amount <= 10000000:  # ₹1 to ₹1cr sanity check
                    return amount
            except:
                pass
    return None

def parse_type(text: str) -> str:
    t = text.lower()
    debit_words = ["debited", "debit", "withdrawn", "paid", "sent", "payment of", "spent"]
    credit_words = ["credited", "credit", "received", "refund", "cashback", "deposited"]
    
    debit_score = sum(1 for w in debit_words if w in t)
    credit_score = sum(1 for w in credit_words if w in t)
    
    return "debit" if debit_score >= credit_score else "credit"

def parse_merchant(text: str) -> str:
    patterns = [
        r'(?:to|at|merchant|VPA|paid to|towards)\s+([A-Za-z0-9\s@._-]{3,40}?)(?:\s+on|\s+for|\s+via|\.|,|$)',
        r'(?:from)\s+([A-Za-z0-9\s@._-]{3,40}?)(?:\s+on|\s+to|\.|,|$)',
        r'UPI[:\s]+([A-Za-z0-9@._-]{5,40})',
        r'(?:Info|Ref|Narration)[:\s]+([A-Za-z0-9\s/_-]{3,40}?)(?:\s+Ref|\.|,|$)',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            merchant = match.group(1).strip()
            if len(merchant) > 2:
                return merchant[:40]
    return "Unknown"

def parse_date(text: str) -> str:
    patterns = [
        r'(\d{2}[-/]\d{2}[-/]\d{4})',   # DD-MM-YYYY or DD/MM/YYYY
        r'(\d{4}[-/]\d{2}[-/]\d{2})',   # YYYY-MM-DD
        r'(\d{2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})',
        r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            date_str = match.group(1)
            for fmt in ["%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"]:
                try:
                    return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
                except:
                    continue
    return datetime.today().strftime("%Y-%m-%d")

def parse_email_body(body: str, subject: str, sender: str) -> Optional[dict]:
    body_clean = clean_html(body)
    full_text = subject + " " + body_clean

    amount = parse_amount(full_text)
    if not amount:
        return None  # Not a transaction email

    return {
        "amount": amount,
        "type": parse_type(full_text),
        "merchant": parse_merchant(body_clean),
        "date": parse_date(full_text),
        "bank": detect_bank(sender, body_clean),
        "payment_mode": detect_payment_mode(full_text),
    }

def fetch_bank_emails(gmail_service, max_results: int = 200) -> list:
    transactions = []

    query = "subject:(debit OR credit OR credited OR debited OR transaction OR payment OR transferred OR withdrawn OR UPI OR NEFT OR IMPS OR alert)"

    try:
        results = gmail_service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        print(f"Found {len(messages)} potential transaction emails")

        skip_subjects = ["otp", "one time password", "login", "password reset",
                         "verify", "verification", "newsletter", "promo", "offer"]

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

                parsed = parse_email_body(body, subject, sender)

                if parsed:
                    parsed["gmail_id"] = msg["id"]
                    parsed["raw_text"] = clean_html(body)[:500]
                    parsed["source"] = "gmail"
                    transactions.append(parsed)
                    print(f"✓ {parsed['bank']} | {parsed['merchant']} | ₹{parsed['amount']} | {parsed['type']}")

            except Exception as e:
                print(f"Error processing email {msg.get('id')}: {e}")
                continue

    except Exception as e:
        raise Exception(f"Failed to fetch Gmail: {str(e)}")

    print(f"Total transactions extracted: {len(transactions)}")
    return transactions
