import email
from email.header import decode_header
import feedparser
import imaplib
import json
import os
import re
import requests
import smtplib
import time
import warnings
import logging
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import parsedate_to_datetime
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import pandas as pd
import urllib.parse  # Hinzugefügt für Nikkei-URL-Normalisierung

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

# CEST ist UTC+2
cest = timezone(timedelta(hours=2))

# Logging einrichten, nur auf Konsole, keine Dateien
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger()

# Pfad zu den Holiday JSON Dateien, CPR-Cache, Economic Calendar CSV, SCFI-Cache und Freight-Cache
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CHINA_HOLIDAY_FILE = os.path.join(BASE_DIR, "holiday_cache", "china.json")
HK_HOLIDAY_FILE = os.path.join(BASE_DIR, "holiday_cache", "hk.json")
CPR_CACHE_FILE = os.path.join(BASE_DIR, "cpr_cache.json")
ECONOMIC_CALENDAR_FILE = os.path.join(BASE_DIR, "data", "economic_calendar.csv")
SCFI_CACHE_FILE = os.path.join(BASE_DIR, "scfi_cache.json")
FREIGHT_CACHE_DIR = os.path.join(BASE_DIR, "freight_indicies")
WCI_CACHE_FILE = os.path.join(FREIGHT_CACHE_DIR, "wci_cache.json")
IACI_CACHE_FILE = os.path.join(FREIGHT_CACHE_DIR, "iaci_cache.json")

# Nikkei-Konstanten inkl Suchzeitraum 
EMAIL_NIKKEI_ASIA = "nikkeiasia-d-nl@namail.nikkei.com"
EMAIL_CHINA_UP_CLOSE = "nikkeiasia-w-nl@namail.nikkei.com"
SEARCH_DAYS = 1

def normalize_url(url):
    """Entfernt Tracking-Parameter aus der URL."""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def resolve_url(url):
    """Löst die ursprüngliche URL zu einer asia.nikkei.com-URL auf."""
    try:
        response = requests.get(url, allow_redirects=True, timeout=5)
        final_url = response.url
        if "asia.nikkei.com" in final_url:
            return final_url
        return None
    except Exception:
        return None

def score_nikkei_article(title):
    """Bewertet einen Artikel auf China-Relevanz."""
    logger.info(f"Bewerte Nikkei-Artikel: {title}")
    score = 0
    china_keywords = ["china", "chinese", "hong kong", "taiwan", "xi jinping", "beijing", "shanghai", "byd", "battery", "ev"]
    japan_keywords = ["japan", "japanese", "tokyo"]
    has_china = any(keyword in title.lower() for keyword in china_keywords)
    has_japan = any(keyword in title.lower() for keyword in japan_keywords)
    
    if has_china:
        score += 5
    if has_japan:
        score -= 3
    if not has_china and not has_japan:
        score -= 1
    logger.info(f"Score für Nikkei-Artikel '{title}': {score}, has_china={has_china}, has_japan={has_japan}")
    return score

def score_china_up_close_article(title):
    """Bewertet einen China Up Close-Artikel."""
    logger.info(f"Bewerte China Up Close-Artikel: {title}")
    score = 0
    is_china = any(keyword in title.lower() for keyword in ["china", "chinese", "hong kong", "taiwan", "xi jinping"])
    is_important = any(keyword in title.lower() for keyword in ["xi jinping", "politburo", "policy"])
    is_indepth = any(keyword in title.lower() for keyword in ["analysis", "in depth", "cover"])
    is_nonchina = any(keyword in title.lower() for keyword in ["japan", "india", "us", "europe"])
    is_footer = any(keyword in title.lower() for keyword in ["subscribe", "newsletter", "app"])
    
    if is_china:
        score += 5
    if is_important:
        score += 3
    if is_indepth:
        score += 3
    if is_nonchina:
        score -= 2
    if is_footer:
        score -= 5
    logger.info(f"Score für China Up Close-Artikel '{title}': {score}, is_china={is_china}, is_important={is_important}, is_indepth={is_indepth}, is_nonchina={is_nonchina}, is_footer={is_footer}")
    return score

def fetch_combined_china_articles():
    """Holt und kombiniert China-relevante Artikel aus Nikkei Asia und China Up Close."""
    logger.info("Starte fetch_combined_china_articles")
    try:
        substack_mail = os.getenv("SUBSTACK_MAIL")
        logger.info(f"SUBSTACK_MAIL-Umgebungsvariable: {'Gefunden' if substack_mail else 'Nicht gefunden'}")
        if not substack_mail:
            logger.error("SUBSTACK_MAIL environment variable not found")
            send_warning_email(
                "Fehler beim Abrufen der Nikkei-Artikel",
                "SUBSTACK_MAIL Umgebungsvariable nicht gefunden"
            )
            return []

        mail_pairs = substack_mail.split(";")
        mail_config = {}
        for pair in mail_pairs:
            if "=" in pair:
                key, value = pair.split("=", 1)
                mail_config[key] = value
        logger.info(f"SUBSTACK_MAIL-Schlüssel: {list(mail_config.keys())}")
        if "GMAIL_USER" not in mail_config or "GMAIL_PASS" not in mail_config:
            logger.error(f"Fehlende Schlüssel in SUBSTACK_MAIL: {', '.join([k for k in ['GMAIL_USER', 'GMAIL_PASS'] if k not in mail_config])}")
            send_warning_email(
                "Fehler beim Abrufen der Nikkei-Artikel",
                f"Fehlende Schlüssel in SUBSTACK_MAIL: {', '.join([k for k in ['GMAIL_USER', 'GMAIL_PASS'] if k not in mail_config])}"
            )
            return []

        email_user = mail_config["GMAIL_USER"]
        email_password = mail_config["GMAIL_PASS"]
        logger.info(f"Versuche IMAP-Login mit Benutzer: {email_user}")

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_user, email_password)
        logger.info("IMAP-Login erfolgreich")
        mail.select("inbox")
        
        articles = []
        seen_urls = set()
        since_date = (datetime.now(timezone.utc) - timedelta(days=SEARCH_DAYS)).strftime("%d-%b-%Y")
        logger.info(f"Suche nach E-Mails seit: {since_date}")
        
        for email_address in [EMAIL_NIKKEI_ASIA, EMAIL_CHINA_UP_CLOSE]:
            logger.info(f"Suche nach E-Mails von: {email_address}")
            result, data = mail.search(None, f'FROM "{email_address}" SINCE {since_date}')
            logger.info(f"Suchergebnis für {email_address}: {result}, Anzahl E-Mails: {len(data[0].split())}")
            if result != "OK":
                send_warning_email(
                    "Fehler beim Abrufen der Nikkei-E-Mails",
                    f"Fehler beim Suchen nach E-Mails von {email_address}: {result}"
                )
                continue
                
            email_ids = data[0].split()
            for email_id in email_ids[-5:]:
                logger.info(f"Verarbeite E-Mail ID: {email_id}")
                result, msg_data = mail.fetch(email_id, "(RFC822)")
                if result != "OK":
                    logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}")
                    continue
                    
                msg = email.message_from_bytes(msg_data[0][1])
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        charset = part.get_content_charset() or 'utf-8'
                        try:
                            html_content = part.get_payload(decode=True).decode(charset)
                        except UnicodeDecodeError:
                            html_content = part.get_payload(decode=True).decode('windows-1252', errors='replace')
                        soup = BeautifulSoup(html_content, "lxml")
                        links = soup.find_all("a", href=True)
                        logger.info(f"Anzahl gefundener Links: {len(links)}")
                        
                        for link in links:
                            href = link.get("href")
                            title = link.get_text(strip=True)
                            logger.info(f"Verarbeite Link: {title} (href: {href})")
                            if not title or len(title) < 10 or "read more" in title.lower() or "subscribe" in title.lower():
                                logger.info(f"Link übersprungen: Titel zu kurz oder unerwünscht")
                                continue
                            if email_address == EMAIL_CHINA_UP_CLOSE and (
                                "This week's China Up Close focuses on" in title or "Read Katsuji Nakazawa's analysis here" in title
                            ):
                                logger.info(f"Link übersprungen: Unerwünschter China Up Close Text")
                                continue
                            final_url = resolve_url(href)
                            if not final_url or "asia.nikkei.com" not in final_url:
                                logger.info(f"Link übersprungen: Keine gültige asia.nikkei.com URL")
                                continue
                            normalized_url = normalize_url(final_url)
                            if normalized_url in seen_urls:
                                logger.info(f"Link übersprungen: URL bereits gesehen")
                                continue
                            score = (
                                score_china_up_close_article(title)
                                if email_address == EMAIL_CHINA_UP_CLOSE
                                else score_nikkei_article(title)
                            )
                            if score > 0:
                                logger.info(f"Artikel hinzugefügt: {title} (URL: {final_url}, Score: {score})")
                                articles.append((score, f"• <a href=\"{final_url}\">{title}</a>"))
                                seen_urls.add(normalized_url)
        
        mail.logout()
        logger.info("IMAP-Logout erfolgreich")
        
        logger.info(f"Gesamtanzahl gefundener Artikel: {len(articles)}")
        articles.sort(reverse=True)
        unique_articles = []
        seen_urls.clear()  # Reset für die finale Auswahl
        for score, article in articles:
            url = article.split('href="')[1].split('">')[0]
            if url not in seen_urls:
                unique_articles.append(article)
                seen_urls.add(url)
                
        logger.info(f"Anzahl eindeutiger Artikel: {len(unique_articles)}")
        return unique_articles[:5]
    except Exception as e:
        logger.error(f"Fehler in fetch_combined_china_articles: {str(e)}")
        send_warning_email(
            "Fehler beim Abrufen der Nikkei-Artikel",
            f"Fehler in fetch_combined_china_articles: {str(e)}"
        )
        return []
        
def load_wci_cache():
    """Lädt den WCI-Cache oder initialisiert ihn als leer, wenn nicht vorhanden."""
    try:
        os.makedirs(FREIGHT_CACHE_DIR, exist_ok=True)
        if os.path.exists(WCI_CACHE_FILE):
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.info("Successfully loaded WCI cache")
                # Konvertiere Schlüssel und entferne redundante 'date'-Felder
                cleaned_cache = {}
                for date_str, data in cache.items():
                    new_date_str = convert_date_format(date_str)
                    cleaned_data = {"value": data["value"]}
                    cleaned_cache[new_date_str] = cleaned_data
                if cleaned_cache != cache:
                    save_wci_cache(cleaned_cache)
                    logger.info("Converted WCI cache dates to DD.MM.YYYY and removed redundant 'date' fields")
                return cleaned_cache
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
                # Konvertiere Schlüssel zu DD.MM.YYYY
                cleaned_cache = {}
                for date_str, data in cache.items():
                    new_date_str = convert_date_format(date_str)
                    cleaned_cache[new_date_str] = data
                if cleaned_cache != cache:
                    save_iaci_cache(cleaned_cache)
                    logger.info("Converted IACI cache dates to DD.MM.YYYY")
                return cleaned_cache
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
        with open(IACI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        if os.path.exists(IACI_CACHE_FILE):
            logger.info(f"Successfully wrote IACI cache to {IACI_CACHE_FILE}")
        else:
            logger.error(f"IACI cache file {IACI_CACHE_FILE} was not created")
            raise Exception(f"IACI cache file {IACI_CACHE_FILE} was not created")
    except Exception as e:
        logger.error(f"Failed to save IACI cache: {str(e)}")
        raise

def convert_date_format(date_str):
    """Konvertiert ein Datum in das Format DD.MM.YYYY."""
    try:
        if '-' in date_str:
            return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d.%m.%Y')
        return date_str
    except ValueError:
        logger.error(f"Could not convert date format for {date_str}, keeping original")
        return date_str

def fetch_wci_email():
    """Holt die neueste Drewry WCI-E-Mail aus den letzten 14 Tagen und gibt den HTML-Inhalt zurück."""
    try:
        env_vars = os.getenv('SUBSTACK_MAIL')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            raise Exception("SUBSTACK_MAIL not set")

        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=', 1)
            if key.strip() == 'GMAIL_USER':
                gmail_user = value.strip()
            elif key.strip() == 'GMAIL_PASS':
                gmail_pass = value.strip()

        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in SUBSTACK_MAIL")
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
            logger.error("No IACI emails from noreply@drewry.co.uk in the last 14 days")
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

def parse_date(date_str):
    """Versucht, ein Datum in verschiedenen Formaten zu parsen."""
    formats = ["%d.%m.%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            logger.info(f"Parsed date {date_str} with format {fmt}")
            return parsed
        except ValueError:
            continue
    raise ValueError(f"Could not parse date: {date_str}")

def calculate_percentage_change(current_value, previous_value):
    """Berechnet die prozentuale Veränderung zwischen zwei Werten, gerundet auf ganze Zahlen."""
    if previous_value is None or previous_value == 0:
        return None
    change = ((current_value - previous_value) / previous_value) * 100
    return round(change)

def send_warning_email(subject, body):
    """Sendet eine Warn-E-Mail bei Problemen."""
    try:
        env_vars = os.getenv("CONFIG")
        if not env_vars:
            logger.error("CONFIG environment variable not found")
            raise Exception("Missing CONFIG")

        pairs = env_vars.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(
            f"Details: {body}\nDate: {datetime.now(cest).strftime('%Y-%m-%d')}",
            "plain",
            "utf-8"
        )
        msg["Subject"] = subject
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = "hadobrockmeyer@gmail.com"

        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        logger.info("Warning email sent successfully")
    except Exception as e:
        logger.error(f"Failed to send warning email: {str(e)}")
        
def generate_briefing_freight():
    logger.info("Starting briefing generation")
    report_date = datetime.now(cest).strftime("%d %b %Y")
    wci_cache = load_wci_cache()
    iaci_cache = load_iaci_cache()
    today = datetime.now(cest)
    # WCI-Verarbeitung
    wci_html_content, wci_subject = fetch_wci_email()
    wci_value = None
    wci_date = None
    if wci_html_content:
        wci_value, wci_date = extract_wci_from_html(wci_html_content, wci_subject)

    # Neueste Cache-Datum für WCI ermitteln
    latest_wci_cache_date = max(
        wci_cache.keys(),
        default=None,
        key=lambda d: parse_date(d)
    ) if wci_cache else None

    # Prüfen, ob die E-Mail neuer ist als der Cache
    if wci_value and wci_date:
        if latest_wci_cache_date:
            email_date = parse_date(wci_date)
            latest_cache_date = parse_date(latest_wci_cache_date)
            if email_date > latest_cache_date:
                wci_cache[wci_date] = {"value": wci_value}
                save_wci_cache(wci_cache)
                wci_cache = load_wci_cache()  # Cache neu laden
                logger.info(f"New WCI value {wci_value:.2f} for {wci_date} saved to cache")
            else:
                logger.info(f"WCI email date {wci_date} is not newer than latest cache date {latest_wci_cache_date}, skipping save")
        else:
            wci_cache[wci_date] = {"value": wci_value}
            save_wci_cache(wci_cache)
            wci_cache = load_wci_cache()  # Cache neu laden
            logger.info(f"No previous WCI cache, saved new value {wci_value:.2f} for {wci_date}")


    # Neueste Werte aus Cache für WCI verwenden
    if latest_wci_cache_date:
        wci_value = wci_cache[latest_wci_cache_date]["value"]
        wci_date = latest_wci_cache_date
        logger.info(f"Using latest WCI cache value {wci_value:.2f} (Date: {wci_date})")
    else:
        wci_value = 0.0
        wci_date = today.strftime("%d.%m.%Y")
        warning_message = "WCI: No email found in the last 14 days, no cache available"
        send_warning_email(warning_message)
        logger.info(f"Sent warning email: {warning_message}")

    # IACI-Verarbeitung
    iaci_html_content, iaci_subject = fetch_iaci_email()
    iaci_value = None
    iaci_date = None
    if iaci_html_content:
        iaci_value, iaci_date = extract_iaci_from_html(iaci_html_content, iaci_subject)

    # Neueste Cache-Datum für IACI ermitteln
    latest_iaci_cache_date = max(
        iaci_cache.keys(),
        default=None,
        key=lambda d: parse_date(d)
    ) if iaci_cache else None

    # Prüfen, ob die E-Mail neuer ist als der Cache
    if iaci_value and iaci_date:
        if latest_iaci_cache_date:
            email_date = parse_date(iaci_date)
            latest_cache_date = parse_date(latest_iaci_cache_date)
            if email_date > latest_cache_date:
                iaci_cache[iaci_date] = {"value": iaci_value}
                save_iaci_cache(iaci_cache)
                logger.info(f"New IACI value {iaci_value:.2f} for {iaci_date} saved to cache")
            else:
                logger.info(f"IACI email date {iaci_date} is not newer than latest cache date {latest_iaci_cache_date}, skipping save")
        else:
            iaci_cache[iaci_date] = {"value": iaci_value}
            save_iaci_cache(iaci_cache)
            logger.info(f"No previous IACI cache, saved new value {iaci_value:.2f} for {iaci_date}")

    # Neueste Werte aus Cache für IACI verwenden
    if latest_iaci_cache_date:
        iaci_value = iaci_cache[latest_iaci_cache_date]["value"]
        iaci_date = latest_iaci_cache_date
        logger.info(f"Using latest IACI cache value {iaci_value:.2f} (Date: {iaci_date})")
    else:
        iaci_value = 0.0
        iaci_date = today.strftime("%d.%m.%Y")
        warning_message = "IACI: No email found in the last 14 days, no cache available"
        send_warning_email(warning_message)
        logger.info(f"Sent warning email: {warning_message}")

    # Prozentuale Veränderung für WCI
    wci_previous_value = None
    sorted_wci_dates = sorted(
        [d for d in wci_cache.keys() if d != latest_wci_cache_date],
        key=lambda d: parse_date(d)
    )
    if sorted_wci_dates:
        wci_previous_value = wci_cache[sorted_wci_dates[-1]]["value"]
        logger.info(f"WCI previous value: {wci_previous_value} for date {sorted_wci_dates[-1]}")
    wci_percentage_change = calculate_percentage_change(wci_value, wci_previous_value)

    # Prozentuale Veränderung für IACI
    iaci_previous_value = None
    sorted_iaci_dates = sorted(
        [d for d in iaci_cache.keys() if d != latest_iaci_cache_date],
        key=lambda d: parse_date(d)
    )
    if sorted_iaci_dates:
        iaci_previous_value = iaci_cache[sorted_iaci_dates[-1]]["value"]
        logger.info(f"IACI previous value: {iaci_previous_value} for date {sorted_iaci_dates[-1]}")
    iaci_percentage_change = calculate_percentage_change(iaci_value, iaci_previous_value)
    logger.info(f"IACI percentage change: {iaci_percentage_change}")

    # Bericht generieren mit Markdown-Links, ohne $ im Wert
    wci_arrow = "↓" if wci_percentage_change and wci_percentage_change < 0 else "↑" if wci_percentage_change else ""
    wci_change_text = f" ({wci_arrow} {wci_percentage_change}%)" if wci_percentage_change is not None else ""
    wci_text = f"• <a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry'>WCI</a>: {wci_value:.2f}{wci_change_text} (Stand {wci_date})"

    iaci_arrow = "↓" if iaci_percentage_change and iaci_percentage_change < 0 else "↑" if iaci_percentage_change else ""
    iaci_change_text = f" ({iaci_arrow} {iaci_percentage_change}%)" if iaci_percentage_change is not None else ""
    iaci_text = f"• <a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/intra-asia-container-index'>IACI</a>: {iaci_value:.2f}{iaci_change_text} (Stand {iaci_date})"

    report = f"""Daily China Briefing - {report_date}
{'=' * 50}
## 🚢 Frachtraten Indizies
{wci_text}
{iaci_text}
"""
    logger.info(f"Report content:\n{report}")
    with open('daily_briefing.md', 'w', encoding='utf-8') as f:
        f.write(report)
    logger.info("Saved briefing to daily_briefing.md")
    return wci_text, iaci_text
    
 # Feiertage
def load_holidays(filepath):
    print(f"DEBUG - load_holidays: Loading holidays from {filepath}")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            holidays = set(item["date"] for item in data.get("holidays", []))
            print(f"DEBUG - load_holidays: Loaded {len(holidays)} holidays")
            return holidays
    except Exception as e:
        print(f"ERROR - load_holidays: Failed to load holidays from {filepath}: {str(e)}")
        return set()  # Fallback: Leere Liste, um fortzufahren

def is_holiday(today_str, holidays_set):
    return today_str in holidays_set

def is_weekend():
    return date.today().weekday() >= 5

# CPR-Cache laden
def load_cpr_cache():
    print(f"DEBUG - load_cpr_cache: Starting to load cache from {CPR_CACHE_FILE}")
    try:
        if os.path.exists(CPR_CACHE_FILE):
            with open(CPR_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                print(f"DEBUG - load_cpr_cache: Successfully loaded cache: {cache}")
                return cache
        else:
            print(f"DEBUG - load_cpr_cache: No cache file found at {CPR_CACHE_FILE}")
            return {}
    except Exception as e:
        print(f"ERROR - load_cpr_cache: {e}")
        return {}

# CPR-Cache speichern
def save_cpr_cache(cache):
    print(f"DEBUG - save_cpr_cache: Starting to save cache to {CPR_CACHE_FILE}")
    print(f"DEBUG - save_cpr_cache: Cache content: {cache}")
    try:
        os.makedirs(os.path.dirname(CPR_CACHE_FILE), exist_ok=True)
        with open(CPR_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print(f"DEBUG - save_cpr_cache: Successfully wrote cache to {CPR_CACHE_FILE}")
        with open(CPR_CACHE_FILE, "r", encoding="utf-8") as f:
            saved_cache = json.load(f)
            print(f"DEBUG - save_cpr_cache: Verified cache content: {saved_cache}")
    except Exception as e:
        print(f"ERROR - save_cpr_cache: Failed to save cache to {CPR_CACHE_FILE}: {str(e)}")
        raise

# SCFI-Cache laden
def load_scfi_cache():
    print(f"DEBUG - load_scfi_cache: Starting to load cache from {SCFI_CACHE_FILE}")
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        os.makedirs(os.path.dirname(SCFI_CACHE_FILE), exist_ok=True)
        if os.path.exists(SCFI_CACHE_FILE):
            with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                for key, value in cache.items():
                    if isinstance(value, (int, float)):
                        cache[key] = {"value": float(value), "api_date": key}
                print(f"DEBUG - load_scfi_cache: Successfully loaded cache: {cache}")
                return cache
        else:
            print(f"DEBUG - load_scfi_cache: No cache file found at {SCFI_CACHE_FILE}")
            return {}
    except Exception as e:
        print(f"ERROR - load_scfi_cache: Failed to load cache: {str(e)}")
        return {}

# SCFI-Cache speichern
def save_scfi_cache(cache):
    print(f"DEBUG - save_scfi_cache: Starting to save cache to {SCFI_CACHE_FILE}")
    print(f"DEBUG - save_scfi_cache: Cache content: {cache}")
    try:
        # Stelle sicher, dass das Verzeichnis existiert
        os.makedirs(os.path.dirname(SCFI_CACHE_FILE), exist_ok=True)
        with open(SCFI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print(f"DEBUG - save_scfi_cache: Successfully wrote cache to {SCFI_CACHE_FILE}")
        with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
            saved_cache = json.load(f)
            print(f"DEBUG - save_scfi_cache: Verified cache content: {saved_cache}")
    except Exception as e:
        print(f"ERROR - save_scfi_cache: Failed to save cache: {str(e)}")
        raise

# SCFI-Daten abrufen
def fetch_scfi():
    print("DEBUG - fetch_scfi: Starting to fetch SCFI data")
    url = "https://en.sse.net.cn/currentIndex?indexName=scfi"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    today_str = date.today().isoformat()
    cache = load_scfi_cache()

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == 0:
            print(f"ERROR - fetch_scfi: API error: {data.get('msg')}")
            raise Exception(data.get("msg"))

        scfi_data = data.get("data", {})
        current_date = scfi_data.get("currentDate")
        line_data_list = scfi_data.get("lineDataList", [])

        if not line_data_list:
            print("ERROR - fetch_scfi: No lineDataList found in API response")
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
            print(f"DEBUG - fetch_scfi: Could not parse date '{current_date}', using today")
            scfi_date = date.today().strftime("%d.%m.%Y")

        print(f"DEBUG - fetch_scfi: SCFI-Wert {scfi_value:.2f} per API ausgelesen (Datum: {scfi_date})")

        pct_change = None
        if last_value is not None:
            pct_change = ((scfi_value - last_value) / last_value) * 100 if last_value != 0 else 0
            print(f"DEBUG - fetch_scfi: Calculated percent change: {pct_change:.2f}% (Current: {scfi_value}, Previous: {last_value})")

        latest_cache_date = max(cache.keys(), default=None)
        should_save = True
        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            if latest_entry["value"] == scfi_value and latest_entry["api_date"] == current_date:
                should_save = False
                print("DEBUG - fetch_scfi: Kein Cache-Update nötig (Wert und Datum unverändert)")

        if should_save:
            cache[today_str] = {"value": scfi_value, "api_date": current_date}
            save_scfi_cache(cache)

        return scfi_value, pct_change, scfi_date, None

    except Exception as e:
        print(f"ERROR - fetch_scfi: Failed to fetch SCFI data: {str(e)}")
        warning_message = None
        latest_cache_date = max(cache.keys(), default=None)
        ten_days_ago = (date.today() - timedelta(days=10)).isoformat()

        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            scfi_value = latest_entry["value"]
            api_date_str = latest_entry["api_date"]
            scfi_date = None

            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
                try:
                    scfi_date = datetime.strptime(api_date_str, fmt).strftime("%d.%m.%Y")
                    break
                except ValueError:
                    continue
            if scfi_date is None:
                scfi_date = date.today().strftime("%d.%m.%Y")

            try:
                api_date = datetime.strptime(api_date_str, "%Y-%m-%d")
                if api_date >= datetime.strptime(ten_days_ago, "%Y-%m-%d"):
                    print(f"DEBUG - fetch_scfi: SCFI-Wert {scfi_value:.2f} aus Cache verwendet (Datum: {scfi_date})")
                    warning_message = f"API nicht erreichbar, Cache-Wert {scfi_value} (Datum: {api_date_str}) genutzt"
                    return scfi_value, None, scfi_date, warning_message
                else:
                    warning_message = f"API nicht erreichbar, Cache-Wert {scfi_value} zu alt (Datum: {api_date_str})"
            except ValueError:
                warning_message = f"API nicht erreichbar, Cache-Datum ungültig (Datum: {api_date_str})"

        scfi_value = 1869.59
        scfi_date = date.today().strftime("%d.%m.%Y")
        warning_message = warning_message or "API ausgefallen, kein Cache verfügbar, Fallback 1869.59 genutzt"
        print(f"DEBUG - fetch_scfi: SCFI-Wert {scfi_value:.2f} als Fallback verwendet (Datum: {scfi_date})")
        return scfi_value, None, scfi_date, warning_message

# SCFI-Warn-E-Mail senden
def send_warning_email(warning_message):
    print("DEBUG - send_warning_email: Preparing to send SCFI warning email")
    try:
        config = os.getenv("CONFIG")
        if not config:
            print("ERROR - send_warning_email: CONFIG environment variable not found")
            raise Exception("Missing CONFIG")

        pairs = config.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(
            f"Problem: API-Ausfall oder veralteter Cache\nDetails: {warning_message}\nDatum: {date.today().strftime('%Y-%m-%d')}",
            "plain",
            "utf-8"
        )
        msg["Subject"] = "China-Briefing SCFI API-Warnung"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = "hadobrockmeyer@gmail.com"

        print("DEBUG - send_warning_email: Connecting to SMTP server")
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        print("DEBUG - send_warning_email: Warning email sent successfully")
    except Exception as e:
        print(f"ERROR - send_warning_email: Failed to send warning email: {str(e)}")
        raise

# Werte vorladen (global)
today_str = date.today().isoformat()
china_holidays = load_holidays(CHINA_HOLIDAY_FILE)
hk_holidays = load_holidays(HK_HOLIDAY_FILE)
is_holiday_china = is_holiday(today_str, china_holidays)
is_holiday_hk = is_holiday(today_str, hk_holidays)
is_weekend_day = is_weekend()

# === Wirtschaftskalendar ===
def fetch_economic_calendar():
    print("DEBUG - fetch_economic_calendar: Starting to fetch economic calendar")
    try:
        if not os.path.exists(ECONOMIC_CALENDAR_FILE):
            print(f"ERROR - fetch_economic_calendar: File {ECONOMIC_CALENDAR_FILE} not found")
            return ["### 📅 Was wichtig wird:", "", "❌ No calendar data available (file not found)."]

        df = pd.read_csv(ECONOMIC_CALENDAR_FILE, encoding="utf-8")
        print(f"DEBUG - fetch_economic_calendar: Loaded {len(df)} events from CSV")

        required_columns = ["Date", "Event", "Organisation", "Priority"]
        if not all(col in df.columns for col in required_columns):
            missing = [col for col in required_columns if col not in df.columns]
            print(f"ERROR - fetch_economic_calendar: Missing columns: {missing}")
            return ["### 📅 Was wichtig wird:", "", "❌ Invalid calendar data (missing columns)."]

        try:
            df["Date"] = pd.to_datetime(df["Date"], format="%d/%m/%Y")
        except Exception as e:
            print(f"ERROR - fetch_economic_calendar: Date parsing failed: {str(e)}")
            return ["### 📅 Was wichtig wird:", "", "❌ Invalid date format."]

        today = datetime.now().date()
        end_date = today + timedelta(days=7)
        df = df[(df["Date"].dt.date >= today) & (df["Date"].dt.date <= end_date)]

        if df.empty:
            print("DEBUG - fetch_economic_calendar: No events in next 7 days, skipping output")
            return ["### 📅 Was wichtig wird:", ""]

        # Priorität sortieren
        priority_order = {"High": 1, "Medium": 2, "Low": 3}
        df["PriorityOrder"] = df["Priority"].map(priority_order).fillna(4)
        df = df.sort_values(by=["Date", "PriorityOrder"])
        df = df.drop(columns=["PriorityOrder"])

        # Deutsche Wochentage
        de_weekdays = {0: "Mo", 1: "Di", 2: "Mi", 3: "Do", 4: "Fr", 5: "Sa", 6: "So"}

        markdown = ["### 📅 Was wichtig wird:", ""]

        # Rendering-Option: "bold" für ** (Buttondown), "arrow" für ➡️ (Testumgebung), "html" für <b>
        highlight_style = "bold"  # Ändere zu "arrow" für Testumgebung oder "html" für <b>

        grouped = df.groupby(df["Date"])
        for date_obj, group in grouped:
            date_str = date_obj.strftime("%d/%m")
            weekday = de_weekdays[date_obj.weekday()]  # Deutsche Abkürzung
            date_text = f"{weekday} {date_str}"
            # Hervorhebung
            if highlight_style == "bold":
                date_line = f"**{date_text}**"
            elif highlight_style == "html":
                date_line = f"<b>{date_text}</b>"
            else:  # arrow
                date_line = f"➡️ {date_text}" if date_obj.date() == today else date_text
            if date_obj.date() == today:
                date_line += " (heute)"
            markdown.append(date_line)
            for _, row in group.iterrows():
                event = str(row['Event'])
                org = str(row['Organisation'])
                prio = str(row['Priority'])
                line = f"- {event} ({org}, {prio})"
                markdown.append(line)
            markdown.append("")  # Leerzeile nach jedem Datum

        print(f"DEBUG - fetch_economic_calendar: Generated {len(markdown)-2} lines")
        return markdown

    except Exception as e:
        print(f"ERROR - fetch_economic_calendar: Unexpected error: {str(e)}")
        return ["### 📅 Was wichtig wird:", "", "❌ Error fetching calendar data."]

# === 🔐 Konfiguration aus ENV-Variable ===
config = os.getenv("CONFIG")
if not config:
    raise ValueError("CONFIG environment variable not found!")
pairs = config.split(";")
config_dict = dict(pair.split("=", 1) for pair in pairs)

# === Google Mapping ===
source_categories = {
    "Wall Street Journal": "EN",
    "Financial Times": "EN",
    "Reuters": "EN",
    "The Guardian": "EN",
    "New York Times": "EN",
    "Bloomberg": "EN",
    "Politico": "EN",
    "FAZ": "DE",
    "Welt": "DE",
    "Tagesspiegel": "DE",
    "NZZ": "DE",
    "Finanzmarktwelt": "DE",
    "Der Standard": "DE",
    "Frankfurter Rundschau": "DE",
    "Le Monde": "FR",
    "Les Echos": "FR",
    "Le Figaro": "FR",
    "SCMP": "ASIA",
    "Nikkei Asia": "ASIA",
    "Yicai": "ASIA"
}

# === Google-News: Feed-Definition ===
feeds_google_news = {
    "EN": "https://news.google.com/rss/search?q=china+when:1d&hl=en&gl=US&ceid=US:en",
    "DE": "https://news.google.com/rss/search?q=china+when:1d&hl=de&gl=DE&ceid=DE:de",
    "FR": "https://news.google.com/rss/search?q=china+when:1d&hl=fr&gl=FR&ceid=FR:fr"
}

# === Think Tanks & Institute ===
feeds_thinktanks = {
    "MERICS": "https://merics.org/en/rss.xml",
    "CSIS": "https://www.csis.org/rss.xml",
    "CREA (Energy & Clean Air)": "https://energyandcleanair.org/feed/",
    "Brookings": "https://www.brookings.edu/feed/",
    "Peterson Institute": "https://www.piie.com/rss/all",
    "CFR – Council on Foreign Relations": "https://www.cfr.org/rss.xml",
    "RAND Corporation": "https://www.rand.org/rss.xml",
    "Chatham House": "https://www.chathamhouse.org/rss.xml",
    "Lowy Institute": "https://www.lowyinstitute.org/the-interpreter/rss.xml"
}

# === Google News China Top-Stories ===
feeds_topchina = {
    "Google News – China": "https://news.google.com/rss/search?q=china+when:1d&hl=en&gl=US&ceid=US:en"
}

# === SCMP & Yicai ===
feeds_scmp_yicai = {
    "SCMP": "https://www.scmp.com/rss/91/feed",
    "Yicai Global": "https://www.yicaiglobal.com/rss/news"
}

# === China-Filter & Score-Funktionen ===
def score_article(title, summary=""):
    title = title.lower()
    summary = summary.lower()
    content = f"{title} {summary}"
    must_have_in_title = [
        "china", "chinese", "xi", "beijing", "shanghai", "hong kong", "taiwan", "prc",
        "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang", "brics",
        "belt and road", "macau", "pla"
    ]
    if not any(kw in title for kw in must_have_in_title):
        return 0
    important_keywords = [
        "gdp", "exports", "imports", "tariffs", "real estate", "economy", "policy", "ai",
        "semiconductors", "pmi", "cpi", "housing", "foreign direct investment", "tech",
        "military", "sanctions", "trade", "data", "manufacturing", "industrial"
    ]
    positive_modifiers = [
        "analysis", "explainer", "comment", "feature", "official", "report", "statement"
    ]
    negative_keywords = [
        "celebrity", "gossip", "dog", "baby", "fashion", "movie", "series", "bizarre",
        "dating", "weird", "quiz", "elon musk", "rapid", "lask", "bundesliga", "eurovision",
        "basketball", "nba", "mlb", "nfl", "liberty", "yankees", "tournament", "playoffs",
        "finale", "score", "blowout"
    ]
    score = 1
    for word in important_keywords:
        if word in content:
            score += 2
    for word in positive_modifiers:
        if word in content:
            score += 1
    for word in negative_keywords:
        if word in content:
            score -= 3
    return score

# === News-Artikel filtern & bewerten ===
def fetch_news(feed_url, max_items=20, top_n=5):
    feed = feedparser.parse(feed_url)
    scored = []
    for entry in feed.entries[:max_items]:
        title = entry.get("title", "")
        summary = entry.get("summary", "")
        link = entry.get("link", "")
        score = score_article(title, summary)
        if score > 0:
            scored.append((score, f'• <a href="{link.strip()}">{title.strip()}</a>'))
    scored.sort(reverse=True, key=lambda x: x[0])
    return [item[1] for item in scored[:top_n]] or ["Keine aktuellen China-Artikel gefunden."]

# === SCMP & Yicai Ranking-Wrapper ===
def fetch_ranked_articles(feed_url, max_items=20, top_n=5):
    return fetch_news(feed_url, max_items=max_items, top_n=top_n)

# === Extract_source (für Google News) ===
def extract_source(title):
    for source in source_categories:
        if f"– {source}" in title or f"- {source}" in title or title.lower().endswith(source.lower()):
            return source
    return "Unknown Source"

# === Substack aus E-Mails abrufen ===
def fetch_substack_from_email(email_user, email_password, folder="INBOX", max_results_per_sender=5):
    print(f"DEBUG - fetch_substack_from_email: Starting to fetch Substack emails")
    posts = []
    try:
        print(f"DEBUG - fetch_substack_from_email: Current working directory: {os.getcwd()}")
        print(f"DEBUG - fetch_substack_from_email: Does substacks.json exist?: {os.path.exists('substacks.json')}")
        with open("substacks.json", "r") as f:
            substack_senders = json.load(f)
        substack_senders = sorted(substack_senders, key=lambda x: x["order"])
        email_counts = defaultdict(int)
        for sender in substack_senders:
            email_counts[sender.get("email")] += 1
        duplicates = [email for email, count in email_counts.items() if count > 1 and email]
        if duplicates:
            print(f"⚠️ Warning: Duplicate email addresses in substacks.json: {duplicates}")
    except FileNotFoundError:
        print("❌ ERROR: substacks.json not found! Using empty list.")
        substack_senders = []
        posts.append(("Allgemein", "❌ Fehler: substacks.json nicht gefunden.", "#", "", 999))
    except json.JSONDecodeError:
        print("❌ ERROR: substacks.json invalid!")
        substack_senders = []
        posts.append(("Allgemein", "❌ Fehler: substacks.json ungültig.", "#", "", 999))
    
    for attempt in range(3):
        try:
            imap = imaplib.IMAP4_SSL("imap.gmail.com")
            imap.login(email_user, email_password)
            imap.select(folder)
            break
        except Exception as e:
            print(f"❌ ERROR: Gmail connection failed (Attempt {attempt+1}/3): {str(e)}")
            if attempt == 2:
                return [("Allgemein", f"❌ Fehler beim Verbinden mit Gmail nach 3 Versuchen: {str(e)}", "#", "", 999)]
            time.sleep(2)
    
    try:
        since_date = (datetime.now() - timedelta(days=2)).strftime("%d-%b-%Y")
        for sender in substack_senders:
            sender_email = sender.get("email")
            sender_name = sender.get("name")
            sender_order = sender.get("order", 999)
            if not sender_email:
                print(f"❌ ERROR: Keine E-Mail-Adresse für {sender_name} angegeben.")
                continue
            try:
                search_query = f'(FROM "{sender_email}" SINCE {since_date})'
                print(f"DEBUG - fetch_substack_from_email: Searching for: {search_query}")
                typ, data = imap.search(None, search_query)
                if typ != "OK":
                    print(f"DEBUG - fetch_substack_from_email: IMAP search error for {sender_name} ({sender_email}): {data}")
                    continue
                email_ids = data[0].split()[-max_results_per_sender:]
                print(f"DEBUG - fetch_substack_from_email: Found email IDs for {sender_name}: {email_ids}")
                if not email_ids:
                    print(f"DEBUG - fetch_substack_from_email: No emails found for {sender_name} in the last 2 days.")
                    continue
                sender_posts = []
                for eid in email_ids:
                    typ, msg_data = imap.fetch(eid, "(RFC822)")
                    if typ != "OK":
                        print(f"DEBUG - fetch_substack_from_email: Error fetching mail {eid} for {sender_name}.")
                        continue
                    msg = email.message_from_bytes(msg_data[0][1])
                    date_str = msg["Date"]
                    mail_date = None
                    if date_str:
                        try:
                            mail_date = parsedate_to_datetime(date_str)
                            print(f"DEBUG - fetch_substack_from_email: Date for mail {eid} from {sender_name}: {mail_date}")
                        except (TypeError, ValueError) as e:
                            print(f"DEBUG - fetch_substack_from_email: Invalid date in mail {eid} from {sender_name}: {date_str}, Error: {str(e)}")
                    html = None
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/html":
                                html = part.get_payload(decode=True).decode(errors="ignore")
                                break
                    elif msg.get_content_type() == "text/html":
                        html = msg.get_payload(decode=True).decode(errors="ignore")
                    if not html:
                        print(f"DEBUG - fetch_substack_from_email: No HTML content in mail {eid} from {sender_name}.")
                        continue
                    soup = BeautifulSoup(html, "lxml")
                    title_tag = (soup.find("h1") or 
                                soup.find("h2") or 
                                soup.find("h3") or 
                                soup.find("p", class_=lambda x: x and "title" in x.lower()) or
                                soup.find("div", class_=lambda x: x and "title" in x.lower()) or
                                soup.find("span", class_=lambda x: x and "title" in x.lower()))
                    if not title_tag:
                        link_tag = soup.find("a", href=lambda x: x and "/post/" in x)
                        if link_tag and link_tag.text.strip():
                            title = link_tag.text.strip()
                        else:
                            title = msg["Subject"].strip() if msg["Subject"] else "Unbenannter Beitrag"
                    else:
                        title = title_tag.text.strip()
                    print(f"DEBUG - fetch_substack_from_email: Title for {sender_name}: {title}")
                    link_tag = soup.find("a", href=lambda x: x and ("app-link/post" in x or "/post/" in x))
                    if not link_tag:
                        link_tag = soup.find("a", href=lambda x: x and "https://" in x)
                    link = link_tag["href"].strip() if link_tag else "#"
                    teaser = ""
                    if title_tag or link_tag:
                        start_tag = title_tag or link_tag
                        content_candidates = start_tag.find_all_next(string=True)
                        found_title = False
                        teaser_parts = []
                        for text in content_candidates:
                            stripped = text.strip()
                            if not found_title and stripped and (stripped in title or stripped in link):
                                found_title = True
                                continue
                            if (found_title and 30 < len(stripped) < 500 and 
                                "dear reader" not in stripped.lower() and 
                                "subscribe" not in stripped.lower() and 
                                "view in browser" not in stripped.lower()):
                                teaser_parts.append(stripped)
                                if len(" ".join(teaser_parts)) > 100:
                                    break
                        teaser = " ".join(teaser_parts).strip()[:300]
                    print(f"DEBUG - fetch_substack_from_email: Teaser for {sender_name}: {teaser}")
                    sender_posts.append((sender_name, title, link, teaser, sender_order, mail_date))
                sender_posts.sort(key=lambda x: x[5] or datetime(1970, 1, 1), reverse=True)
                posts.extend(sender_posts)
            except Exception as e:
                print(f"❌ ERROR: Error processing {sender_name} ({sender_email}): {str(e)}")
                continue
        imap.logout()
    except Exception as e:
        posts.append(("Allgemein", f"❌ Fehler beim Verbinden mit Gmail: {str(e)}", "#", "", 999))
    return posts if posts else [("Allgemein", "Keine neuen Substack-Mails gefunden.", "#", "", 999)]

# === Caixin Newsletter ===
def score_caixin_article(title):
    title_lower = title.lower()
    must_have_in_title = [
        "china", "chinese", "xi", "beijing", "shanghai", "hong kong", "taiwan", "prc",
        "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang", "brics",
        "belt and road", "macau", "pla"
    ]
    important_keywords = [
        "gdp", "exports", "imports", "tariffs", "real estate", "economy", "policy", "ai",
        "semiconductors", "pmi", "cpi", "housing", "foreign direct investment", "tech",
        "military", "sanctions", "trade", "data", "manufacturing", "industrial"
    ]
    positive_modifiers = [
        "analysis", "explainer", "comment", "feature", "official", "report", "statement",
        "in depth", "long read", "cover story"
    ]
    negative_keywords = [
        "celebrity", "gossip", "dog", "baby", "fashion", "movie", "series", "bizarre",
        "dating", "weird", "quiz", "elon musk", "rapid", "lask", "bundesliga", "eurovision",
        "basketball", "nba", "mlb", "nfl", "liberty", "yankees", "tournament", "playoffs",
        "finale", "score", "blowout", "caixin summer", "summit",
        "canada", "british columbia", "japan", "uzbekistan", "india"
    ]
    # Basis-Score: 1 bei China-Bezug, sonst 0
def score_caixin_article(title):
    title_lower = title.lower()
    score = 0

    # Schlüsselwörter für China-Bezug
    must_have_in_title = [
        "china", "chinese", "xi", "beijing", "shanghai", "hong kong", "taiwan", "prc",
        "communist party", "cpc", "byd", "alibaba", "tencent", "huawei", "li qiang", "brics",
        "belt and road", "macau", "pla", "guangdong", "shenzhen"
    ]
    # Wichtige Themen
    important_keywords = [
        "gdp", "exports", "imports", "tariffs", "real estate", "economy", "policy", "ai",
        "semiconductors", "pmi", "cpi", "housing", "foreign direct investment", "tech",
        "military", "sanctions", "trade", "data", "manufacturing", "industrial"
    ]
    # Positive Modifikatoren
    positive_modifiers = [
        "analysis", "explainer", "comment", "feature", "official", "report", "statement",
        "in depth", "long read", "cover story"
    ]
    # Negative Schlüsselwörter
    negative_keywords = [
        "celebrity", "gossip", "dog", "baby", "fashion", "movie", "series", "bizarre",
        "dating", "weird", "quiz", "elon musk", "rapid", "lask", "bundesliga", "eurovision",
        "basketball", "nba", "mlb", "nfl", "liberty", "yankees", "tournament", "playoffs",
        "finale", "score", "blowout", "caixin summer", "summit",
        "canada", "british columbia", "japan", "uzbekistan", "india", "korea", "australia"
    ]
    # Footer-Links
    footer_phrases = [
        "subscribe", "unsubscribe", "caixin global", "newsletters", "mobile apps", "sign up",
        "read online", "enjoy unlimited access"
    ]

    # Scoring-Logik
    if any(kw in title_lower for kw in must_have_in_title):
        score += 3
    if any(kw in title_lower for kw in important_keywords):
        score += 2
    if any(kw in title_lower for kw in positive_modifiers):
        score += 6
    if any(kw in title_lower for kw in negative_keywords):
        score -= 3
    if any(kw in title_lower for kw in footer_phrases):
        score = 0  # Footer-Links ausschließen

    print(f"DEBUG - score_caixin_article: Title '{title[:50]}...': Score {score} (China-relevance: {any(kw in title_lower for kw in must_have_in_title)}, Important: {any(kw in title_lower for kw in important_keywords)}, In Depth/Cover/Analysis: {any(kw in title_lower for kw in positive_modifiers)}, Non-China: {any(kw in title_lower for kw in negative_keywords)}, Footer: {any(kw in title_lower for kw in footer_phrases)})")
    return max(score, 0)

def fetch_caixin_from_email(email_user, email_password, folder="INBOX", max_results=5):
    print("DEBUG - fetch_caixin_from_email: Starting to fetch Caixin emails")
    posts = []
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        for attempt in range(3):
            try:
                imap.login(email_user, email_password)
                imap.select(folder)
                print(f"DEBUG - fetch_caixin_from_email: Successfully logged in to Gmail, selected folder {folder}")
                break
            except Exception as e:
                print(f"❌ ERROR - fetch_caixin_from_email: Gmail connection failed (Attempt {attempt+1}/3): {str(e)}")
                if attempt == 2:
                    return []  # Leere Liste für Live-Umgebung
                time.sleep(2)
    except Exception as e:
        print(f"❌ ERROR - fetch_caixin_from_email: Failed to connect to Gmail: {str(e)}")
        return []

    try:
        since_date = (datetime.now() - timedelta(days=1)).strftime("%d-%b-%Y")
        search_query = f'FROM caixinglobal.team@102113822.mailchimpapp.com SINCE {since_date}'
        print(f"DEBUG - fetch_caixin_from_email: Executing search query: {search_query}")
        typ, data = imap.search(None, search_query.encode('utf-8'))
        if typ != "OK":
            print(f"❌ ERROR - fetch_caixin_from_email: IMAP search failed: {data}")
            imap.logout()
            return []

        email_ids = data[0].split()
        print(f"DEBUG - fetch_caixin_from_email: Found {len(email_ids)} email IDs: {email_ids}")

        # Sortiere E-Mails nach Datum (neueste zuerst)
        email_data = []
        for eid in email_ids:
            typ, msg_data = imap.fetch(eid, "(BODY[HEADER.FIELDS (SUBJECT DATE FROM)])")
            if typ == "OK":
                msg = email.message_from_bytes(msg_data[0][1])
                subject = msg.get("Subject", "No Subject")
                date_str = msg.get("Date", "No Date")
                from_str = msg.get("From", "No From")
                try:
                    parsed_date = parsedate_to_datetime(date_str)
                except Exception as e:
                    print(f"DEBUG - fetch_caixin_from_email: Failed to parse date for email ID {eid}: {date_str}, error: {e}")
                    parsed_date = datetime.min
                print(f"DEBUG - fetch_caixin_from_email: Email ID {eid}, Subject: {subject}, Date: {date_str}, From: {from_str}")
                email_data.append((eid, parsed_date, subject, from_str))
        
        email_data.sort(key=lambda x: x[1], reverse=True)
        email_ids = [eid for eid, _, _, _ in email_data]
        print(f"DEBUG - fetch_caixin_from_email: Processing {len(email_ids)} emails (newest first): {email_ids}")

        if not email_ids:
            print("DEBUG - fetch_caixin_from_email: No emails found in the last day")
            imap.logout()
            return []  # Leere Liste für Live-Umgebung

        generic_titles = {
            "in depth", "cover story", "analysis", "finance", "economy", "business", "tech",
            "briefing", "news graphics", "opinion", "world", "podcast", "the wall street journal",
            "weekend long read"
        }
        
        # Neue Liste für irrelevante Link-Texte
        irrelevant_phrases = {
            "read more", "click here", "official says", "official said", "a chinese official",
            "learn more", "view online", "subscribe now", "full story", "continue reading"
        }

        scored_posts = []
        for eid in email_ids:
            typ, msg_data = imap.fetch(eid, "(RFC822)")
            if typ != "OK":
                print(f"❌ ERROR - fetch_caixin_from_email: Error fetching mail {eid}")
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = msg.get("Subject", "No Subject")
            date_str = msg.get("Date", "")
            print(f"DEBUG - fetch_caixin_from_email: Processing email ID {eid}, Subject: {subject}, Date: {date_str}")
            html = None
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html = part.get_payload(decode=True).decode(errors="ignore")
                        break
            elif msg.get_content_type() == "text/html":
                html = msg.get_payload(decode=True).decode(errors="ignore")
            if not html:
                print(f"❌ ERROR - fetch_caixin_from_email: No HTML content in mail {eid}")
                continue
            with open(f"caixin_email_{eid}.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"DEBUG - fetch_caixin_from_email: Saved HTML for mail {eid} to caixin_email_{eid}.html")
            soup = BeautifulSoup(html, "lxml")
            links = soup.find_all("a", href=lambda x: x and "caixinglobal" in x.lower())
            print(f"DEBUG - fetch_caixin_from_email: Found {len(links)} links with 'caixinglobal' in email ID {eid}")
            
            for link_tag in links:
                # Standard-Titel aus dem Link-Text
                title = link_tag.get_text(strip=True)
                title_lower = title.lower()
                
                # Prüfe, ob der Titel irrelevant ist
                if not title or len(title) < 10 or title_lower in generic_titles or title_lower in irrelevant_phrases or len(title.split()) < 5:
                    print(f"DEBUG - fetch_caixin_from_email: Skipping link with title '{title}' (too short, generic, or irrelevant)")
                    continue
                
                # Versuche, einen besseren Titel aus der Umgebung zu finden
                better_title = None
                parent = link_tag.find_parent(["p", "h1", "h2", "h3", "div"])
                if parent:
                    # Suche nach einem Titel in einem übergeordneten Element
                    title_tag = parent.find_previous(["h1", "h2", "h3", "p"]) or parent
                    candidate = title_tag.get_text(strip=True)
                    candidate_lower = candidate.lower()
                    if (candidate and len(candidate) >= 10 and len(candidate.split()) >= 5 and 
                        candidate_lower not in generic_titles and candidate_lower not in irrelevant_phrases):
                        better_title = candidate
                        print(f"DEBUG - fetch_caixin_from_email: Found better title '{better_title[:50]}...' from parent element")
                
                # Fallback auf Betreff, wenn kein besserer Titel gefunden wurde
                final_title = better_title or title or subject
                if final_title == subject:
                    print(f"DEBUG - fetch_caixin_from_email: Using email subject as title: '{final_title[:50]}...'")
                
                # Weitere Validierung
                if final_title.lower() in generic_titles or final_title.lower() in irrelevant_phrases or len(final_title.split()) < 5:
                    print(f"DEBUG - fetch_caixin_from_email: Skipping final title '{final_title[:50]}...' (generic or too short)")
                    continue
                
                link = link_tag.get("href", "#").strip()
                if not link or link == "#" or "unsubscribe" in link.lower():
                    print(f"DEBUG - fetch_caixin_from_email: Skipping link with URL '{link}' (invalid or unsubscribe)")
                    continue
                
                try:
                    response = requests.head(link, allow_redirects=True, timeout=5)
                    final_url = response.url
                    print(f"DEBUG - fetch_caixin_from_email: Resolved URL {link[:50]}... to {final_url[:50]}...")
                except Exception as e:
                    print(f"DEBUG - fetch_caixin_from_email: Could not resolve URL {link[:50]}...: {str(e)}")
                    final_url = link
                
                if "caixinglobal.com" not in final_url.lower():
                    print(f"DEBUG - fetch_caixin_from_email: Skipping non-caixinglobal.com URL: {final_url[:50]}...")
                    continue
                
                score = score_caixin_article(final_title)
                print(f"DEBUG - fetch_caixin_from_email: Article '{final_title[:50]}...' scored {score}")
                if score > 0:
                    scored_posts.append((score, f'• <a href="{final_url}">{final_title}</a>'))
                else:
                    print(f"DEBUG - fetch_caixin_from_email: Skipped article '{final_title[:50]}...' with score 0")

        scored_posts.sort(reverse=True, key=lambda x: x[0])
        posts = [item[1] for item in scored_posts[:max_results]]
        if not posts:
            print("DEBUG - fetch_caixin_from_email: No relevant articles found after scoring")
            imap.logout()
            return []  # Leere Liste für Live-Umgebung

        imap.logout()
        print(f"DEBUG - fetch_caixin_from_email: Returning {len(posts)} articles")
        return posts
    except Exception as e:
        print(f"❌ ERROR - fetch_caixin_from_email: Unexpected error: {str(e)}")
        imap.logout()
        return []
    
# === China Update aus YT abrufen ===
def fetch_youtube_endpoint():
    print("DEBUG - fetch_youtube_endpoint: Fetching latest China Update episode via API")
    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        print("❌ ERROR - fetch_youtube_endpoint: YOUTUBE_API_KEY not found in environment variables")
        return []
    try:
        youtube = build("youtube", "v3", developerKey=api_key)
        request = youtube.search().list(
            part="snippet",
            channelId="UCy287hC44mRWpFLj4hK8gKA",
            maxResults=1,
            order="date",
            type="video"
        )
        response = request.execute()
        print(f"DEBUG - fetch_youtube_endpoint: Full API response: {response}")
        if not response.get("items"):
            print("DEBUG - fetch_youtube_endpoint: No videos found in API response")
            return []
        video = response["items"][0]
        title = video["snippet"]["title"].strip()
        video_id = video["id"]["videoId"]
        link = f"https://youtu.be/{video_id}"  # Verkürzter YouTube-Link
        thumbnail = video["snippet"].get("thumbnails", {}).get("high", {}).get("url", "")
        if not thumbnail:
            thumbnail = video["snippet"].get("thumbnails", {}).get("medium", {}).get("url", "")
        if not thumbnail:
            thumbnail = video["snippet"].get("thumbnails", {}).get("default", {}).get("url", "")
        date_str = video["snippet"]["publishedAt"]
        try:
            pub_date = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
            two_days_ago = datetime.now() - timedelta(days=2)
            print(f"DEBUG - fetch_youtube_endpoint: Parsed date: {pub_date}, Two days ago: {two_days_ago}")
            if pub_date < two_days_ago:
                print(f"DEBUG - fetch_youtube_endpoint: Latest video ({title}) is older than 2 days")
                return []
        except ValueError as e:
            print(f"DEBUG - fetch_youtube_endpoint: Invalid date format: {date_str}, Error: {str(e)}")
            return []
        print(f"DEBUG - fetch_youtube_endpoint: Found episode: {title} ({link}), Thumbnail: {thumbnail}")
        return [{
            "title": title,
            "link": link,
            "thumbnail": thumbnail
        }]
    except HttpError as e:
        print(f"❌ ERROR - fetch_youtube_endpoint: HTTP error from YouTube API: {str(e)}")
        return []
    except Exception as e:
        print(f"❌ ERROR - fetch_youtube_endpoint: Failed to fetch YouTube episode: {str(e)}")
        return []

# === NBS-Daten abrufen ===
def fetch_latest_nbs_data():
    print("DEBUG - fetch_latest_nbs_data: Fetching NBS data")
    url = "http://www.stats.gov.cn/english/PressRelease/rss.xml"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        items = []
        for li in soup.select("ul.list_009 li")[:5]:
            a = li.find("a")
            if a and a.text:
                title = a.text.strip()
                link = "https://www.stats.gov.cn" + a["href"]
                items.append(f"• {title} ({link})")
        print(f"DEBUG - fetch_latest_nbs_data: Found {len(items)} NBS items")
        return items or ["Keine aktuellen Veröffentlichungen gefunden."]
    except Exception as e:
        print(f"ERROR - fetch_latest_nbs_data: Failed to fetch NBS data: {str(e)}")
        return [f"❌ Fehler beim Abrufen der NBS-Daten: {e}"]

# === Börsendaten & Wechselkurse abrufen ===
def fetch_index_data():
    print("DEBUG - fetch_index_data: Fetching index data")
    indices = {
        "Hang Seng Index (HSI)": "^HSI",
        "Hang Seng China Enterprises (HSCEI)": "^HSCE",
        "SSE Composite Index (Shanghai)": "000001.SS",
        "Shenzhen Component Index": "399001.SZ"
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    results = []
    for name, symbol in indices.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            if len(closes) < 2 or not all(closes[-2:]):
                results.append(f"❌ {name}: Keine gültigen Kursdaten verfügbar.")
                continue
            prev_close = closes[-2]
            last_close = closes[-1]
            change = last_close - prev_close
            pct = (change / prev_close) * 100
            arrow = "→" if abs(pct) < 0.01 else "↑" if change > 0 else "↓"
            results.append(f"• {name}: {round(last_close,2)} {arrow} ({pct:+.2f} %)")
        except Exception as e:
            results.append(f"❌ {name}: Fehler beim Abrufen ({e})")
    print(f"DEBUG - fetch_index_data: Retrieved {len(results)} index results")
    return results

# Interpretation für USD/CNY-Spread
def interpret_usd_cny_spread(spread_pips):
    if spread_pips <= -100:
        return "CPR stark unter Markterwartungen: starker Abwertungsdruck"
    elif -99 <= spread_pips <= -20:
        return "CPR leicht stärker als Markterwartungen: leichter Abwertungsdruck"
    elif -19 <= spread_pips <= 19:
        return "CPR liegt innerhalb der Markterwartungen"
    elif 20 <= spread_pips <= 99:
        return "CPR leicht schwächer als Markterwartungen: Markt erwartet stärkeren Yuan"
    else:
        return "CPR stark über Markterwartungen: Markt drängt auf Yuan-Stärke"

# Interpretation für CNH–CNY-Spread
def interpret_cnh_cny_spread(spread_pips):
    if spread_pips <= -50:
        return "Starke CNY-Aufwertung"
    elif -49 <= spread_pips <= -10:
        return "Leichte CNY-Stärke"
    elif -9 <= spread_pips <= 9:
        return "Stabile Marktbedingungen"
    elif 10 <= spread_pips <= 49:
        return "Leichte CNY-Schwäche"
    else:
        return "Starke CNY-Abwertung"

def fetch_cpr_forexlive():
    print("DEBUG - fetch_cpr_forexlive: Starting to fetch CPR from ForexLive")
    urls = [
        "https://www.forexlive.com/CentralBanks",
        "https://www.forexlive.com/"
    ]
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in urls:
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            articles = soup.find_all(["h2", "h3", "div"], class_=lambda x: x and ("card__title" in x or "article" in x) if x else False)
            print(f"DEBUG - fetch_cpr_forexlive: Found {len(articles)} articles on {url}")
            for article in articles:
                title = article.text.strip().lower()
                print(f"DEBUG - fetch_cpr_forexlive: Checking article: {title[:50]}...")
                if "pboc" in title and ("usd/cny" in title or "cny" in title or "reference rate" in title or "yuan" in title):
                    match = re.search(r"\d+\.\d{4}", title)
                    if match:
                        cpr = float(match.group())
                        estimate_match = re.search(r"estimate at (\d+\.\d{4})|vs\. (\d+\.\d{4})|vs\. estimate (\d+\.\d{4})", title)
                        estimate = float(estimate_match.group(1) or estimate_match.group(2) or estimate_match.group(3)) if estimate_match else None
                        if estimate is not None:
                            pips_diff = int((cpr - estimate) * 10000)
                        else:
                            pips_diff = None
                        print(f"✅ DEBUG - fetch_cpr_forexlive: Found CPR: USD/CNY = {cpr}, Estimate = {estimate}, Pips = {pips_diff}")
                        return cpr, estimate, pips_diff
            print(f"❌ DEBUG - fetch_cpr_forexlive: No CPR article found on {url}")
            print(f"DEBUG - fetch_cpr_forexlive: Sample articles: {[a.text.strip()[:50] for a in articles[:5]]}")
        except Exception as e:
            print(f"❌ ERROR - fetch_cpr_forexlive: Failed to fetch from {url}: {str(e)}")
    return None, None, None

def fetch_cpr_from_x():
    print("DEBUG - fetch_cpr_from_x: Starting to fetch CPR from X")
    headers = {"User-Agent": "Mozilla/5.0"}
    accounts = ["ForexLive", "Sino_Market"]
    for account in accounts:
        try:
            search_url = f"https://x.com/search?q=from:{account}%20PBOC%20USD/CNY%20reference%20rate"
            r = requests.get(search_url, headers=headers, timeout=10)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            tweets = soup.find_all("div", attrs={"data-testid": "tweetText"})
            print(f"DEBUG - fetch_cpr_from_x: Found {len(tweets)} tweets from @{account}")
            for tweet in tweets[:3]:
                text = tweet.text.strip().lower()
                print(f"DEBUG - fetch_cpr_from_x: Checking tweet: {text[:50]}...")
                if "pboc" in text and ("usd/cny" in text or "cny" in text or "reference rate" in text):
                    match = re.search(r"\d+\.\d{4}", text)
                    if match:
                        cpr = float(match.group())
                        estimate_match = re.search(r"estimate at (\d+\.\d{4})|vs\. (\d+\.\d{4})|vs\. estimate (\d+\.\d{4})", text)
                        estimate = float(estimate_match.group(1) or estimate_match.group(2) or estimate_match.group(3)) if estimate_match else 7.1820
                        pips_diff = int((cpr - estimate) * 10000)
                        print(f"✅ DEBUG - fetch_cpr_from_x: Found CPR from @{account}: USD/CNY = {cpr}, Estimate = {estimate}, Pips = {pips_diff}")
                        return cpr, estimate, pips_diff
            print(f"❌ DEBUG - fetch_cpr_from_x: No CPR post found from @{account}")
        except Exception as e:
            print(f"❌ ERROR - fetch_cpr_from_x: Failed to fetch from @{account}: {str(e)}")
    return None, None, None

def fetch_cpr_usdcny():
    print("DEBUG - fetch_cpr_usdcny: Starting to fetch CPR")
    cpr_cache = load_cpr_cache()
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    print(f"DEBUG - fetch_cpr_usdcny: Today: {today_str}, Yesterday: {yesterday_str}")

    print("DEBUG - fetch_cpr_usdcny: Trying CFETS")
    url = "https://www.chinamoney.com.cn/english/bmkcpr/"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        r = requests.get(url, headers=headers, timeout=10)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            print("❌ ERROR - fetch_cpr_usdcny: No tables found on CFETS page")
            print(f"DEBUG - fetch_cpr_usdcny: HTML excerpt: {soup.prettify()[:500]}")
        else:
            for table in tables:
                for row in table.find_all("tr")[1:]:
                    cells = row.find_all("td")
                    if len(cells) >= 2 and cells[0].text.strip() == "USD/CNY":
                        cpr_text = cells[1].text.strip()
                        try:
                            cpr = float(cpr_text)
                            print(f"✅ DEBUG - fetch_cpr_usdcny: Found CPR from CFETS: USD/CNY = {cpr}")
                            cpr_cache[today_str] = cpr
                            save_cpr_cache(cpr_cache)
                            prev_cpr = cpr_cache.get(yesterday_str)
                            return cpr, None, None, prev_cpr
                        except ValueError:
                            print(f"❌ ERROR - fetch_cpr_usdcny: Invalid CPR value '{cpr_text}'")
        print("❌ ERROR - fetch_cpr_usdcny: USD/CNY CPR not found in CFETS tables")
    except Exception as e:
        print(f"❌ ERROR - fetch_cpr_usdcny: Failed to fetch CPR from CFETS: {str(e)}")

    print("⚠️ DEBUG - fetch_cpr_usdcny: CFETS failed, trying ForexLive")
    cpr, estimate, pips_diff = fetch_cpr_forexlive()
    if cpr is not None:
        print(f"DEBUG - fetch_cpr_usdcny: Storing CPR {cpr} from ForexLive")
        cpr_cache[today_str] = cpr
        save_cpr_cache(cpr_cache)
        prev_cpr = cpr_cache.get(yesterday_str)
        return cpr, estimate, pips_diff, prev_cpr

    print("⚠️ DEBUG - fetch_cpr_usdcny: ForexLive failed, trying X posts")
    cpr, estimate, pips_diff = fetch_cpr_from_x()
    if cpr is not None:
        print(f"DEBUG - fetch_cpr_usdcny: Storing CPR {cpr} from X")
        cpr_cache[today_str] = cpr
        save_cpr_cache(cpr_cache)
        prev_cpr = cpr_cache.get(yesterday_str)
        return cpr, estimate, pips_diff, prev_cpr

    print("⚠️ DEBUG - fetch_cpr_usdcny: All sources failed, using cache or Reuters estimate")
    cpr = cpr_cache.get(today_str)
    prev_cpr = cpr_cache.get(yesterday_str)
    if cpr is not None:
        print(f"DEBUG - fetch_cpr_usdcny: Using cached CPR for today: {cpr}")
        return cpr, None, None, prev_cpr
    print("DEBUG - fetch_cpr_usdcny: No cached CPR found, using Reuters estimate")
    return None, 7.1820, None, prev_cpr

def fetch_currency_data():
    print("DEBUG - fetch_currency_data: Starting to fetch currency data")
    currencies = {
        "USDCNY": "USDCNY=X",
        "USDCNH": "USDCNH=X",
    }
    headers = {"User-Agent": "Mozilla/5.0"}
    results = {}
    
    cpr, estimate, pips_diff, prev_cpr = fetch_cpr_usdcny()
    if cpr is not None:
        results["CPR"] = (cpr, estimate, pips_diff, prev_cpr)
    else:
        results["CPR"] = ("❌ CPR (CNY/USD): Keine Daten verfügbar.", estimate, pips_diff, prev_cpr)
    
    for name, symbol in currencies.items():
        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            if not data.get("chart") or not data["chart"].get("result"):
                results[name] = f"❌ {name}: Keine Daten in der API-Antwort."
                continue
            result = data["chart"]["result"][0]
            closes = result["indicators"]["quote"][0]["close"]
            prev_close = result.get("meta", {}).get("chartPreviousClose")
            if not closes or len(closes) == 0 or prev_close is None:
                results[name] = f"❌ {name}: Keine gültigen Kursdaten verfügbar (closes={closes}, prev_close={prev_close})."
                continue
            last_close = closes[-1]
            if len(closes) == 1:
                change = last_close - prev_close
                pct = (change / prev_close) * 100 if prev_close != 0 else 0
            else:
                prev_close = closes[-2]
                change = last_close - prev_close
                pct = (change / prev_close) * 100 if prev_close != 0 else 0
            arrow = "→" if abs(pct) < 0.01 else "↑" if change > 0 else "↓"
            results[name] = (last_close, arrow, pct)
        except Exception as e:
            results[name] = f"❌ {name}: Unerwarteter Fehler ({str(e)})"
    print(f"DEBUG - fetch_currency_data: Retrieved currency data: {results}")
    return results

# === Stimmen von X ===
x_accounts = [
    {"account": "Sino_Market", "name": "CN Wire", "url": "https://x.com/Sino_Market"},
    {"account": "tonychinaupdate", "name": "China Update", "url": "https://x.com/tonychinaupdate"},
    {"account": "YuanTalks", "name": "YUAN TALKS", "url": "https://x.com/YuanTalks"},
    {"account": "Brad_Setser", "name": "Brad Setser", "url": "https://x.com/Brad_Setser"},
    {"account": "KennedyCSIS", "name": "Scott Kennedy", "url": "https://x.com/KennedyCSIS"},
]

def fetch_recent_x_posts(account, name, url):
    print(f"DEBUG - fetch_recent_x_posts: Fetching posts for {name} (@{account})")
    return [f"• {name} (@{account}) → {url}"]

# === Render Markdown für Substack ===
def render_markdown(posts):
    print(f"DEBUG - render_markdown: Processing {len(posts)} posts")
    markdown = []
    current_sender = None
    for sender_name, title, link, teaser, sender_order, _ in sorted(posts, key=lambda x: (x[4], x[5] or datetime(1970, 1, 1)), reverse=True):
        if sender_name != current_sender:
            markdown.append(f"\n### {sender_name}")
            current_sender = sender_name
        markdown.append(f'• <a href="{link}">{title}</a>')
        if teaser:
            markdown.append(f'  {teaser}')
    return markdown

def generate_briefing():
    print("DEBUG - generate_briefing: Starting to generate briefing")
    date_str = datetime.now().strftime("%d. %B %Y")
    briefing = [f"Guten Morgen, Hado!\n\n🗓️ {date_str}\n\n📬 Dies ist dein tägliches China-Briefing.\n"]

    # Börsenindizes
    briefing.append("\n## 📊 Börsenindizes China (08:00 Uhr MESZ)")
    if is_weekend_day or is_holiday_china:
        briefing.append("📈 Heute kein Handelstag an den chinesischen Börsen.")
    else:
        briefing.extend(fetch_index_data())
    if is_weekend_day or is_holiday_hk:
        briefing.append("📈 Heute kein Handelstag an der Hongkonger Börse.")

    # Wechselkurse
    briefing.append("\n## 💱 Wechselkurse (08:00 Uhr MESZ)")
    if is_weekend_day or is_holiday_china or is_holiday_hk:
        briefing.append("📉 Heute keine aktuellen Wechselkurse.")
    else:
        currency_data = fetch_currency_data()
        print(f"DEBUG - generate_briefing: Currency data: {currency_data}")
        try:
            with open(CPR_CACHE_FILE, "r", encoding="utf-8") as f:
                cache_content = json.load(f)
                print(f"DEBUG - generate_briefing: Cache content after fetch: {cache_content}")
        except Exception as e:
            print(f"ERROR - generate_briefing: Failed to read cache after fetch: {str(e)}")
        cpr_data = currency_data.get("CPR")
        if isinstance(cpr_data, tuple) and isinstance(cpr_data[0], float):
            cpr, estimate, pips_diff, prev_cpr = cpr_data
            print(f"DEBUG - generate_briefing: CPR={cpr}, estimate={estimate}, pips_diff={pips_diff}, prev_cpr={prev_cpr}")
            if estimate is not None:
                pips_formatted = f"Spread: CPR vs Est {pips_diff:+d} pips"
                spread_arrow = "↓" if pips_diff <= -20 else "↑" if pips_diff >= 20 else "→"
                usd_cny_interpretation = interpret_usd_cny_spread(pips_diff)
                if prev_cpr is not None:
                    pct_change = ((cpr - prev_cpr) / prev_cpr) * 100 if prev_cpr != 0 else 0
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f} ({pct_change:+.2f} %) vs. Est.: {estimate:.4f} ({pips_formatted} {spread_arrow}, {usd_cny_interpretation})"
                    print(f"DEBUG - generate_briefing: CPR line with pct_change: {cpr_line}")
                else:
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f} vs. Est.: {estimate:.4f} ({pips_formatted} {spread_arrow}, {usd_cny_interpretation})"
                    print(f"DEBUG - generate_briefing: CPR line without pct_change: {cpr_line}")
                briefing.append(cpr_line)
            else:
                if prev_cpr is not None:
                    pct_change = ((cpr - prev_cpr) / prev_cpr) * 100 if prev_cpr != 0 else 0
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f} ({pct_change:+.2f} %)"
                    print(f"DEBUG - generate_briefing: CPR line with prev_cpr: {cpr_line}")
                    briefing.append(cpr_line)
                else:
                    cpr_line = f"• CPR (CNY/USD): {cpr:.4f}"
                    print(f"DEBUG - generate_briefing: CPR line without prev_cpr: {cpr_line}")
                    briefing.append(cpr_line)
        else:
            briefing.append(str(cpr_data[0]))
            if cpr_data[1] is not None:
                briefing.append(f"  - Estimate: {cpr_data[1]:.4f}")
        if isinstance(currency_data.get("USDCNY"), tuple):
            val_cny, arrow_cny, pct_cny = currency_data["USDCNY"]
            briefing.append(f"• CNY/USD (Onshore): {val_cny:.4f} {arrow_cny} ({pct_cny:+.2f} %)")
        else:
            briefing.append(currency_data.get("USDCNY"))
        if isinstance(currency_data.get("USDCNH"), tuple):
            val_cnh, arrow_cnh, pct_cnh = currency_data["USDCNH"]
            briefing.append(f"• CNH/USD (Offshore): {val_cnh:.4f} {arrow_cnh} ({pct_cnh:+.2f} %)")
        else:
            briefing.append(currency_data.get("USDCNH"))
        if isinstance(currency_data.get("USDCNY"), tuple) and isinstance(currency_data.get("USDCNH"), tuple):
            val_cny = currency_data["USDCNY"][0]
            val_cnh = currency_data["USDCNH"][0]
            spread = val_cnh - val_cny
            spread_pips = int(spread * 10000)
            cnh_cny_interpretation = interpret_cnh_cny_spread(spread_pips)
            spread_arrow = "↓" if spread_pips <= -10 else "↑" if spread_pips >= 10 else "→"
            briefing.append(f"• Spread CNH–CNY: {spread:+.4f} {spread_arrow} ({cnh_cny_interpretation})")

    # Frachtraten Indizies
    briefing.append("\n## 🚢 Frachtraten Indizies")
    try:
        # SCFI-Daten
        scfi_value, pct_change, scfi_date, warning_message = fetch_scfi()
        if warning_message:
            send_warning_email(warning_message)
        arrow = "→"
        pct_change_str = "0.00"
        if pct_change is not None:
            pct_change_str = f"{pct_change:.2f}"
            if pct_change > 0:
                arrow = "↑"
            elif pct_change < 0:
                arrow = "↓"
        scfi_line = f"• <a href=\"https://en.sse.net.cn/indices/scfinew.jsp\">SCFI</a>: ${scfi_value:.2f} {arrow} ({pct_change_str}%, Stand {scfi_date})"
        
        # WCI- und IACI-Daten
        try:
            wci_text, iaci_text = generate_briefing_freight()
            # Sicherstellen, dass $ im Text enthalten ist
            wci_text = wci_text.replace("WCI</a>: ", "WCI</a>: $")
            iaci_text = iaci_text.replace("IACI</a>: ", "IACI</a>: $")
        except Exception as e:
            logger.error(f"Failed to fetch WCI/IACI data: {str(e)}")
            wci_text = f"• <a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/world-container-index-assessed-by-drewry'>WCI</a>: $0.00 (Stand {date.today().strftime('%d.%m.%Y')})"
            iaci_text = f"• <a href='https://www.drewry.co.uk/supply-chain-advisors/supply-chain-expertise/intra-asia-container-index'>IACI</a>: $0.00 (Stand {date.today().strftime('%d.%m.%Y')})"
            send_warning_email(f"WCI/IACI data fetch failed: {str(e)}")
        
        briefing.extend([scfi_line, wci_text, iaci_text])
        
        # SCFI-Cache-Debugging
        try:
            with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache_content = json.load(f)
                print(f"DEBUG - generate_briefing: SCFI cache content after fetch: {cache_content}")
        except Exception as e:
            print(f"ERROR - generate_briefing: Failed to read SCFI cache after fetch: {str(e)}")
    except Exception as e:
        print(f"ERROR - generate_briefing: Failed to fetch SCFI data: {str(e)}")
        briefing.append(f"❌ Fehler beim Abrufen der Frachtraten: {str(e)}")

    # Wirtschaftskalender
    briefing.append("")  # Leerzeile für Abstand
    briefing.extend(fetch_economic_calendar())
    
    # Top 5 China-Stories
    briefing.append("\n## 🏆 Top 5 China-Stories laut Google News")
    for source, url in feeds_topchina.items():
        briefing.append(f"\n### {source}")
        briefing.extend(fetch_news(url, max_items=30, top_n=5))

    # NBS-Daten
    briefing.append("\n## 📈 NBS – Nationale Statistikdaten")
    briefing.extend(fetch_latest_nbs_data())

    # X-Stimmen
    briefing.append("\n## 📡 Stimmen & Perspektiven von X")
    for acc in x_accounts:
        briefing.extend(fetch_recent_x_posts(acc["account"], acc["name"], acc["url"]))

    # Google News nach Sprache/Quelle
    briefing.append("\n## 🌎 Google News – Nach Sprache & Quelle sortiert")
    all_articles = {
        "EN": defaultdict(list),
        "DE": defaultdict(list),
        "FR": defaultdict(list),
        "ASIA": defaultdict(list),
        "OTHER": defaultdict(list)
    }
    for lang, url in feeds_google_news.items():
        feed = feedparser.parse(url)
        for entry in feed.entries:
            title = entry.get("title", "").strip()
            summary = entry.get("summary", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue
            score = score_article(title, summary)
            if score <= 0:
                continue
            source = extract_source(title)
            category = source_categories.get(source, lang if lang in ["EN", "DE", "FR"] else "OTHER")
            if source in ["SCMP", "Nikkei Asia", "Yicai"]:
                category = "ASIA"
            clean_title = title
            if f"– {source}" in title:
                clean_title = title.split(f"– {source}")[0].strip()
            elif f"- {source}" in title:
                clean_title = title.split(f"- {source}")[0].strip()
            if clean_title.lower().endswith(source.lower()):
                clean_title = clean_title[:-(len(source))].strip("- :— ").strip()
            all_articles[category][source].append((score, f'• <a href="{link}">{clean_title}</a>'))
    category_titles = {
        "EN": "🇺🇸 Englischsprachige Medien",
        "DE": "🇩🇪 Deutschsprachige Medien",
        "FR": "🇫🇷 Französische Medien",
        "ASIA": "🌏 Asiatische Medien",
        "OTHER": "🧪 Sonstige Quellen"
    }
    for cat_key, sources in all_articles.items():
        if not sources:
            continue
        briefing.append(f"\n### {category_titles.get(cat_key)}")
        for source_name, articles in sorted(sources.items()):
            if not articles:
                continue
            briefing.append(f"\n{source_name}")
            top_articles = sorted(articles, reverse=True)[:5]
            briefing.extend([a[1] for a in top_articles])

    # SCMP
    briefing.append("\n## 📺 SCMP – Top-Themen")
    briefing.extend(fetch_ranked_articles(feeds_scmp_yicai["SCMP"]))

    # Caixin
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        briefing.append("\n## 📜 Caixin – Top-Themen")
        briefing.append("❌ Fehler: SUBSTACK_MAIL Umgebungsvariable nicht gefunden!")
    else:
        try:
            mail_pairs = substack_mail.split(";")
            mail_config = {}
            for pair in mail_pairs:
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    mail_config[key] = value
            if "GMAIL_USER" not in mail_config or "GMAIL_PASS" not in mail_config:
                briefing.append("\n## 📜 Caixin – Top-Themen")
                missing_keys = [k for k in ["GMAIL_USER", "GMAIL_PASS"] if k not in mail_config]
                briefing.append(f"❌ Fehler: Fehlende Schlüssel in SUBSTACK: {', '.join(missing_keys)}")
            else:
                email_user = mail_config["GMAIL_USER"]
                email_password = mail_config["GMAIL_PASS"]
                caixin_posts = fetch_caixin_from_email(email_user, email_password)
                if caixin_posts:
                    briefing.append("\n## 📜 Caixin – Top-Themen")
                    briefing.extend(caixin_posts)
        except ValueError as e:
            briefing.append("\n## 📜 Caixin – Top-Themen")
            briefing.append(f"❌ Fehler beim Parsen von SUBSTACK: {str(e)}")

    
    # Nikkei Top-Artikel
    briefing.append("\n## 📜 Nikkei Top-Artikel")
    nikkei_articles = fetch_combined_china_articles()
    if nikkei_articles:
        briefing.extend(nikkei_articles)
    else:
        briefing.append("Keine Nikkei-Artikel gefunden.")
    # China Update YouTube
    youtube_episodes = fetch_youtube_endpoint()
    if youtube_episodes:
        briefing.append("\n### China Update")
        for episode in youtube_episodes:
            title = episode["title"]
            link = episode["link"]
            thumbnail = episode["thumbnail"]
            if thumbnail:
                # Maskierter Link mit JS-Umleitung
                briefing.append(f'<a href="#" onclick="window.location.href=\'{link}\'; return false;"><img src="{thumbnail}" alt="{title}" style="max-width: 320px; height: auto; display: block; margin: 10px 0; border: none;" class="no-preview"></a>')
            else:
                briefing.append(f'• <a href="{link}">{title}</a>')

    # Substack-Abschnitt
    briefing.append("\n## 📬 Aktuelle Substack-Artikel")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        briefing.append("❌ Fehler: SUBSTACK_MAIL Umgebungsvariable nicht gefunden!")
    else:
        try:
            mail_pairs = substack_mail.split(";")
            mail_config = {}
            for pair in mail_pairs:
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    mail_config[key] = value
            if "GMAIL_USER" not in mail_config or "GMAIL_PASS" not in mail_config:
                missing_keys = [k for k in ["GMAIL_USER", "GMAIL_PASS"] if k not in mail_config]
                briefing.append(f"❌ Fehler: Fehlende Schlüssel in SUBSTACK:{', '.join(missing_keys)}")
            else:
                email_user = mail_config["GMAIL_USER"]
                email_password = mail_config["GMAIL_PASS"]
                posts = fetch_substack_from_email(email_user, email_password)
                briefing.extend(render_markdown(posts))
        except ValueError as e:
            briefing.append(f"❌ Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")

    briefing.append("\nEinen erfolgreichen Tag! 🌟")

    print("DEBUG - generate_briefing: Briefing generated successfully")
    # Debugging: HTML-Output speichern
    with open("newsletter.html", "w", encoding="utf-8") as f:
        f.write(f"""\
<html>
<head>
    <meta charset="UTF-8">
    <meta name="robots" content="noindex, nofollow, noarchive">
    <meta property="og:image" content="">
    <meta property="og:image:secure_url" content="">
    <meta property="og:image:type" content="">
    <meta property="og:image:width" content="">
    <meta property="og:image:height" content="">
    <meta property="og:type" content="website">
    <meta property="og:title" content="Daily China Briefing">
    <meta property="og:description" content="">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:image" content="">
    <meta name="twitter:image:alt" content="">
    <meta name="twitter:title" content="Daily China Briefing">
    <meta name="twitter:description" content="">
    <style>
        .no-preview {{ pointer-events: auto; }}
        a[href="#"] img {{ border: none !important; }}
    </style>
</head>
<body style="margin: 0; padding: 0;">
    <div style="background-color: #ffffff; padding: 20px;">
        <pre style="font-family: Arial, sans-serif; margin: 0;">
{chr(10).join(briefing)}\n
        </pre>
    </div>
</body>
</html>""")
    return f"""\
<html>
<head>
    <meta charset="UTF-8">
    <meta name="robots" content="noindex, nofollow, noarchive">
    <meta property="og:image" content="">
    <meta property="og:image:secure_url" content="">
    <meta property="og:image:type" content="">
    <meta property="og:image:width" content="">
    <meta property="og:image:height" content="">
    <meta property="og:type" content="website">
    <meta property="og:title" content="Daily China Briefing">
    <meta property="og:description" content="">
    <meta name="twitter:card" content="summary">
    <meta name="twitter:image" content="">
    <meta name="twitter:image:alt" content="">
    <meta name="twitter:title" content="Daily China Briefing">
    <meta name="twitter:description" content="">
    <style>
        .no-preview {{ pointer-events: auto; }}
        a[href="#"] img {{ border: none !important; }}
    </style>
</head>
<body style="margin: 0; padding: 0;">
    <div style="background-color: #ffffff; padding: 20px;">
        <pre style="font-family: Arial, sans-serif; margin: 0;">
{chr(10).join(briefing)}\n
        </pre>
    </div>
</body>
</html>"""
# === E-Mail senden ===
def send_briefing():
    print("🧠 DEBUG - send_briefing: Starting to generate and send briefing")
    briefing_content = generate_briefing()

    msg = MIMEText(briefing_content, "html", "utf-8")
    msg["Subject"] = "📰 Dein tägliches China-Briefing"
    msg["From"] = config_dict["EMAIL_USER"]
    msg["To"] = config_dict["EMAIL_TO"]

    print("📤 DEBUG - send_briefing: Sending email")
    try:
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        print("✅ DEBUG - send_briefing: Email sent successfully")
    except Exception as e:
        print(f"❌ ERROR - send_briefing: Failed to send email: {str(e)}")

# === Hauptskript ===
if __name__ == "__main__":
    send_briefing()
