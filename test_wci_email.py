import os
import re
import logging
import imaplib
import email
import smtplib
import json
import feedparser
import requests
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header
from bs4 import BeautifulSoup

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
WCI_CACHE_FILE = os.path.join(BASE_DIR, "WCI", "wci_cache.json")
SCFI_CACHE_FILE = os.path.join(BASE_DIR, "scfi_cache.json")

def load_wci_cache():
    """Lädt den WCI-Cache."""
    logger.debug(f"Loading cache from {WCI_CACHE_FILE}")
    try:
        os.makedirs(os.path.dirname(WCI_CACHE_FILE), exist_ok=True)
        if os.path.exists(WCI_CACHE_FILE):
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.debug(f"Successfully loaded cache: {cache}")
                return cache
        logger.debug(f"No cache file found at {WCI_CACHE_FILE}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load cache: {str(e)}")
        return {}

def save_wci_cache(cache):
    """Speichert den WCI-Cache."""
    logger.debug(f"Saving cache to {WCI_CACHE_FILE}: {cache}")
    try:
        os.makedirs(os.path.dirname(WCI_CACHE_FILE), exist_ok=True)
        with open(WCI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully wrote cache to {WCI_CACHE_FILE}")
    except Exception as e:
        logger.error(f"Failed to save cache: {str(e)}")
        raise

def load_scfi_cache():
    """Lädt den SCFI-Cache."""
    logger.debug(f"Loading cache from {SCFI_CACHE_FILE}")
    try:
        os.makedirs(os.path.dirname(SCFI_CACHE_FILE), exist_ok=True)
        if os.path.exists(SCFI_CACHE_FILE):
            with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.debug(f"Successfully loaded cache: {cache}")
                return cache
        logger.debug(f"No cache file found at {SCFI_CACHE_FILE}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load cache: {str(e)}")
        return {}

def save_scfi_cache(cache):
    """Speichert den SCFI-Cache."""
    logger.debug(f"Saving cache to {SCFI_CACHE_FILE}: {cache}")
    try:
        os.makedirs(os.path.dirname(SCFI_CACHE_FILE), exist_ok=True)
        with open(SCFI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully wrote cache to {SCFI_CACHE_FILE}")
    except Exception as e:
        logger.error(f"Failed to save cache: {str(e)}")
        raise

def fetch_wci():
    """Holt WCI-Daten aus der Drewry-E-Mail mit Cache und Fallback."""
    logger.debug("Starting to fetch WCI data")
    today_str = datetime.now().strftime("%Y-%m-%d")
    cache = load_wci_cache()

    try:
        # E-Mail-Zugangsdaten
        env_vars = os.getenv('DREWRY')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            raise Exception("DREWRY not set")

        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=')
            if key == 'GMAIL_USER':
                gmail_user = value
            elif key == 'GMAIL_PASS':
                gmail_pass = value

        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            raise Exception("GMAIL credentials missing")

        # E-Mail abrufen
        logger.debug("Connecting to Gmail IMAP")
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(gmail_user, gmail_pass)
        mail.select('inbox')

        # Zeitfenster: Letzte 3 Tage
        since_date = (datetime.now() - timedelta(days=3)).strftime("%d-%b-%Y")
        search_criteria = f'(FROM "noreply@drewry.co.uk" "Drewry World Container Index" SINCE "{since_date}")'
        logger.debug(f"Searching emails with criteria: {search_criteria}")
        result, data = mail.search(None, search_criteria)

        if result != 'OK':
            logger.error("Failed to search emails")
            raise Exception("IMAP search failed")

        email_ids = data[0].split()
        if not email_ids:
            logger.error("No emails found from noreply@drewry.co.uk")
            raise Exception("No Drewry emails found")

        # Neueste E-Mail
        latest_email_id = email_ids[-1]
        logger.debug(f"Fetching email ID: {latest_email_id}")
        result, data = mail.fetch(latest_email_id, '(RFC822)')

        if result != 'OK':
            logger.error("Failed to fetch email")
            raise Exception("IMAP fetch failed")

        raw_email = data[0][1]
        email_message = email.message_from_bytes(raw_email)

        subject, encoding = decode_header(email_message['subject'])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding if encoding else 'utf-8')
        logger.debug(f"Email subject: {subject}")

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
            logger.error("No HTML content found in email")
            raise Exception("No HTML content")

        email_id_str = latest_email_id.decode('utf-8')
        html_filename = f'wci_email_{email_id_str}.html'
        logger.debug(f"Saving HTML content to {html_filename}")
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # WCI extrahieren
        soup = BeautifulSoup(html_content, 'html.parser')
        wci_text = soup.get_text()
        wci_match = re.search(r'\$(\d{1,3}(,\d{3})*)\s*per 40ft container', wci_text)
        date_match = re.search(r'(\d{1,2}\s+\w+\s+\d{4})', subject or wci_text)

        if not wci_match:
            logger.error("Could not extract WCI value from text")
            raise Exception("WCI value extraction failed")

        wci_value = float(wci_match.group(1).replace(',', ''))
        wci_date = None
        if date_match:
            for fmt in ["%d %B %Y", "%d %b %Y"]:
                try:
                    wci_date = datetime.strptime(date_match.group(1), fmt).strftime("%d.%m.%Y")
                    break
                except ValueError:
                    continue
        if wci_date is None:
            wci_date = datetime.now().strftime("%d.%m.%Y")
            logger.debug(f"Could not parse date, using today: {wci_date}")

        # Prozentänderung aus Cache
        pct_change = None
        latest_cache_date = max([k for k in cache.keys() if k != today_str], default=None)
        if latest_cache_date:
            last_value = cache[latest_cache_date]["value"]
            pct_change = ((wci_value - last_value) / last_value) * 100 if last_value != 0 else 0
            logger.debug(f"Calculated percent change: {pct_change:.2f}% (Current: {wci_value}, Previous: {last_value})")

        # Cache aktualisieren
        should_save = True
        if today_str in cache:
            latest_entry = cache[today_str]
            if latest_entry["value"] == wci_value and latest_entry["api_date"] == wci_date:
                should_save = False
                logger.debug("No cache update needed (value and date unchanged)")

        if should_save:
            cache[today_str] = {"value": wci_value, "api_date": wci_date}
            save_wci_cache(cache)

        logger.info(f"Extracted WCI: {wci_value:.2f}, Date: {wci_date}, Percent Change: {pct_change if pct_change is not None else 'N/A'}")
        mail.logout()
        return wci_value, pct_change, wci_date, None

    except Exception as e:
        logger.error(f"Failed to fetch WCI data: {str(e)}")
        warning_message = None
        latest_cache_date = max(cache.keys(), default=None)
        ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            wci_value = latest_entry["value"]
            api_date_str = latest_entry["api_date"]
            wci_date = api_date_str

            try:
                api_date = datetime.strptime(api_date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
                if api_date >= ten_days_ago:
                    logger.info(f"Using cached WCI value {wci_value:.2f} (Date: {wci_date})")
                    warning_message = f"E-Mail not reachable, used cache value {wci_value} (Date: {api_date_str})"
                    return wci_value, None, wci_date, warning_message
                else:
                    warning_message = f"E-Mail not reachable, cache value {wci_value} too old (Date: {api_date_str})"
            except ValueError:
                warning_message = f"E-Mail not reachable, invalid cache date (Date: {api_date_str})"

        wci_value = 0.0
        wci_date = datetime.now().strftime("%d.%m.%Y")
        warning_message = warning_message or "E-Mail not reachable, no valid cache available"
        logger.info(f"No valid cache, returning zero value (Date: {wci_date})")
        return wci_value, None, wci_date, warning_message

def fetch_scfi():
    """Holt SCFI-Daten von der API."""
    logger.debug("Starting to fetch SCFI data")
    url = "https://en.sse.net.cn/currentIndex?indexName=scfi"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    today_str = datetime.now().strftime("%Y-%m-%d")
    cache = load_scfi_cache()

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == 0:
            logger.error(f"API error: {data.get('msg')}")
            raise Exception(data.get("msg"))

        scfi_data = data.get("data", {})
        current_date = scfi_data.get("currentDate")
        line_data_list = scfi_data.get("lineDataList", [])

        if not line_data_list:
            logger.error("No lineDataList found in API response")
            raise Exception("No lineDataList in API response")

        scfi_value = float(line_data_list[0]["currentContent"])
        last_value = float(line_data_list[0]["lastContent"])
        scfi_date = None

        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
            try:
                scfi_date = datetime.strptime(current_date, fmt).strftime("%d.%m.%Y")
                break
            except ValueError:
                continue
        if scfi_date is None:
            logger.debug(f"Could not parse date '{current_date}', using today")
            scfi_date = datetime.now().strftime("%d.%m.%Y")

        logger.info(f"SCFI value {scfi_value:.2f} retrieved via API (Date: {scfi_date})")

        pct_change = None
        if last_value is not None:
            pct_change = ((scfi_value - last_value) / last_value) * 100 if last_value != 0 else 0
            logger.info(f"Calculated percent change: {pct_change:.2f}% (Current: {scfi_value}, Previous: {last_value})")

        latest_cache_date = max(cache.keys(), default=None)
        should_save = True
        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            if latest_entry["value"] == scfi_value and latest_entry["api_date"] == scfi_date:
                should_save = False
                logger.debug("No cache update needed (value and date unchanged)")

        if should_save:
            cache[today_str] = {"value": scfi_value, "api_date": scfi_date}
            save_scfi_cache(cache)

        return scfi_value, pct_change, scfi_date, None

    except Exception as e:
        logger.error(f"Failed to fetch SCFI data: {str(e)}")
        warning_message = None
        latest_cache_date = max(cache.keys(), default=None)
        ten_days_ago = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")

        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            scfi_value = latest_entry["value"]
            api_date_str = latest_entry["api_date"]
            scfi_date = api_date_str

            try:
                api_date = datetime.strptime(api_date_str, "%d.%m.%Y").strftime("%Y-%m-%d")
                if api_date >= ten_days_ago:
                    logger.info(f"Using cached SCFI value {scfi_value:.2f} (Date: {scfi_date})")
                    warning_message = f"API not reachable, used cache value {scfi_value} (Date: {api_date_str})"
                    return scfi_value, None, scfi_date, warning_message
                else:
                    warning_message = f"API not reachable, cache value {scfi_value} too old (Date: {api_date_str})"
            except ValueError:
                warning_message = f"API not reachable, invalid cache date (Date: {api_date_str})"

        scfi_value = 1869.59
        scfi_date = datetime.now().strftime("%d.%m.%Y")
        warning_message = warning_message or "API failed, no cache available, used fallback 1869.59"
        logger.info(f"Using fallback SCFI value {scfi_value:.2f} (Date: {scfi_date})")
        return scfi_value, None, scfi_date, warning_message

def send_warning_email(warning_message, index_type="WCI"):
    """Sendet eine Warn-E-Mail bei Problemen."""
    logger.debug(f"Preparing to send {index_type} warning email")
    try:
        env_vars = os.getenv("CONFIG")
        if not env_vars:
            logger.error("CONFIG environment variable not found")
            raise Exception("Missing CONFIG")

        pairs = env_vars.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(
            f"Problem: {index_type} data issue\nDetails: {warning_message}\nDate: {datetime.now().strftime('%Y-%m-%d')}",
            "plain",
            "utf-8"
        )
        msg["Subject"] = f"China-Briefing {index_type} Warning"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = "hadobrockmeyer@gmail.com"

        logger.debug("Connecting to SMTP server")
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        logger.info(f"{index_type} warning email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send {index_type} warning email: {str(e)}")
        raise

def fetch_news():
    """Holt die neuesten Nachrichten aus einem RSS-Feed."""
    logger.debug("Starting news fetch")
    try:
        rss_url = "https://www.scmp.com/rss/91/feed"
        feed = feedparser.parse(rss_url)
        if not feed.entries:
            logger.error("No news entries found in RSS feed")
            return []

        news_items = []
        for entry in feed.entries[:3]:
            title = entry.get('title', 'No title')
            link = entry.get('link', '#')
            published = entry.get('published', 'No date')
            news_items.append({'title': title, 'link': link, 'published': published})

        logger.info(f"Fetched {len(news_items)} news items")
        return news_items

    except Exception as e:
        logger.error(f"Error fetching news: {str(e)}")
        return []

def fetch_cpr():
    """Platzhalter für CPR-Daten."""
    logger.debug("Starting CPR fetch")
    try:
        cpr_data = {"index": "1500", "change": "increased 2%"}
        logger.info("Fetched CPR data (placeholder)")
        return cpr_data
    except Exception as e:
        logger.error(f"Error fetching CPR: {str(e)}")
        return None

def send_results_email(wci_value, wci_date, wci_pct_change, scfi_value, scfi_date):
    """Sendet die Ergebnisse per E-Mail."""
    logger.debug("Starting email sending")
    try:
        env_vars = os.getenv('DREWRY')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            return False

        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=')
            if key == 'GMAIL_USER':
                gmail_user = value
            elif key == 'GMAIL_PASS':
                gmail_pass = value

        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            return False

        msg = MIMEMultipart()
        msg['From'] = f"Daily China Briefing <{gmail_user}>"
        msg['To'] = gmail_user
        msg['Subject'] = f"Daily China Briefing Results - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

        wci_text = f"WCI: {wci_value:.2f}"
        if wci_pct_change is not None:
            arrow = "↑" if wci_pct_change > 0 else "↓" if wci_pct_change < 0 else "→"
            wci_text += f" {arrow} ({wci_pct_change:.2f}% w/w)"
        wci_text += f" (Stand {wci_date})"

        scfi_text = f"SCFI: {scfi_value:.2f}"
        if scfi_percent_change is not None:
            arrow = "↑" if scfi_percent_change > 0 else "↓" if scfi_percent_change < 0 else "→"
            scfi_text += f" {arrow} ({scfi_percent_change:.2f}% w/w)"
        scfi_text += f" (Stand {scfi_date})"

        body = f"""Attached are the logs and briefing from the Daily China Briefing workflow.
Date: {datetime.now().strftime('%d %b %Y %H:%M:%S')}
{wci_text}
{scfi_text}
"""
        msg.attach(MIMEText(body, 'plain'))

        files_to_attach = ['wci_test_log.txt', 'daily_briefing.md', 'WCI/wci_cache.json', 'scfi_cache.json'] + glob.glob('wci_email_*.html')
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

    report_date = datetime.now().strftime("%d %b %Y")

    # WCI abrufen
    wci_value, wci_pct_change, wci_date, wci_warning = fetch_wci()
    if wci_warning:
        send_warning_email(wci_warning, "WCI")

    wci_text = f"• WCI: {wci_value:.2f}"
    if wci_pct_change is not None:
        arrow = "↑" if wci_pct_change > 0 else "↓" if wci_pct_change < 0 else "→"
        wci_text += f" {arrow} ({abs(wci_pct_change):.2f}%, Stand {wci_date})"
    else:
        wci_text += f" (Stand {wci_date})"

    # SCFI abrufen
    scfi_value, scfi_pct_change, scfi_date, scfi_warning = fetch_scfi()
    if scfi_warning:
        send_warning_email(scfi_warning, "SCFI")

    scfi_text = f"• SCFI: {scfi_value:.2f}"
    if scfi_pct_change is not None:
        arrow = "↑" if scfi_pct_change > 0 else "↓" if scfi_pct_change < 0 else "→"
        scfi_text += f" {arrow} ({abs(scfi_pct_change):.2f}%, Stand {scfi_date})"
    else:
        scfi_text += f" (Stand {scfi_date})"

    # CPR (Platzhalter)
    cpr_data = fetch_cpr()
    cpr_text = "• CPR: Not available"
    if cpr_data:
        cpr_text = f"• CPR: {cpr_data['index']}"
        if cpr_data.get('change'):
            cpr_text += f", {cpr_data['change']} w/w"

    # Nachrichten
    news_items = fetch_news()
    news_text = "News\n" + "-" * 20 + "\n"
    if news_items:
        for item in news_items:
            news_text += f"- {item['title']} ({item['published']}): {item['link']}\n"
    else:
        news_text += "No news available\n"

    report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
{scfi_text}
{cpr_text}
{'-' * 20}
{news_text}
"""

    logger.info("Generated briefing report")
    logger.debug(f"Report content:\n{report}")

    try:
        with open('daily_briefing.md', 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info("Saved briefing to daily_briefing.md")
    except Exception as e:
        logger.error(f"Failed to save briefing: {str(e)}")
        return "Daily China Briefing: Error saving report"

    send_results_email(wci_value, wci_date, wci_pct_change, scfi_value, scfi_date)
    return report

if __name__ == "__main__":
    logger.debug("Starting main execution")
    report = generate_briefing()
    print(report)
    logger.debug("Main execution completed")
