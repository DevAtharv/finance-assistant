import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

MERCHANT_RULES = {
    "food": {
        "keywords": ["swiggy", "zomato", "dominos", "pizza", "mcdonalds", "kfc", "subway", "burger", "biryani", "restaurant", "cafe", "food", "eat"],
        "category": "Food", "subcategory": "Food Delivery"
    },
    "grocery": {
        "keywords": ["bigbasket", "blinkit", "grofers", "zepto", "dmart", "reliance fresh", "grocery", "supermarket"],
        "category": "Food", "subcategory": "Groceries"
    },
    "transport": {
        "keywords": ["uber", "ola", "rapido", "metro", "irctc", "makemytrip", "goibibo", "redbus", "petrol", "fuel", "indigo", "spicejet"],
        "category": "Transport", "subcategory": "Cab / Travel"
    },
    "shopping": {
        "keywords": ["amazon", "flipkart", "myntra", "ajio", "nykaa", "meesho", "snapdeal", "shopping"],
        "category": "Shopping", "subcategory": "Online Shopping"
    },
    "bills": {
        "keywords": ["airtel", "jio", "vodafone", "bsnl", "electricity", "bescom", "tata power", "rent", "maintenance", "broadband", "internet"],
        "category": "Bills", "subcategory": "Utilities"
    },
    "entertainment": {
        "keywords": ["netflix", "amazon prime", "hotstar", "spotify", "youtube", "bookmyshow", "pvr", "inox"],
        "category": "Entertainment", "subcategory": "Subscriptions"
    },
    "health": {
        "keywords": ["pharmacy", "medplus", "apollo", "1mg", "netmeds", "hospital", "clinic", "doctor", "medicine"],
        "category": "Health", "subcategory": "Medical"
    },
    "investment": {
        "keywords": ["zerodha", "groww", "upstox", "sip", "mutual fund", "lic", "insurance", "ppf", "nps"],
        "category": "Investment", "subcategory": "Stocks / SIP"
    },
    "income": {
        "keywords": ["salary", "payroll", "freelance", "payment received", "income", "stipend"],
        "category": "Income", "subcategory": "Salary"
    },
}

def rule_based_categorize(merchant: str) -> dict:
    merchant_lower = merchant.lower()
    for _, config in MERCHANT_RULES.items():
        if any(kw in merchant_lower for kw in config["keywords"]):
            return {
                "category": config["category"],
                "subcategory": config["subcategory"],
                "confidence": "rule-based"
            }
    return {"category": "Other", "subcategory": "Uncategorized", "confidence": "rule-based"}

def ai_categorize(merchant: str, amount: float, tx_type: str) -> dict:
    try:
        prompt = f"""Categorize this Indian financial transaction.
Transaction:
- Merchant: {merchant}
- Amount: Rs.{amount}
- Type: {tx_type}

Return ONLY a JSON object:
{{
  "category": "<Food/Transport/Shopping/Bills/Health/Entertainment/Investment/Income/Transfer/Other>",
  "subcategory": "<specific subcategory>",
  "merchant_clean": "<cleaned merchant name>"
}}"""
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0,
        )
        text = response.choices[0].message.content.strip()
        text = text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        result["confidence"] = "ai"
        return result
    except Exception:
        return rule_based_categorize(merchant)

def categorize(transactions: list) -> list:
    categorized = []
    for tx in transactions:
        merchant = tx.get("merchant", "Unknown")
        result = rule_based_categorize(merchant)
        if result["category"] == "Other" and os.environ.get("OPENAI_API_KEY"):
            result = ai_categorize(merchant, tx.get("amount", 0), tx.get("type", "debit"))
        tx["category"] = result.get("category", "Other")
        tx["subcategory"] = result.get("subcategory", "Uncategorized")
        tx["merchant_clean"] = result.get("merchant_clean", merchant)
        categorized.append(tx)
    return categorized