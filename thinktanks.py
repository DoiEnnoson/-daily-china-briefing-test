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
                logger.info(f
