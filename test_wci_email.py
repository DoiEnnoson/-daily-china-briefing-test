import os
import re
import logging
import imaplib
import email
import smtplib
import json
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header
from bs4 import BeautifulSoup
import glob

# CEST ist UTC+2
cest = timezone(timedelta(hours=2))

# Logging einrichten mit eindeutigem Dateinamen
log_filename = f'wci_test_log_{datetime.now(cest).strftime("%Y%m%d_%H%M%S")}.txt'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# Pfade
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FREIGHT_CACHE_DIR = os.path.join(BASE_DIR, "freight_indicies")
WCI_CACHE_FILE = os.path.join(FREIGHT_CACHE_DIR, "wci_cache.json")
IACI_CACHE_FILE = os.path.join(FREIGHT_CACHE_DIR, "iaci_cache.json")

def load_wci_cache():
    """Lädt den WCI-Cache oder initialisiert ihn als leer, wenn nicht vorhanden."""
    logger.debug(f"Loading WCI cache from {WCI_CACHE_FILE}")
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        if os.path.exists(WCI_CACHE_FILE):
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.debug(f"Successfully loaded WCI cache: {cache}")
                return cache
        logger.debug(f"No WCI cache file found at {WCI_CACHE_FILE}, initializing empty cache")
        cache = {}
        save_wci_cache(cache)
        return cache
    except Exception as e:
        logger.error(f"Failed to load or create WCI cache: {str(e)}")
        cache = {}
        save_wci_cache(cache)
        return cache

def save_wci_cache(cache):
    """Speichert den WCI-Cache und prüft, ob die Datei erstellt wurde."""
    logger.debug(f"Saving WCI cache to {WCI_CACHE_FILE}: {cache}")
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        with open(WCI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        if os.path.exists(WCI_CACHE_FILE):
            logger.info(f"Successfully wrote WCI cache to {WCI_CACHE_FILE}")
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                logger.debug(f"WCI cache file content after save: {f.read()}")
        else:
            logger.error(f"WCI cache file {WCI_CACHE_FILE} was not created")
            raise Exception(f"WCI cache file {WCI_CACHE_FILE} was not created")
    except Exception as e:
        logger.error(f"Failed to save WCI cache: {str(e)}")
        raise

def load_iaci_cache():
    """Lädt den IACI-Cache oder initialisiert ihn als leer, wenn nicht vorhanden."""
    logger.debug(f"Loading IACI cache from {IACI_CACHE_FILE}")
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        if os.path.exists(IACI_CACHE_FILE):
            with open(IACI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.debug(f"Successfully loaded IACI cache: {cache}")
                return cache
        logger.debug(f"No IACI cache file found at {IACI_CACHE_FILE}, initializing empty cache")
        cache = {}
        save_iaci_cache(cache)
        return cache
    except Exception as e:
        logger.error(f"Failed to load or create IACI cache: {str(e)}")
        cache = {}
        save_iaci_cache(cache)
        return cache

def save_iaci_cache(cache):
    """Speichert den IACI-Cache und prüft, ob die Datei erstellt wurde."""
    logger.debug(f"Saving IACI cache to {IACI_CACHE_FILE}: {cache}")
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        with open(IACI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        if os.path.exists(IACI_CACHE_FILE):
            logger.info(f"Successfully wrote IACI cache to {IACI_CACHE_FILE}")
            with open(IACI_CACHE_FILE, "r", encoding="utf-8") as f:
                logger.debug(f"IACI cache file content after save: {f.read()}")
        else:
            logger.error(f"IACI cache file {IACI_CACHE_FILE} was not created")
            raise Exception(f"IACI cache file {IACI_CACHE_FILE} was not created")
    except Exception as e:
        logger.error(f"Failed to save IACI cache: {str(e)}")
        raise

def fetch_wci_email():
    """Holt die neueste Drewry WCI-E-Mail aus den letzten 7 Tagen und speichert den HTML-Inhalt."""
    logger.debug("Starting WCI email fetch")
    try:
        env_vars = os.getenv('DREWRY')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            raise Exception("DREWRY not set")

        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=', 1)
            if key.strip() == 'GMAIL_USER':
                gmail_user = value.strip()
            elif key.strip() == 'GMAIL_PASS':
                gmail_pass = value.strip()

        logger.debug(f"Gmail user: {gmail_user}, pass: {'*' * len(gmail_pass) if gmail_pass else 'None'}")
        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            raise Exception("GMAIL credentials missing")

        mail = imaplib.IMAP4_SSL('imap.gmail.com', timeout=30)
        mail.login(gmail_user, gmail_pass)
        mail.select('inbox')

        # Suche für die letzten 7 Tage in CEST
        today = datetime.now(cest)
        date_range = [(today - timedelta(days=i)).strftime("%d-%b-%Y") for i in range(7)]
        email_ids = []
        for date in date_range:
            search_criteria = f'(FROM "noreply@drewry.co.uk" "World Container Index")'
            logger.debug(f"Searching WCI emails with criteria: {search_criteria}")
            result, data = mail.search(None, search_criteria)
            if result == 'OK' and data[0]:
                email_ids.extend(data[0].split())

        if not email_ids:
            logger.error("No WCI emails found from noreply@drewry.co.uk in the last 7 days")
            raise Exception("No WCI emails found")

        latest_email_id = email_ids[-1]
        logger.debug(f"Fetching WCI email ID: {latest_email_id}")
        result, data = mail.fetch(latest_email_id, '(RFC822)')

        if result != 'OK':
            logger.error(f"Failed to fetch WCI email ID {latest_email_id}")
            raise Exception("Failed to fetch WCI email")

        raw_email = data[0][1]
        email_message = email.message_from_bytes(raw_email)

        subject, encoding = decode_header(email_message['subject'])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding if encoding else 'utf-8')
        logger.debug(f"WCI email subject: {subject}")

        if "World Container Index" not in subject:
            logger.error(f"WCI email ID {latest_email_id} does not match expected subject")
            raise Exception("No matching WCI email found")

        html_content = None
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == 'text/html':
                    html_content = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
        else:
            if email_message.get_content_type() == 'text/html':
                html_content = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

        if not html_content:
            logger.error(f"No HTML content found in WCI email ID {latest_email_id}")
            raise Exception("No HTML content found")

        email_id_str = latest_email_id.decode('utf-8')
        html_filename = f'wci_email_{email_id_str}.html'
        logger.debug(f"Saving WCI HTML content to {html_filename}")
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Successfully saved WCI email content to {html_filename}")
        mail.logout()
        return html_filename, subject

    except Exception as e:
        logger.error(f"Error fetching WCI email: {str(e)}")
        if 'mail' in locals():
            mail.logout()
        return None, None

def fetch_iaci_email():
    """Holt die neueste Drewry IACI-E-Mail aus den letzten 15 Tagen und speichert den HTML-Inhalt."""
    logger.debug("Starting IACI email fetch")
    try:
        env_vars = os.getenv('DREWRY')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            raise Exception("DREWRY not set")

        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=', 1)
            if key.strip() == 'GMAIL_USER':
                gmail_user = value.strip()
            elif key.strip() == 'GMAIL_PASS':
                gmail_pass = value.strip()

        logger.debug(f"Gmail user: {gmail_user}, pass: {'*' * len(gmail_pass) if gmail_pass else 'None'}")
        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            raise Exception("GMAIL credentials missing")

        mail = imaplib.IMAP4_SSL('imap.gmail.com', timeout=30)
        mail.login(gmail_user, gmail_pass)
        mail.select('inbox')

        # Suche für die letzten 15 Tage in CEST
        today = datetime.now(cest)
        date_range = [(today - timedelta(days=i)).strftime("%d-%b-%Y") for i in range(15)]
        email_ids = []
        for date in date_range:
            search_criteria = f'(FROM "noreply@drewry.co.uk" "Intra-Asia Container Index")'
            logger.debug(f"Searching IACI emails with criteria: {search_criteria}")
            result, data = mail.search(None, search_criteria)
            if result == 'OK' and data[0]:
                email_ids.extend(data[0].split())

        if not email_ids:
            logger.error("No IACI emails found from noreply@drewry.co.uk in the last 15 days")
            raise Exception("No IACI emails found")

        latest_email_id = email_ids[-1]
        logger.debug(f"Fetching IACI email ID: {latest_email_id}")
        result, data = mail.fetch(latest_email_id, '(RFC822)')

        if result != 'OK':
            logger.error(f"Failed to fetch IACI email ID {latest_email_id}")
            raise Exception("Failed to fetch IACI email")

        raw_email = data[0][1]
        email_message = email.message_from_bytes(raw_email)

        subject, encoding = decode_header(email_message['subject'])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding if encoding else 'utf-8')
        logger.debug(f"IACI email subject: {subject}")

        if "Intra-Asia Container Index" not in subject:
            logger.error(f"IACI email ID {latest_email_id} does not match expected subject")
            raise Exception("No matching IACI email found")

        html_content = None
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == 'text/html':
                    html_content = part.get_payload(decode=True).decode('utf-8', errors='ignore')
                    break
        else:
            if email_message.get_content_type() == 'text/html':
                html_content = email_message.get_payload(decode=True).decode('utf-8', errors='ignore')

        if not html_content:
            logger.error(f"No HTML content found in IACI email ID {latest_email_id}")
            raise Exception("No HTML content found")

        email_id_str = latest_email_id.decode('utf-8')
        html_filename = f'iaci_email_{email_id_str}.html'
        logger.debug(f"Saving IACI HTML content to {html_filename}")
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Successfully saved IACI email content to {html_filename}")
        mail.logout()
        return html_filename, subject

    except Exception as e:
        logger.error(f"Error fetching IACI email: {str(e)}")
        if 'mail' in locals():
            mail.logout()
        return None, None

def extract_wci_from_html(html_file, subject):
    """Extrahiert den WCI-Wert und das Datum aus der HTML-Datei."""
    logger.debug(f"Attempting to read WCI HTML file: {html_file}")
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        wci_text = soup.get_text(strip=True)
        logger.debug(f"Extracted WCI text (first 500 chars): {wci_text[:500]}")

        wci_match = re.search(r'\$(\d{1,3}(,\d{3})*)\s*per 40ft container', wci_text)
        if not wci_match:
            logger.error("Could not extract WCI value from text")
            return None, None

        wci_value = float(wci_match.group(1).replace(',', ''))

        date_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', subject or wci_text)
        wci_date = None
        if date_match:
            for fmt in ["%d %B %Y", "%d %b %Y"]:
                try:
                    wci_date = datetime.strptime(date_match.group(1), fmt).strftime("%d.%m.%Y")
                    break
                except ValueError:
                    continue
        if wci_date is None:
            wci_date = datetime.now(cest).strftime("%d.%m.%Y")
            logger.debug(f"Could not parse WCI date, using today: {wci_date}")

        logger.info(f"Extracted WCI: {wci_value:.2f}, Date: {wci_date}")
        return wci_value, wci_date

    except Exception as e:
        logger.error(f"Error processing WCI HTML file {html_file}: {str(e)}")
        return None, None

def extract_iaci_from_html(html_file, subject):
    """Extrahiert den IACI-Wert und das Datum aus der HTML-Datei."""
    logger.debug(f"Attempting to read IACI HTML file: {html_file}")
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        iaci_text = soup.get_text(strip=True)
        logger.debug(f"Extracted IACI text (first 500 chars): {iaci_text[:500]}")

        iaci_match = re.search(r'\$(\d{1,3}(,\d{3})*)\s*per 40ft container', iaci_text)
        if not iaci_match:
            logger.error("Could not extract IACI value from text")
            return None, None

        iaci_value = float(iaci_match.group(1).replace(',', ''))

        date_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', subject or iaci_text)
        iaci_date = None
        if date_match:
            for fmt in ["%d %B %Y", "%d %b %Y"]:
                try:
                    iaci_date = datetime.strptime(date_match.group(1), fmt).strftime("%d.%m.%Y")
                    break
                except ValueError:
                    continue
        if iaci_date is None:
            iaci_date = datetime.now(cest).strftime("%d.%m.%Y")
            logger.debug(f"Could not parse IACI date, using today: {iaci_date}")

        logger.info(f"Extracted IACI: {iaci_value:.2f}, Date: {iaci_date}")
        return iaci_value, iaci_date

    except Exception as e:
        logger.error(f"Error processing IACI HTML file {html_file}: {str(e)}")
        return None, None

def calculate_percentage_change(current_value, previous_value):
    """Berechnet die prozentuale Veränderung zwischen zwei Werten."""
    if previous_value is None or previous_value == 0:
        return None
    change = ((current_value - previous_value) / previous_value) * 100
    return round(change, 2)

def send_warning_email(warning_message):
    """Sendet eine Warn-E-Mail bei Problemen."""
    logger.debug("Preparing to send warning email")
    try:
        env_vars = os.getenv("CONFIG")
        if not env_vars:
            logger.error("CONFIG environment variable not found")
            raise Exception("Missing CONFIG")

        pairs = env_vars.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(
            f"Problem: WCI/IACI data issue\nDetails: {warning_message}\nDate: {datetime.now(cest).strftime('%Y-%m-%d')}",
            "plain",
            "utf-8"
        )
        msg["Subject"] = "China-Briefing WCI/IACI Warning"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = "hadobrockmeyer@gmail.com"

        logger.debug("Connecting to SMTP server")
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        logger.info("Warning email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send warning email: {str(e)}")
        raise

def send_results_email(wci_value, wci_date, iaci_value, iaci_date, wci_percentage_change=None, iaci_percentage_change=None):
    """Sendet die WCI- und IACI-Ergebnisse per E-Mail."""
    logger.debug("Starting email sending")
    try:
        env_vars = os.getenv('DREWRY')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            return False

        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=', 1)
            if key.strip() == 'GMAIL_USER':
                gmail_user = value.strip()
            elif key.strip() == 'GMAIL_PASS':
                gmail_pass = value.strip()

        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            return False

        msg = MIMEMultipart()
        msg['From'] = f"Daily China Briefing <{gmail_user}>"
        msg['To'] = gmail_user
        msg['Subject'] = f"Daily China Briefing WCI/IACI Results - {datetime.now(cest).strftime('%Y-%m-%d %H:%M:%S')}"

        wci_arrow = "↓" if wci_percentage_change and wci_percentage_change < 0 else "↑" if wci_percentage_change else ""
        wci_change_text = f" ({wci_arrow} {wci_percentage_change:.2f}%)" if wci_percentage_change is not None else ""
        wci_text = f"• WCI: {wci_value:.2f}{wci_change_text} (Stand {wci_date})"

        iaci_arrow = "↓" if iaci_percentage_change and iaci_percentage_change < 0 else "↑" if iaci_percentage_change else ""
        iaci_change_text = f" ({iaci_arrow} {iaci_percentage_change:.2f}%)" if iaci_percentage_change is not None else ""
        iaci_text = f"• IACI: {iaci_value:.2f}{iaci_change_text} (Stand {iaci_date})"

        body = f"""Attached are the logs and briefing from the Daily China Briefing WCI/IACI workflow.
Date: {datetime.now(cest).strftime('%d %b %Y %H:%M:%S')}
{wci_text}
{iaci_text}
"""
        msg.attach(MIMEText(body, 'plain'))

        files_to_attach = [log_filename, 'daily_briefing.md', 'freight_indicies/wci_cache.json', 'freight_indicies/iaci_cache.json'] + glob.glob('wci_email_*.html') + glob.glob('iaci_email_*.html')
        for file in files_to_attach:
            if os.path.exists(file):
                logger.debug(f"Attaching file: {file}")
                with open(file, 'rb') as f:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header('Content-Disposition', f'attachment; filename={os.path.basename(file)}')
                msg.attach(part)
            else:
                logger.warning(f"File not found for attachment: {file}")

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(gmail_user, gmail_pass)
        server.send_message(msg)
        server.quit()
        logger.info("Email sent successfully")
        return True

    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        return False

def generate_briefing():
    logger.debug("Starting briefing generation")
    report_date = datetime.now(cest).strftime("%d %b %Y")
    wci_cache = load_wci_cache()
    iaci_cache = load_iaci_cache()

    # WCI-Verarbeitung
    wci_html_file, wci_subject = fetch_wci_email()
    wci_value = None
    wci_date = None
    if wci_html_file:
        wci_value, wci_date = extract_wci_from_html(wci_html_file, wci_subject)
    if not wci_value:
        logger.error("Failed to fetch or extract WCI value")
        latest_wci_cache_date = max(wci_cache.keys(), default=None) if wci_cache else None
        ten_days_ago = (datetime.now(cest) - timedelta(days=10)).strftime("%Y-%m-%d")
        if latest_wci_cache_date:
            latest_entry = wci_cache[latest_wci_cache_date]
            wci_value = latest_entry["value"]
            wci_date = latest_wci_cache_date
            try:
                cache_date = datetime.strptime(wci_date, "%d.%m.%Y").strftime("%Y-%m-%d")
                if cache_date >= ten_days_ago:
                    logger.info(f"Using cached WCI value {wci_value:.2f} (Date: {wci_date})")
                    warning_message = f"WCI: E-Mail not reachable or value not extracted, used cache value {wci_value} (Date: {wci_date})"
                    send_warning_email(warning_message)
                else:
                    warning_message = f"WCI: E-Mail not reachable, cache value {wci_value} too old (Date: {wci_date})"
                    send_warning_email(warning_message)
                    wci_value = 0.0
                    wci_date = datetime.now(cest).strftime("%d.%m.%Y")
            except ValueError:
                warning_message = f"WCI: E-Mail not reachable, invalid cache date (Date: {wci_date})"
                send_warning_email(warning_message)
                wci_value = 0.0
                wci_date = datetime.now(cest).strftime("%d.%m.%Y")
        else:
            warning_message = "WCI: E-Mail not reachable, no valid cache available"
            send_warning_email(warning_message)
            wci_value = 0.0
            wci_date = datetime.now(cest).strftime("%d.%m.%Y")
    else:
        if wci_date not in wci_cache:
            wci_cache[wci_date] = {"value": wci_value}
            save_wci_cache(wci_cache)
        else:
            logger.debug(f"WCI cache entry for {wci_date} already exists, skipping save")

    # IACI-Verarbeitung
    iaci_html_file, iaci_subject = fetch_iaci_email()
    iaci_value = None
    iaci_date = None
    if iaci_html_file:
        iaci_value, iaci_date = extract_iaci_from_html(iaci_html_file, iaci_subject)
    if not iaci_value:
        logger.error("Failed to fetch or extract IACI value")
        latest_iaci_cache_date = max(iaci_cache.keys(), default=None) if iaci_cache else None
        ten_days_ago = (datetime.now(cest) - timedelta(days=10)).strftime("%Y-%m-%d")
        if latest_iaci_cache_date:
            latest_entry = iaci_cache[latest_iaci_cache_date]
            iaci_value = latest_entry["value"]
            iaci_date = latest_iaci_cache_date
            try:
                cache_date = datetime.strptime(iaci_date, "%d.%m.%Y").strftime("%Y-%m-%d")
                if cache_date >= ten_days_ago:
                    logger.info(f"Using cached IACI value {iaci_value:.2f} (Date: {iaci_date})")
                    warning_message = f"IACI: E-Mail not reachable or value not extracted, used cache value {iaci_value} (Date: {iaci_date})"
                    send_warning_email(warning_message)
                else:
                    warning_message = f"IACI: E-Mail not reachable, cache value {iaci_value} too old (Date: {iaci_date})"
                    send_warning_email(warning_message)
                    iaci_value = 0.0
                    iaci_date = datetime.now(cest).strftime("%d.%m.%Y")
            except ValueError:
                warning_message = f"IACI: E-Mail not reachable, invalid cache date (Date: {iaci_date})"
                send_warning_email(warning_message)
                iaci_value = 0.0
                iaci_date = datetime.now(cest).strftime("%d.%m.%Y")
        else:
            warning_message = "IACI: E-Mail not reachable, no valid cache available"
            send_warning_email(warning_message)
            iaci_value = 0.0
            iaci_date = datetime.now(cest).strftime("%d.%m.%Y")
    else:
        if iaci_date not in iaci_cache:
            iaci_cache[iaci_date] = {"value": iaci_value}
            save_iaci_cache(iaci_cache)
        else:
            logger.debug(f"IACI cache entry for {iaci_date} already exists, skipping save")

    # Prozentuale Veränderung
    wci_previous_value = None
    sorted_wci_dates = sorted([d for d in wci_cache.keys() if d != wci_date])
    if sorted_wci_dates:
        wci_previous_value = wci_cache[sorted_wci_dates[-1]]["value"]
    wci_percentage_change = calculate_percentage_change(wci_value, wci_previous_value)

    iaci_previous_value = None
    sorted_iaci_dates = sorted([d for d in iaci_cache.keys() if d != iaci_date])
    if sorted_iaci_dates:
        iaci_previous_value = iaci_cache[sorted_iaci_dates[-1]]["value"]
    iaci_percentage_change = calculate_percentage_change(iaci_value, iaci_previous_value)

    # Bericht generieren
    wci_arrow = "↓" if wci_percentage_change and wci_percentage_change < 0 else "↑" if wci_percentage_change else ""
    wci_change_text = f" ({wci_arrow} {wci_percentage_change:.2f}%)" if wci_percentage_change is not None else ""
    wci_text = f"• WCI: {wci_value:.2f}{wci_change_text} (Stand {wci_date})"

    iaci_arrow = "↓" if iaci_percentage_change and iaci_percentage_change < 0 else "↑" if iaci_percentage_change else ""
    iaci_change_text = f" ({iaci_arrow} {iaci_percentage_change:.2f}%)" if iaci_percentage_change is not None else ""
    iaci_text = f"• IACI: {iaci_value:.2f}{iaci_change_text} (Stand {iaci_date})"

    report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
{iaci_text}
"""
    logger.debug(f"Report content:\n{report}")
    with open('daily_briefing.md', 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info("Saved briefing to daily_briefing.md")

    send_results_email(wci_value, wci_date, iaci_value, iaci_date, wci_percentage_change, iaci_percentage_change)
    return report

if __name__ == "__main__":
    logger.debug("Starting main execution")
    report = generate_briefing()
    logger.debug("Main execution completed")
