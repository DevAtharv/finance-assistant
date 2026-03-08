# 💰 Finance Assistant

An automated personal finance tracker that connects to your Gmail, extracts bank transaction alerts, categorizes them using AI, and securely stores them in a database.

## ✨ Features
* **Automated Email Parsing:** Fetches alert emails from major Indian banks (HDFC, SBI, ICICI, Axis, Kotak, Paytm, PhonePe).
* **Smart Data Extraction:** Extracts amount, date, merchant, and payment mode (UPI, NEFT, etc.) using Regex.
* **AI Categorization:** Intelligently categorizes transactions for better financial tracking.
* **Secure Storage:** Saves data securely in a Supabase PostgreSQL database.
* **OAuth 2.0 Integration:** Secure Google Login with read-only Gmail access.

## 🛠️ Tech Stack
* **Backend:** Python, Flask, Gunicorn
* **Database:** Supabase (PostgreSQL)
* **APIs:** Google Cloud (Gmail API), OpenAI
* **Authentication:** Google OAuth 2.0

## 🚀 Local Setup Instructions

1. **Clone the repository:**
   ```bash
   git clone [https://github.com/DevAtharv/finance-assistant.git](https://github.com/DevAtharv/finance-assistant.git)
   cd finance-assistant