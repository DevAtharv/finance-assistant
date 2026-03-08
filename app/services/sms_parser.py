import re
from datetime import datetime
from typing import Optional

PATTERNS = [
    {
        "bank": "HDFC",
        "pattern": r"Rs\.?([\d,]+\.?\d*)\s*(debited|credited).*?a/c\s*\*+(\d+).*?on\s*([\d\-]+).*?(?:Info:|UPI[:/])?\s*([A-Za-z0-9@\s]+?)(?:\.|Avl|Available|$)",
    },
    {
        "bank": "SBI",
        "pattern": r"a/c\s*[Xx]+(\d+)\s*(debited|credited)\s*by\s*([\d,]+\.?\d*).*?on\s*([\d/]+).*?(?:transfer to|UPI:)?\s*([A-Za-z0-9@\s]+?)(?:\s*UPI|\s*Ref|$)",
    },
    {
        "bank": "ICICI",
        "pattern": r"Rs\s*([\d,]+\.?\d*)\s*(debited|credited).*?[Xx]+(\d+).*?on\s*([\d\-A-Za-z]+).*?(?:UPI:|NEFT:)?\s*([A-Za-z0-9@\s]+?)(?:\.|Avl|$)",
    },
    {
        "bank": "Axis",
        "pattern": r"INR\s*([\d,]+\.?\d*)\s*(?:has been)?\s*(debited|credited).*?(\d{4}).*?(?:on|dated)\s*([\d\-/]+).*?(?:towards|to|UPI:)?\s*([A-Za-z0-9@\s]+?)(?:\.|Avl|$)",
    },
    {
        "bank": "Kotak",
        "pattern": r"Rs\.([\d,]+\.?\d*)\s*(debited|credited).*?(\d{4}).*?on\s*([\d\-/]+).*?(?:UPI|NEFT|IMPS)?:?\s*([A-Za-z0-9@\s]+?)(?:\.|Bal|$)",
    },
    {
        "bank": "UPI",
        "pattern": r"(?:Rs\.?|INR|₹)\s*([\d,]+\.?\d*).*?(debit|credit|debited|credited|sent|received).*?(?:UPI|upi).*?([A-Za-z0-9@._]+)",
    },
]

def parse_amount(amount_str: str) -> float:
    return float(amount_str.replace(",", "").strip())

def parse_date(date_str: str) -> Optional[str]:
    formats = ["%d-%m-%y", "%d-%m-%Y", "%d/%m/%Y", "%d/%m/%y", "%d-%b-%Y", "%d-%b-%y"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.today().strftime("%Y-%m-%d")

def parse_sms(sms_text: str) -> Optional[dict]:
    sms_text = sms_text.strip()
    text_lower = sms_text.lower()
    skip_keywords = ["otp", "password", "login"]
    if any(kw in text_lower for kw in skip_keywords) and "debit" not in text_lower and "credit" not in text_lower:
        return None
    for bank_config in PATTERNS:
        match = re.search(bank_config["pattern"], sms_text, re.IGNORECASE)
        if match:
            groups = match.groups()
            try:
                tx_type = "debit"
                if any(word in text_lower for word in ["credit", "credited", "received", "added"]):
                    tx_type = "credit"
                amount = parse_amount(groups[0])
                merchant = groups[-1].strip() if groups[-1] else "Unknown"
                merchant = re.sub(r'\s+', ' ', merchant).strip()
                date_str = None
                for g in groups:
                    if g and re.match(r'\d{1,2}[-/]\d{1,2}[-/]\d{2,4}', str(g)):
                        date_str = g
                        break
                    if g and re.match(r'\d{1,2}-[A-Za-z]{3}-\d{2,4}', str(g)):
                        date_str = g
                        break
                return {
                    "bank": bank_config["bank"],
                    "amount": amount,
                    "type": tx_type,
                    "merchant": merchant[:100],
                    "date": parse_date(date_str) if date_str else datetime.today().strftime("%Y-%m-%d"),
                    "payment_mode": "UPI" if "upi" in text_lower else "NEFT" if "neft" in text_lower else "Other",
                    "raw_text": sms_text[:500],
                }
            except (ValueError, IndexError):
                continue
    amount_match = re.search(r'(?:Rs\.?|INR|₹)\s*([\d,]+\.?\d*)', sms_text, re.IGNORECASE)
    if amount_match:
        tx_type = "credit" if any(w in text_lower for w in ["credit", "received"]) else "debit"
        return {
            "bank": "Unknown",
            "amount": parse_amount(amount_match.group(1)),
            "type": tx_type,
            "merchant": "Unknown",
            "date": datetime.today().strftime("%Y-%m-%d"),
            "payment_mode": "Other",
            "raw_text": sms_text[:500],
        }
    return None

def parse_bulk_sms(sms_block: str) -> list:
    results = []
    messages = re.split(r'\n{2,}|---+|\*{3,}', sms_block.strip())
    for msg in messages:
        msg = msg.strip()
        if len(msg) < 20:
            continue
        parsed = parse_sms(msg)
        if parsed:
            results.append(parsed)
    return results