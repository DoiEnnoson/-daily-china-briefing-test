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

# Logging-Konfiguration - nur INFO-Level für Production
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[logging.FileHandler('thinktanks.log'), logging.StreamHandler()])
logger = logging.getLogger(__name__)

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
        logger.info(f"E-Mail erfolgreich gesendet: {subject}")
    except Exception as e:
        logger.error(f"Fehler beim Senden der E-Mail: {str(e)}")

def load_thinktanks():
    """Lädt Think Tanks aus thinktanks.json."""
    try:
        thinktanks_path = os.path.join(BASE_DIR, "thinktanks.json")
        with open(thinktanks_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Fehler beim Laden von thinktanks.json: {str(e)}")
        return []

def extract_email_address(sender):
    """Extrahiert E-Mail-Adresse aus Sender-String."""
    match = re.search(r'<(.+?)>', sender)
    return match.group(1) if match else sender

def resolve_tracking_url(url):
    """Löst Tracking-URLs auf."""
    try:
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        
        if 'msdynmkt_target' in query_params:
            target_json = query_params['msdynmkt_target'][0]
            target_data = json.loads(target_json)
            if 'TargetUrl' in target_data:
                return urllib.parse.unquote(target_data['TargetUrl'])
        
        if "public-eur.mkt.dynamics.com" in url or "clicks.mlsend.com" in url:
            response = requests.get(url, allow_redirects=True, timeout=5)
            return response.url
            
        return url
    except Exception as e:
        logger.warning(f"URL-Auflösung fehlgeschlagen: {str(e)}")
        return url

def clean_merics_title(subject):
    """Bereinigt MERICS E-Mail-Betreff."""
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
    """Parst eine MERICS E-Mail und extrahiert den Hauptartikel-Link."""
    articles = []
    
    subject = decode_header(msg.get("Subject", ""))[0][0]
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
        return articles
    
    soup = BeautifulSoup(html_content, "lxml")
    
    # Suche nach Hauptlink
    main_link_texts = ["on our website", "read more", "download the pdf", "as a pdf", "here", "full tracker"]
    found_link = None
    all_links = soup.find_all("a", href=True)
    
    # Strategie 1: Link mit CTA-Text
    for link in all_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True).lower()
        
        skip_patterns = ["mailto:", "unsubscribe", "privacy", "legal", "cookie", "profile", "linkedin", "twitter", "facebook", "youtube"]
        if any(pattern in href.lower() or pattern in link_text for pattern in skip_patterns):
            continue
        
        if any(main_text in link_text for main_text in main_link_texts):
            resolved_url = resolve_tracking_url(href)
            if "merics.org" in resolved_url:
                found_link = resolved_url
                break
    
    # Strategie 2: Erster merics.org Link
    if not found_link:
        for link in all_links:
            href = link.get("href", "")
            resolved_url = resolve_tracking_url(href)
            if "merics.org" in resolved_url and not any(skip in resolved_url.lower() for skip in ["unsubscribe", "profile"]):
                found_link = resolved_url
                break
    
    if found_link:
        title = clean_merics_title(subject)
        articles.append(f"• [{title}]({found_link})")
    
    return articles

def fetch_merics_emails(mail, days=30):
    """Holt MERICS-Artikel aus E-Mails. Nutzt bestehende IMAP-Verbindung."""
    try:
        thinktanks = load_thinktanks()
        merics = next((tt for tt in thinktanks if tt["abbreviation"] == "MERICS"), None)
        if not merics:
            logger.error("MERICS nicht in thinktanks.json gefunden")
            return [], 0

        email_senders = [extract_email_address(sender) for sender in merics["email_senders"]]
        mail.select("inbox")
        all_articles = []
        seen_urls = set()
        email_count = 0
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        
        logger.info(f"Suche MERICS E-Mails seit {since_date}")

        for sender in email_senders:
            result, data = mail.search(None, f'FROM "{sender}" SINCE {since_date}')
            if result != "OK":
                continue

            email_ids = data[0].split()
            email_count += len(email_ids)
            
            for email_id in email_ids:
                result, msg_data = mail.fetch(email_id, "(RFC822)")
                if result != "OK":
                    continue

                msg = email.message_from_bytes(msg_data[0][1])
                articles = parse_merics_email(msg)
                
                for article in articles:
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

def score_csis_article(title, description):
    """Bewertet CSIS Geopolitics Artikel nach Relevanz."""
    score = 0
    keywords = {
        "china": 3, "chinese": 3, "beijing": 3, "xi jinping": 3,
        "taiwan": 2, "hong kong": 2, "south china sea": 2,
        "asia": 1, "indo-pacific": 2, "asean": 1, "india": 1,
        "north korea": 1, "japan": 1, "korea": 1
    }
    
    text = f"{title.lower()} {description.lower()}"
    for keyword, points in keywords.items():
        if keyword in text:
            score += points
    
    return score

def parse_csis_geopolitics_email(msg):
    """Parst CSIS Geopolitics E-Mail und extrahiert relevante Podcast-Links."""
    subject = decode_header(msg.get("Subject", ""))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Parse CSIS E-Mail: {subject}")
    
    html_content = None
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            charset = part.get_content_charset() or "utf-8"
            try:
                html_content = part.get_payload(decode=True).decode(charset)
            except:
                html_content = part.get_payload(decode=True).decode("windows-1252", errors="replace")
            break
    
    if not html_content:
        return []
    
    soup = BeautifulSoup(html_content, 'html.parser')
    all_links = soup.find_all('a', href=True)
    csis_links = [link for link in all_links if "csis.org" in link.get("href", "")]
    
    articles = []
    processed_count = 0
    
    for link in csis_links:
        href = link.get("href", "")
        link_text = link.get_text(strip=True).lower()
        
        # Skip Footer-Links
        footer_keywords = ["privacy", "unsubscribe", "preferences", "view it in your browser"]
        if any(keyword in link_text for keyword in footer_keywords):
            continue
        
        processed_count += 1
        
        # Titel-Extraktion: Multi-Level Table Search
        title = None
        current_element = link
        
        for level in range(5):
            parent_table = current_element.find_parent("table")
            if not parent_table:
                break
            
            all_trs = parent_table.find_all("tr")
            
            if len(all_trs) > 3:
                em_text4_elements = parent_table.find_all(class_="em_text4")
                if em_text4_elements:
                    # Nimm das LETZTE em_text4 Element (meist der Podcast-Titel)
                    last_em_text4 = em_text4_elements[-1]
                    title = last_em_text4.get_text(strip=True)
                    title = " ".join(title.split())
                    break
            
            current_element = parent_table
        
        # Fallback: Übergeordnete Tabelle
        if not title:
            parent_table = link.find_parent("table")
            if parent_table:
                em_text4 = parent_table.find(class_="em_text4")
                if em_text4:
                    title = " ".join(em_text4.get_text(strip=True).split())
        
        if not title:
            continue
        
        # Score berechnen
        score = score_csis_article(title, "")
        
        if score > 0:
            # Duplikats-Check
            if title in [art.split('](')[0].split('[')[1] for art in articles]:
                continue
            
            articles.append(f"• [{title}]({href})")
    
    logger.info(f"CSIS: {len(articles)} Artikel extrahiert")
    return articles

def fetch_csis_geopolitics_emails(mail, days=120):
    """Holt CSIS Geopolitics Artikel. Nutzt bestehende IMAP-Verbindung."""
    try:
        mail.select("inbox")
        all_articles = []
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        sender_email = "geopolitics@csis.org"
        
        logger.info(f"Suche CSIS E-Mails seit {since_date}")
        result, data = mail.search(None, f'FROM "{sender_email}" SINCE {since_date}')
        
        if result != "OK":
            return [], 0
        
        email_ids = data[0].split()
        logger.info(f"CSIS: {len(email_ids)} E-Mails gefunden")
        
        for email_id in email_ids:
            result, msg_data = mail.fetch(email_id, "(RFC822)")
            if result != "OK":
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            articles = parse_csis_geopolitics_email(msg)
            all_articles.extend(articles)
        
        logger.info(f"CSIS: {len(all_articles)} Artikel gesamt")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_csis_geopolitics_emails: {str(e)}")
        return [], 0

def main():
    """Hauptfunktion."""
    try:
        # E-Mail-Credentials laden
        substack_mail_path = os.path.join(BASE_DIR, "SUBSTACK_MAIL")
        with open(substack_mail_path, "r") as f:
            content = f.read()
            email_user = re.search(r'GMAIL_USER="([^"]+)"', content).group(1)
            email_password = re.search(r'GMAIL_PASS="([^"]+)"', content).group(1)
    except Exception as e:
        logger.error(f"Fehler beim Laden der Credentials: {str(e)}")
        return
    
    # EINMAL IMAP-Verbindung aufbauen
    try:
        logger.info("Stelle IMAP-Verbindung her...")
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_user, email_password)
        logger.info("IMAP-Login erfolgreich")
    except Exception as e:
        logger.error(f"IMAP-Login fehlgeschlagen: {str(e)}")
        return
    
    try:
        # MERICS E-Mails abrufen
        merics_articles, _ = fetch_merics_emails(mail, days=30)
        
        # CSIS E-Mails abrufen
        csis_articles, _ = fetch_csis_geopolitics_emails(mail, days=120)
        
    finally:
        # EINMAL IMAP-Logout
        mail.logout()
        logger.info("IMAP-Logout erfolgreich")
    
    # Briefing erstellen
    briefing = []
    briefing.append("## Think Tanks")
    briefing.append("### MERICS")
    if merics_articles:
        briefing.extend(merics_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    briefing.append("")
    briefing.append("### CSIS")
    briefing.append("#### Geopolitics & Foreign Policy")
    if csis_articles:
        briefing.extend(csis_articles)
    else:
        briefing.append("• Keine relevanten Artikel gefunden.")
    
    # HTML-Konvertierung
    html_lines = []
    for line in briefing:
        html_line = re.sub(r'\[([^\]]+)\]\(([^\)]+)\)', r'<a href="\2">\1</a>', line)
        html_lines.append(html_line)
    
    html_content = html_lines[0] + "<br><br>\n"
    html_content += html_lines[1] + "<br>\n"
    for i in range(2, len(html_lines)):
        html_content += html_lines[i]
        if i < len(html_lines) - 1:
            html_content += "<br>\n"
    
    # E-Mail senden
    send_email("Think Tanks - MERICS Update", html_content, email_user, email_password)
    
    # Konsolen-Ausgabe
    print("\n" + "="*50)
    print("BRIEFING:")
    print("="*50)
    print("\n".join(briefing))
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
