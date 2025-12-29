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

# Globale Zeitfenster-Einstellung für ALLE Think Tanks
GLOBAL_THINKTANK_DAYS = 120  # 4 Monate für alle Think Tank Newsletter

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

def fetch_merics_emails(mail, email_user, email_password, days=None):
    """
    Holt MERICS-Artikel aus E-Mails mit verbessertem Parsing.
    Verwendet eine bestehende IMAP-Verbindung.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
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
    
    Struktur: Die E-Mail enthält mehrere Episode-Abschnitte, jeder mit:
    - em_text4 mit Episode-Titel (oft in <span>)
    - Beschreibung
    - "Listen Here" Button mit Link
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Geopolitics - Betreff: {subject}")
    
    # Event-Invites überspringen
    if any(keyword in subject.lower() for keyword in ["event invite", "join us", "register here", "rsvp"]):
        logger.info("Geopolitics - Event Invite übersprungen")
        return articles
    
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
    
    # Finde alle em_text4 Elemente (Titel)
    all_em_text4 = soup.find_all("td", class_="em_text4")
    
    logger.info(f"Geopolitics Parser - {len(all_em_text4)} em_text4 Elemente gefunden")
    
    # Gehe durch alle em_text4 Elemente und suche den nächsten "Listen Here" Link
    for title_cell in all_em_text4:
        title_text = title_cell.get_text(strip=True)
        title_text = " ".join(title_text.split())
        
        # Überspringe "New Episodes:" Header
        if "new episodes:" in title_text.lower():
            logger.info(f"Geopolitics Parser - Überspringe Header: {title_text}")
            continue
        
        # Titel muss mindestens 15 Zeichen haben
        if len(title_text) < 15:
            continue
        
        logger.info(f"Geopolitics Parser - Gefundener Titel: {title_text}")
        
        # Suche nach dem nächsten "Listen Here" Link NACH diesem em_text4
        # Gehe durch alle nachfolgenden Elemente
        current = title_cell
        found_link = None
        
        # Suche in den nächsten 10 Geschwister-Elementen
        for _ in range(10):
            current = current.find_next("td")
            if not current:
                break
            
            # Suche nach einem Link mit "Listen Here" Text
            links = current.find_all("a", href=True)
            for link in links:
                link_text = link.get_text(strip=True).lower()
                href = link.get("href", "")
                
                if "listen here" in link_text or "listen on csis" in link_text:
                    if "csis.org" in href or "pardot.csis.org" in href:
                        found_link = href
                        logger.info(f"Geopolitics Parser - Link gefunden: {href[:60]}...")
                        break
            
            if found_link:
                break
        
        if not found_link:
            logger.info(f"Geopolitics Parser - Kein Link für Titel gefunden: {title_text[:50]}...")
            continue
        
        # Score berechnen
        score = score_csis_article(title_text, "")
        logger.info(f"Geopolitics Parser - Score: {score}")
        
        if score > 0:
            # Duplikats-Check
            if title_text in [art.split('](')[0].split('[')[1] for art in articles]:
                logger.info(f"Geopolitics Parser - Duplikat übersprungen")
                continue
            
            formatted_article = f"• [{title_text}]({found_link})"
            articles.append(formatted_article)
            logger.info(f"Geopolitics Parser - Artikel hinzugefügt: {title_text[:50]}...")
        else:
            logger.info(f"Geopolitics Parser - Score zu niedrig: {score}")
    
    logger.info(f"Geopolitics Parser - {len(articles)} Artikel extrahiert")
    return articles

def fetch_csis_geopolitics_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS Geopolitics & Foreign Policy Artikel aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "geopolitics@csis.org"
        
        logger.info(f"Geopolitics - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS Geopolitics: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Geopolitics - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            # Betreff loggen
            subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
            if isinstance(subject, bytes):
                subject = subject.decode()
            logger.info(f"Geopolitics - Betreff: {subject}")
            
            articles = parse_csis_geopolitics_email(msg)
            logger.info(f"Geopolitics - {len(articles)} Artikel aus dieser E-Mail extrahiert")
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
                        logger.info(f"Geopolitics - Artikel hinzugefügt: {article[:80]}...")
        
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
    
    # Event-Invites überspringen
    if any(keyword in subject.lower() for keyword in ["event invite", "join us", "register here", "rsvp"]):
        logger.info("Freeman Chair - Event Invite übersprungen")
        return articles
    
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
            if "pardot.csis.org" in href or "csis.org" in href:
                resolved_url = resolve_tracking_url(href)
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
                "www.csis.org/podcasts$",
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
        title = f"Pekingology: {subject}"
        formatted_article = f"• [{title}]({found_link})"
        articles.append(formatted_article)
        logger.info(f"Freeman Chair - Artikel erstellt: {title}")
    else:
        logger.warning(f"Freeman Chair - Kein Link gefunden für: {subject}")
    
    return articles

def parse_csis_trustee_email(msg):
    """
    Spezialisierter Parser für CSIS Trustee Chair Newsletter.
    Extrahiert Reports, Charts, Videos und Podcast-Episoden (keine Events).
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Trustee Chair - Betreff: {subject}")
    
    # Event-Invites überspringen
    if any(keyword in subject.lower() for keyword in ["event invite", "join us", "register here", "rsvp"]):
        logger.info("Trustee Chair - Event Invite übersprungen")
        return articles
    
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
        logger.warning("Keine HTML-Inhalte in CSIS Trustee E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Liste bekannter CSIS-Personen (nur Namen → Skip)
    csis_staff = [
        "scott kennedy", "ilaria mazzocco", "ryan featherston", "isabella mccallum",
        "andy yang", "qingfeng yu", "jeannette l. chu", "michael davidson",
        "john l. holden", "margaret jackson", "claire reade", "daniel h. rosen",
        "deborah seligsohn", "logan wright", "ruixue jia", "hongbin li",
        "ethan michelson", "yu zhou", "elizabeth knup", "teevrat garg",
        "jessica teets", "han shen lin", "michael szonyi", "evelyn cheng"
    ]
    
    # Negative Keywords (sehr streng)
    negative_keywords = [
        "view in your browser",
        "visit our microsite",
        "trustee chair in chinese business",
        "our new non-resident",
        "non-resident affiliate",
        "upcoming virtual event",
        "upcoming event",
        "register here",
        "amcham",
        "e-magazine",
        "first digital report",
        "email not displaying",
        "manage preferences",
        "privacy policy",
        "follow us",
        "unsubscribe",
        "copyright",
        "panelists",
        "moderator",
        "speaker"
    ]
    
    # Finde alle Links
    all_links = soup.find_all("a", href=True)
    seen_titles = set()
    
    logger.info(f"Trustee Chair Parser - {len(all_links)} Links gefunden")
    
    for link in all_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True)
        
        # Muss ein CSIS/Pardot Link sein
        if "csis.org" not in href and "pardot.csis.org" not in href:
            continue
        
        # Skip unwichtige Links (strenger)
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
            "www.csis.org/analysis$",
            "www.csis.org/events$",
            "www.csis.org/about",
            "www.csis.org/people",
            "www.csis.org/podcasts$",
            "www.csis.org$",
            "/chinese-business-and-economics$",
            "bigdatachina.csis.org$"
        ]
        
        if any(skip in href.lower() for skip in skip_patterns):
            continue
        
        # Suche nach Titel in der Nähe des Links
        title = None
        
        # Methode 1: Suche RÜCKWÄRTS nach Content vor "Read/Listen/Watch Here" Buttons
        # Diese Buttons sind in Tabellen mit rotem Hintergrund (#e31836)
        button_texts = ["read here", "listen here", "watch here", "subscribe"]
        
        if any(btn in link_text.lower() for btn in button_texts):
            # Button gefunden! Suche nach Titel VOR diesem Button
            parent_table = link.find_parent("table")
            if parent_table:
                # Gehe durch vorherige Geschwister-Tabellen
                prev_tables = parent_table.find_all_previous("table", limit=3)
                for prev_table in prev_tables:
                    # Suche nach Text in <a>, <strong>, <b>, <em> Tags
                    content_tags = prev_table.find_all(["a", "strong", "b", "em"])
                    for tag in content_tags:
                        text = tag.get_text(strip=True)
                        if text and len(text) > 30:  # Mindestens 30 Zeichen
                            title = text
                            break
                    if title:
                        break
        
        # Methode 2: Link-Text selbst (wenn lang genug und kein Button)
        if not title and link_text and len(link_text) > 30:
            if not any(btn in link_text.lower() for btn in button_texts):
                title = link_text
        
        # Methode 3: Suche nach vorherigem <a> oder <strong> im selben Parent
        if not title:
            parent = link.find_parent(["td", "tr", "div"])
            if parent:
                # Suche alle Links/Bold-Text im Parent
                content_elements = parent.find_all(["a", "strong", "b"])
                for elem in content_elements:
                    elem_text = elem.get_text(strip=True)
                    if elem_text and len(elem_text) > 30 and elem != link:
                        title = elem_text
                        break
        
        if not title:
            logger.debug(f"Trustee Chair - Kein Titel für Link: {href[:60]}...")
            continue
        
        # STRENGE FILTER
        title_lower = title.lower()
        
        # 1. Negative Keywords
        if any(neg in title_lower for neg in negative_keywords):
            logger.debug(f"Trustee Chair - Negatives Keyword: {title[:40]}...")
            continue
        
        # 2. Nur Personen-Namen (Name + optional Title)
        is_only_name = False
        for staff_name in csis_staff:
            if title_lower == staff_name or title_lower.startswith(staff_name + ","):
                is_only_name = True
                break
        
        if is_only_name:
            logger.debug(f"Trustee Chair - Nur Name: {title}")
            continue
        
        # 3. Titel muss mindestens 30 Zeichen haben
        if len(title) < 30:
            logger.debug(f"Trustee Chair - Zu kurz: {title}")
            continue
        
        # 4. Duplikats-Check
        if title in seen_titles:
            logger.debug(f"Trustee Chair - Duplikat: {title[:40]}...")
            continue
        
        seen_titles.add(title)
        
        # 5. Bereinige Titel von Datumsangaben am Ende
        title = re.sub(r',?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d+,?\s+\d{4}$', '', title)
        
        # Resolve Tracking URL
        resolved_url = resolve_tracking_url(href)
        
        formatted_article = f"• [{title}]({resolved_url})"
        articles.append(formatted_article)
        logger.info(f"Trustee Chair - Artikel: {title[:50]}...")
    
    logger.info(f"Trustee Chair Parser - {len(articles)} Artikel extrahiert")
    return articles

def parse_csis_japan_email(msg):
    """
    Spezialisierter Parser für CSIS Japan Chair Newsletter.
    Extrahiert Artikel mit em_text4 Titeln und "Read More Here" Links.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Japan Chair - Betreff: {subject}")
    
    # Event-Invites überspringen
    if any(keyword in subject.lower() for keyword in ["event invite", "join us", "register here", "rsvp"]):
        logger.info("Japan Chair - Event Invite übersprungen")
        return articles
    
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
        logger.warning("Keine HTML-Inhalte in CSIS Japan Chair E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde alle em_text4 Titel (große Schrift)
    title_elements = soup.find_all("td", class_=lambda x: x and "em_text4" in x)
    
    logger.info(f"Japan Chair Parser - {len(title_elements)} em_text4 Elemente gefunden")
    
    seen_titles = set()
    
    for title_element in title_elements:
        # Extrahiere Titel-Text
        title_text = title_element.get_text(strip=True)
        
        # Bereinige Titel
        title_text = title_text.replace("​​", "").strip()  # Entferne Zero-Width-Spaces
        
        # Überspringe zu kurze Titel
        if len(title_text) < 30:
            logger.debug(f"Japan Chair - Titel zu kurz: {title_text}")
            continue
        
        # Duplikats-Check
        if title_text in seen_titles:
            logger.debug(f"Japan Chair - Duplikat: {title_text[:40]}...")
            continue
        
        seen_titles.add(title_text)
        
        # Suche nach Link NACH diesem Titel
        # Finde die nächste Zeile mit einem CTA-Button
        next_link = None
        
        # Methode 1: Suche in nachfolgenden Elementen (max 15 Schritte)
        current = title_element
        for _ in range(15):
            current = current.find_next()
            if not current:
                break
            
            # Suche nach Links mit relevanten Texten
            if current.name == "a":
                link_text = current.get_text(strip=True).lower()
                href = current.get("href")
                
                # Erweiterte Link-Keywords
                link_keywords = [
                    "read more", "read here", "read on csis", 
                    "read full", "learn more", "view"
                ]
                
                if href and "csis.org" in href and any(kw in link_text for kw in link_keywords):
                    next_link = href
                    break
            
            # Suche innerhalb von td-Elementen
            if current.name == "td":
                # Versuche jeden Link zu csis.org/analysis zu finden
                link = current.find("a", href=re.compile(r"csis\.org/analysis"))
                if link:
                    next_link = link.get("href")
                    break
        
        # Methode 2: Wenn kein spezifischer Link gefunden, suche nach JEDEM csis.org/analysis Link
        if not next_link:
            # Suche im gesamten E-Mail-Bereich nach dem Titel nach Links
            all_links = soup.find_all("a", href=re.compile(r"csis\.org/(analysis|commentary)"))
            for link in all_links:
                # Prüfe ob der Link nach dem Titel kommt
                if link.get("href"):
                    next_link = link.get("href")
                    logger.info(f"Japan Chair - Fallback-Link gefunden: {next_link[:60]}...")
                    break
        
        if not next_link:
            logger.warning(f"Japan Chair - Kein Link für Titel gefunden: {title_text[:40]}...")
            continue
        
        # Resolve Tracking URL
        resolved_url = resolve_tracking_url(next_link)
        
        formatted_article = f"• [{title_text}]({resolved_url})"
        articles.append(formatted_article)
        logger.info(f"Japan Chair - Artikel: {title_text[:50]}...")
    
    logger.info(f"Japan Chair Parser - {len(articles)} Artikel extrahiert")
    return articles

def parse_chinapower_email(msg):
    """
    Spezialisierter Parser für CSIS China Power Newsletter.
    Extrahiert Artikel aus Newsletter-Sections (nicht Event-Invites).
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"China Power - Betreff: {subject}")
    
    # Skip Event Invites
    if "event invite" in subject.lower() or "join us" in subject.lower():
        logger.info("China Power - Event Invite übersprungen")
        return articles
    
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
        logger.warning("Keine HTML-Inhalte in China Power E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde alle h2 Titel (Artikel-Überschriften)
    h2_elements = soup.find_all("h2")
    
    logger.info(f"China Power Parser - {len(h2_elements)} h2 Elemente gefunden")
    
    seen_titles = set()
    
    for h2 in h2_elements:
        title_text = h2.get_text(strip=True)
        
        # Skip unwichtige Titel
        skip_titles = [
            "china power project",
            "love the chinapower podcast",
            "subscribe on itunes"
        ]
        
        if any(skip in title_text.lower() for skip in skip_titles):
            logger.debug(f"China Power - Header übersprungen: {title_text}")
            continue
        
        # Mindestlänge
        if len(title_text) < 20:
            logger.debug(f"China Power - Titel zu kurz: {title_text}")
            continue
        
        # Duplikats-Check
        if title_text in seen_titles:
            logger.debug(f"China Power - Duplikat: {title_text[:40]}...")
            continue
        
        seen_titles.add(title_text)
        
        # Suche nach "Read here" / "Listen here" / "Watch here" Links
        # Diese sind normalerweise in der Nähe des h2
        next_link = None
        
        # Suche in nachfolgenden Elementen (max 10 Schritte)
        current = h2
        for _ in range(10):
            current = current.find_next()
            if not current:
                break
            
            # Suche nach Links mit relevanten Texten
            if current.name == "a":
                link_text = current.get_text(strip=True).lower()
                href = current.get("href")
                
                if href and "csis.org" in href and any(keyword in link_text for keyword in ["read here", "listen here", "watch here", "watch the recording"]):
                    next_link = href
                    logger.debug(f"China Power - Link gefunden: {href[:60]}...")
                    break
            
            # Suche auch in verschachtelten Elementen
            if current.name in ["p", "td", "div"]:
                link = current.find("a", href=True, string=lambda x: x and any(kw in x.lower() for kw in ["read here", "listen here", "watch here", "watch the recording"]))
                if link:
                    href = link.get("href")
                    if href and "csis.org" in href:
                        next_link = href
                        logger.debug(f"China Power - Verschachtelter Link gefunden: {href[:60]}...")
                        break
        
        if not next_link:
            logger.debug(f"China Power - Kein Link für Titel gefunden: {title_text[:40]}...")
            continue
        
        # Resolve Tracking URL
        resolved_url = resolve_tracking_url(next_link)
        
        formatted_article = f"• [{title_text}]({resolved_url})"
        articles.append(formatted_article)
        logger.info(f"China Power - Artikel: {title_text[:50]}...")
    
    logger.info(f"China Power Parser - {len(articles)} Artikel extrahiert")
    return articles

def fetch_csis_freeman_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS Freeman Chair (Pekingology) Artikel aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
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

def fetch_csis_trustee_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS Trustee Chair Artikel aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "cbe@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS Trustee: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Trustee Chair - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_csis_trustee_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS Trustee Chair: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_csis_trustee_emails: {str(e)}")
        return [], 0

def fetch_csis_japan_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS Japan Chair Artikel aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "JapanChair@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS Japan Chair: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Japan Chair - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_csis_japan_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS Japan Chair: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_csis_japan_emails: {str(e)}")
        return [], 0

def fetch_chinapower_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS China Power Newsletter aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "ChinaPower@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS China Power: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"China Power - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_chinapower_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS China Power: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_chinapower_emails: {str(e)}")
        return [], 0

def parse_korea_chair_email(msg):
    """
    Spezialisierter Parser für CSIS Korea Chair Newsletter.
    Extrahiert Critical Questions und andere Publikationen.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Korea Chair - Betreff: {subject}")
    
    # Event-Invites überspringen
    if any(keyword in subject.lower() for keyword in ["event invite", "join us", "register here", "rsvp"]):
        logger.info("Korea Chair - Event Invite übersprungen")
        return articles
    
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
        logger.warning("Keine HTML-Inhalte in Korea Chair E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Methode 1: Finde Titel in <td> mit class="em_text4"
    title_element = soup.find("td", class_="em_text4")
    
    if title_element:
        title = title_element.get_text(strip=True)
        title = re.sub(r'\s+', ' ', title)  # Mehrfache Leerzeichen entfernen
        logger.info(f"Korea Chair - Titel gefunden: {title}")
        
        # Suche nach "Read on CSIS.org" Link
        read_link = soup.find("a", string=re.compile(r"Read on CSIS\.org", re.IGNORECASE))
        
        if not read_link:
            # Alternative: Suche nach Link mit href zu csis.org/analysis
            read_link = soup.find("a", href=re.compile(r"csis\.org/analysis"))
        
        if read_link:
            href = read_link.get("href")
            
            if href:
                # Pardot-URL auflösen
                final_url = resolve_tracking_url(href)
                
                # China-Relevanz prüfen
                title_lower = title.lower()
                china_keywords = [
                    "china", "chinese", "beijing", "xi jinping", "taiwan", "hong kong",
                    "south china sea", "dprk", "north korea", "asia", "indo-pacific"
                ]
                
                is_china_relevant = any(keyword in title_lower for keyword in china_keywords)
                
                if is_china_relevant:
                    formatted_article = f"• [{title}]({final_url})"
                    articles.append(formatted_article)
                    logger.info(f"Korea Chair - Artikel hinzugefügt: {title[:50]}...")
                else:
                    logger.info(f"Korea Chair - Nicht China-relevant: {title[:50]}...")
    else:
        logger.warning("Korea Chair - Kein Titel-Element gefunden")
    
    return articles

def fetch_korea_chair_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS Korea Chair Newsletter aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "koreachair@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS Korea Chair: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Korea Chair - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_korea_chair_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS Korea Chair: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_korea_chair_emails: {str(e)}")
        return [], 0

def parse_ghpc_email(msg):
    """
    Spezialisierter Parser für CSIS Global Health Policy Center Newsletter.
    Extrahiert Artikel, Videos und Transcripts mit China-Bezug.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"GHPC - Betreff: {subject}")
    
    # Event-Invites überspringen
    if any(keyword in subject.lower() for keyword in ["event invite", "join us", "register here", "rsvp"]):
        logger.info("GHPC - Event Invite übersprungen")
        return articles
    
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
        logger.warning("Keine HTML-Inhalte in GHPC E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde alle großen Titel (em_text4, em_text3, em_text5)
    title_elements = soup.find_all("td", class_=lambda x: x and any(cls in x for cls in ["em_text4", "em_text3", "em_text5"]))
    
    logger.info(f"GHPC Parser - {len(title_elements)} Titel-Elemente gefunden")
    
    seen_titles = set()
    
    for title_element in title_elements:
        title = title_element.get_text(strip=True)
        title = re.sub(r'\s+', ' ', title)  # Mehrfache Leerzeichen entfernen
        
        # Überspringe zu kurze Titel
        if len(title) < 20:
            logger.debug(f"GHPC - Titel zu kurz: {title}")
            continue
        
        # Duplikats-Check
        if title in seen_titles:
            logger.debug(f"GHPC - Duplikat: {title[:40]}...")
            continue
        
        seen_titles.add(title)
        
        # China-Relevanz prüfen
        title_lower = title.lower()
        china_keywords = [
            "china", "chinese", "beijing", "xi jinping", "taiwan", "hong kong",
            "south china sea", "dprk", "north korea", "asia", "indo-pacific",
            "fentanyl", "pandemic"
        ]
        
        is_china_relevant = any(keyword in title_lower for keyword in china_keywords)
        
        if not is_china_relevant:
            logger.info(f"GHPC - Nicht China-relevant: {title[:50]}...")
            continue
        
        # Suche nach Links (flexibel für verschiedene Typen)
        next_link = None
        
        # Methode 1: Suche nach spezifischen Button-Texten
        current = title_element
        for _ in range(15):
            current = current.find_next()
            if not current:
                break
            
            if current.name == "a":
                link_text = current.get_text(strip=True).lower()
                href = current.get("href")
                
                # Erweiterte Link-Keywords (inkl. Videos & Transcripts)
                link_keywords = [
                    "read", "watch", "view", "listen", "download",
                    "transcript", "video", "learn more"
                ]
                
                if href and "csis.org" in href and any(kw in link_text for kw in link_keywords):
                    next_link = href
                    break
            
            # Suche in td-Elementen
            if current.name == "td":
                link = current.find("a", href=re.compile(r"csis\.org/(analysis|commentary|events|videos)"))
                if link:
                    next_link = link.get("href")
                    break
        
        # Methode 2: Fallback - suche nach beliebigem CSIS-Link
        if not next_link:
            all_links = soup.find_all("a", href=re.compile(r"csis\.org/(analysis|commentary|events|videos)"))
            if all_links:
                next_link = all_links[0].get("href")
                logger.info(f"GHPC - Fallback-Link gefunden")
        
        if next_link:
            # Pardot-URL auflösen
            final_url = resolve_tracking_url(next_link)
            
            formatted_article = f"• [{title}]({final_url})"
            articles.append(formatted_article)
            logger.info(f"GHPC - Artikel hinzugefügt: {title[:50]}...")
        else:
            logger.warning(f"GHPC - Kein Link für Titel gefunden: {title[:40]}...")
    
    logger.info(f"GHPC Parser - {len(articles)} Artikel extrahiert")
    return articles

def fetch_ghpc_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS Global Health Policy Center Newsletter aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "GHPC@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS GHPC: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"GHPC - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_ghpc_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS Global Health Policy Center: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_ghpc_emails: {str(e)}")
        return [], 0

def parse_aerospace_email(msg):
    """
    Spezialisierter Parser für CSIS Aerospace Security Project Newsletter.
    Extrahiert Artikel, Events und Videos mit China-Bezug.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Aerospace - Betreff: {subject}")
    
    # Event-Invites überspringen
    if any(keyword in subject.lower() for keyword in ["event invite", "join us", "register here", "rsvp"]):
        logger.info("Aerospace - Event Invite übersprungen")
        return articles
    
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
        logger.warning("Keine HTML-Inhalte in Aerospace E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde alle großen Titel (em_text4, em_text3, em_text5)
    title_elements = soup.find_all("td", class_=lambda x: x and any(cls in x for cls in ["em_text4", "em_text3", "em_text5"]))
    
    logger.info(f"Aerospace Parser - {len(title_elements)} Titel-Elemente gefunden")
    
    seen_titles = set()
    
    for title_element in title_elements:
        title = title_element.get_text(strip=True)
        title = re.sub(r'\s+', ' ', title)  # Mehrfache Leerzeichen entfernen
        
        # Überspringe zu kurze Titel
        if len(title) < 20:
            logger.debug(f"Aerospace - Titel zu kurz: {title}")
            continue
        
        # Duplikats-Check
        if title in seen_titles:
            logger.debug(f"Aerospace - Duplikat: {title[:40]}...")
            continue
        
        seen_titles.add(title)
        
        # China-Relevanz prüfen
        title_lower = title.lower()
        china_keywords = [
            "china", "chinese", "beijing", "xi jinping", "taiwan", "hong kong",
            "south china sea", "pla", "people's liberation army", "asia", "indo-pacific"
        ]
        
        is_china_relevant = any(keyword in title_lower for keyword in china_keywords)
        
        if not is_china_relevant:
            logger.info(f"Aerospace - Nicht China-relevant: {title[:50]}...")
            continue
        
        # Suche nach Links (flexibel für verschiedene Typen)
        next_link = None
        
        # Methode 1: Suche nach spezifischen Button-Texten
        current = title_element
        for _ in range(15):
            current = current.find_next()
            if not current:
                break
            
            if current.name == "a":
                link_text = current.get_text(strip=True).lower()
                href = current.get("href")
                
                # Erweiterte Link-Keywords
                link_keywords = [
                    "read", "watch", "view", "listen", "download",
                    "register", "learn more", "rsvp"
                ]
                
                if href and "csis.org" in href and any(kw in link_text for kw in link_keywords):
                    next_link = href
                    break
            
            # Suche in td-Elementen
            if current.name == "td":
                link = current.find("a", href=re.compile(r"csis\.org/(analysis|commentary|events|videos)"))
                if link:
                    next_link = link.get("href")
                    break
        
        # Methode 2: Fallback - suche nach beliebigem CSIS-Link
        if not next_link:
            all_links = soup.find_all("a", href=re.compile(r"csis\.org/(analysis|commentary|events|videos)"))
            if all_links:
                next_link = all_links[0].get("href")
                logger.info(f"Aerospace - Fallback-Link gefunden")
        
        if next_link:
            # Pardot-URL auflösen
            final_url = resolve_tracking_url(next_link)
            
            formatted_article = f"• [{title}]({final_url})"
            articles.append(formatted_article)
            logger.info(f"Aerospace - Artikel hinzugefügt: {title[:50]}...")
        else:
            logger.warning(f"Aerospace - Kein Link für Titel gefunden: {title[:40]}...")
    
    logger.info(f"Aerospace Parser - {len(articles)} Artikel extrahiert")
    return articles

def fetch_aerospace_emails(mail, email_user, email_password, days=None):
    """
    Holt CSIS Aerospace Security Project Newsletter aus E-Mails.
    """
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
    
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "defenseoutreach@csis.org"
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CSIS Aerospace: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Aerospace - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_aerospace_email(msg)
            
            # Duplikate filtern
            for article in articles:
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"CSIS Aerospace Security Project: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_aerospace_emails: {str(e)}")
        return [], 0

def deduplicate_csis_articles(*article_lists):
    """
    Entfernt Duplikate aus allen CSIS Newsletter-Listen.
    Behält die erste Instanz jedes Artikels.
    
    Args:
        *article_lists: Variable Anzahl von Artikel-Listen
    
    Returns:
        Tuple der deduplizierten Listen in der gleichen Reihenfolge
    """
    seen_urls = set()
    deduplicated_lists = []
    
    for article_list in article_lists:
        deduplicated = []
        
        for article in article_list:
            # URL aus Markdown-Link extrahieren
            url_match = re.search(r'\((https?://[^\)]+)\)', article)
            
            if url_match:
                url = url_match.group(1)
                
                if url not in seen_urls:
                    deduplicated.append(article)
                    seen_urls.add(url)
                else:
                    logger.info(f"CSIS Duplikat entfernt: {article[:60]}...")
            else:
                # Kein URL gefunden, behalte Artikel
                deduplicated.append(article)
        
        deduplicated_lists.append(deduplicated)
    
    return tuple(deduplicated_lists)

def main():
    logger.info("Starte Think Tanks Skript (MERICS + CSIS)")
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        logger.error("SUBSTACK_MAIL Umgebungsvariable nicht gefunden")
        return

    try:
        mail_config = dict(pair.split("=", 1) for pair in substack_mail.split(";") if "=" in pair)
        email_user = mail_config.get("GMAIL_USER")
        email_password = mail_config.get("GMAIL_PASS")
        if not email_user or not email_password:
            logger.error("GMAIL_USER oder GMAIL_PASS fehlt in SUBSTACK_MAIL")
            return
    except Exception as e:
        logger.error(f"Fehler beim Parsen von SUBSTACK_MAIL: {str(e)}")
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
        # MERICS (nutzt GLOBAL_THINKTANK_DAYS)
        merics_articles, merics_count = fetch_merics_emails(mail, email_user, email_password)
        
        # CSIS Geopolitics (nutzt GLOBAL_THINKTANK_DAYS)
        csis_geo_articles, csis_geo_count = fetch_csis_geopolitics_emails(mail, email_user, email_password)
        
        # CSIS Freeman Chair (nutzt GLOBAL_THINKTANK_DAYS)
        csis_freeman_articles, csis_freeman_count = fetch_csis_freeman_emails(mail, email_user, email_password)
        
        # CSIS Trustee Chair (nutzt GLOBAL_THINKTANK_DAYS)
        csis_trustee_articles, csis_trustee_count = fetch_csis_trustee_emails(mail, email_user, email_password)
        
        # CSIS Japan Chair (nutzt GLOBAL_THINKTANK_DAYS)
        csis_japan_articles, csis_japan_count = fetch_csis_japan_emails(mail, email_user, email_password)
        
        # CSIS China Power (nutzt GLOBAL_THINKTANK_DAYS)
        chinapower_articles, chinapower_count = fetch_chinapower_emails(mail, email_user, email_password)
        
        # CSIS Korea Chair (nutzt GLOBAL_THINKTANK_DAYS)
        korea_chair_articles, korea_chair_count = fetch_korea_chair_emails(mail, email_user, email_password)
        
        # CSIS Global Health Policy Center (nutzt GLOBAL_THINKTANK_DAYS)
        ghpc_articles, ghpc_count = fetch_ghpc_emails(mail, email_user, email_password)
        
        # CSIS Aerospace Security Project (nutzt GLOBAL_THINKTANK_DAYS)
        aerospace_articles, aerospace_count = fetch_aerospace_emails(mail, email_user, email_password)
        
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
    
    # CSIS Trustee Chair
    briefing.append("")
    briefing.append("#### Trustee Chair in Chinese Business & Economics")
    if csis_trustee_articles:
        briefing.extend(csis_trustee_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    # CSIS Japan Chair
    briefing.append("")
    briefing.append("#### Japan Chair")
    if csis_japan_articles:
        briefing.extend(csis_japan_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    # CSIS China Power
    briefing.append("")
    briefing.append("#### China Power")
    if chinapower_articles:
        briefing.extend(chinapower_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    # CSIS Korea Chair
    briefing.append("")
    briefing.append("#### Korea Chair")
    if korea_chair_articles:
        briefing.extend(korea_chair_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    # CSIS Global Health Policy Center
    briefing.append("")
    briefing.append("#### Global Health Policy Center")
    if ghpc_articles:
        briefing.extend(ghpc_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    # CSIS Aerospace Security Project
    briefing.append("")
    briefing.append("#### Aerospace Security Project")
    if aerospace_articles:
        briefing.extend(aerospace_articles)
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
