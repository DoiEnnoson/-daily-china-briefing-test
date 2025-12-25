import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import os
import requests
from bs4 import BeautifulSoup
import smtplib
from email.mime.text import MIMEText
import urllib.parse
import re
import logging
import json

# Logging-Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler('thinktanks.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

# Basisverzeichnis
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def send_email(subject, body, email_user, email_password, to_email="hadobrockmeyer@gmail.com"):
    """Sendet eine E-Mail."""
    try:
        msg = MIMEText(body, "html")
        msg['Subject'] = subject
        msg['From'] = email_user
        msg['To'] = to_email
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(email_user, email_password)
            server.send_message(msg)
        logger.info(f"E-Mail erfolgreich an {to_email} gesendet: {subject}")
    except Exception as e:
        logger.error(f"Fehler beim Senden der E-Mail an {to_email}: {str(e)}")

def load_thinktanks():
    """Lädt Think Tanks aus thinktanks.json."""
    try:
        thinktanks_path = os.path.join(BASE_DIR, "thinktanks.json")
        with open(thinktanks_path, "r", encoding="utf-8") as f:
            thinktanks = json.load(f)
        logger.info(f"Geladen: {len(thinktanks)} Think Tanks")
        return thinktanks
    except Exception as e:
        logger.error(f"Fehler beim Laden von thinktanks.json: {str(e)}")
        return []

def extract_email_address(sender):
    """Extrahiert E-Mail-Adresse aus Sender-String."""
    match = re.search(r'<(.+?)>', sender)
    return match.group(1) if match else sender

def resolve_tracking_url(url):
    """Löst Tracking-URLs auf (Dynamics, Mailchimp, etc.)."""
    try:
        # Dynamics-URLs mit msdynmkt_target Parameter
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        if 'msdynmkt_target' in query_params:
            target_json = query_params['msdynmkt_target'][0]
            import json
            target_data = json.loads(target_json)
            if 'TargetUrl' in target_data:
                final_url = urllib.parse.unquote(target_data['TargetUrl'])
                logger.debug(f"Dynamics URL aufgelöst: {url} -> {final_url}")
                return final_url
        
        # Fallback: Folge den Redirects
        if "public-eur.mkt.dynamics.com" in url or "clicks.mlsend.com" in url:
            response = requests.get(url, allow_redirects=True, timeout=5)
            final_url = response.url
            logger.debug(f"Redirect aufgelöst: {url} -> {final_url}")
            return final_url
            
        return url
    except Exception as e:
        logger.warning(f"Fehler beim Auflösen der URL {url}: {str(e)}")
        return url

def clean_merics_title(subject):
    """Bereinigt MERICS E-Mail-Betreff für Titel."""
    # Entferne Präfixe
    prefixes = [
        "MERICS China Security & Risk Tracker: ",
        "MERICS China Essentials Special Issue: ",
        "MERICS China Essentials: ",
        "MERICS ",
    ]
    
    cleaned = subject
    for prefix in prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
            break
    
    return cleaned.strip()

def parse_merics_email(msg):
    """
    Spezialisierter Parser für MERICS E-Mails.
    Extrahiert Hauptartikel aus dem E-Mail-Betreff und findet den primären Link.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    # Datum extrahieren
    try:
        date = email.utils.parsedate_to_datetime(msg.get("Date", ""))
    except:
        date = datetime.now()
    
    logger.info(f"Parse MERICS E-Mail: {subject} vom {date.strftime('%Y-%m-%d')}")
    
    # HTML-Inhalt finden
    html_content = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            charset = part.get_content_charset() or "utf-8"
            try:
                html_content = part.get_payload(decode=True).decode(charset)
            except UnicodeDecodeError:
                html_content = part.get_payload(decode=True).decode("windows-1252", errors="replace")
            break
    
    if not html_content:
        logger.warning("Keine HTML-Inhalte gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Suche nach dem Hauptlink
    # MERICS nutzt typischerweise "on our website", "Read more", "download", etc.
    main_link_texts = [
        "on our website",
        "read more", 
        "download the pdf",
        "as a pdf",
        "here",
        "full tracker"
    ]
    
    found_link = None
    all_links = soup.find_all("a", href=True)
    
    # Strategie 1: Finde den ersten relevanten Link zum Hauptartikel
    for link in all_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True).lower()
        
        # Überspringe unwichtige Links
        skip_patterns = [
            "mailto:",
            "unsubscribe",
            "privacy",
            "legal",
            "cookie",
            "profile",
            "linkedin",
            "twitter",
            "facebook",
            "youtube"
        ]
        
        if any(pattern in href.lower() or pattern in link_text for pattern in skip_patterns):
            continue
        
        # Suche nach typischen MERICS-Hauptlink-Texten
        if any(main_text in link_text for main_text in main_link_texts):
            resolved_url = resolve_tracking_url(href)
            if "merics.org" in resolved_url:
                found_link = resolved_url
                logger.info(f"Hauptlink gefunden über Text '{link_text}': {found_link}")
                break
    
    # Strategie 2: Falls kein Link über Text gefunden, nimm den ersten merics.org Link
    if not found_link:
        for link in all_links:
            href = link.get("href", "")
            resolved_url = resolve_tracking_url(href)
            if "merics.org" in resolved_url and not any(skip in resolved_url.lower() for skip in ["unsubscribe", "profile"]):
                found_link = resolved_url
                logger.info(f"Hauptlink gefunden als erster merics.org Link: {found_link}")
                break
    
    # Wenn ein Link gefunden wurde, erstelle Artikel
    if found_link:
        title = clean_merics_title(subject)
        formatted_article = f"• [{title}]({found_link})"
        articles.append(formatted_article)
        logger.info(f"MERICS Artikel erstellt: {title}")
    else:
        logger.warning(f"Kein geeigneter Link in E-Mail gefunden: {subject}")
    
    return articles

def fetch_merics_emails(email_user, email_password, days=7):
    """
    Holt MERICS-Artikel aus E-Mails mit verbessertem Parsing.
    """
    logger.info("Starte fetch_merics_emails mit verbessertem Parser")
    try:
        thinktanks = load_thinktanks()
        merics = next((tt for tt in thinktanks if tt["abbreviation"] == "MERICS"), None)
        if not merics:
            logger.error("MERICS nicht in thinktanks.json gefunden")
            send_email("Fehler in fetch_merics_emails", "<p>MERICS nicht in thinktanks.json gefunden</p>", email_user, email_password)
            return [], 0

        email_senders = merics["email_senders"]
        email_senders = [extract_email_address(sender) for sender in email_senders]
        logger.info(f"Bereinigte Absender: {email_senders}")

        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            mail.login(email_user, email_password)
            logger.info("IMAP-Login erfolgreich")
        except Exception as e:
            logger.error(f"IMAP-Login fehlgeschlagen: {str(e)}")
            send_email("Fehler in fetch_merics_emails", f"<p>IMAP-Login fehlgeschlagen: {str(e)}</p>", email_user, email_password)
            return [], 0

        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        email_count = 0
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        logger.info(f"Suche nach E-Mails seit: {since_date}")

        for sender in email_senders:
            logger.info(f"Suche nach E-Mails von: {sender}")
            result, data = mail.search(None, f'FROM "{sender}" SINCE {since_date}')
            if result != "OK":
                logger.warning(f"Fehler bei der Suche nach E-Mails von {sender}: {result}")
                continue

            email_ids = data[0].split()
            email_count += len(email_ids)
            logger.info(f"Anzahl gefundener E-Mails von {sender}: {len(email_ids)}")
            
            for email_id in email_ids:
                logger.debug(f"Verarbeite E-Mail ID: {email_id}")
                result, msg_data = mail.fetch(email_id, "(RFC822)")
                if result != "OK":
                    logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                
                # Nutze den spezialisierten Parser
                articles = parse_merics_email(msg)
                
                # Duplikate filtern
                for article in articles:
                    # Extrahiere URL aus Markdown-Link
                    url_match = re.search(r'\((https?://[^\)]+)\)', article)
                    if url_match:
                        url = url_match.group(1)
                        if url not in seen_urls:
                            all_articles.append(article)
                            seen_urls.add(url)

        mail.logout()
        logger.info("IMAP-Logout erfolgreich")
        logger.info(f"Anzahl eindeutiger MERICS-Artikel: {len(all_articles)}")
        return all_articles, email_count
        
    except Exception as e:
        logger.error(f"Fehler in fetch_merics_emails: {str(e)}")
        send_email("Fehler in fetch_merics_emails", f"<p>Fehler beim Abrufen von MERICS-E-Mails: {str(e)}</p>", email_user, email_password)
        return [], 0
    finally:
        try:
            mail.logout()
            logger.info("IMAP-Logout im finally-Block erfolgreich")
        except:
            pass

def main():
    logger.info("Starte verbessertes Testskript für MERICS-Artikel-Extraktion")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        logger.error("SUBSTACK_MAIL Umgebungsvariable nicht gefunden")
        send_email("Fehler in thinktanks.py", "<p>SUBSTACK_MAIL Umgebungsvariable nicht gefunden</p>", "", "")
        return

    try:
        mail_config = dict(pair.split("=", 1) for pair in substack_mail.split(";") if "=" in pair)
        email_user = mail_config.get("GMAIL_USER")
        email_password = mail_config.get("GMAIL_PASS")
        logger.info(f"Geparsed: GMAIL_USER={email_user}")
        if not email_user or not email_password:
            logger.error("GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL")
            send_email("Fehler in thinktanks.py", "<p>GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL</p>", email_user, email_password)
            return
    except Exception as e:
        logger.error(f"Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")
        send_email("Fehler in thinktanks.py", f"<p>Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}</p>", "", "")
        return

    # Suche nach E-Mails der letzten 30 Tage für bessere Testabdeckung
    articles, email_count = fetch_merics_emails(email_user, email_password, days=30)
    
    # Briefing erstellen (wie in der Hauptdatei)
    briefing = []
    briefing.append("## Think Tanks")
    briefing.append("### MERICS")
    
    if articles:
        briefing.extend(articles)
    else:
        briefing.append("• Keine relevanten MERICS-Artikel gefunden.")

    # Konvertiere zu HTML für E-Mail
    html_content = "<br>\n".join(briefing)
    
    # E-Mail senden
    send_email("Think Tanks - MERICS Update", html_content, email_user, email_password)
    logger.info("E-Mail erfolgreich versendet")
    
    # Vorschau auf Konsole
    print("\n" + "="*50)
    print("VORSCHAU DER E-MAIL:")
    print("="*50)
    print("\n".join(briefing))
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
