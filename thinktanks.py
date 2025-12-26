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
    """Löst Tracking-URLs auf (Dynamics, Mailchimp, Pardot, etc.)."""
    try:
        # Pardot-URLs (CSIS verwendet pardot.csis.org)
        if "pardot.csis.org" in url:
            response = requests.get(url, allow_redirects=True, timeout=5)
            final_url = response.url
            logger.debug(f"Pardot-URL aufgelöst: {url} -> {final_url}")
            return final_url
        
        # Dynamics-URLs mit msdynmkt_target Parameter
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        if 'msdynmkt_target' in query_params:
            target_json = query_params['msdynmkt_target'][0]
            target_data = json.loads(target_json)
            if 'TargetUrl' in target_data:
                final_url = urllib.parse.unquote(target_data['TargetUrl'])
                return final_url
        
        # Fallback: Folge den Redirects
        if "public-eur.mkt.dynamics.com" in url or "clicks.mlsend.com" in url:
            response = requests.get(url, allow_redirects=True, timeout=5)
            final_url = response.url
            return final_url
            
        return url
    except Exception as e:
        logger.warning(f"Fehler beim Auflösen der URL {url}: {str(e)}")
        return url

def clean_merics_title(subject):
    """Bereinigt MERICS E-Mail-Betreff für Titel."""
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
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Suche nach dem Hauptlink
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
                break
    
    # Strategie 2: Falls kein Link über Text gefunden, nimm den ersten merics.org Link
    if not found_link:
        for link in all_links:
            href = link.get("href", "")
            resolved_url = resolve_tracking_url(href)
            if "merics.org" in resolved_url and not any(skip in resolved_url.lower() for skip in ["unsubscribe", "profile"]):
                found_link = resolved_url
                break
    
    # Wenn ein Link gefunden wurde, erstelle Artikel
    if found_link:
        title = clean_merics_title(subject)
        formatted_article = f"• [{title}]({found_link})"
        articles.append(formatted_article)
    
    return articles

def fetch_merics_emails(mail, email_user, email_password, days=7):
    """
    Holt MERICS-Artikel aus E-Mails mit verbessertem Parsing.
    Verwendet eine bestehende IMAP-Verbindung.
    """
    try:
        thinktanks = load_thinktanks()
        merics = next((tt for tt in thinktanks if tt["abbreviation"] == "MERICS"), None)
        if not merics:
            logger.error("MERICS nicht in thinktanks.json gefunden")
            return [], 0

        email_senders = merics["email_senders"]
        email_senders = [extract_email_address(sender) for sender in email_senders]

        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        email_count = 0
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

        for sender in email_senders:
            result, data = mail.search(None, f'FROM "{sender}" SINCE {since_date}')
            if result != "OK":
                logger.warning(f"Fehler bei der Suche nach E-Mails von {sender}: {result}")
                continue

            email_ids = data[0].split()
            email_count += len(email_ids)
            
            for email_id in email_ids:
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

        logger.info(f"MERICS: {len(all_articles)} Artikel gefunden")
        return all_articles, email_count
        
    except Exception as e:
        logger.error(f"Fehler in fetch_merics_emails: {str(e)}")
        return [], 0

def score_csis_article(title, description=""):
    """Bewertet einen CSIS-Artikel auf China-Relevanz."""
    title_lower = title.lower()
    desc_lower = description.lower()
    content = f"{title_lower} {desc_lower}"
    
    # MUSS China-Bezug haben
    china_keywords = [
        "china", "chinese", "xi jinping", "xi", "beijing", "shanghai",
        "taiwan", "hong kong", "prc", "ccp", "communist party",
        "sino-", "u.s.-china", "us-china", "asean"
    ]
    
    if not any(kw in content for kw in china_keywords):
        return 0
    
    score = 5  # Basis-Score für China-Erwähnung
    
    # Wichtige Themen
    important_topics = [
        "technology", "trade", "security", "military", "defense",
        "economy", "tariff", "semiconductor", "ai", "geopolitics",
        "indo-pacific", "south china sea", "strait"
    ]
    
    for topic in important_topics:
        if topic in content:
            score += 2
    
    # Negative Keywords (andere Regionen ohne China-Bezug)
    negative_keywords = [
        "venezuela", "gaza", "israel", "palestine", "ukraine", "russia",
        "europe", "africa", "middle east"
    ]
    
    # Nur abziehen wenn China NICHT erwähnt wird
    if not any(kw in content for kw in china_keywords):
        for neg in negative_keywords:
            if neg in content:
                score -= 5
    
    return max(score, 0)

def parse_csis_geopolitics_email(msg):
    """
    Spezialisierter Parser für CSIS Geopolitics & Foreign Policy Newsletter.
    Extrahiert Podcast-Episoden mit China-Relevanz.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
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
        logger.warning("Keine HTML-Inhalte in CSIS Geopolitics E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Strategie: Finde alle Links, die zu csis.org führen
    all_links = soup.find_all("a", href=True)
    
    for link in all_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True)
        
        # Muss ein CSIS/Pardot Link sein
        if "csis.org" not in href and "pardot.csis.org" not in href:
            continue
        
        # Skip Newsletter-Footer und UI-Links FRÜH
        skip_patterns = [
            "unsubscribe", "preferences", "forward", "view it in your browser",
            "email not displaying", "www.csis.org/geopolitics", "www.csis.org$",
            "privacy-policy", "my-mailing-preferences"
        ]
        
        if any(skip in href.lower() for skip in skip_patterns):
            continue
        
        if any(skip in link_text.lower() for skip in skip_patterns):
            continue
        
        # Skip Social Media Links
        if any(social in href.lower() for social in ["facebook.com", "twitter.com", "linkedin.com", "instagram.com", "youtube.com"]):
            continue
        
        # Finde den Titel
        title = None
        description = ""
        
        # Methode 1: Suche RÜCKWÄRTS nach dem VORHERIGEN em_text4 Element
        current_element = link
        found_table_with_multiple_trs = None
        
        # Gehe bis zu 5 Ebenen hoch, um eine Tabelle mit mehreren <tr> zu finden
        for level in range(5):
            current_element = current_element.find_parent("table")
            if not current_element:
                break
            
            all_trs = current_element.find_all("tr")
            
            if len(all_trs) > 3:
                found_table_with_multiple_trs = current_element
                break
        
        if found_table_with_multiple_trs:
            all_em_text4 = found_table_with_multiple_trs.find_all("td", class_="em_text4")
            
            for title_cell in reversed(all_em_text4):
                title_text = title_cell.get_text(strip=True)
                title_text = " ".join(title_text.split())
                
                if "new episodes:" in title_text.lower():
                    continue
                
                if title_text and len(title_text) > 20:
                    title = title_text
                    break
        
        # Methode 2: Falls nicht gefunden, suche in übergeordneter Tabelle
        if not title:
            parent_table = link.find_parent("table")
            if parent_table:
                title_cell = parent_table.find("td", class_="em_text4")
                if title_cell:
                    title_text = title_cell.get_text(strip=True)
                    title_text = " ".join(title_text.split())
                    if title_text and len(title_text) > 20 and "new episodes:" not in title_text.lower():
                        title = title_text
        
        # Methode 3: Suche nach <strong> oder <b>
        if not title:
            parent = link.find_parent(["tr", "td"])
            if parent:
                strong_tags = parent.find_all(["strong", "b"])
                for strong in strong_tags:
                    strong_text = strong.get_text(strip=True)
                    strong_text = " ".join(strong_text.split())
                    if strong_text and len(strong_text) > 20:
                        title = strong_text
                        break
        
        # Methode 4: Verwende Link-Text als letzten Ausweg
        if not title and link_text and len(link_text) > 20:
            if "listen here" not in link_text.lower() and "read more" not in link_text.lower():
                title = link_text
        
        if not title:
            continue
        
        # Score berechnen
        score = score_csis_article(title, description)
        
        if score > 0:
            # Duplikats-Check
            if title in [art.split('](')[0].split('[')[1] for art in articles]:
                continue
            
            # URL auflösen
            resolved_url = resolve_tracking_url(href)
            formatted_article = f"• [{title}]({resolved_url})"
            articles.append(formatted_article)
    
    return articles

def fetch_csis_geopolitics_emails(mail, email_user, email_password, days=120):
    """
    Holt CSIS Geopolitics & Foreign Policy Artikel aus E-Mails.
    """
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "geopolitics@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS Geopolitics: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_csis_geopolitics_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS Geopolitics: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_csis_geopolitics_emails: {str(e)}")
        return [], 0

def parse_csis_freeman_email(msg):
    """
    Spezialisierter Parser für CSIS Freeman Chair Newsletter (Pekingology Podcast).
    Format: Podcast-Titel im Betreff, Beschreibung im Body, "Listen on CSIS.org" Link.
    """
    articles = []
    
    # Betreff extrahieren = Podcast-Titel
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Freeman Chair - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in CSIS Freeman E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Suche nach dem "Listen on CSIS.org" Link
    # Der Link ist typischerweise in einem <td bgcolor="#3DD5FF"> mit Link-Text "Listen on CSIS.org"
    found_link = None
    
    all_links = soup.find_all("a", href=True)
    
    for link in all_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True).lower()
        
        # Skip unwichtige Links
        skip_patterns = [
            "mailto:",
            "unsubscribe",
            "privacy",
            "preferences",
            "view it in your browser",
            "facebook.com",
            "twitter.com",
            "linkedin.com",
            "instagram.com",
            "youtube.com",
            "apple.com",
            "spotify.com"
        ]
        
        if any(skip in href.lower() or skip in link_text for skip in skip_patterns):
            continue
        
        # Suche nach "Listen on CSIS.org" oder ähnlichen Texten
        if "listen on csis" in link_text or "csis.org" in link_text:
            # Prüfe ob es ein Pardot-Link ist (tracking)
            if "pardot.csis.org" in href or "csis.org" in href:
                resolved_url = resolve_tracking_url(href)
                # Prüfe ob es zu /podcasts/ oder /pekingology/ führt
                if "/podcasts/" in resolved_url or "/pekingology/" in resolved_url or "csis.org" in resolved_url:
                    found_link = resolved_url
                    logger.info(f"Freeman Chair - Link gefunden: {resolved_url}")
                    break
    
    # Fallback: Suche nach jedem csis.org Link der nicht zu Standardseiten führt
    if not found_link:
        for link in all_links:
            href = link.get("href", "")
            
            skip_patterns = [
                "www.csis.org$",
                "www.csis.org/analysis",
                "www.csis.org/events",
                "www.csis.org/people",
                "www.csis.org/podcasts$",  # Hauptseite, nicht Episode
                "unsubscribe",
                "privacy",
                "preferences"
            ]
            
            if any(skip in href.lower() for skip in skip_patterns):
                continue
            
            if "csis.org" in href or "pardot.csis.org" in href:
                resolved_url = resolve_tracking_url(href)
                if "csis.org" in resolved_url:
                    found_link = resolved_url
                    logger.info(f"Freeman Chair - Fallback Link: {resolved_url}")
                    break
    
    if found_link:
        # Titel: "Pekingology: [Betreff]"
        title = f"Pekingology: {subject}"
        formatted_article = f"• [{title}]({found_link})"
        articles.append(formatted_article)
        logger.info(f"Freeman Chair - Artikel erstellt: {title}")
    else:
        logger.warning(f"Freeman Chair - Kein Link gefunden für: {subject}")
    
    return articles

def fetch_csis_freeman_emails(mail, email_user, email_password, days=120):
    """
    Holt CSIS Freeman Chair (Pekingology) Artikel aus E-Mails.
    """
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "FreemanChair@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS Freeman: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Freeman Chair - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_csis_freeman_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS Freeman Chair: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_csis_freeman_emails: {str(e)}")
        return [], 0

def main():
    logger.info("Starte erweitertes Testskript für Think Tanks (MERICS + CSIS)")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        logger.error("SUBSTACK_MAIL Umgebungsvariable nicht gefunden")
        send_email("Fehler in thinktanks.py", "<p>SUBSTACK_MAIL Umgebungsvariable nicht gefunden</p>", "", "")
        return

    try:
        mail_config = dict(pair.split("=", 1) for pair in substack_mail.split(";") if "=" in pair)
        email_user = mail_config.get("GMAIL_USER")
        email_password = mail_config.get("GMAIL_PASS")
        if not email_user or not email_password:
            logger.error("GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL")
            send_email("Fehler in thinktanks.py", "<p>GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL</p>", email_user, email_password)
            return
    except Exception as e:
        logger.error(f"Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")
        send_email("Fehler in thinktanks.py", f"<p>Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}</p>", "", "")
        return

    # IMAP-Verbindung aufbauen
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_user, email_password)
        logger.info("IMAP-Login erfolgreich")
    except Exception as e:
        logger.error(f"IMAP-Login fehlgeschlagen: {str(e)}")
        return
    
    try:
        # MERICS (30 Tage)
        merics_articles, merics_count = fetch_merics_emails(mail, email_user, email_password, days=30)
        
        # CSIS Geopolitics (120 Tage)
        csis_geo_articles, csis_geo_count = fetch_csis_geopolitics_emails(mail, email_user, email_password, days=120)
        
        # CSIS Freeman Chair (120 Tage)
        csis_freeman_articles, csis_freeman_count = fetch_csis_freeman_emails(mail, email_user, email_password, days=120)
        
    finally:
        mail.logout()
        logger.info("IMAP-Logout erfolgreich")
    
    # Briefing erstellen
    briefing = []
    briefing.append("## Think Tanks")
    
    # MERICS
    briefing.append("### MERICS")
    if merics_articles:
        briefing.extend(merics_articles)
    else:
        briefing.append("• Keine relevanten MERICS-Artikel gefunden.")
    
    # CSIS Header
    briefing.append("")
    briefing.append("### CSIS")
    
    # CSIS Geopolitics
    briefing.append("#### Geopolitics & Foreign Policy")
    if csis_geo_articles:
        briefing.extend(csis_geo_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    # CSIS Freeman Chair
    briefing.append("")
    briefing.append("#### Freeman Chair in China Studies")
    if csis_freeman_articles:
        briefing.extend(csis_freeman_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")

    # Konvertiere zu HTML
    html_lines = []
    for line in briefing:
        html_line = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', line)
        html_lines.append(html_line)
    
    # HTML zusammenbauen
    html_content = ""
    for i, line in enumerate(html_lines):
        if line.startswith("##"):
            html_content += line + "<br><br>\n"
        elif line.startswith("###") and not line.startswith("####"):
            html_content += line + "<br>\n"
        elif line.startswith("####"):
            html_content += line + "<br>\n"
        elif line == "":
            html_content += "<br>\n"
        else:
            html_content += line
            if i < len(html_lines) - 1:
                html_content += "<br>\n"
    
    # E-Mail senden
    send_email("Think Tanks - MERICS & CSIS Update", html_content, email_user, email_password)
    logger.info("E-Mail erfolgreich versendet")
    
    # Vorschau auf Konsole
    print("\n" + "="*50)
    print("VORSCHAU DER E-MAIL:")
    print("="*50)
    print("\n".join(briefing))
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
