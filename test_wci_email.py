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
    if not drewry_config:
        logger.error("DREWRY environment variable not found")
        return
    
    try:
        mail_pairs = drewry_config.split(";")
        mail_config = dict(pair.split("=", 1) for pair in mail_pairs)
        email_user = mail_config.get("GMAIL_USER")
        email_password = mail_config.get("GMAIL_PASS")
        if not email_user or not email_password:
            logger.error("Missing GMAIL_USER or GMAIL_PASS in DREWRY secret")
            return
        logger.debug(f"Successfully parsed DREWRY secret: GMAIL_USER={email_user}")
    except Exception as e:
        logger.error(f"Failed to parse DREWRY secret: {str(e)}")
        return

    # Verbindung zu Gmail herstellen
    try:
        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        logger.debug("Connecting to Gmail IMAP server")
        for attempt in range(3):
            try:
                imap.login(email_user, email_password)
                imap.select("INBOX")
                logger.debug("Successfully logged in to Gmail and selected INBOX")
                break
            except Exception as e:
                logger.error(f"Gmail connection failed (Attempt {attempt+1}/3): {str(e)}")
                if attempt == 2:
                    logger.error("Failed to connect to Gmail after 3 attempts")
                    return
                import time
                time.sleep(2)
    except Exception as e:
        logger.error(f"Failed to connect to Gmail: {str(e)}")
        return

    try:
        # Suche nach E-Mails von Drewry in den letzten 3 Tagen
        since_date = (datetime.now() - timedelta(days=3)).strftime("%d-%b-%Y")
        search_query = 'FROM noreply@drewry.co.uk "Drewry World Container Index" SINCE ' + since_date
        logger.debug(f"Executing IMAP search query: {search_query}")
        typ, data = imap.search(None, search_query.encode('utf-8'))
        if typ != "OK":
            logger.error(f"IMAP search failed: {data}")
            imap.logout()
            return

        email_ids = data[0].split()
        logger.debug(f"Found {len(email_ids)} email IDs: {email_ids}")

        if not email_ids:
            logger.debug("No Drewry emails found in the last 3 days")
            imap.logout()
            return

        # E-Mails nach Datum sortieren (neueste zuerst)
        email_data = []
        for eid in email_ids:
            typ, msg_data = imap.fetch(eid, "(BODY[HEADER.FIELDS (DATE SUBJECT FROM)])")
            if typ == "OK":
                msg = email.message_from_bytes(msg_data[0][1])
                date_str = msg.get("Date", "No Date")
                subject = msg.get("Subject", "No Subject")
                from_str = msg.get("From", "No From")
                try:
                    parsed_date = parsedate_to_datetime(date_str)
                    logger.debug(f"Email ID {eid}: Subject='{subject}', Date='{date_str}', From='{from_str}'")
                except Exception as e:
                    parsed_date = datetime.min
                    logger.debug(f"Failed to parse date for email ID {eid}: {date_str}, Error: {str(e)}")
                email_data.append((eid, parsed_date, subject, from_str))
        
        email_data.sort(key=lambda x: x[1], reverse=True)
        logger.debug(f"Sorted {len(email_data)} emails by date (newest first)")

        if not email_data:
            logger.debug("No emails after sorting")
            imap.logout()
            return

        # Neueste E-Mail verarbeiten
        eid, parsed_date, subject, from_str = email_data[0]
        logger.debug(f"Processing newest email ID {eid}: Subject='{subject}', Date='{parsed_date}', From='{from_str}'")
        
        typ, msg_data = imap.fetch(eid, "(RFC822)")
        if typ != "OK":
            logger.error(f"Error fetching mail {eid}")
            imap.logout()
            return
        
        msg = email.message_from_bytes(msg_data[0][1])
        html = None
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    html = part.get_payload(decode=True).decode(errors="ignore")
                    break
        elif msg.get_content_type() == "text/html":
            html = msg.get_payload(decode=True).decode(errors="ignore")
        
        if not html:
            logger.error(f"No HTML content in mail {eid}")
            imap.logout()
            return
        
        # HTML speichern (für Debugging)
        with open(f"wci_email_{eid}.html", "w", encoding="utf-8") as f:
            f.write(html)
        logger.debug(f"Saved HTML for mail {eid} to wci_email_{eid}.html")
        logger.debug(f"Email HTML content (first 500 chars): {html[:500]}")
        
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
