from flask import Blueprint, render_template, request, redirect, url_for, session, flash
import os

auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/")
def landing():
    if session.get("user_id"):
        return redirect(url_for("dashboard.index"))
    return render_template("landing.html")

@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        try:
            from supabase import create_client
            sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
            res = sb.auth.sign_in_with_password({"email": email, "password": password})
            session["user_id"] = res.user.id
            session["email"] = res.user.email
            session["access_token"] = res.session.access_token
            return redirect(url_for("dashboard.index"))
        except Exception as e:
            flash(str(e), "error")
    return render_template("auth.html", mode="login")

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        try:
            from supabase import create_client
            sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
            res = sb.auth.sign_up({"email": email, "password": password})
            flash("Account created! Please check your email to verify.", "success")
            return redirect(url_for("auth.login"))
        except Exception as e:
            flash(str(e), "error")
    return render_template("auth.html", mode="register")

@auth_bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.landing"))