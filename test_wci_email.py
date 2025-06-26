import imaplib
import email
import os
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta
import logging

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

def test_wci_email():
    logger.debug("Starting test_wci_email script")
    
    # Secret aus Umgebungsvariablen laden
    drewry_config = os.getenv("DREWRY")
    logger.debug(f"DREWRY environment variable: {drewry_config if drewry_config else 'Not found'}")
    if not drewry_config:
        logger.error("DREWRY environment variable not found")
        return
    
    try:
        mail_pairs = drewry_config.split(";")
        mail_config = dict(pair.split("=", 1) for pair in mail_pairs)
        email_user = mail_config.get("GMAIL_USER")
        email_password = mail_config.get("GMAIL_PASS")
        if not email_user or not email_password:
            logger.error(f"Missing GMAIL_USER or GMAIL_PASS in DREWRY secret. Config: {mail_config}")
            return
        logger.debug(f"Successfully parsed DREWRY secret: GMAIL_USER={email_user}, GMAIL_PASS={'*' * len(email_password)}")
    except Exception as e:
        logger.error(f"Failed to parse DREWRY secret: {str(e)}")
        return

    # Verbindung zu Gmail herstellen
    try:
        logger.debug("Attempting to connect to Gmail IMAP server (imap.gmail.com:993)")
        imap = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        logger.debug(f"Connecting to Gmail with user: {email_user}")
        for attempt in range(3):
            try:
                imap.login(email_user, email_password)
                logger.debug("Successfully logged in to Gmail")
                imap.select("INBOX")
                logger.debug("Selected INBOX folder")
                break
            except Exception as e:
                logger.error(f"Gmail connection failed (Attempt {attempt+1}/3): {str(e)}")
                if attempt == 2:
                    logger.error("Failed to connect to Gmail after 3 attempts")
                    return
                import time
                time.sleep(2)
    except Exception as e:
        logger.error(f"Failed to initialize IMAP connection: {str(e)}")
        return

    try:
        # Suche nach E-Mails von Drewry in den letzten 3 Tagen
        since_date = (datetime.now() - timedelta(days=3)).strftime("%d-%b-%Y")
        # Vereinfachte Suchabfrage: Nur FROM und SINCE, dann Betreff separat
        search_query = f'FROM noreply@drewry.co.uk SINCE {since_date}'
        logger.debug(f"Executing IMAP search query: {search_query}")
        typ, data = imap.search(None, search_query.encode('utf-8'))
        if typ != "OK":
            logger.error(f"IMAP search failed: Type={typ}, Data={data}")
            imap.logout()
            return

        email_ids = data[0].split()
        logger.debug(f"Found {len(email_ids)} email IDs: {email_ids}")

        if not email_ids:
            logger.debug("No Drewry emails found in the last 3 days")
            imap.logout()
            return

        # E-Mails nach Datum sortieren und Betreff prüfen
        email_data = []
        for eid in email_ids:
            try:
                typ, msg_data = imap.fetch(eid, "(BODY[HEADER.FIELDS (DATE SUBJECT FROM)])")
                if typ != "OK":
                    logger.error(f"Failed to fetch header for email ID {eid}: {msg_data}")
                    continue
                msg = email.message_from_bytes(msg_data[0][1])
                date_str = msg.get("Date", "No Date")
                subject = msg.get("Subject", "No Subject")
                from_str = msg.get("From", "No From")
                try:
                    parsed_date = parsedate_to_datetime(date_str)
                    logger.debug(f"Email ID {eid}: Subject='{subject}', Date='{date_str}', From='{from_str}', Parsed Date={parsed_date}")
                    # Prüfe, ob Betreff "Drewry World Container Index" enthält
                    if "Drewry World Container Index" in subject:
                        email_data.append((eid, parsed_date, subject, from_str))
                    else:
                        logger.debug(f"Email ID {eid} skipped: Subject does not contain 'Drewry World Container Index'")
                except Exception as e:
                    logger.debug(f"Failed to parse date for email ID {eid}: {date_str}, Error: {str(e)}")
            except Exception as e:
                logger.error(f"Error processing email ID {eid}: {str(e)}")
        
        email_data.sort(key=lambda x: x[1], reverse=True)
        logger.debug(f"Sorted {len(email_data)} emails by date (newest first): {[f'ID={x[0]}, Date={x[1]}, Subject={x[2]}' for x in email_data]}")

        if not email_data:
            logger.debug("No emails with 'Drewry World Container Index' in subject found")
            imap.logout()
            return

        # Neueste E-Mail verarbeiten
        eid, parsed_date, subject, from_str = email_data[0]
        logger.debug(f"Processing newest email ID {eid}: Subject='{subject}', Date='{parsed_date}', From='{from_str}'")
        
        typ, msg_data = imap.fetch(eid, "(RFC822)")
        if typ != "OK":
            logger.error(f"Error fetching mail {eid}: {msg_data}")
            imap.logout()
            return
        
        msg = email.message_from_bytes(msg_data[0][1])
        html = None
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode(errors="ignore")
                    logger.debug("Found HTML content in multipart email")
                    break
        elif msg.get_content_type() == "text/html":
            html = msg.get_payload(decode=True).decode(errors="ignore")
            logger.debug("Found HTML content in single-part email")
        
        if not html:
            logger.error(f"No HTML content in mail {eid}")
            imap.logout()
            return
        
        # HTML speichern (für Debugging)
        try:
            html_filename = f"wci_email_{eid.decode('utf-8')}.html"
            with open(html_filename, "w", encoding="utf-8") as f:
                f.write(html)
            logger.debug(f"Saved HTML for mail {eid} to {html_filename}")
            logger.debug(f"Email HTML content (first 500 chars): {html[:500]}")
        except Exception as e:
            logger.error(f"Failed to save HTML for mail {eid}: {str(e)}")
        
        # Kurze Zusammenfassung
        logger.info(f"Successfully processed newest Drewry email: ID={eid}, Subject='{subject}', Date='{parsed_date}'")
        
        imap.logout()
        logger.debug("Logged out from Gmail")
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        imap.logout()

if __name__ == "__main__":
    logger.debug("Starting main execution")
    test_wci_email()
    logger.debug("Test execution completed")
