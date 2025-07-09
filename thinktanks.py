import imaplib
import email
import os
import json
import logging
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
import smtplib
from email.mime.text import MIMEText
import re
import urllib.parse
import json as json_parser
from bs4 import BeautifulSoup
import requests
import email.header

# Logging einrichten (umfangreich für Debugging)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger()

# Basisverzeichnis (Repository-Root)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
THINKTANKS_JSON = os.path.join(BASE_DIR, "thinktanks.json")

def decode_header(header):
    """Dekodiert E-Mail-Header (z. B. Betreff) mit korrektem Encoding."""
    try:
        decoded = email.header.decode_header(header)[0][0]
        if isinstance(decoded, bytes):
            charset = email.header.decode_header(header)[0][1] or 'utf-8'
            return decoded.decode(charset, errors='replace')
        return decoded
    except Exception as e:
        logger.warning(f"Fehler beim Dekodieren des Headers: {str(e)}")
        return header

def send_email(subject, body, email_user, email_password, recipient="hadobrockmeyer@gmail.com"):
    """Sendet eine E-Mail (Warnung oder Status)."""
    logger.info(f"Sende E-Mail: {subject} an {recipient}")
    if not email_user or not email_password:
        logger.error("E-Mail-Credentials fehlen, überspringe E-Mail")
        return
    try:
        msg = MIMEText(body)
        msg['Subject'] = subject
        msg['From'] = email_user
        msg['To'] = recipient
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        logger.info(f"E-Mail erfolgreich an {recipient} gesendet")
    except Exception as e:
        logger.error(f"Fehler beim Senden der E-Mail an {recipient}: {str(e)}")

def load_thinktanks():
    """Lädt die Think Tanks aus der JSON-Datei."""
    logger.info(f"Aktuelles Arbeitsverzeichnis: {os.getcwd()}")
    logger.info(f"Lade Think Tanks aus {THINKTANKS_JSON}")
    logger.info(f"Inhalt von {BASE_DIR}:")
    try:
        for item in os.listdir(BASE_DIR):
            logger.info(f" - {item}")
    except Exception as e:
        logger.error(f"Konnte Verzeichnis nicht auflisten: {str(e)}")
    if not os.path.exists(THINKTANKS_JSON):
        logger.error(f"{THINKTANKS_JSON} nicht gefunden")
        send_email(
            "Fehler in thinktanks.py",
            f"{THINKTANKS_JSON} nicht gefunden",
            os.getenv("GMAIL_USER", ""), os.getenv("GMAIL_PASS", "")
        )
        return []
    try:
        with open(THINKTANKS_JSON, "r", encoding="utf-8") as f:
            thinktanks = json.load(f)
        logger.info(f"Geladen: {len(thinktanks)} Think Tanks")
        logger.info(f"Inhalt von thinktanks.json: {json.dumps(thinktanks, indent=2)}")
        return thinktanks
    except json.JSONDecodeError:
        logger.error(f"{THINKTANKS_JSON} ist ungültig")
        send_email(
            "Fehler in thinktanks.py",
            f"{THINKTANKS_JSON} ist ungültig",
            os.getenv("GMAIL_USER", ""), os.getenv("GMAIL_PASS", "")
        )
        return []

def extract_email_address(sender):
    """Extrahiert die E-Mail-Adresse aus einem Sender-String."""
    logger.info(f"Extrahiere E-Mail-Adresse aus: {sender}")
    match = re.search(r'<([^>]+)>', sender)
    if match:
        email_addr = match.group(1)
        logger.info(f"E-Mail-Adresse gefunden: {email_addr}")
        return email_addr
    email_addr = sender.strip()
    logger.info(f"E-Mail-Adresse (Fallback): {email_addr}")
    return email_addr

def normalize_url(url):
    """Entfernt Tracking-Parameter aus der URL."""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def resolve_merics_url(url):
    """Löst MERICS-Tracking-URLs auf die Ziel-URL auf."""
    logger.info(f"Auflösen der URL: {url}")
    if "public-eur.mkt.dynamics.com" in url:
        try:
            parsed = urllib.parse.urlparse(url)
            query_params = urllib.parse.parse_qs(parsed.query)
            target = query_params.get("target", [None])[0]
            if target:
                target_data = json_parser.loads(target)
                target_url = urllib.parse.unquote(target_data["TargetUrl"])
                logger.info(f"Ziel-URL gefunden: {target_url}")
                return target_url
        except Exception as e:
            logger.warning(f"Konnte MERICS-URL nicht auflösen: {url}, Fehler: {str(e)}")
    try:
        response = requests.get(url, allow_redirects=True, timeout=5)
        return response.url
    except Exception as e:
        logger.warning(f"Konnte URL nicht auflösen: {url}, Fehler: {str(e)}")
        return url

def score_thinktank_article(title, url):
    """Bewertet einen Artikel auf China-Relevanz."""
    logger.info(f"Bewerte Think Tank Artikel: {title} (URL: {url})")
    title_lower = title.lower()
    score = 5  # MERICS ist immer China-relevant
    important_keywords = [
        "economy", "policy", "trade", "geopolitics", "technology", "ai", "semiconductors",
        "military", "diplomacy", "sanctions", "energy", "climate", "infrastructure"
    ]
    positive_modifiers = [
        "analysis", "report", "brief", "commentary", "working paper", "policy brief",
        "in depth", "research", "study"
    ]
    negative_keywords = [
        "subscribe", "donate", "event", "webinar", "conference", "membership",
        "newsletter", "signup", "registration", "legal notice", "privacy policy",
        "website", "unsubscribe", "profile", "read in browser"
    ]
    if any(kw in title_lower for kw in important_keywords):
        score += 3
    if any(kw in title_lower for kw in positive_modifiers):
        score += 2
    if any(kw in title_lower for kw in negative_keywords):
        score -= 5
    if "merics.org" in url and "/report/" in url:
        score += 3
    if "merics.org" in url and "/sites/default/files/" in url:
        score += 2  # PDFs sind relevant, aber etwas niedriger gewichtet
    logger.info(f"Score für '{title}' (URL: {url}): {score}")
    return max(score, 0)

def fetch_merics_emails(email_user, email_password, days=30, max_articles=10):
    """Holt alle E-Mails von MERICS-Absendern und extrahiert Artikel."""
    logger.info("Starte fetch_merics_emails")
    try:
        thinktanks = load_thinktanks()
        merics = next((tt for tt in thinktanks if tt["abbreviation"] == "MERICS"), None)
        if not merics:
            logger.error("MERICS nicht in thinktanks.json gefunden")
            send_email(
                "Fehler in fetch_merics_emails",
                "MERICS nicht in thinktanks.json gefunden",
                email_user, email_password
            )
            return [], 0

        email_senders = merics["email_senders"]
        logger.info(f"Verarbeite MERICS mit Absendern: {email_senders}")
        email_senders = [extract_email_address(sender) for sender in email_senders]
        logger.info(f"Bereinigte Absender: {email_senders}")

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            logger.info(f"Versuche IMAP-Login mit Benutzer: {email_user}")
            mail.login(email_user, email_password)
            logger.info("IMAP-Login erfolgreich")
        except Exception as e:
            logger.error(f"IMAP-Login fehlgeschlagen: {str(e)}")
            send_email(
                "Fehler in fetch_merics_emails",
                f"IMAP-Login fehlgeschlagen: {str(e)}",
                email_user, email_password
            )
            return [], 0

        mail.select("inbox")
        articles = []
        seen_urls = set()
        email_count = 0
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        logger.info(f"Suche nach E-Mails seit: {since_date}")

        for sender in email_senders:
            logger.info(f"Suche nach E-Mails von: {sender}")
            result, data = mail.search(None, f'FROM "{sender}" SINCE {since_date}')
            if result != "OK":
                logger.warning
