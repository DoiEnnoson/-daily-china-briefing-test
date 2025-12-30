import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
import re
from bs4 import BeautifulSoup
import json
import logging

# Logging-Konfiguration
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_brookings_email(msg):
    """
    Spezialisierter Parser für Brookings China Center Newsletter.
    
    Struktur der E-Mails:
    - Großer Titel im Betreff (z.B. "Our 2025 Year in Review")
    - Mehrere Hauptsektionen mit H1-Überschriften
    - Jede Sektion hat mehrere Artikel mit:
      - H1 oder H2 Titel (verlinkt)
      - Kurze Beschreibung
      - "Read more" Link
    
    Returns:
        Liste von Artikeln im Format: [(title, link, description, date), ...]
    """
    articles = []
    
    # Betreff extrahieren
    subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
    if isinstance(subject, bytes):
        subject = subject.decode()
    
    logger.info(f"Brookings - Betreff: {subject}")
    
    # Datum extrahieren
    try:
        mail_date = email.utils.parsedate_to_datetime(msg.get("Date", ""))
    except:
        mail_date = datetime.now()
    
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
    
    # Strategie: Finde alle H1/H2 Überschriften, die Links enthalten
    # Diese sind die Artikel-Titel
    
    # Suche nach H1 und H2 Tags
    headings = soup.find_all(['h1', 'h2'])
    
    seen_urls = set()
    current_section = None
    
    for heading in headings:
        # Überspringe zu kleine Texte (Header/Footer)
        heading_text = heading.get_text(strip=True)
        
        # Identifiziere Sektions-Überschriften (ohne Link, größer, spezifische Muster)
        if not heading.find('a') and len(heading_text) > 10:
            # Prüfe ob es eine Hauptsektion ist
            section_keywords = [
                "developments in", "chinese domestic", "china's foreign policy",
                "technology, ai, and energy", "about the china center"
            ]
            
            if any(kw in heading_text.lower() for kw in section_keywords):
                current_section = heading_text
                logger.info(f"Brookings - Neue Sektion: {current_section}")
                continue
        
        # Suche nach verlinkten Artikeln in H1/H2
        link = heading.find('a', href=True)
        
        if not link:
            continue
        
        title = link.get_text(strip=True)
        url = link.get('href', '')
        
        # Überspringe zu kurze Titel
        if len(title) < 20:
            logger.debug(f"Brookings - Titel zu kurz: {title}")
            continue
        
        # Überspringe Navigation/Footer Links
        skip_patterns = [
            "view in browser", "unsubscribe", "manage newsletter",
            "x/twitter", "facebook", "instagram", "linkedin",
            "read his introductory", "watch the recording",
            "brookings institution"
        ]
        
        if any(pattern in title.lower() for pattern in skip_patterns):
            logger.debug(f"Brookings - Navigation übersprungen: {title}")
            continue
        
        # Überspringe Event-Ankündigungen (keine eigentlichen Artikel)
        if "event invite" in title.lower() or "join us" in title.lower():
            logger.debug(f"Brookings - Event übersprungen: {title}")
            continue
        
        # Duplikats-Check
        if url in seen_urls:
            logger.debug(f"Brookings - Duplikat übersprungen: {title}")
            continue
        
        seen_urls.add(url)
        
        # China-Relevanz-Check
        content_to_check = f"{title}".lower()
        
        china_keywords = [
            "china", "chinese", "xi jinping", "beijing", "taiwan",
            "hong kong", "us-china", "sino-", "prc", "communist party"
        ]
        
        is_china_relevant = any(keyword in content_to_check for keyword in china_keywords)
        
        # Für Brookings China Center sollte alles relevant sein,
        # aber wir filtern trotzdem offensichtlich irrelevante Inhalte
        if not is_china_relevant:
            # Überprüfe ob es eine Hauptsektion ist, die trotzdem relevant ist
            if current_section and any(kw in current_section.lower() for kw in ["china", "us-china"]):
                is_china_relevant = True
        
        if not is_china_relevant:
            logger.info(f"Brookings - Nicht China-relevant: {title}")
            continue
        
        # Artikel hinzufügen - NUR als einfacher Markdown-Link
        formatted_article = f"• [{title}]({url})"
        
        articles.append(formatted_article)
        logger.info(f"Brookings - Artikel hinzugefügt: {title[:50]}...")
    
    logger.info(f"Brookings Parser - {len(articles)} Artikel extrahiert")
    return articles


def fetch_brookings_emails(mail, email_user, email_password, days=120):
    """
    Holt Brookings China Center Newsletter aus E-Mails.
    
    Args:
        mail: Bestehende IMAP-Verbindung
        email_user: Gmail-Benutzername
        email_password: Gmail-Passwort
        days: Anzahl der Tage zurück (Standard: 120)
    
    Returns:
        Tuple: (artikel_liste, anzahl_emails)
    """
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
                logger.warning(f"Fehler beim Abrufen der E-Mail {email_id}: {result}")
                continue
            
            msg = email.message_from_bytes(msg_data[0][1])
            
            articles = parse_brookings_email(msg)
            
            # Duplikate filtern
            for article in articles:
                # Extrahiere URL aus Markdown-Link
                url_match = re.search(r'\((https?://[^\)]+)\)', article)
                if url_match:
                    url = url_match.group(1)
                    if url not in seen_urls:
                        all_articles.append(article)
                        seen_urls.add(url)
        
        logger.info(f"Brookings China Center: {len(all_articles)} Artikel gefunden")
        return all_articles, len(email_ids)
        
    except Exception as e:
        logger.error(f"Fehler in fetch_brookings_emails: {str(e)}")
        return [], 0


# Test-Funktion
def test_brookings_parser():
    """Testet den Brookings Parser mit echten E-Mails"""
    import os
    
    substack_mail = os.getenv("SUBSTACK_MAIL")
    if not substack_mail:
        print("❌ SUBSTACK_MAIL Umgebungsvariable nicht gefunden")
        return
    
    try:
        mail_config = dict(pair.split("=", 1) for pair in substack_mail.split(";") if "=" in pair)
        email_user = mail_config.get("GMAIL_USER")
        email_password = mail_config.get("GMAIL_PASS")
        
        if not email_user or not email_password:
            print("❌ GMAIL_USER oder GMAIL_PASS fehlt")
            return
    except Exception as e:
        print(f"❌ Fehler beim Parsen: {str(e)}")
        return
    
    # IMAP-Verbindung
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_user, email_password)
        print("✅ IMAP-Login erfolgreich")
        
        articles, email_count = fetch_brookings_emails(mail, email_user, email_password, days=120)
        
        print(f"\n{'='*60}")
        print(f"Brookings China Center - {email_count} E-Mails gefunden")
        print(f"{len(articles)} Artikel extrahiert")
        print(f"{'='*60}\n")
        
        for article in articles:
            print(article)
            print()
        
        mail.logout()
        
    except Exception as e:
        print(f"❌ Fehler: {str(e)}")


if __name__ == "__main__":
    test_brookings_parser()
