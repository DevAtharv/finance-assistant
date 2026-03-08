from collections import defaultdict
from datetime import datetime, timedelta
from typing import List

def analyze_transactions(transactions: List[dict], month: str = None) -> dict:
    if not month:
        month = datetime.today().strftime("%Y-%m")

    monthly_txns = [t for t in transactions if str(t.get("date", "")).startswith(month)]
    prev_month = get_prev_month(month)
    prev_txns = [t for t in transactions if str(t.get("date", "")).startswith(prev_month)]

    debits = [t for t in monthly_txns if t.get("type") == "debit"]
    credits = [t for t in monthly_txns if t.get("type") == "credit"]

    total_expense = sum(t["amount"] for t in debits)
    total_income = sum(t["amount"] for t in credits)
    savings = total_income - total_expense
    savings_rate = (savings / total_income * 100) if total_income > 0 else 0

    category_spend = defaultdict(float)
    for t in debits:
        category_spend[t.get("category", "Other")] += t["amount"]

    category_data = [
        {"category": cat, "amount": round(amt, 2),
         "percentage": round(amt / total_expense * 100, 1) if total_expense > 0 else 0}
        for cat, amt in sorted(category_spend.items(), key=lambda x: -x[1])
    ]

    daily_spend = defaultdict(float)
    for t in debits:
        daily_spend[t.get("date", "")] += t["amount"]

    daily_trend = [
        {"date": date, "amount": round(amt, 2)}
        for date, amt in sorted(daily_spend.items())
    ]

    merchant_spend = defaultdict(float)
    for t in debits:
        merchant_spend[t.get("merchant_clean", t.get("merchant", "Unknown"))] += t["amount"]

    top_merchants = [
        {"merchant": m, "amount": round(a, 2)}
        for m, a in sorted(merchant_spend.items(), key=lambda x: -x[1])[:5]
    ]

    alerts = generate_alerts(debits, prev_txns, category_spend, total_expense)
    recent = sorted(monthly_txns, key=lambda x: x.get("date", ""), reverse=True)[:10]

    return {
        "month": month,
        "summary": {
            "total_income": round(total_income, 2),
            "total_expense": round(total_expense, 2),
            "savings": round(savings, 2),
            "savings_rate": round(savings_rate, 1),
            "transaction_count": len(monthly_txns),
        },
        "category_breakdown": category_data,
        "daily_trend": daily_trend,
        "top_merchants": top_merchants,
        "alerts": alerts,
        "recent_transactions": recent,
    }

def generate_alerts(debits, prev_txns, category_spend, total_expense):
    alerts = []
    prev_debits = [t for t in prev_txns if t.get("type") == "debit"]
    prev_category_spend = defaultdict(float)
    for t in prev_debits:
        prev_category_spend[t.get("category", "Other")] += t["amount"]
    for cat, amt in category_spend.items():
        prev_amt = prev_category_spend.get(cat, 0)
        if prev_amt > 0:
            increase = ((amt - prev_amt) / prev_amt) * 100
            if increase > 30:
                alerts.append({
                    "type": "warning",
                    "message": f"{cat} spending is up {round(increase)}% vs last month",
                    "icon": "📈"
                })
    if debits:
        max_tx = max(debits, key=lambda x: x["amount"])
        if max_tx["amount"] > total_expense * 0.3:
            alerts.append({
                "type": "info",
                "message": f"Large transaction: Rs.{max_tx['amount']:,.0f} at {max_tx.get('merchant', 'Unknown')}",
                "icon": "💸"
            })
    return alerts

def get_prev_month(month_str: str) -> str:
    dt = datetime.strptime(month_str + "-01", "%Y-%m-%d")
    prev = dt.replace(day=1) - timedelta(days=1)
    return prev.strftime("%Y-%m")

def get_ai_summary(transactions: list, analysis: dict) -> str:
    try:
        import os
        from openai import OpenAI
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        s = analysis["summary"]
        top_cats = analysis["category_breakdown"][:3]
        top_cat_str = ", ".join([f"{c['category']} (Rs.{c['amount']:,.0f})" for c in top_cats])
        prompt = f"""Write a 3-sentence personal finance summary in a friendly tone:
- Total Income: Rs.{s['total_income']:,.0f}
- Total Expenses: Rs.{s['total_expense']:,.0f}
- Savings: Rs.{s['savings']:,.0f} ({s['savings_rate']}%)
- Top spending: {top_cat_str}
Be specific and encouraging. No bullet points."""
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        s = analysis["summary"]
        return (f"This month you earned Rs.{s['total_income']:,.0f} and spent Rs.{s['total_expense']:,.0f}, "
                f"saving Rs.{s['savings']:,.0f} ({s['savings_rate']}% savings rate). "
                f"Keep tracking your expenses to improve your financial health.")