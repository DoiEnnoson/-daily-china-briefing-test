import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
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
GLOBAL_THINKTANK_DAYS = 60  # Test: 60 Tage

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
    Nutzt TITEL-LINKS statt Button-Links.
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
        "speaker",
        "subscribe"  # Podcast subscribe button
    ]
    
    # Button-Texte (diese Links ignorieren)
    button_texts = ["read here", "listen here", "watch here", "subscribe", "visit our microsite"]
    
    # Finde alle Links
    all_links = soup.find_all("a", href=True)
    seen_titles = set()
    
    logger.info(f"Trustee Chair Parser - {len(all_links)} Links gefunden")
    
    for link in all_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True)
        
        # DEBUG: Zeige ALLE Links
        has_img = link.find("img") is not None
        logger.debug(f"Trustee Chair - Link gefunden: href={href[:60]}, text='{link_text[:50]}', has_img={has_img}")
        
        # Skip Links die nur Bilder enthalten (keine Text-Links)
        if link.find("img") and not link_text:
            logger.info(f"Trustee Chair - 🖼️ BILD-LINK GESKIPPT: {href[:60]}")
            continue
        
        # Skip Button-Links sofort
        if any(btn in link_text.lower() for btn in button_texts):
            logger.debug(f"Trustee Chair - Button übersprungen: {link_text}")
            continue
        
        # Muss ein CSIS/Pardot Link sein
        if "csis.org" not in href and "pardot.csis.org" not in href:
            continue
        
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
        
        # TITEL DIREKT AUS LINK-TEXT
        title = link_text
        
        # Titel muss mindestens 30 Zeichen haben
        if len(title) < 30:
            logger.debug(f"Trustee Chair - Zu kurz: {title}")
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
        
        # 3. Duplikats-Check
        if title in seen_titles:
            logger.debug(f"Trustee Chair - Duplikat: {title[:40]}...")
            continue
        
        seen_titles.add(title)
        
        # 4. Bereinige Titel von Datumsangaben am Ende
        title = re.sub(r',?\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d+,?\s+\d{4}$', '', title)
        
        # Resolve Tracking URL
        resolved_url = resolve_tracking_url(href)
        
        formatted_article = f"• [{title}]({resolved_url})"
        articles.append(formatted_article)
        logger.info(f"Trustee Chair - ✅ ARTIKEL HINZUGEFÜGT: {title[:50]}... | URL: {resolved_url[:60]}")
    
    # Sortiere: Videos/Podcasts ans Ende (Gmail rendert YouTube-Thumbnails automatisch)
    video_articles = []
    text_articles = []
    
    for article in articles:
        # Erkenne Video/Podcast-Links
        if any(domain in article.lower() for domain in ["youtube.com", "youtu.be", "podcasts.apple.com", "spotify.com"]):
            video_articles.append(article)
        else:
            text_articles.append(article)
    
    # Kombiniere: Text zuerst, dann Videos/Podcasts
    sorted_articles = text_articles + video_articles
    
    logger.info(f"Trustee Chair Parser - {len(sorted_articles)} Artikel extrahiert ({len(text_articles)} Text, {len(video_articles)} Video/Podcast)")
    logger.info(f"Trustee Chair - FINALE ARTIKEL-LISTE:")
    for idx, article in enumerate(sorted_articles, 1):
        logger.info(f"  {idx}. {article[:80]}...")
    return sorted_articles

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

# ============================================================================
# BROOKINGS CHINA CENTER PARSER
# ============================================================================

def parse_brookings_email(msg):
    """
    Spezialisierter Parser für Brookings China Center Newsletter.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Brookings - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in Brookings E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    headings = soup.find_all(['h1', 'h2'])
    
    seen_urls = set()
    current_section = None
    
    for heading in headings:
        heading_text = heading.get_text(strip=True)
        
        # Identifiziere Sektions-Überschriften
        if not heading.find('a') and len(heading_text) > 10:
            section_keywords = [
                "developments in", "chinese domestic", "china's foreign policy",
                "technology, ai, and energy", "about the china center"
            ]
            
            if any(kw in heading_text.lower() for kw in section_keywords):
                current_section = heading_text
                logger.info(f"Brookings - Neue Sektion: {current_section}")
                continue
        
        # Suche nach verlinkten Artikeln
        link = heading.find('a', href=True)
        if not link:
            continue
        
        title = link.get_text(strip=True)
        url = link.get('href', '')
        
        # Überspringe zu kurze Titel
        if len(title) < 20:
            continue
        
        # Überspringe Navigation/Footer Links
        skip_patterns = [
            "view in browser", "unsubscribe", "manage newsletter",
            "x/twitter", "facebook", "instagram", "linkedin",
            "read his introductory", "watch the recording",
            "brookings institution", "john l. thornton china center"
        ]
        
        if any(pattern in title.lower() for pattern in skip_patterns):
            continue
        
        # Duplikats-Check
        if url in seen_urls:
            continue
        seen_urls.add(url)
        
        # China-Relevanz-Check
        china_keywords = [
            "china", "chinese", "xi jinping", "beijing", "taiwan",
            "hong kong", "us-china", "sino-", "prc", "communist party"
        ]
        
        is_china_relevant = any(keyword in title.lower() for keyword in china_keywords)
        
        if not is_china_relevant:
            if current_section and any(kw in current_section.lower() for kw in ["china", "us-china"]):
                is_china_relevant = True
        
        if not is_china_relevant:
            logger.info(f"Brookings - Nicht China-relevant: {title}")
            continue
        
        formatted_article = f"• [{title}]({url})"
        articles.append(formatted_article)
        logger.info(f"Brookings - Artikel hinzugefügt: {title[:50]}...")
    
    logger.info(f"Brookings Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_brookings_emails(mail, email_user, email_password, days=None):
    """Holt Brookings China Center Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "chinacenter@brookings.edu"
        
        logger.info(f"Brookings - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für Brookings: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Brookings - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_brookings_email(msg)
            all_articles.extend(articles)
        
        logger.info(f"Brookings China Center: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_brookings_emails: {str(e)}")
        return [], 0

# ============================================================================
# ENDE BROOKINGS PARSER
# ============================================================================

# ============================================================================
# PIIE (PETERSON INSTITUTE) PARSER
# ============================================================================

def parse_piie_email(msg):
    """
    Spezialisierter Parser für PIIE Insider Newsletter.
    Extrahiert Artikel mit China-Bezug, filtert Events raus.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"PIIE - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in PIIE E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde alle H2 Überschriften (Artikel-Titel)
    h2_elements = soup.find_all("h2")
    
    logger.info(f"PIIE Parser - {len(h2_elements)} H2 Elemente gefunden")
    
    seen_titles = set()
    
    for h2 in h2_elements:
        # Suche nach Link im H2
        link = h2.find("a", href=True)
        if not link:
            continue
        
        title = link.get_text(strip=True)
        url = link.get("href", "")
        
        # Überspringe zu kurze Titel
        if len(title) < 20:
            logger.debug(f"PIIE - Titel zu kurz: {title}")
            continue
        
        # Event-Filter (sehr wichtig!)
        event_keywords = [
            "event", "watch", "join us", "register", "rsvp",
            "rebuilding and realignment", "is it time for africa"
        ]
        
        if any(kw in title.lower() for kw in event_keywords):
            logger.info(f"PIIE - Event gefiltert: {title[:50]}...")
            continue
        
        # Section-Header überspringen
        section_headers = [
            "recent publications", "piie charts", "events",
            "piie in the news", "insider exclusive", "policy for the planet",
            "piie insider live"
        ]
        
        if any(header in title.lower() for header in section_headers):
            logger.debug(f"PIIE - Section Header übersprungen: {title}")
            continue
        
        # Footer-Links überspringen
        skip_patterns = [
            "unsubscribe", "manage preferences", "update your profile",
            "view web version", "peterson institute for international economics"
        ]
        
        if any(pattern in title.lower() for pattern in skip_patterns):
            continue
        
        # Duplikats-Check
        if title in seen_titles:
            logger.debug(f"PIIE - Duplikat: {title[:40]}...")
            continue
        
        seen_titles.add(title)
        
        # China-Relevanz prüfen
        china_keywords = [
            "china", "chinese", "xi jinping", "beijing", "taiwan",
            "hong kong", "us-china", "sino-", "prc", "yuan",
            "renminbi", "shanghai", "asia", "indo-pacific"
        ]
        
        is_china_relevant = any(keyword in title.lower() for keyword in china_keywords)
        
        if not is_china_relevant:
            logger.info(f"PIIE - Nicht China-relevant: {title[:50]}...")
            continue
        
        # Resolve Tracking URL
        final_url = resolve_tracking_url(url)
        
        # Formatiere Artikel (ohne Autor)
        formatted_article = f"• [{title}]({final_url})"
        
        articles.append(formatted_article)
        logger.info(f"PIIE - Artikel hinzugefügt: {title[:50]}...")
    
    logger.info(f"PIIE Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_piie_emails(mail, email_user, email_password, days=None):
    """Holt PIIE Insider Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "insider@piie.com"
        
        logger.info(f"PIIE - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für PIIE: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"PIIE - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_piie_email(msg)
            all_articles.extend(articles)
        
        logger.info(f"PIIE: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_piie_emails: {str(e)}")
        return [], 0

# ============================================================================
# ENDE PIIE PARSER
# ============================================================================

# ============================================================================
# CFR (COUNCIL ON FOREIGN RELATIONS) PARSER - DAILY BRIEF
# ============================================================================

def parse_cfr_daily_brief(msg):
    """
    Parser für CFR Daily News Brief.
    Extrahiert NUR China-relevante Artikel aus den grauen Boxen.
    Ignoriert: Top of Agenda, Across the Globe, What's Next, Videos
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"CFR Daily Brief - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in CFR Daily Brief gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde graue Boxen (border: 1px solid #969da7)
    # Diese Boxen enthalten die Artikel-Links
    bordered_sections = soup.find_all("td", style=lambda x: x and "border" in x and "#969da7" in x)
    
    logger.info(f"CFR Daily Brief Parser - {len(bordered_sections)} graue Boxen gefunden")
    
    seen_titles = set()
    
    for section in bordered_sections:
        # Finde Titel (großer Link)
        title = ""
        url = ""
        
        # Suche nach dem ersten großen Link
        links = section.find_all("a", href=True)
        for link in links:
            # Überspringe Bild-Links
            if link.find("img"):
                continue
            
            link_text = link.get_text(strip=True)
            href = link.get("href", "")
            
            # Überspringe Links ohne URL oder zu kurze Links
            if not href or len(link_text) < 15:
                continue
            
            # Prüfe ob es ein echter Artikel-Link ist (kein Bildcredit)
            # Bildcredits haben oft "/" oder "Getty" im Text
            if "/" in link_text or "getty" in link_text.lower() or "afp" in link_text.lower():
                continue
            
            # Prüfe ob Link groß genug ist (vermutlich Titel)
            if len(link_text) > 15:
                title = link_text
                url = href
                break
        
        if not title or not url:
            continue
        
        # KEINE erweiterte Titel-Suche mehr - nur der Link-Text zählt!
        # Beschreibungen sind zu lang und nicht hilfreich
        
        # Überspringe YouTube Shorts / Videos
        if "youtube.com" in url or "youtu.be" in url:
            logger.debug(f"CFR Daily Brief - YouTube Link übersprungen: {title[:40]}...")
            continue
        
        # Überspringe zu kurze Titel
        if len(title) < 20:
            logger.debug(f"CFR Daily Brief - Titel zu kurz: {title}")
            continue
        
        # Duplikats-Check
        if title in seen_titles:
            logger.debug(f"CFR Daily Brief - Duplikat: {title[:40]}...")
            continue
        
        seen_titles.add(title)
        
        # China-Relevanz prüfen - NUR im Titel, NICHT in Beschreibung
        china_keywords = [
            "china", "chinese", "xi jinping", "xi ", "beijing", "taiwan",
            "hong kong", "hongkong", "us-china", "sino-", "prc", "yuan",
            "renminbi", "shanghai", "ccp", "communist party", "cpc"
        ]
        
        # Prüfe NUR den Titel
        is_china_relevant = any(keyword in title.lower() for keyword in china_keywords)
        
        # Spezielle Ausnahme: "Council Special Report" ist manchmal relevant
        # wenn der E-Mail-Betreff China erwähnt
        if not is_china_relevant and "council special report" in title.lower():
            # Prüfe ob Betreff China-relevant ist
            if any(kw in subject.lower() for kw in ["china", "beijing", "taiwan", "hong kong", "xi"]):
                is_china_relevant = True
        
        # Spezielle Ausnahmen für zu breite Matches
        # "Asia" alleine ist zu breit, außer es ist explizit "Asia-Pacific" oder mit China-Kontext
        if not is_china_relevant and "asia" in title.lower():
            # Nur relevant wenn es auch China/Taiwan/Hong Kong im Titel erwähnt
            if any(kw in title.lower() for kw in ["china", "chinese", "taiwan", "hong kong", "beijing", "shanghai"]):
                is_china_relevant = True
        
        # Filtere zu breite Artikel raus
        too_broad = [
            "all about the united nations",
            "what to know about the united nations",
            "what to know about palestinian",
            "major moments in un history"
        ]
        
        if any(broad in title.lower() for broad in too_broad):
            is_china_relevant = False
        
        if not is_china_relevant:
            logger.info(f"CFR Daily Brief - Nicht China-relevant: {title[:50]}...")
            continue
        
        # Resolve Tracking URL
        final_url = resolve_tracking_url(url)
        
        # Formatiere Artikel
        formatted_article = f"• [{title}]({final_url})"
        
        articles.append(formatted_article)
        logger.info(f"CFR Daily Brief - Artikel hinzugefügt: {title[:50]}...")
    
    logger.info(f"CFR Daily Brief Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_cfr_daily_brief(mail, email_user, email_password, days=None):
    """Holt CFR Daily Brief Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "dailybrief@cfr.org"
        
        logger.info(f"CFR Daily Brief - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CFR Daily Brief: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"CFR Daily Brief - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_cfr_daily_brief(msg)
            all_articles.extend(articles)
        
        logger.info(f"CFR Daily Brief: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_cfr_daily_brief: {str(e)}")
        return [], 0

# ============================================================================
# ENDE CFR DAILY BRIEF PARSER
# ============================================================================

# ============================================================================
# CFR EYES ON ASIA (ASIA STUDIES PROGRAM) PARSER
# ============================================================================

def parse_cfr_eyes_on_asia(msg):
    """
    Parser für CFR Eyes on Asia Newsletter (Asia Studies Program).
    Extrahiert NUR China-relevante Artikel aus dem Hauptbereich.
    Stoppt bei: "Asia Fellows in the News" oder "About the Asia Program"
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"CFR Eyes on Asia - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in CFR Eyes on Asia gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde Stop-Punkt Position im HTML (als String-Position)
    stop_phrases = ["asia fellows in the news", "about the asia program"]
    stop_position = len(html_content)  # Default: Ende des Dokuments
    
    for phrase in stop_phrases:
        pos = html_content.lower().find(phrase)
        if pos != -1 and pos < stop_position:
            stop_position = pos
            logger.info(f"CFR Eyes on Asia - Stop-Punkt '{phrase}' gefunden bei Position {pos}")
    
    # Finde alle Content-Links
    seen_titles = set()
    all_links = soup.find_all("a", href=True)
    
    logger.info(f"CFR Eyes on Asia - {len(all_links)} Links insgesamt gefunden")
    
    # Debug: Zähle CFR-Links
    cfr_links = [link for link in all_links if "cfr.org" in link.get("href", "")]
    logger.info(f"CFR Eyes on Asia - {len(cfr_links)} CFR-Links gefunden")
    
    # Debug: Zähle Content-Links (inkl. Tracking-Links!)
    content_paths = ["/article/", "/blog/", "/expert-brief/", "/backgrounder/", 
                    "/podcast/", "/opinion/", "/interactive/", "/report/"]
    
    # Tracking-Links: link.cfr.org/click/...
    content_links = []
    for link in cfr_links:
        href = link.get("href", "")
        # Entweder direkter Content-Link ODER Tracking-Link
        if any(path in href for path in content_paths) or "link.cfr.org/click" in href:
            content_links.append(link)
    
    logger.info(f"CFR Eyes on Asia - {len(content_links)} Content-Links gefunden (inkl. Tracking-Links)")
    
    for link in all_links:
        title = link.get_text(strip=True)
        url = link.get("href", "")
        
        # Nur CFR-Links
        if "cfr.org" not in url:
            continue
        
        # Check ob dieser Link NACH dem Stop-Punkt kommt
        # NEUE METHODE: Suche nach href im Original-HTML
        url_pos = html_content.find(url)
        
        if url_pos != -1 and url_pos >= stop_position:
            # Link ist nach Stop-Punkt, überspringe
            logger.debug(f"CFR Eyes on Asia - Link nach Stop-Punkt: {title[:30]}...")
            continue
        elif url_pos == -1:
            # URL nicht im HTML gefunden? Das ist verdächtig, aber nehmen wir ihn trotzdem
            logger.debug(f"CFR Eyes on Asia - URL nicht gefunden im HTML, nehme trotzdem: {title[:30]}...")
        
        # Filter 1: Überspringe Navigation/Footer
        if any(x in title.lower() for x in [
            "unsubscribe", "manage", "preferences", "view in browser", 
            "email preferences", "facebook", "twitter", "instagram", "linkedin",
            "youtube", "council on foreign relations"
        ]):
            continue
        
        # Filter 2: Nur Content-Links (entweder Tracking oder direkte Content-Pfade)
        is_content_link = False
        if "link.cfr.org/click" in url:
            is_content_link = True
        elif any(path in url for path in content_paths):
            is_content_link = True
        
        if not is_content_link:
            continue
        
        # Filter 4: Titel-Länge (Artikel haben lange Titel)
        if len(title) < 20:
            continue
        
        # Filter 5: Keine Image-Credits
        if any(x in title for x in ["/", "Getty", "AFP", "Reuters"]) and len(title) < 100:
            continue
        
        # Duplikats-Check
        if title in seen_titles:
            continue
        
        seen_titles.add(title)
        
        # China-Relevanz prüfen
        china_keywords = [
            "china", "chinese", "xi jinping", "xi ", "beijing", "taiwan",
            "hong kong", "hongkong", "us-china", "sino-", "prc", "yuan",
            "renminbi", "shanghai", "ccp", "communist party", "cpc", "asia-pacific",
            "apec", "asean"
        ]
        
        is_china_relevant = any(keyword in title.lower() for keyword in china_keywords)
        
        if not is_china_relevant:
            logger.info(f"CFR Eyes on Asia - Nicht China-relevant: {title[:50]}...")
            continue
        
        # Resolve Tracking URL
        final_url = resolve_tracking_url(url)
        
        # Formatiere Artikel
        formatted_article = f"• [{title}]({final_url})"
        
        articles.append(formatted_article)
        logger.info(f"CFR Eyes on Asia - Artikel hinzugefügt: {title[:50]}...")
    
    logger.info(f"CFR Eyes on Asia Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_cfr_eyes_on_asia(mail, email_user, email_password, days=None):
    """Holt CFR Eyes on Asia Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "jkurlantzick@cfr.org"
        
        logger.info(f"CFR Eyes on Asia - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CFR Eyes on Asia: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"CFR Eyes on Asia - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_cfr_eyes_on_asia(msg)
            all_articles.extend(articles)
        
        logger.info(f"CFR Eyes on Asia: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_cfr_eyes_on_asia: {str(e)}")
        return [], 0

# ============================================================================
# ENDE CFR EYES ON ASIA PARSER
# ============================================================================

# ============================================================================
# ASPI (ASIA SOCIETY POLICY INSTITUTE) - CHINA 5 PARSER
# ============================================================================

def parse_aspi_china5(msg):
    """
    Parser für ASPI China 5 Newsletter.
    Extrahiert die 5 wöchentlichen China-Stories.
    Format: Numbered sections (1-5) mit Titeln.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"ASPI China 5 - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in ASPI China 5 gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde alle H2 Tags (die Titel der 5 Stories)
    # Pattern: "1. [Title]", "2. [Title]", etc.
    all_h2 = soup.find_all("h2")
    
    for h2 in all_h2:
        title_text = h2.get_text(strip=True)
        
        # Prüfe ob es eine numbered section ist (z.B. "1. Bondholders Reject...")
        if not title_text:
            continue
        
        # Extrahiere Nummer und Titel
        # Pattern: "1. Title" oder "1.Title" oder "1. Title"
        import re
        match = re.match(r'^(\d+)\.\s*(.+)$', title_text)
        
        if not match:
            continue
        
        section_num = match.group(1)
        title = match.group(2).strip()
        
        # Überspringe wenn Titel zu kurz
        if len(title) < 10:
            continue
        
        # Finde den Link im H2 oder im nächsten <a> Tag
        link_tag = h2.find("a", href=True)
        
        # Wenn kein Link im H2, suche im Text danach
        if not link_tag:
            # Suche "For More" Link in der Section
            next_sibling = h2.find_next_sibling()
            counter = 0
            final_url = "#"
            
            # Durchsuche die nächsten Siblings für "For More" Link
            while next_sibling and counter < 10:
                if next_sibling.name and "for more" in next_sibling.get_text().lower():
                    for_more_link = next_sibling.find("a", href=True)
                    if for_more_link:
                        final_url = for_more_link.get("href", "#")
                        break
                next_sibling = next_sibling.find_next_sibling()
                counter += 1
        else:
            final_url = link_tag.get("href", "#")
        
        # Resolve Tracking URL
        final_url = resolve_tracking_url(final_url)
        
        # Formatiere Artikel
        formatted_article = f"• [{title}]({final_url})"
        
        articles.append(formatted_article)
        logger.info(f"ASPI China 5 - Section {section_num} hinzugefügt: {title[:50]}...")
    
    logger.info(f"ASPI China 5 Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_aspi_china5(mail, email_user, email_password, days=None):
    """Holt ASPI China 5 Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "policyinstitute@asiasociety.org"
        
        logger.info(f"ASPI China 5 - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        # Suche nach "China 5" im Betreff
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date} SUBJECT "China 5"')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für ASPI China 5: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine 'China 5' E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"ASPI China 5 - {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_aspi_china5(msg)
            all_articles.extend(articles)
        
        logger.info(f"ASPI China 5: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_aspi_china5: {str(e)}")
        return [], 0

# ============================================================================
# ENDE ASPI CHINA 5 PARSER
# ============================================================================

# ============================================================================
# CHATHAM HOUSE PARSER
# ============================================================================

def parse_chatham_house(msg):
    """
    Parser für Chatham House Newsletter.
    Extrahiert H1-basierte Artikel mit China-Relevanz.
    Format: H1 Titel + "Read the expert comment/research paper" Link.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Chatham House - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in Chatham House gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Finde alle H1-ähnlichen Tags (echte H1 + P mit class="h1")
    all_h1 = soup.find_all("h1")
    all_h1 += soup.find_all("p", class_="h1")  # Chatham House nutzt <p class="h1">
    
    for h1 in all_h1:
        title_text = h1.get_text(strip=True)
        
        if not title_text or len(title_text) < 10:
            continue
        
        # China-Relevanz prüfen
        china_keywords = [
            "china", "chinese", "xi jinping", "xi ", "beijing", "taiwan",
            "hong kong", "hongkong", "renminbi", "yuan", "shanghai", 
            "ccp", "communist party", "cpc", "prc", "south china sea"
        ]
        
        is_china_relevant = any(keyword in title_text.lower() for keyword in china_keywords)
        
        if not is_china_relevant:
            logger.info(f"Chatham House - Nicht China-relevant: {title_text[:50]}...")
            continue
        
        # Finde den zugehörigen Link
        # Suche nach "Read the expert comment" / "Read the research paper"
        parent = h1.find_parent()
        if not parent:
            continue
        
        next_link = None
        
        # Suche in den nächsten Siblings nach Link mit "Read"
        for sibling in parent.find_all_next(limit=20):
            link_tag = sibling.find("a", href=True)
            if link_tag:
                link_text = link_tag.get_text(strip=True).lower()
                if "read" in link_text and ("comment" in link_text or "paper" in link_text or "release" in link_text):
                    next_link = link_tag.get("href", "")
                    break
        
        if not next_link:
            next_link = "#"
        
        # Resolve Tracking URL
        final_url = resolve_tracking_url(next_link)
        
        # Formatiere Artikel
        formatted_article = f"• [{title_text}]({final_url})"
        
        articles.append(formatted_article)
        logger.info(f"Chatham House - Artikel hinzugefügt: {title_text[:50]}...")
    
    logger.info(f"Chatham House Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_chatham_house(mail, email_user, email_password, days=None):
    """Holt Chatham House Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "ch@email-chathamhouse.org"
        
        logger.info(f"Chatham House - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für Chatham House: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine Chatham House E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Chatham House - {len(email_ids)} E-Mails gefunden")
        
        # Deduplizierung innerhalb Chatham House (da gleiche Artikel in mehreren Newslettern)
        seen_chatham_titles = set()
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_chatham_house(msg)
            
            # Dedupliziere nach TITEL (Tracking-URLs sind unterschiedlich)
            for article in articles:
                title_match = re.search(r'\[([^\]]+)\]', article)
                if title_match:
                    title = title_match.group(1).lower().strip()
                    if title not in seen_chatham_titles:
                        all_articles.append(article)
                        seen_chatham_titles.add(title)
                else:
                    all_articles.append(article)
        
        logger.info(f"Chatham House: {len(all_articles)} Artikel gefunden (nach interner Deduplizierung)")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_chatham_house: {str(e)}")
        return [], 0

# ============================================================================
# ENDE CHATHAM HOUSE PARSER
# ============================================================================

# ============================================================================
# LOWY INSTITUTE (THE INTERPRETER) PARSER
# ============================================================================

def parse_lowy_interpreter(msg):
    """
    Parser für Lowy Institute "The Interpreter" Newsletter.
    Extrahiert Artikel mit China-Relevanz.
    Format: Featured + Recent articles gruppiert nach Tagen.
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Lowy Institute - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in Lowy Institute gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # China-Relevanz Keywords
    china_keywords = [
        "china", "chinese", "xi jinping", "xi ", "beijing", "taiwan",
        "hong kong", "hongkong", "shanghai", "prc", "south china sea",
        "indo-pacific", "asia-pacific"
    ]
    
    # Finde alle Links in der E-Mail
    all_links = soup.find_all("a", href=True)
    
    for link in all_links:
        href = link.get("href", "")
        title = link.get_text(strip=True)
        
        # Skip Header/Footer/Social Links
        if not href:
            continue
        # Skip unsubscribe/preferences/social
        if any(skip in href.lower() for skip in ["unsubscribe", "preferences", "linkedin", "twitter", "facebook", "bluesky", "youtube", "rss"]):
            continue
        # Skip short/empty titles
        if not title or len(title) < 15:
            continue
        # Skip author names (usually short, no punctuation)
        if len(title) < 40 and ":" not in title and "?" not in title:
            continue
        
        # China-Relevanz prüfen
        is_china_relevant = any(keyword in title.lower() for keyword in china_keywords)
        
        if not is_china_relevant:
            logger.info(f"Lowy - Nicht China-relevant: {title[:50]}...")
            continue
        
        # HubSpot/Tracking URLs direkt verwenden (redirecten automatisch)
        final_url = href
        
        # Formatiere Artikel
        formatted_article = f"• [{title}]({final_url})"
        
        articles.append(formatted_article)
        logger.info(f"Lowy - Artikel hinzugefügt: {title[:50]}...")
    
    logger.info(f"Lowy Institute Parser - {len(articles)} Artikel extrahiert")
    return articles


def score_thinktank_article(title, content=""):
    """
    Bewertet einen Think Tank-Artikel auf China-Relevanz.
    Generische Version für alle Think Tanks.
    """
    title_lower = title.lower()
    content_lower = content.lower()
    full_text = f"{title_lower} {content_lower}"
    
    # MUSS China-Bezug haben
    china_keywords = [
        "china", "chinese", "xi jinping", "xi", "beijing", "shanghai",
        "taiwan", "hong kong", "prc", "ccp", "communist party",
        "sino-", "u.s.-china", "us-china", "asia-pacific", "indo-pacific"
    ]
    
    if not any(kw in full_text for kw in china_keywords):
        return 0
    
    score = 5  # Basis-Score für China-Erwähnung
    
    # Wichtige Themen
    important_topics = [
        "technology", "trade", "security", "military", "defense",
        "economy", "tariff", "semiconductor", "ai", "geopolitics",
        "south china sea", "strait", "policy", "investment", "fdi"
    ]
    
    for topic in important_topics:
        if topic in full_text:
            score += 2
    
    return max(score, 0)


def parse_hinrich_foundation(msg):
    """
    Parser für Hinrich Foundation Newsletter.
    Extrahiert China-relevante Artikel aus thematischen Newsletters.
    """
    articles = []
    seen_titles = set()
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Hinrich Foundation - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in Hinrich Foundation E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # STRATEGIE 1: Finde alle <h1>, <h2>, <h3> Tags (Hinrich nutzt verschiedene)
    for heading in soup.find_all(['h1', 'h2', 'h3']):
        title = heading.get_text(strip=True)
        
        # Skip zu kurze oder leere Titel
        if not title or len(title) < 10:
            continue
        
        # Skip Duplikate
        if title in seen_titles:
            continue
        
        # Sammle Beschreibungstext nach dem Heading (für besseren China-Check)
        description = ""
        next_elem = heading.find_next(['p', 'h1', 'h2', 'h3'])
        if next_elem and next_elem.name == 'p':
            description = next_elem.get_text(strip=True)[:300]  # Max 300 Zeichen
        
        # Finde den zugehörigen Link
        link_tag = None
        current = heading
        
        # Suche in den nächsten 15 Elementen nach einem relevanten Link
        for _ in range(15):
            current = current.find_next(['a', 'h1', 'h2', 'h3'])
            if not current:
                break
            
            # Stoppe bei nächstem Heading (neuer Artikel beginnt)
            if current.name in ['h1', 'h2', 'h3']:
                break
            
            # Prüfe ob es ein relevanter Link ist
            if current.name == 'a' and current.get('href'):
                href = current.get('href')
                link_text = current.get_text(strip=True).upper()
                
                # Akzeptiere verschiedene Link-Texte
                if any(keyword in link_text for keyword in ['READ', 'REGISTER', 'ACCESS', 'WATCH', 'VIEW', 'LEARN']):
                    link_tag = current
                    break
                
                # ODER: Akzeptiere Links zu hinrichfoundation.com (auch ohne Button-Text)
                if 'hinrichfoundation.com' in href and 'unsubscribe' not in href.lower():
                    link_tag = current
                    break
        
        if link_tag and link_tag.get('href'):
            href = link_tag['href']
            
            # Überspringe interne Links (preferences, unsubscribe, etc.)
            if any(skip in href.lower() for skip in ['unsubscribe', 'preferences', 'mailto:', '#']):
                continue
            
            # China-Check (Titel ODER Beschreibung)
            china_keywords = [
                "china", "chinese", "xi jinping", "xi", "beijing", "shanghai",
                "taiwan", "hong kong", "prc", "ccp", "communist party",
                "sino-", "u.s.-china", "us-china"
            ]
            
            title_lower = title.lower()
            desc_lower = description.lower()
            content = f"{title_lower} {desc_lower}"
            has_china = any(kw in content for kw in china_keywords)
            
            if has_china:
                articles.append(f"• [{title}]({href})")
                seen_titles.add(title)
                logger.info(f"Hinrich - Artikel hinzugefügt: {title[:60]}...")
            else:
                logger.info(f"Hinrich - Kein China-Bezug, übersprungen: {title[:60]}...")
    
    logger.info(f"Hinrich Foundation Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_hinrich_foundation(mail, email_user, email_password, days=None):
    """Holt Hinrich Foundation Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        # Lade thinktanks.json um die richtige E-Mail-Adresse zu bekommen
        thinktanks_path = os.path.join(os.path.dirname(__file__), "thinktanks.json")
        with open(thinktanks_path, "r", encoding="utf-8") as f:
            thinktanks = json.load(f)
        
        # Finde Hinrich Foundation
        hinrich = next((tt for tt in thinktanks if tt["abbreviation"] == "Hinrich"), None)
        if not hinrich or not hinrich["email_senders"]:
            logger.warning("Hinrich Foundation nicht in thinktanks.json gefunden oder keine Sender angegeben")
            return [], 0
        
        # Extrahiere E-Mail-Adresse (mit oder ohne "Name <email>" Format)
        sender_raw = hinrich["email_senders"][0]
        # Extrahiere aus "Name <email@domain.com>" Format
        email_match = re.search(r'<(.+?)>', sender_raw)
        sender_email = email_match.group(1) if email_match else sender_raw
        
        logger.info(f"Hinrich Foundation - Extrahierte E-Mail: {sender_email}")
        
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        
        logger.info(f"Hinrich Foundation - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für Hinrich Foundation: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine Hinrich Foundation E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Hinrich Foundation - {len(email_ids)} E-Mails gefunden")
        
        # Deduplizierung nach TITEL
        seen_titles = set()
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            parsed_articles = parse_hinrich_foundation(msg)
            
            # Deduplizierung: Nur neue Artikel hinzufügen
            for article in parsed_articles:
                # Extrahiere Titel aus Markdown-Link
                title_match = article.split('[')[1].split(']')[0] if '[' in article and ']' in article else article
                if title_match not in seen_titles:
                    all_articles.append(article)
                    seen_titles.add(title_match)
        
        logger.info(f"Hinrich Foundation - FINAL: {len(all_articles)} Artikel (nach Dedup)")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_hinrich_foundation: {str(e)}")
        return [], 0


def parse_crea_energy(msg):
    """
    Parser für CREA (Centre for Research on Energy and Clean Air).
    Extrahiert monatliche China Energy & Emissions Reports.
    ALLE Artikel sind China-relevant (100% China-fokussiert).
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"CREA - Betreff: {subject}")
    
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
        logger.warning("Keine HTML-Inhalte in CREA E-Mail gefunden")
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # DEBUG: Zähle alle Links
    all_links = soup.find_all('a', href=True)
    logger.info(f"CREA DEBUG - Gefundene Links insgesamt: {len(all_links)}")
    
    # CREA nutzt Button-Links mit spezifischem Text
    # Beispiel: "China energy and emissions trends: February 2026 snapshot"
    # Zwei Haupttypen: Monatlicher Snapshot + Monthly Roundup mit mehreren Sektionen
    
    links_processed = 0
    links_skipped_internal = 0
    links_skipped_short = 0
    links_skipped_no_energyandcleanair = 0
    links_skipped_no_china = 0
    links_skipped_chinese = 0
    
    for link in all_links:
        href = link.get('href')
        title = link.get_text(strip=True)
        
        links_processed += 1
        
        # DEBUG: Zeige jeden Link
        logger.debug(f"CREA DEBUG Link {links_processed}: '{title[:50]}...' -> {href[:60]}...")
        
        # Skip interne Links
        if any(skip in href.lower() for skip in ['unsubscribe', 'preferences', 'mailto:', 'track/open', 'vcard', 'profile']):
            links_skipped_internal += 1
            logger.debug(f"CREA DEBUG - Skip internal: {href[:40]}")
            continue
        
        # Skip kurze/leere Titel
        if not title or len(title) < 15:
            links_skipped_short += 1
            logger.debug(f"CREA DEBUG - Skip short title: '{title}'")
            continue
        
        # Nur Links zu energyandcleanair.org Reports
        if 'energyandcleanair.org' not in href:
            links_skipped_no_energyandcleanair += 1
            logger.debug(f"CREA DEBUG - Skip nicht energyandcleanair.org: {href[:40]}")
            continue
            
        # Check für "china" im URL oder Titel
        if 'china' not in href.lower() and 'china' not in title.lower():
            links_skipped_no_china += 1
            logger.debug(f"CREA DEBUG - Skip kein 'china': '{title}' | {href}")
            continue
        
        # Skip chinesische Version (Duplikat)
        if '🇨🇳' in title or '/zh/' in href:
            links_skipped_chinese += 1
            logger.debug(f"CREA DEBUG - Skip chinesische Version: {title[:40]}...")
            continue
        
        articles.append(f"• [{title}]({href})")
        logger.info(f"CREA - Artikel hinzugefügt: {title[:60]}...")
    
    logger.info(f"CREA DEBUG - Links verarbeitet: {links_processed}")
    logger.info(f"CREA DEBUG - Skip internal: {links_skipped_internal}")
    logger.info(f"CREA DEBUG - Skip short: {links_skipped_short}")
    logger.info(f"CREA DEBUG - Skip no energyandcleanair.org: {links_skipped_no_energyandcleanair}")
    logger.info(f"CREA DEBUG - Skip no china: {links_skipped_no_china}")
    logger.info(f"CREA DEBUG - Skip chinese: {links_skipped_chinese}")
    logger.info(f"CREA Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_crea_energy(mail, email_user, email_password, days=None):
    """Holt CREA Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        # Lade thinktanks.json um die richtige E-Mail-Adresse zu bekommen
        thinktanks_path = os.path.join(os.path.dirname(__file__), "thinktanks.json")
        with open(thinktanks_path, "r", encoding="utf-8") as f:
            thinktanks = json.load(f)
        
        # Finde CREA
        crea = next((tt for tt in thinktanks if tt["abbreviation"] == "CREA"), None)
        if not crea or not crea["email_senders"]:
            logger.warning("CREA nicht in thinktanks.json gefunden oder keine Sender angegeben")
            return [], 0
        
        # Extrahiere E-Mail-Adresse (mit oder ohne "Name <email>" Format)
        sender_raw = crea["email_senders"][0]
        # Extrahiere aus "Name <email@domain.com>" Format
        email_match = re.search(r'<(.+?)>', sender_raw)
        sender_email = email_match.group(1) if email_match else sender_raw
        
        logger.info(f"CREA - Extrahierte E-Mail: {sender_email}")
        
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        
        logger.info(f"CREA - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für CREA: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine CREA E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"CREA - {len(email_ids)} E-Mails gefunden")
        
        # Deduplizierung nach TITEL
        seen_titles = set()
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            parsed_articles = parse_crea_energy(msg)
            
            # Deduplizierung: Nur neue Artikel hinzufügen
            for article in parsed_articles:
                # Extrahiere Titel aus Markdown-Link
                title_match = article.split('[')[1].split(']')[0] if '[' in article and ']' in article else article
                if title_match not in seen_titles:
                    all_articles.append(article)
                    seen_titles.add(title_match)
        
        logger.info(f"CREA - FINAL: {len(all_articles)} Artikel (nach Dedup)")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_crea_energy: {str(e)}")
        return [], 0


def fetch_lowy_interpreter(mail, email_user, email_password, days=None):
    """Holt Lowy Institute Newsletter aus E-Mails."""
    if days is None:
        days = GLOBAL_THINKTANK_DAYS
        
    try:
        mail.select("inbox")
        all_articles = []
        
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "interpreter@lowyinstitute.org"
        
        logger.info(f"Lowy Institute - Suche nach E-Mails von {sender_email} seit {since_date}")
        
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            logger.warning(f"IMAP-Suche fehlgeschlagen für Lowy Institute: {result}")
            return [], 0
        
        email_ids = data[0].split()
        
        if not email_ids:
            logger.warning(f"Keine Lowy Institute E-Mails von {sender_email} in den letzten {days} Tagen gefunden")
            return [], 0
        
        logger.info(f"Lowy Institute - {len(email_ids)} E-Mails gefunden")
        
        # Deduplizierung nach TITEL (Tracking-URLs sind unterschiedlich)
        seen_lowy_titles = set()
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_lowy_interpreter(msg)
            
            # Dedupliziere nach Titel
            for article in articles:
                title_match = re.search(r'\[([^\]]+)\]', article)
                if title_match:
                    title = title_match.group(1).lower().strip()
                    if title not in seen_lowy_titles:
                        all_articles.append(article)
                        seen_lowy_titles.add(title)
                else:
                    all_articles.append(article)
        
        logger.info(f"Lowy Institute: {len(all_articles)} Artikel gefunden (nach interner Deduplizierung)")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_lowy_interpreter: {str(e)}")
        return [], 0

# ============================================================================
# ENDE LOWY INSTITUTE PARSER
# ============================================================================

# ============================================================================

def deduplicate_csis_articles(*article_lists):
    """
    Entfernt Duplikate aus allen CSIS Newsletter-Listen.
    Behält die erste Instanz jedes Artikels.
    """
    newsletter_names = [
        "Geopolitics",
        "Freeman Chair",
        "Trustee Chair",
        "Japan Chair",
        "China Power",
        "Korea Chair",
        "GHPC",
        "Aerospace"
    ]
    
    seen_urls = set()
    deduplicated_lists = []
    
    for idx, article_list in enumerate(article_lists):
        newsletter_name = newsletter_names[idx] if idx < len(newsletter_names) else f"Liste {idx+1}"
        
        logger.info(f"CSIS Dedup - {newsletter_name}: {len(article_list)} Artikel VOR Deduplizierung")
        
        deduplicated = []
        
        for article in article_list:
            # URL aus Markdown-Link extrahieren
            url_match = re.search(r'\((https?://[^\)]+)\)', article)
            
            if url_match:
                url = url_match.group(1)
                # Normalisiere URL (entferne Query-Parameter)
                normalized_url = url.split('?')[0]
                
                if normalized_url not in seen_urls:
                    deduplicated.append(article)
                    seen_urls.add(normalized_url)
                    logger.debug(f"CSIS Dedup - {newsletter_name}: Behalte {article[:50]}...")
                else:
                    logger.info(f"CSIS Dedup - {newsletter_name}: ❌ Duplikat entfernt: {article[:60]}...")
            else:
                # Kein URL gefunden, behalte Artikel
                deduplicated.append(article)
                logger.debug(f"CSIS Dedup - {newsletter_name}: Kein URL gefunden, behalte: {article[:50]}...")
        
        logger.info(f"CSIS Dedup - {newsletter_name}: {len(deduplicated)} Artikel NACH Deduplizierung")
        deduplicated_lists.append(deduplicated)
    
    total_before = sum(len(lst) for lst in article_lists)
    total_after = sum(len(lst) for lst in deduplicated_lists)
    logger.info(f"CSIS Dedup - GESAMT: {total_before} → {total_after} Artikel ({total_before - total_after} Duplikate entfernt)")
    
    return tuple(deduplicated_lists)

def normalize_url(url):
    """
    Normalisiert URLs für bessere Duplikatserkennung.
    - Entfernt Query-Parameter (?...)
    - Folgt Brookings/CSIS Tracking-Redirects zum finalen Artikel
    """
    # Entferne Query-Parameter
    base_url = url.split('?')[0]
    
    # Für Brookings connect.brookings.edu Links: Extrahiere Titel aus URL
    # Diese haben Format: connect.brookings.edu/e3t/Ctc/.../[TRACKING_PARAMS]
    # Wir können nicht automatisch resolven, also verwenden wir nur den Domain + Path
    if "connect.brookings.edu" in base_url:
        # Tracking-URLs sind eindeutig pro Newsletter, aber nicht pro Artikel
        # Wir müssen den finalen Zielartikel identifizieren
        # Leider können wir das nicht aus der URL extrahieren
        return base_url
    
    return base_url

# ============================================================================
# DYNAMIC BRIEFING GENERATION (JSON-gesteuert)
# ============================================================================

def load_thinktank_order():
    """
    Lädt thinktanks.json und gibt sortierte Liste zurück.
    Returns: List of dicts mit {order, think_tank, abbreviation}
    """
    try:
        json_path = os.path.join(BASE_DIR, "thinktanks.json")
        with open(json_path, "r", encoding="utf-8") as f:
            thinktanks = json.load(f)
        # Sortiere nach order
        thinktanks_sorted = sorted(thinktanks, key=lambda x: x.get("order", 999))
        logger.info(f"thinktanks.json geladen: {len(thinktanks_sorted)} Think Tanks")
        return thinktanks_sorted
    except Exception as e:
        logger.error(f"Fehler beim Laden von thinktanks.json: {str(e)}")
        return []


def build_dynamic_briefing(think_tank_data_dict):
    """
    Baut Briefing dynamisch basierend auf thinktanks.json Order.
    
    Args:
        think_tank_data_dict: Dict mit Think Tank Namen → Artikel-Listen
        Format: {
            "MERICS": merics_articles,
            "PIIE": piie_articles,
            "Brookings": brookings_articles,
            ...
        }
    
    Returns:
        List of briefing lines
    """
    briefing = []
    briefing.append("## Think Tanks Briefing")
    briefing.append("")
    
    # Lade Reihenfolge aus JSON
    thinktanks_order = load_thinktank_order()
    
    for tt in thinktanks_order:
        name = tt.get("think_tank")
        abbrev = tt.get("abbreviation")
        
        # Spezialbehandlung für CSIS (hat Subsektionen)
        if abbrev == "CSIS":
            briefing.append(f"### {name}")
            
            # CSIS Subsektionen
            csis_sections = [
                ("Geopolitics & Foreign Policy", think_tank_data_dict.get("CSIS_Geopolitics", [])),
                ("Freeman Chair in China Studies", think_tank_data_dict.get("CSIS_Freeman", [])),
                ("Trustee Chair in Chinese Business & Economics", think_tank_data_dict.get("CSIS_Trustee", [])),
                ("Japan Chair", think_tank_data_dict.get("CSIS_Japan", [])),
                ("China Power", think_tank_data_dict.get("CSIS_ChinaPower", [])),
                ("Korea Chair", think_tank_data_dict.get("CSIS_Korea", [])),
                ("GHPC", think_tank_data_dict.get("CSIS_GHPC", [])),
                ("Aerospace Security", think_tank_data_dict.get("CSIS_Aerospace", []))
            ]
            
            for section_name, articles in csis_sections:
                briefing.append(f"#### {section_name}")
                if articles:
                    briefing.extend(articles)
                else:
                    briefing.append("• Keine relevanten Artikel gefunden.")
                briefing.append("")
            
            continue
        
        # Spezialbehandlung für CFR (hat 2 Newsletter)
        if abbrev == "CFR":
            briefing.append(f"### {name}")
            
            # CFR Daily Brief
            briefing.append("#### Daily News Brief")
            cfr_daily = think_tank_data_dict.get("CFR_Daily", [])
            if cfr_daily:
                briefing.extend(cfr_daily)
            else:
                briefing.append("• Keine relevanten Artikel gefunden.")
            briefing.append("")
            
            # CFR Eyes on Asia
            briefing.append("#### Eyes on Asia")
            cfr_asia = think_tank_data_dict.get("CFR_Asia", [])
            if cfr_asia:
                briefing.extend(cfr_asia)
            else:
                briefing.append("• Keine relevanten Artikel gefunden.")
            briefing.append("")
            
            continue
        
        # Standard Think Tanks
        # Versuche erst abbreviation, dann think_tank name
        articles = think_tank_data_dict.get(abbrev, [])
        if not articles and abbrev != name:
            articles = think_tank_data_dict.get(name, [])
        
        briefing.append(f"### {name}")
        if articles:
            briefing.extend(articles)
        else:
            briefing.append("• Keine relevanten Artikel gefunden.")
        briefing.append("")
    
    return briefing

def deduplicate_all_thinktanks(merics_articles, brookings_articles, piie_articles, cfr_daily_articles, cfr_asia_articles, aspi_china5_articles, chatham_articles, lowy_articles, hinrich_articles, *csis_articles):
    """
    Globale Deduplizierung über ALLE Think Tanks hinweg.
    Entfernt Duplikate zwischen MERICS, Brookings, PIIE, CFR (Daily + Eyes on Asia), ASPI (China 5), Chatham House, Lowy Institute, Hinrich Foundation und CSIS.
    
    Args:
        merics_articles: MERICS Artikel-Liste
        brookings_articles: Brookings Artikel-Liste
        piie_articles: PIIE Artikel-Liste
        cfr_daily_articles: CFR Daily Brief Artikel-Liste
        cfr_asia_articles: CFR Eyes on Asia Artikel-Liste
        aspi_china5_articles: ASPI China 5 Artikel-Liste
        chatham_articles: Chatham House Artikel-Liste
        lowy_articles: Lowy Institute Artikel-Liste
        hinrich_articles: Hinrich Foundation Artikel-Liste
        *csis_articles: Variable Anzahl CSIS Newsletter-Listen
    
    Returns:
        Tuple: (merics_dedup, brookings_dedup, piie_dedup, cfr_daily_dedup, cfr_asia_dedup, aspi_china5_dedup, chatham_dedup, lowy_dedup, hinrich_dedup, *csis_dedup)
    """
    logger.info("=" * 60)
    logger.info("STARTE GLOBALE THINK TANK DEDUPLIZIERUNG")
    logger.info("=" * 60)
    
    seen_urls = set()
    seen_titles = set()  # NEU: Deduplizierung nach Titeln für Brookings
    
    # MERICS deduplizieren (kommt zuerst, hat Priorität)
    merics_dedup = []
    for article in merics_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]  # Normalisiere
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                merics_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                logger.info(f"Global Dedup - MERICS: ❌ Duplikat: {article[:60]}...")
        else:
            merics_dedup.append(article)
    
    logger.info(f"MERICS: {len(merics_articles)} → {len(merics_dedup)} ({len(merics_articles)-len(merics_dedup)} Duplikate)")
    
    # Brookings deduplizieren (WICHTIG: auch nach Titel!)
    brookings_dedup = []
    for article in brookings_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]  # Normalisiere
            title = title_match.group(1).lower().strip() if title_match else ""
            
            # Prüfe SOWOHL URL als AUCH Titel
            if url not in seen_urls and title not in seen_titles:
                brookings_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - Brookings: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            brookings_dedup.append(article)
    
    logger.info(f"Brookings: {len(brookings_articles)} → {len(brookings_dedup)} ({len(brookings_articles)-len(brookings_dedup)} Duplikate)")
    
    # PIIE deduplizieren
    piie_dedup = []
    for article in piie_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                piie_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - PIIE: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            piie_dedup.append(article)
    
    logger.info(f"PIIE: {len(piie_articles)} → {len(piie_dedup)} ({len(piie_articles)-len(piie_dedup)} Duplikate)")
    
    # CFR Daily Brief deduplizieren
    cfr_daily_dedup = []
    for article in cfr_daily_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                cfr_daily_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - CFR Daily: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            cfr_daily_dedup.append(article)
    
    logger.info(f"CFR Daily: {len(cfr_daily_articles)} → {len(cfr_daily_dedup)} ({len(cfr_daily_articles)-len(cfr_daily_dedup)} Duplikate)")
    
    # CFR Eyes on Asia deduplizieren
    cfr_asia_dedup = []
    for article in cfr_asia_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                cfr_asia_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - CFR Eyes on Asia: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            cfr_asia_dedup.append(article)
    
    logger.info(f"CFR Eyes on Asia: {len(cfr_asia_articles)} → {len(cfr_asia_dedup)} ({len(cfr_asia_articles)-len(cfr_asia_dedup)} Duplikate)")
    
    # ASPI China 5 deduplizieren
    aspi_china5_dedup = []
    for article in aspi_china5_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                aspi_china5_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - ASPI China 5: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            aspi_china5_dedup.append(article)
    
    logger.info(f"ASPI China 5: {len(aspi_china5_articles)} → {len(aspi_china5_dedup)} ({len(aspi_china5_articles)-len(aspi_china5_dedup)} Duplikate)")
    
    # Chatham House deduplizieren
    chatham_dedup = []
    for article in chatham_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                chatham_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - Chatham House: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            chatham_dedup.append(article)
    
    logger.info(f"Chatham House: {len(chatham_articles)} → {len(chatham_dedup)} ({len(chatham_articles)-len(chatham_dedup)} Duplikate)")
    
    # Lowy Institute deduplizieren
    lowy_dedup = []
    for article in lowy_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                lowy_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - Lowy Institute: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            lowy_dedup.append(article)
    
    logger.info(f"Lowy Institute: {len(lowy_articles)} → {len(lowy_dedup)} ({len(lowy_articles)-len(lowy_dedup)} Duplikate)")
    
    # Hinrich Foundation deduplizieren
    hinrich_dedup = []
    for article in hinrich_articles:
        url_match = re.search(r'\((https?://[^\)]+)\)', article)
        title_match = re.search(r'\[([^\]]+)\]', article)
        
        if url_match:
            url = url_match.group(1).split('?')[0]
            title = title_match.group(1).lower().strip() if title_match else ""
            
            if url not in seen_urls and title not in seen_titles:
                hinrich_dedup.append(article)
                seen_urls.add(url)
                if title:
                    seen_titles.add(title)
            else:
                reason = "URL" if url in seen_urls else "Titel"
                logger.info(f"Global Dedup - Hinrich Foundation: ❌ Duplikat ({reason}): {article[:60]}...")
        else:
            hinrich_dedup.append(article)
    
    logger.info(f"Hinrich Foundation: {len(hinrich_articles)} → {len(hinrich_dedup)} ({len(hinrich_articles)-len(hinrich_dedup)} Duplikate)")
    
    # CSIS deduplizieren (alle Newsletter)
    csis_names = [
        "CSIS Geopolitics", "CSIS Freeman", "CSIS Trustee", "CSIS Japan",
        "CSIS China Power", "CSIS Korea", "CSIS GHPC", "CSIS Aerospace"
    ]
    
    csis_dedup_lists = []
    for idx, csis_list in enumerate(csis_articles):
        name = csis_names[idx] if idx < len(csis_names) else f"CSIS {idx+1}"
        dedup = []
        
        for article in csis_list:
            url_match = re.search(r'\((https?://[^\)]+)\)', article)
            if url_match:
                url = url_match.group(1).split('?')[0]  # Normalisiere
                if url not in seen_urls:
                    dedup.append(article)
                    seen_urls.add(url)
                else:
                    logger.info(f"Global Dedup - {name}: ❌ Duplikat: {article[:60]}...")
            else:
                dedup.append(article)
        
        logger.info(f"{name}: {len(csis_list)} → {len(dedup)} ({len(csis_list)-len(dedup)} Duplikate)")
        csis_dedup_lists.append(dedup)
    
    logger.info("=" * 60)
    logger.info("GLOBALE DEDUPLIZIERUNG ABGESCHLOSSEN")
    logger.info("=" * 60)
    
    return (merics_dedup, brookings_dedup, piie_dedup, cfr_daily_dedup, cfr_asia_dedup, aspi_china5_dedup, chatham_dedup, lowy_dedup, hinrich_dedup, *csis_dedup_lists)

def main():
    logger.info("Starte Think Tanks Skript (MERICS + CSIS + Brookings)")
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
        
        # Brookings China Center (nutzt GLOBAL_THINKTANK_DAYS)
        brookings_articles, brookings_count = fetch_brookings_emails(mail, email_user, email_password)
        
        # PIIE (Peterson Institute) (nutzt GLOBAL_THINKTANK_DAYS)
        piie_articles, piie_count = fetch_piie_emails(mail, email_user, email_password)
        
        # CFR Daily Brief (nutzt GLOBAL_THINKTANK_DAYS)
        cfr_daily_articles, cfr_daily_count = fetch_cfr_daily_brief(mail, email_user, email_password)
        
        # CFR Eyes on Asia (nutzt GLOBAL_THINKTANK_DAYS)
        cfr_asia_articles, cfr_asia_count = fetch_cfr_eyes_on_asia(mail, email_user, email_password)
        
        # ASPI China 5 (nutzt GLOBAL_THINKTANK_DAYS)
        aspi_china5_articles, aspi_china5_count = fetch_aspi_china5(mail, email_user, email_password)
        
        # Chatham House (nutzt GLOBAL_THINKTANK_DAYS)
        chatham_articles, chatham_count = fetch_chatham_house(mail, email_user, email_password)
        
        # Lowy Institute (nutzt GLOBAL_THINKTANK_DAYS)
        lowy_articles, lowy_count = fetch_lowy_interpreter(mail, email_user, email_password)
        
        # Hinrich Foundation (nutzt GLOBAL_THINKTANK_DAYS)
        hinrich_articles, hinrich_count = fetch_hinrich_foundation(mail, email_user, email_password)
        
        # CREA (nutzt GLOBAL_THINKTANK_DAYS)
        crea_articles, crea_count = fetch_crea_energy(mail, email_user, email_password)
        
        # GLOBALE Deduplizierung über ALLE Think Tanks
        logger.info("Starte GLOBALE Think Tank Deduplizierung...")
        merics_articles, brookings_articles, piie_articles, cfr_daily_articles, cfr_asia_articles, aspi_china5_articles, chatham_articles, lowy_articles, hinrich_articles, crea_articles, csis_geo_articles, csis_freeman_articles, csis_trustee_articles, csis_japan_articles, chinapower_articles, korea_chair_articles, ghpc_articles, aerospace_articles = deduplicate_all_thinktanks(
            merics_articles,
            brookings_articles,
            piie_articles,
            cfr_daily_articles,
            cfr_asia_articles,
            aspi_china5_articles,
            chatham_articles,
            lowy_articles,
            hinrich_articles,
            crea_articles,
            csis_geo_articles,
            csis_freeman_articles,
            csis_trustee_articles,
            csis_japan_articles,
            chinapower_articles,
            korea_chair_articles,
            ghpc_articles,
            aerospace_articles
        )
        logger.info("Globale Deduplizierung abgeschlossen")
        
    finally:
        mail.logout()
        logger.info("IMAP-Logout erfolgreich")
    
    # Briefing erstellen
    briefing = []
    # Build Think Tank Data Dict für Dynamic Briefing
    think_tank_data = {
        "CREA": crea_articles,
        "PIIE": piie_articles,
        "MERICS": merics_articles,
        "Brookings": brookings_articles,
        "Hinrich": hinrich_articles,
        "ASPI Policy": [],  # Noch kein Parser
        "Lowy": lowy_articles,
        "Chatham House": chatham_articles,
        "CFR_Daily": cfr_daily_articles,
        "CFR_Asia": cfr_asia_articles,
        "CSIS_Geopolitics": csis_geo_articles,
        "CSIS_Freeman": csis_freeman_articles,
        "CSIS_Trustee": csis_trustee_articles,
        "CSIS_Japan": csis_japan_articles,
        "CSIS_ChinaPower": chinapower_articles,
        "CSIS_Korea": korea_chair_articles,
        "CSIS_GHPC": ghpc_articles,
        "CSIS_Aerospace": aerospace_articles,
        "ASPI": aspi_china5_articles,
        "Atlantic Council": []  # Noch keine Daten
    }
    
    # Generiere dynamisches Briefing basierend auf thinktanks.json
    briefing = build_dynamic_briefing(think_tank_data)

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
    send_email("Think Tanks Briefing", html_content, email_user, email_password)
    logger.info("E-Mail erfolgreich versendet")
    
    # Vorschau auf Konsole
    print("\n" + "="*50)
    print("VORSCHAU DER E-MAIL:")
    print("="*50)
    print("\n".join(briefing))
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
