from flask import Flask
from dotenv import load_dotenv
import os

load_dotenv()

def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("SECRET_KEY", "dev-secret")

    from app.routes.auth import auth_bp
    from app.routes.ingest import ingest_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.reports import reports_bp
    from app.routes.gmail import gmail_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(ingest_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(gmail_bp)

    return app