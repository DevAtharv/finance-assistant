import re
from datetime import datetime
from typing import Optional
import base64

# Bank email sender addresses
BANK_SENDERS = {
    "hdfc": ["alerts@hdfcbank.net", "noreply@hdfcbank.com"],
    "sbi": ["sbialerts@sbi.co.in", "noreply@sbi.co.in"],
    "icici": ["alerts@icicibank.com", "noreply@icicibank.com"],
    "axis": ["alerts@axisbank.com", "noreply@axisbank.com"],
    "kotak": ["alerts@kotak.com", "noreply@kotak.com"],
    "paytm": ["noreply@paytm.com"],
    "phonepe": ["noreply@phonepe.com"],
}

# Email body patterns per bank
EMAIL_PATTERNS = [
    # HDFC
    {
        "bank": "HDFC",
        "pattern": r"(?:Rs\.?|INR)\s*([\d,]+\.?\d*)\s*(?:has been)?\s*(debited|credited).*?(?:account|A/c|a/c)\s*[Xx*]+(\d+).*?(?:on|dated)?\s*([\d\-/]+)?.*?(?:at|to|Info:)?\s*([A-Za-z0-9@\s]+?)(?:\.|Avl|Available|$)",
    },
    # SBI
    {
        "bank": "SBI",
        "pattern": r"(?:Rs\.?|INR)\s*([\d,]+\.?\d*).*?(debited|credited).*?[Xx]+(\d+).*?(?:on|dated)?\s*([\d\-/]+)?.*?(?:to|Info:)?\s*([A-Za-z0-9@\s]+?)(?:\.|Avl|$)",
    },
    # ICICI
    {
        "bank": "ICICI",
        "pattern": r"(?:Rs\.?|INR)\s*([\d,]+\.?\d*)\s*(debited|credited).*?[Xx]+(\d+).*?(?:on)?\s*([\d\-A-Za-z]+)?.*?(?:UPI:|NEFT:)?\s*([A-Za-z0-9@\s]+?)(?:\.|Avl|$)",
    },
    # Axis
    {
        "bank": "Axis",
        "pattern": r"(?:Rs\.?|INR)\s*([\d,]+\.?\d*)\s*(?:has been)?\s*(debited|credited).*?(\d{4}).*?(?:on|dated)\s*([\d\-/]+)?.*?(?:towards|to)?\s*([A-Za-z0-9@\s]+?)(?:\.|Avl|$)",
    },
    # Kotak
    {
        "bank": "Kotak",
        "pattern": r"(?:Rs\.?|INR)\.([\d,]+\.?\d*)\s*(debited|credited).*?(\d{4}).*?(?:on)?\s*([\d\-/]+)?.*?([A-Za-z0-9@\s]+?)(?:\.|Bal|$)",
    },
    # Generic UPI
    {
        "bank": "UPI",
        "pattern": r"(?:Rs\.?|INR|₹)\s*([\d,]+\.?\d*).*?(debit|credit|debited|credited|sent|received).*?([A-Za-z0-9@._\s]+?)(?:\.|$)",
    },
]

def decode_email_body(payload: dict) -> str:
    """Recursively decode email body from Gmail API payload."""
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
    """Strip HTML tags from email body."""
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def parse_amount(amount_str: str) -> Optional[float]:
    try:
        return float(amount_str.replace(",", "").strip())
    except Exception:
        return None

def try_parse_date(date_str: str) -> str:
    formats = ["%d-%m-%y", "%d-%m-%Y", "%d/%m/%Y", "%d/%m/%y",
               "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.today().strftime("%Y-%m-%d")

def detect_payment_mode(text: str) -> str:
    text_lower = text.lower()
    if "upi" in text_lower: return "UPI"
    if "neft" in text_lower: return "NEFT"
    if "imps" in text_lower: return "IMPS"
    if "rtgs" in text_lower: return "RTGS"
    if "atm" in text_lower or "cash" in text_lower: return "Cash/ATM"
    if "emi" in text_lower: return "EMI"
    return "Other"

def parse_email_body(body: str, bank_name: str = "Unknown") -> Optional[dict]:
    """Parse a bank email body and extract transaction details."""
    body_clean = clean_html(body)
    text_lower = body_clean.lower()

    # Skip OTP and non-transaction emails
    skip_keywords = ["otp", "one time password", "login attempt", "password reset", "statement"]
    if any(kw in text_lower for kw in skip_keywords):
        return None

    # Must contain financial keywords
    if not any(kw in text_lower for kw in ["debited", "credited", "debit", "credit", "transaction"]):
        return None

    for pattern_config in EMAIL_PATTERNS:
        match = re.search(pattern_config["pattern"], body_clean, re.IGNORECASE | re.DOTALL)
        if match:
            groups = match.groups()
            try:
                amount = parse_amount(groups[0])
                if not amount or amount <= 0:
                    continue

                # Determine transaction type
                tx_type = "debit"
                if any(w in text_lower for w in ["credit", "credited", "received", "added"]):
                    tx_type = "credit"
                if any(w in text_lower for w in ["debit", "debited", "withdrawn", "sent"]):
                    tx_type = "debit"

                # Extract merchant (last group)
                merchant = groups[-1].strip() if groups[-1] else "Unknown"
                merchant = re.sub(r'\s+', ' ', merchant).strip()[:100]

                # Extract date
                date_str = None
                for g in groups[1:]:
                    if g and re.match(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', str(g)):
                        date_str = g
                        break

                return {
                    "bank": bank_name,
                    "amount": amount,
                    "type": tx_type,
                    "merchant": merchant,
                    "date": try_parse_date(date_str) if date_str else datetime.today().strftime("%Y-%m-%d"),
                    "payment_mode": detect_payment_mode(body_clean),
                    "raw_text": body_clean[:500],
                    "source": "gmail",
                }
            except Exception:
                continue

    return None

def fetch_bank_emails(gmail_service, max_results: int = 100) -> list:
    """
    Fetch bank transaction emails from Gmail.
    Returns list of parsed transactions.
    """
    transactions = []

    # Build search query for all bank senders
    all_senders = []
    for senders in BANK_SENDERS.values():
        all_senders.extend(senders)

    sender_query = " OR ".join([f"from:{s}" for s in all_senders])
    query = f"({sender_query}) subject:(debit OR credit OR transaction OR alert)"

    try:
        results = gmail_service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results
        ).execute()

        messages = results.get("messages", [])

        for msg in messages:
            try:
                full_msg = gmail_service.users().messages().get(
                    userId="me",
                    id=msg["id"],
                    format="full"
                ).execute()

                # Get email metadata
                headers = {h["name"].lower(): h["value"]
                          for h in full_msg.get("payload", {}).get("headers", [])}

                sender = headers.get("from", "").lower()
                subject = headers.get("subject", "")
                date_header = headers.get("date", "")

                # Detect bank from sender
                bank_name = "Unknown"
                for bank, senders in BANK_SENDERS.items():
                    if any(s in sender for s in senders):
                        bank_name = bank.upper()
                        break

                # Decode body
                body = decode_email_body(full_msg.get("payload", {}))
                if not body:
                    continue

                # Parse transaction
                parsed = parse_email_body(body, bank_name)
                if parsed:
                    parsed["gmail_id"] = msg["id"]
                    transactions.append(parsed)

            except Exception:
                continue

    except Exception as e:
        raise Exception(f"Failed to fetch Gmail: {str(e)}")

    return transactions