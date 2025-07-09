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
    """Ladet die Think Tanks aus thinktanks.json."""
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
    """Extrahiert die E-Mail-Adresse aus einem Absenderstring."""
    match = re.search(r'<(.+?)>', sender)
    return match.group(1) if match else sender

def normalize_url(url):
    """Entfernt Tracking-Parameter aus der URL, aber behält Query-Parameter bei."""
    parsed = urllib.parse.urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

def resolve_merics_url(url):
    """Löst die ursprüngliche URL auf, inkl. Tracking-URLs."""
    try:
        # Prüfe, ob es eine Tracking-URL ist
        parsed = urllib.parse.urlparse(url)
        query_params = urllib.parse.parse_qs(parsed.query)
        if 'target' in query_params:
            # Extrahiere die Ziel-URL aus dem 'target'-Parameter
            target_url = query_params['target'][0]
            decoded_url = urllib.parse.unquote(target_url)
            if decoded_url.startswith("https://merics.org"):
                logger.debug(f"Dekodierte Ziel-URL: {decoded_url}")
                return decoded_url
        # Führe normale Weiterleitungsauflösung durch
        response = requests.get(url, allow_redirects=True, timeout=5)
        final_url = response.url
        logger.debug(f"Ziel-URL gefunden: {final_url}")
        return final_url
    except Exception as e:
        logger.warning(f"Fehler beim Auflösen der URL {url}: {str(e)}")
        return url

def scrape_web_title(url):
    """Scraped den Titel einer Webseite."""
    try:
        response = requests.get(url, timeout=5)
        soup = BeautifulSoup(response.text, "lxml")
        title = soup.title.string.strip() if soup.title else ""
        logger.debug(f"Web-Titel für {url}: {title}")
        return title
    except Exception as e:
        logger.warning(f"Fehler beim Scrapen des Titels für {url}: {str(e)}")
        return None

def extract_pdf_title(filename, subject=""):
    """Extrahiert den Titel eines PDFs, bevorzugt aus dem Betreff."""
    if subject and subject != "Kein Betreff":
        return subject
    name = os.path.basename(filename).replace('.pdf', '')
    name = re.sub(r'_\d{6}_WEB_\d', '', name)
    name = name.replace('-', ' ').replace('_', ' ')
    name = re.sub(r'\s+', ' ', name).strip()
    logger.debug(f"PDF-Titel aus Dateinamen oder Betreff: {name}")
    return name

def score_thinktank_article(title, url):
    """Bewertet einen Artikel auf Relevanz."""
    score = 0
    keywords = {
        "china": 5, "chinese": 5, "technology": 3, "innovation": 3,
        "geopolitics": 3, "policy": 3, "economy": 2, "report": 2
    }
    negative_keywords = ["subscribe", "unsubscribe", "donate", "legal", "privacy"]
    title_lower = title.lower()
    for keyword, value in keywords.items():
        if keyword in title_lower:
            score += value
            logger.debug(f"Positiver Treffer für '{keyword}' in '{title}': +{value}")
    if any(keyword in title_lower for keyword in negative_keywords):
        score -= 2
        logger.debug(f"Negativer Treffer in '{title}': -2")
    if "merics.org" in url and "/report/" in url:
        score += 3
        logger.debug(f"Bonus für /report/ in URL {url}: +3")
    if "merics.org" in url and "/sites/default/files/" in url:
        score += 2
        logger.debug(f"Bonus für /sites/default/files/ in URL {url}: +2")
    logger.debug(f"Gesamtscore für '{title}' (URL: {url}): {score}")
    return score

def fetch_merics_emails(email_user, email_password, days=180, max_articles=10):
    """Holt MERICS-Artikel aus E-Mails."""
    logger.info("Starte fetch_merics_emails")
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
        articles = []
        seen_urls = set()
        email_count = 0
        since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        logger.info(f"Suche nach E-Mails seit: {since_date}")

        # Gezielte Suche nach fehlenden URLs
        missing_urls = [
            "https://merics.org/en/report/trade-offs-innovating-china-times-global-technology-rivalry",
            "https://merics.org/sites/default/files/2025-06/ETNC Report 2025 Quest-for-strategic-autonomy-europe-grapples-with-the-us-china-rivalry.pdf"
        ]

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
                subject = decode_header(msg.get("Subject", "Kein Betreff"))[0][0]
                if isinstance(subject, bytes):
                    subject = subject.decode()
                date = msg.get("Date", "Kein Datum")
                try:
                    date = email.utils.parsedate_to_datetime(date)
                except:
                    date = datetime.now()
                logger.debug(f"E-Mail Betreff: {subject}, Datum: {date.strftime('%Y-%m-%d %H:%M')}")

                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            html_content = part.get_payload(decode=True).decode(charset)
                        except UnicodeDecodeError:
                            html_content = part.get_payload(decode=True).decode("windows-1252", errors="replace")
                        soup = BeautifulSoup(html_content, "lxml")
                        links = soup.find_all("a", href=True)
                        logger.debug(f"Anzahl gefundener Links: {len(links)}")

                        for link in links:
                            href = link.get("href")
                            title = link.get_text(strip=True)
                            logger.debug(f"Verarbeite Link: {title} (href: {href})")
                            final_url = resolve_merics_url(href)
                            if final_url.startswith("mailto:"):
                                logger.debug(f"Link übersprungen: Mailto-URL {final_url}")
                                continue
                            # Entferne Filter für unerwünschte Keywords vorübergehend
                            # if any(kw in title.lower() for kw in ["subscribe", "unsubscribe", "donate", "legal notice", "privacy policy", "website", "read in browser", "profile", "pdf here", "on our website", "as a pdf"]):
                            #     logger.debug(f"Link übersprungen: Unerwünschtes Keyword in Titel: {title}")
                            #     continue
                            if "merics.org" in final_url and "/sites/default/files/" in final_url:
                                title = extract_pdf_title(final_url, subject)
                                logger.debug(f"PDF-Titel aus Dateinamen oder Betreff: {title}")
                            elif "merics.org" in final_url and "/report/" in final_url:
                                web_title = scrape_web_title(final_url)
                                title = web_title if web_title else subject
                                logger.debug(f"Web-Titel: {title}")
                            normalized_url = normalize_url(final_url)
                            if normalized_url in seen_urls:
                                logger.debug(f"Link übersprungen: URL bereits gesehen: {normalized_url}")
                                continue
                            if normalized_url in missing_urls:
                                logger.info(f"Fehlende URL gefunden: {normalized_url} (Titel: {title})")
                            score = score_thinktank_article(title, final_url)
                            logger.debug(f"Score für '{title}' (URL: {final_url}): {score}")
                            if score > 0:
                                logger.info(f"Artikel hinzugefügt: {title} (URL: {final_url}, Score: {score})")
                                articles.append((score, f"• {title}"))
                                seen_urls.add(normalized_url)

        mail.logout()
        logger.info("IMAP-Logout erfolgreich")
        articles.sort(key=lambda x: x[0], reverse=True)
        unique_articles = [article for score, article in articles[:max_articles]]
        logger.info(f"Anzahl eindeutiger MERICS-Artikel: {len(unique_articles)}")
        return unique_articles, email_count
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
    logger.info("Starte Testskript für MERICS-Artikel-Extraktion")
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

    articles, email_count = fetch_merics_emails(email_user, email_password, days=180, max_articles=10)
    output_file = os.path.join(BASE_DIR, "main", "daily-china-briefing-test", "thinktanks_briefing.md")
    markdown = ["## Think Tanks", "", "### MERICS", ""]
    if articles:
        for i, article in enumerate(articles):
            markdown.append(article)
            markdown.append("")  # Leere Zeile nach jedem Artikel
    else:
        markdown.append("• Keine relevanten MERICS-Artikel gefunden.")
        markdown.append("")
    
    logger.info(f"Schreibe Ergebnisse nach {output_file}")
    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("\n".join(markdown))
        logger.info(f"Ergebnisse in {output_file} gespeichert")
    except Exception as e:
        logger.error(f"Fehler beim Schreiben von {output_file}: {str(e)}")
        send_email("Fehler in thinktanks.py", f"<p>Fehler beim Schreiben von {output_file}: {str(e)}</p>", email_user, email_password)

    status_message = "\n".join(markdown)
    send_email("Think Tanks Status", status_message, email_user, email_password)

if __name__ == "__main__":
    main()
