import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import os
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import time

def send_warning_email(subject, body):
    """Sendet eine Warn-E-Mail an hadobrockmeyer@gmail.com."""
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - send_warning_email: SUBSTACK_MAIL nicht gesetzt")
            return
        try:
            user_part, pass_part = substack_mail.split(";")
            email_user = user_part.split("=")[1]
            email_password = pass_part.split("=")[1]
        except (ValueError, IndexError) as e:
            print(f"❌ ERROR - send_warning_email: SUBSTACK_MAIL Format ungültig (erwartet: GMAIL_USER=email;GMAIL_PASS=pass, bekommen: {substack_mail})")
            return
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = "hadobrockmeyer@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        print(f"DEBUG - send_warning_email: Warn-E-Mail gesendet: {subject}")
    except Exception as e:
        print(f"❌ ERROR - send_warning_email: Fehler beim Senden der Warn-E-Mail: {str(e)}")

def send_article_email(posts):
    """Sendet eine E-Mail mit den gefundenen Nikkei-Artikeln an hadobrockmeyer@gmail.com."""
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        if not substack_mail:
            print("❌ ERROR - send_article_email: SUBSTACK_MAIL nicht gesetzt")
            return
        try:
            user_part, pass_part = substack_mail.split(";")
            email_user = user_part.split("=")[1]
            email_password = pass_part.split("=")[1]
        except (ValueError, IndexError) as e:
            print(f"❌ ERROR - send_article_email: SUBSTACK_MAIL Format ungültig (erwartet: GMAIL_USER=email;GMAIL_PASS=pass, bekommen: {substack_mail})")
            return
        subject = f"Nikkei Asia Briefing - {datetime.now().strftime('%Y-%m-%d')}"
        if posts:
            # Füge nach jedem Artikel eine zusätzliche Leerzeile hinzu
            formatted_posts = [f"{post}\n" for post in posts]
            body = "## 📜 Nikkei Asia – Top-Themen:\n\n" + "\n".join(formatted_posts)
        else:
            body = "Keine Nikkei-Artikel gefunden."
        msg = MIMEText(body, "html")  # HTML-Format für klickbare Links
        msg["Subject"] = subject
        msg["From"] = email_user
        msg["To"] = "hadobrockmeyer@gmail.com"
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        print(f"DEBUG - send_article_email: E-Mail mit Artikeln gesendet: {subject}")
    except Exception as e:
        print(f"❌ ERROR - send_article_email: Fehler beim Senden der Artikel-E-Mail: {str(e)}")

def score_nikkei_article(title):
    """Bewertet einen Artikel auf China-Relevanz."""
    title_lower = title.lower()
    must_have_keywords = [
        "china", "chinese", "xi", "beijing", "shanghai", "hong kong", "taiwan", "prc",
        "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang", "brics",
        "belt and road", "mac...
