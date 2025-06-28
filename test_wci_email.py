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

# Logging einrichten
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wci_test_log.txt', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

# Pfade
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WCI_CACHE_DIR = os.path.join(BASE_DIR, "WCI")
WCI_CACHE_FILE = os.path.join(WCI_CACHE_DIR, "wci_cache.json")

def load_wci_cache():
    """Lädt den WCI-Cache oder initialisiert ihn als leer, wenn nicht vorhanden."""
    logger.debug(f"Loading cache from {WCI_CACHE_FILE}")
    try:
        os.makedirs(WCI_CACHE_DIR, exist_ok=True)
        if os.path.exists(WCI_CACHE_FILE):
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.debug(f"Successfully loaded cache: {cache}")
                return cache
        logger.debug(f"No cache file found at {WCI_CACHE_FILE}, initializing empty cache")
        cache = {}
        save_wci_cache(cache)
        return cache
    except Exception as e:
        logger.error(f"Failed to load or create cache: {str(e)}")
        cache = {}
        save_wci_cache(cache)
        return cache

def save_wci_cache(cache):
    """Speichert den WCI-Cache und prüft, ob die Datei erstellt wurde."""
    logger.debug(f"Saving cache to {WCI_CACHE_FILE}: {cache}")
    try:
        os.makedirs(WCI_CACHE_DIR, exist_ok=True)
        with open(WCI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        if os.path.exists(WCI_CACHE_FILE):
            logger.info(f"Successfully wrote cache to {WCI_CACHE_FILE}")
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                logger.debug(f"Cache file content after save: {f.read()}")
        else:
            logger.error(f"Cache file {WCI_CACHE_FILE} was not created")
            raise Exception(f"Cache file {WCI_CACHE_FILE} was not created")
    except Exception as e:
        logger.error(f"Failed to save cache: {str(e)}")
        raise

def fetch_wci_email():
    """Holt die neueste Drewry-E-Mail aus den letzten 7 Tagen und speichert den HTML-Inhalt."""
    logger.debug("Starting email fetch")
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
            search_criteria = f'(FROM "noreply@drewry.co.uk" ON "{date}")'
            logger.debug(f"Searching emails with criteria: {search_criteria}")
            result, data = mail.search(None, search_criteria)
            if result == 'OK' and data[0]:
                email_ids.extend(data[0].split())

        if not email_ids:
            logger.error("No emails found from noreply@drewry.co.uk in the last 7 days")
            raise Exception("No Drewry emails found")

        latest_email_id = email_ids[-1]
        logger.debug(f"Fetching email ID: {latest_email_id}")
        result, data = mail.fetch(latest_email_id, '(RFC822)')

        if result != 'OK':
            logger.error(f"Failed to fetch email ID {latest_email_id}")
            raise Exception("Failed to fetch email")

        raw_email = data[0][1]
        email_message = email.message_from_bytes(raw_email)

        subject, encoding = decode_header(email_message['subject'])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding if encoding else 'utf-8')
        logger.debug(f"Email subject: {subject}")

        if "Drewry World Container Index" not in subject:
            logger.error(f"Email ID {latest_email_id} does not match expected subject")
            raise Exception("No matching Drewry email found")

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
            logger.error(f"No HTML content found in email ID {latest_email_id}")
            raise Exception("No HTML content found")

        email_id_str = latest_email_id.decode('utf-8')
        html_filename = f'wci_email_{email_id_str}.html'
        logger.debug(f"Saving HTML content to {html_filename}")
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        logger.info(f"Successfully saved email content to {html_filename}")
        mail.logout()
        return html_filename, subject

    except Exception as e:
        logger.error(f"Error fetching email: {str(e)}")
        if 'mail' in locals():
            mail.logout()
        return None, None

def extract_wci_from_html(html_file, subject):
    """Extrahiert den WCI-Wert und das Datum aus der HTML-Datei."""
    logger.debug(f"Attempting to read HTML file: {html_file}")
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')

        wci_text = soup.get_text(strip=True)
        logger.debug(f"Extracted text (first 500 chars): {wci_text[:500]}")

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
            logger.debug(f"Could not parse date, using today: {wci_date}")

        logger.info(f"Extracted WCI: {wci_value:.2f}, Date: {wci_date}")
        return wci_value, wci_date

    except Exception as e:
        logger.error(f"Error processing HTML file {html_file}: {str(e)}")
        return None, None

def calculate_percentage_change(current_value, previous_value):
    """Berechnet die prozentuale Veränderung zwischen zwei Werten."""
    if previous_value is None or previous_value == 0:
        return None
    change = ((current_value - previous_value) / previous_value) * 100
    return round(change, 2)

def send_warning_email(warning_message):
    """Sendet eine Warn-E-Mail bei Problemen."""
    logger.debug("Preparing to send WCI warning email")
    try:
        env_vars = os.getenv("CONFIG")
        if not env_vars:
            logger.error("CONFIG environment variable not found")
            raise Exception("Missing CONFIG")

        pairs = env_vars.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(
            f"Problem: WCI data issue\nDetails: {warning_message}\nDate: {datetime.now(cest).strftime('%Y-%m-%d')}",
            "plain",
            "utf-8"
        )
        msg["Subject"] = "China-Briefing WCI Warning"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = "hadobrockmeyer@gmail.com"

        logger.debug("Connecting to SMTP server")
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        logger.info("WCI warning email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send WCI warning email: {str(e)}")
        raise

def send_results_email(wci_value, wci_date, percentage_change=None):
    """Sendet die WCI-Ergebnisse per E-Mail."""
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
        msg['Subject'] = f"Daily China Briefing WCI Results - {datetime.now(cest).strftime('%Y-%m-%d %H:%M:%S')}"

        arrow = "↓" if percentage_change and percentage_change < 0 else "↑" if percentage_change else ""
        change_text = f" ({arrow} {percentage_change:.2f}%)" if percentage_change is not None else ""
        wci_text = f"• WCI: {wci_value:.2f}{change_text} (Stand {wci_date})"

        body = f"""Attached are the logs and briefing from the Daily China Briefing WCI workflow.
Date: {datetime.now(cest).strftime('%d %b %Y %H:%M:%S')}
{wci_text}
"""
        msg.attach(MIMEText(body, 'plain'))

        files_to_attach = ['wci_test_log.txt', 'daily_briefing.md', 'WCI/wci_cache.json'] + glob.glob('wci_email_*.html')
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

def clean_old_cache(cache):
    """Entfernt Cache-Einträge älter als 30 Tage."""
    thirty_days_ago = datetime.now(cest) - timedelta(days=30)
    cleaned_cache = {}
    for date_str, data in cache.items():
        try:
            cache_date = datetime.strptime(date_str, "%d.%m.%Y").replace(tzinfo=cest)  # CEST-Zeitzone hinzufügen
            if cache_date >= thirty_days_ago:
                cleaned_cache[date_str] = data
        except ValueError:
            logger.warning(f"Invalid date format in cache: {date_str}")
    return cleaned_cache

def generate_briefing():
    logger.debug("Starting briefing generation")
    report_date = datetime.now(cest).strftime("%d %b %Y")
    cache = load_wci_cache()

    html_file, subject = fetch_wci_email()
    if not html_file:
        logger.error("Failed to fetch WCI email")
        latest_cache_date = max(cache.keys(), default=None) if cache else None
        ten_days_ago = (datetime.now(cest) - timedelta(days=10)).strftime("%Y-%m-%d")
        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            wci_value = latest_entry["value"]
            email_date_str = latest_cache_date
            try:
                cache_date = datetime.strptime(email_date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
                if cache_date >= ten_days_ago:
                    logger.info(f"Using cached WCI value {wci_value:.2f} (Date: {email_date_str})")
                    # Finde vorherigen Wert
                    previous_value = None
                    sorted_dates = sorted([d for d in cache.keys() if d != email_date_str])
                    if sorted_dates:
                        previous_value = cache[sorted_dates[-1]]["value"]
                    percentage_change = calculate_percentage_change(wci_value, previous_value)
                    warning_message = f"E-Mail not reachable, used cache value {wci_value} (Date: {email_date_str})"
                    send_warning_email(warning_message)
                    arrow = "↓" if percentage_change and percentage_change < 0 else "↑" if percentage_change else ""
                    change_text = f" ({arrow} {percentage_change:.2f}%)" if percentage_change is not None else ""
                    wci_text = f"• WCI: {wci_value:.2f}{change_text} (Stand {email_date_str})"
                    report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
"""
                    with open('daily_briefing.md', 'w', encoding='utf-8') as f:
                        f.write(report)
                    logger.info("Saved briefing to daily_briefing.md")
                    send_results_email(wci_value, email_date_str, percentage_change)
                    return report
                else:
                    warning_message = f"E-Mail not reachable, cache value {wci_value} too old (Date: {email_date_str})"
            except ValueError:
                warning_message = f"E-Mail not reachable, invalid cache date (Date: {email_date_str})"
        wci_value = 0.0
        wci_date = datetime.now(cest).strftime("%d.%m.%Y")
        warning_message = warning_message or "E-Mail not reachable, no valid cache available"
        send_warning_email(warning_message)
        wci_text = f"• WCI: {wci_value:.2f} (Stand {wci_date})"
        report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
"""
        with open('daily_briefing.md', 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info("Saved briefing to daily_briefing.md")
        send_results_email(wci_value, wci_date)
        return report

    wci_value, wci_date = extract_wci_from_html(html_file, subject)
    if not wci_value:
        logger.error("Failed to extract WCI value")
        latest_cache_date = max(cache.keys(), default=None) if cache else None
        ten_days_ago = (datetime.now(cest) - timedelta(days=10)).strftime("%Y-%m-%d")
        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            wci_value = latest_entry["value"]
            email_date_str = latest_cache_date
            try:
                cache_date = datetime.strptime(email_date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
                if cache_date >= ten_days_ago:
                    logger.info(f"Using cached WCI value {wci_value:.2f} (Date: {email_date_str})")
                    # Finde vorherigen Wert
                    previous_value = None
                    sorted_dates = sorted([d for d in cache.keys() if d != email_date_str])
                    if sorted_dates:
                        previous_value = cache[sorted_dates[-1]]["value"]
                    percentage_change = calculate_percentage_change(wci_value, previous_value)
                    warning_message = f"Could not extract WCI value, used cache value {wci_value} (Date: {email_date_str})"
                    send_warning_email(warning_message)
                    arrow = "↓" if percentage_change and percentage_change < 0 else "↑" if percentage_change else ""
                    change_text = f" ({arrow} {percentage_change:.2f}%)" if percentage_change is not None else ""
                    wci_text = f"• WCI: {wci_value:.2f}{change_text} (Stand {email_date_str})"
                    report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
"""
                    with open('daily_briefing.md', 'w', encoding='utf-8') as f:
                        f.write(report)
                    logger.info("Saved briefing to daily_briefing.md")
                    send_results_email(wci_value, email_date_str, percentage_change)
                    return report
                else:
                    warning_message = f"Could not extract WCI value, cache value {wci_value} too old (Date: {email_date_str})"
            except ValueError:
                warning_message = f"Could not extract WCI value, invalid cache date (Date: {email_date_str})"
        wci_value = 0.0
        wci_date = datetime.now(cest).strftime("%d.%m.%Y")
        warning_message = warning_message or "Could not extract WCI value, no valid cache available"
        send_warning_email(warning_message)
        wci_text = f"• WCI: {wci_value:.2f} (Stand {wci_date})"
        report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
"""
        with open('daily_briefing.md', 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info("Saved briefing to daily_briefing.md")
        send_results_email(wci_value, wci_date)
        return report

    # Cache bereinigen
    cache = clean_old_cache(cache)

    # Cache nur aktualisieren, wenn email_date neu ist
    if wci_date not in cache:
        cache[wci_date] = {"value": wci_value}
        save_wci_cache(cache)
    else:
        logger.debug(f"Cache entry for {wci_date} already exists, skipping save")

    # Finde vorherigen Wert
    previous_value = None
    sorted_dates = sorted([d for d in cache.keys() if d != wci_date])
    if sorted_dates:
        previous_value = cache[sorted_dates[-1]]["value"]

    # Prozentuale Veränderung berechnen
    percentage_change = calculate_percentage_change(wci_value, previous_value)

    # Bericht generieren
    arrow = "↓" if percentage_change and percentage_change < 0 else "↑" if percentage_change else ""
    change_text = f" ({arrow} {percentage_change:.2f}%)" if percentage_change is not None else ""
    wci_text = f"• WCI: {wci_value:.2f}{change_text} (Stand {wci_date})"

    report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
"""
    logger.debug(f"Report content:\n{report}")
    with open('daily_briefing.md', 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info("Saved briefing to daily_briefing.md")

    send_results_email(wci_value, wci_date, percentage_change)
    return report

if __name__ == "__main__":
    logger.debug("Starting main execution")
    report = generate_briefing()
    logger.debug("Main execution completed")
