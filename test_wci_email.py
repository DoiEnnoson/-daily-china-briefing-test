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
from email.header import decode_header
from bs4 import BeautifulSoup

# CEST ist UTC+2
cest = timezone(timedelta(hours=2))

# Logging einrichten, nur auf Konsole, keine Dateien
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger()

# Pfade
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FREIGHT_CACHE_DIR = os.path.join(BASE_DIR, "freight_indicies")
WCI_CACHE_FILE = os.path.join(FREIGHT_CACHE_DIR, "wci_cache.json")
IACI_CACHE_FILE = os.path.join(FREIGHT_CACHE_DIR, "iaci_cache.json")

def load_wci_cache():
    """Lädt den WCI-Cache oder initialisiert ihn als leer, wenn nicht vorhanden."""
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        if os.path.exists(WCI_CACHE_FILE):
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.info("Successfully loaded WCI cache")
                return cache
        logger.info(f"No WCI cache file found at {WCI_CACHE_FILE}, initializing empty cache")
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
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        with open(WCI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        if os.path.exists(WCI_CACHE_FILE):
            logger.info(f"Successfully wrote WCI cache to {WCI_CACHE_FILE}")
        else:
            logger.error(f"WCI cache file {WCI_CACHE_FILE} was not created")
            raise Exception(f"WCI cache file {WCI_CACHE_FILE} was not created")
    except Exception as e:
        logger.error(f"Failed to save WCI cache: {str(e)}")
        raise

def load_iaci_cache():
    """Lädt den IACI-Cache oder initialisiert ihn als leer, wenn nicht vorhanden."""
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        if os.path.exists(IACI_CACHE_FILE):
            with open(IACI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.info("Successfully loaded IACI cache")
                return cache
        logger.info(f"No IACI cache file found at {IACI_CACHE_FILE}, initializing empty cache")
        cache = {}
        save_iaci_cache(cache)
        return cache
    except json.JSONDecodeError as e:
        logger.error(f"Corrupted IACI cache file, reinitializing: {str(e)}")
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
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        existing_cache = {}
        if os.path.exists(IACI_CACHE_FILE):
            try:
                with open(IACI_CACHE_FILE, "r", encoding="utf-8") as f:
                    existing_cache = json.load(f)
            except json.JSONDecodeError:
                logger.error("Corrupted IACI cache file, overwriting with new data")
        
        existing_cache.update(cache)
        with open(IACI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(existing_cache, f, ensure_ascii=False, indent=2)
        
        if os.path.exists(IACI_CACHE_FILE):
            logger.info(f"Successfully wrote IACI cache to {IACI_CACHE_FILE}")
        else:
            logger.error(f"IACI cache file {IACI_CACHE_FILE} was not created")
            raise Exception(f"IACI cache file {IACI_CACHE_FILE} was not created")
    except Exception as e:
        logger.error(f"Failed to save IACI cache: {str(e)}")
        raise

def fetch_wci_email():
    """Holt die neueste Drewry WCI-E-Mail aus den letzten 14 Tagen und gibt den HTML-Inhalt zurück."""
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

        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            raise Exception("GMAIL credentials missing")

        mail = imaplib.IMAP4_SSL('imap.gmail.com', timeout=30)
        mail.login(gmail_user, gmail_pass)
        
        result, data = mail.select('inbox')
        if result != 'OK':
            logger.error(f"Failed to select inbox: {result}, data: {data}")
            raise Exception(f"IMAP select failed: {result}")

        today = datetime.now(cest)
        since_date = (today - timedelta(days=14)).strftime("%d-%b-%Y")
        search_criteria = f'FROM noreply@drewry.co.uk SINCE {since_date}'
        result, data = mail.search(None, search_criteria)
        if result != 'OK':
            logger.error(f"Failed to search WCI emails: {result}, data: {data}")
            raise Exception(f"IMAP search failed: {result}")

        email_ids = data[0].split()
        if not email_ids:
            logger.error("No WCI emails found from noreply@drewry.co.uk in the last 14 days")
            raise Exception("No WCI emails found")

        for email_id in email_ids[::-1]:
            result, data = mail.fetch(email_id, '(RFC822)')
            if result != 'OK':
                logger.error(f"Failed to fetch WCI email ID {email_id}")
                continue

            raw_email = data[0][1]
            email_message = email.message_from_bytes(raw_email)

            subject, encoding = decode_header(email_message['subject'])[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding if encoding else 'utf-8')

            if "World Container Index" in subject:
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
                    logger.error(f"No HTML content found in WCI email ID {email_id}")
                    continue

                logger.info("Successfully fetched WCI email content")
                mail.logout()
                return html_content, subject

        logger.error("No matching WCI email found")
        raise Exception("No matching WCI email found")

    except Exception as e:
        logger.error(f"Error fetching WCI email: {str(e)}")
        if 'mail' in locals():
            mail.logout()
        return None, None

def fetch_iaci_email():
    """Holt die neueste Drewry IACI-E-Mail aus den letzten 14 Tagen und gibt den HTML-Inhalt zurück."""
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

        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            raise Exception("GMAIL credentials missing")

        mail = imaplib.IMAP4_SSL('imap.gmail.com', timeout=30)
        mail.login(gmail_user, gmail_pass)
        
        result, data = mail.select('inbox')
        if result != 'OK':
            logger.error(f"Failed to select inbox: {result}, data: {data}")
            raise Exception(f"IMAP select failed: {result}")

        today = datetime.now(cest)
        since_date = (today - timedelta(days=14)).strftime("%d-%b-%Y")
        search_criteria = f'FROM noreply@drewry.co.uk SINCE {since_date}'
        result, data = mail.search(None, search_criteria)
        if result != 'OK':
            logger.error(f"Failed to search IACI emails: {result}, data: {data}")
            raise Exception(f"IMAP search failed: {result}")

        email_ids = data[0].split()
        if not email_ids:
            logger.error("No IACI emails found from noreply@drewry.co.uk in the last 14 days")
            raise Exception("No IACI emails found")

        for email_id in email_ids[::-1]:
            result, data = mail.fetch(email_id, '(RFC822)')
            if result != 'OK':
                logger.error(f"Failed to fetch IACI email ID {email_id}")
                continue

            raw_email = data[0][1]
            email_message = email.message_from_bytes(raw_email)

            subject, encoding = decode_header(email_message['subject'])[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding if encoding else 'utf-8')

            if "Intra-Asia" in subject:
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
                    logger.error(f"No HTML content found in IACI email ID {email_id}")
                    continue

                logger.info("Successfully fetched IACI email content")
                mail.logout()
                return html_content, subject

        logger.error("No matching IACI email found")
        raise Exception("No matching IACI email found")

    except Exception as e:
        logger.error(f"Error fetching IACI email: {str(e)}")
        if 'mail' in locals():
            mail.logout()
        return None, None

def extract_wci_from_html(html_content, subject):
    """Extrahiert den WCI-Wert und das Datum aus dem HTML-Inhalt."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        wci_text = soup.get_text(strip=True)

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
            logger.info(f"Could not parse WCI date, using today: {wci_date}")

        logger.info(f"Extracted WCI: {wci_value:.2f}, Date: {wci_date}")
        return wci_value, wci_date

    except Exception as e:
        logger.error(f"Error processing WCI HTML content: {str(e)}")
        return None, None

def extract_iaci_from_html(html_content, subject):
    """Extrahiert den IACI-Wert und das Datum aus dem HTML-Inhalt."""
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        iaci_text = soup.get_text(strip=True)

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
            logger.info(f"Could not parse IACI date, using today: {iaci_date}")

        logger.info(f"Extracted IACI: {iaci_value:.2f}, Date: {iaci_date}")
        return iaci_value, iaci_date

    except Exception as e:
        logger.error(f"Error processing IACI HTML content: {str(e)}")
        return None, None

def calculate_percentage_change(current_value, previous_value):
    """Berechnet die prozentuale Veränderung zwischen zwei Werten, gerundet auf ganze Zahlen."""
    if previous_value is None or previous_value == 0:
        return None
    change = ((current_value - previous_value) / previous_value) * 100
    return round(change)

def send_warning_email(warning_message):
    """Sendet eine Warn-E-Mail bei Problemen."""
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

        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        logger.info("Warning email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send warning email: {str(e)}")
        raise

def send_results_email(wci_value, wci_date, iaci_value, iaci_date, wci_percentage_change=None, iaci_percentage_change=None):
    """Sendet die WCI- und IACI-Ergebnisse per HTML-E-Mail ohne Anhänge."""
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
        wci_change_text = f" ({wci_arrow} {wci_percentage_change}%)" if wci_percentage_change is not None else ""
        wci_text = f"<li><a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry'>WCI</a>: ${wci_value:.2f}{wci_change_text} (Stand {wci_date})</li>"

        iaci_arrow = "↓" if iaci_percentage_change and iaci_percentage_change < 0 else "↑" if iaci_percentage_change else ""
        iaci_error = iaci_percentage_change if iaci_percentage_change is not None else 0
        iaci_change_text = f" ({iaci_arrow} {iaci_error}%)" if iaci_percentage_change is not None else ""
        iaci_text = f"<li><a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/intra-asia-container-index'>IACI</a>: ${iaci_value:.2f}{iaci_change_text} (Stand {iaci_date})</li>"

        body = f"""<html>
<body>
<p>Daily China Briefing WCI/IACI Results</p>
<p>Date: {datetime.now(cest).strftime('%d %b %Y %H:%M:%S')}</p>
<ul>
{wci_text}
{iaci_text}
</ul>
</body>
</html>"""
        msg.attach(MIMEText(body, 'html', 'utf-8'))

        server = smtplib.SMTP彼此

System: I notice there is an error in the `send_results_email` function of the provided script. Specifically, there is an issue with the `iaci_error` variable, which seems to be a typo and is causing incorrect handling of the IACI percentage change in the email body. Let me fix this and provide the corrected version of the script.

Here is the corrected `send_results_email` function (the rest of the script remains unchanged):

```python
def send_results_email(wci_value, wci_date, iaci_value, iaci_date, wci_percentage_change=None, iaci_percentage_change=None):
    """Sendet die WCI- und IACI-Ergebnisse per HTML-E-Mail ohne Anhänge."""
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
        wci_change_text = f" ({wci_arrow} {wci_percentage_change}%)" if wci_percentage_change is not None else ""
        wci_text = f"<li><a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry'>WCI</a>: ${wci_value:.2f}{wci_change_text} (Stand {wci_date})</li>"

        iaci_arrow = "↓" if iaci_percentage_change and iaci_percentage_change < 0 else "↑" if iaci_percentage_change else ""
        iaci_change_text = f" ({iaci_arrow} {iaci_percentage_change}%)" if iaci_percentage_change is not None else ""
        iaci_text = f"<li><a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/intra-asia-container-index'>IACI</a>: ${iaci_value:.2f}{iaci_change_text} (Stand {iaci_date})</li>"

        body = f"""<html>
<body>
<p>Daily China Briefing WCI/IACI Results</p>
<p>Date: {datetime.now(cest).strftime('%d %b %Y %H:%M:%S')}</p>
<ul>
{wci_text}
{iaci_text}
</ul>
</body>
</html>"""
        msg.attach(MIMEText(body, 'html', 'utf-8'))

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
