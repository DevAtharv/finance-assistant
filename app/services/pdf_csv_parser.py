import pdfplumber
import pandas as pd
import re
from datetime import datetime
from typing import List, Optional
import io

def parse_csv(file_content: bytes) -> List[dict]:
    try:
        df = pd.read_csv(io.BytesIO(file_content))
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        transactions = []
        date_cols = ["date", "txn_date", "transaction_date", "value_date"]
        amount_cols = ["amount", "debit", "credit", "withdrawal", "deposit"]
        desc_cols = ["description", "narration", "particulars", "remarks", "details"]
        date_col = next((c for c in date_cols if c in df.columns), None)
        desc_col = next((c for c in desc_cols if c in df.columns), None)
        for _, row in df.iterrows():
            try:
                date_str = str(row[date_col]).strip() if date_col else datetime.today().strftime("%Y-%m-%d")
                parsed_date = try_parse_date(date_str)
                amount, tx_type = extract_amount_type(row, df.columns.tolist())
                if amount is None or amount <= 0:
                    continue
                description = str(row[desc_col]).strip() if desc_col else "Unknown"
                transactions.append({
                    "date": parsed_date,
                    "amount": amount,
                    "type": tx_type,
                    "merchant": description[:100],
                    "bank": "CSV Import",
                    "payment_mode": detect_payment_mode(description),
                    "raw_text": str(row.to_dict())[:500],
                })
            except Exception:
                continue
        return transactions
    except Exception as e:
        raise ValueError(f"Could not parse CSV: {str(e)}")

def parse_pdf(file_content: bytes) -> List[dict]:
    transactions = []
    try:
        with pdfplumber.open(io.BytesIO(file_content)) as pdf:
            for page in pdf.pages:
                tables = page.extract_tables()
                for table in tables:
                    rows = parse_pdf_table(table)
                    transactions.extend(rows)
                if not tables:
                    text = page.extract_text()
                    if text:
                        rows = parse_pdf_text(text)
                        transactions.extend(rows)
        return transactions
    except Exception as e:
        raise ValueError(f"Could not parse PDF: {str(e)}")

def parse_pdf_table(table: list) -> List[dict]:
    if not table or len(table) < 2:
        return []
    transactions = []
    headers = [str(h).lower().strip() if h else "" for h in table[0]]
    for row in table[1:]:
        if not row or all(cell is None or str(cell).strip() == "" for cell in row):
            continue
        try:
            row_dict = {headers[i]: str(row[i]).strip() if row[i] else "" for i in range(min(len(headers), len(row)))}
            date_val = next((v for k, v in row_dict.items() if any(d in k for d in ["date", "txn"])), None)
            desc_val = next((v for k, v in row_dict.items() if any(d in k for d in ["desc", "narr", "part", "remark"])), "Unknown")
            debit_val = next((v for k, v in row_dict.items() if "debit" in k or "withdrawal" in k), None)
            credit_val = next((v for k, v in row_dict.items() if "credit" in k or "deposit" in k), None)
            amount = None
            tx_type = "debit"
            if debit_val and clean_number(debit_val):
                amount = clean_number(debit_val)
                tx_type = "debit"
            elif credit_val and clean_number(credit_val):
                amount = clean_number(credit_val)
                tx_type = "credit"
            else:
                amount_val = next((v for k, v in row_dict.items() if "amount" in k), None)
                if amount_val:
                    amount = clean_number(amount_val)
            if amount and amount > 0:
                transactions.append({
                    "date": try_parse_date(date_val) if date_val else datetime.today().strftime("%Y-%m-%d"),
                    "amount": amount,
                    "type": tx_type,
                    "merchant": desc_val[:100],
                    "bank": "PDF Import",
                    "payment_mode": detect_payment_mode(desc_val),
                    "raw_text": str(row_dict)[:500],
                })
        except Exception:
            continue
    return transactions

def parse_pdf_text(text: str) -> List[dict]:
    transactions = []
    lines = text.split("\n")
    date_pattern = re.compile(r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})\b')
    amount_pattern = re.compile(r'(?:Rs\.?|INR|₹)?\s*([\d,]+\.?\d{0,2})')
    for line in lines:
        date_match = date_pattern.search(line)
        amount_match = amount_pattern.search(line)
        if date_match and amount_match:
            try:
                amount = clean_number(amount_match.group(1))
                if amount and amount > 0:
                    tx_type = "credit" if any(w in line.lower() for w in ["cr", "credit", "received"]) else "debit"
                    transactions.append({
                        "date": try_parse_date(date_match.group(1)),
                        "amount": amount,
                        "type": tx_type,
                        "merchant": line[:100].strip(),
                        "bank": "PDF Import",
                        "payment_mode": detect_payment_mode(line),
                        "raw_text": line[:500],
                    })
            except Exception:
                continue
    return transactions

def clean_number(val: str) -> Optional[float]:
    try:
        cleaned = re.sub(r'[^\d.]', '', str(val).replace(",", ""))
        return float(cleaned) if cleaned else None
    except Exception:
        return None

def try_parse_date(date_str: str) -> str:
    formats = ["%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y",
               "%d %b %Y", "%d %b %y", "%d-%b-%Y", "%d-%b-%y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return datetime.today().strftime("%Y-%m-%d")

def extract_amount_type(row, columns):
    debit_col = next((c for c in columns if "debit" in c or "withdrawal" in c), None)
    credit_col = next((c for c in columns if "credit" in c or "deposit" in c), None)
    if debit_col and pd.notna(row.get(debit_col)) and clean_number(str(row[debit_col])):
        return clean_number(str(row[debit_col])), "debit"
    if credit_col and pd.notna(row.get(credit_col)) and clean_number(str(row[credit_col])):
        return clean_number(str(row[credit_col])), "credit"
    amount_col = next((c for c in columns if "amount" in c), None)
    if amount_col and pd.notna(row.get(amount_col)):
        return clean_number(str(row[amount_col])), "debit"
    return None, "debit"

def detect_payment_mode(text: str) -> str:
    text_lower = text.lower()
    if "upi" in text_lower: return "UPI"
    if "neft" in text_lower: return "NEFT"
    if "imps" in text_lower: return "IMPS"
    if "rtgs" in text_lower: return "RTGS"
    if "atm" in text_lower or "cash" in text_lower: return "Cash/ATM"
    if "emi" in text_lower: return "EMI"
    return "Other"