import os
import glob
import re
import logging
import imaplib
import email
from email.header import decode_header
from datetime import datetime
from bs4 import BeautifulSoup

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

def fetch_wci_email():
    """Holt die neueste Drewry-E-Mail und speichert den HTML-Inhalt."""
    logger.debug("Starting email fetch")
    try:
        # Umgebungsvariablen für Gmail-Zugangsdaten
        env_vars = os.getenv('DREWRY')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            return None
        
        # Parse Umgebungsvariablen
        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=')
            if key == 'GMAIL_USER':
                gmail_user = value
            elif key == 'GMAIL_PASS':
                gmail_pass = value
        
        if not gmail_user or not gmail_pass:
            logger.error("GMAIL_USER or GMAIL_PASS not found in DREWRY")
            return None

        # Verbindung zu Gmail herstellen
        logger.debug("Connecting to Gmail IMAP")
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(gmail_user, gmail_pass)
        mail.select('inbox')
        
        # Suche nach E-Mails von noreply@drewry.co.uk
        today = datetime.now().strftime("%d-%b-%Y")
        search_criteria = f'(FROM "noreply@drewry.co.uk" ON "{today}")'
        logger.debug(f"Searching emails with criteria: {search_criteria}")
        result, data = mail.search(None, search_criteria)
        
        if result != 'OK':
            logger.error("Failed to search emails")
            mail.logout()
            return None
        
        email_ids = data[0].split()
        if not email_ids:
            logger.error("No emails found from noreply@drewry.co.uk")
            mail.logout()
            return None
        
        # Hole die neueste E-Mail
        latest_email_id = email_ids[-1]
        logger.debug(f"Fetching email ID: {latest_email_id}")
        result, data = mail.fetch(latest_email_id, '(RFC822)')
        
        if result != 'OK':
            logger.error("Failed to fetch email")
            mail.logout()
            return None
        
        # E-Mail parsen
        raw_email = data[0][1]
        email_message = email.message_from_bytes(raw_email)
        
        # Betreff dekodieren
        subject, encoding = decode_header(email_message['subject'])[0]
        if isinstance(subject, bytes):
            subject = subject.decode(encoding if encoding else 'utf-8')
        logger.debug(f"Email subject: {subject}")
        
        # HTML-Inhalt extrahieren
        html_content = None
        if email_message.is_multipart():
            for part in email_message.walk():
                if part.get_content_type() == 'text/html':
                    html_content = part.get_payload(decode=True).decode('utf-8')
                    break
        else:
            if email_message.get_content_type() == 'text/html':
                html_content = email_message.get_payload(decode=True).decode('utf-8')
        
        if not html_content:
            logger.error("No HTML content found in email")
            mail.logout()
            return None
        
        # Speichere HTML-Inhalt
        email_id_str = latest_email_id.decode('utf-8')
        html_filename = f'wci_email_{email_id_str}.html'
        logger.debug(f"Saving HTML content to {html_filename}")
        with open(html_filename, 'w', encoding='utf-8') as f:
            f.write(html_content)
        
        logger.info(f"Successfully saved email content to {html_filename}")
        mail.logout()
        return html_filename
    
    except Exception as e:
        logger.error(f"Error fetching email: {str(e)}")
        if 'mail' in locals():
            mail.logout()
        return None

def extract_wci_from_html(html_file):
    """Extrahiert den WCI-Wert und den Prozentsatz aus der HTML-Datei."""
    logger.debug(f"Attempting to read HTML file: {html_file}")
    try:
        with open(html_file, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f, 'html.parser')
        
        # Suche nach dem <div>-Element mit dem WCI-Wert
        wci_div = soup.find('div', string=re.compile(r'Drewry’s World Container Index.*?\$\d{1,3}(,\d{3})*\s'))
        if not wci_div:
            logger.error("No div containing WCI value found in HTML")
            return None, None
        
        wci_text = wci_div.get_text(strip=True)
        logger.debug(f"Found WCI text: {wci_text}")
        
        # Extrahiere WCI-Wert und Prozentsatz mit Regex
        wci_match = re.search(r'\$(\d{1,3}(,\d{3})*)', wci_text)
        percent_match = re.search(r'(\w+)\s+(\d+)%', wci_text)
        
        if not wci_match:
            logger.error("Could not extract WCI value from text")
            return None, None
        
        wci_value = wci_match.group(0)  # z. B. "$2,983"
        percent_change = None
        if percent_match:
            direction = percent_match.group(1)  # "decreased" oder "increased"
            percent_value = percent_match.group(2)  # "9"
            percent_change = f"{direction} {percent_value}%"  # z. B. "decreased 9%"
        
        logger.info(f"Extracted WCI: {wci_value}, Change: {percent_change}")
        return wci_value, percent_change
    
    except Exception as e:
        logger.error(f"Error processing HTML file {html_file}: {str(e)}")
        return None, None

def generate_briefing():
    logger.debug("Starting briefing generation")
    
    # Finde die neueste wci_email_*.html-Datei
    html_files = glob.glob('wci_email_*.html')
    if not html_files:
        logger.error("No wci_email_*.html files found")
        return "Daily China Briefing: No WCI data available"
    
    # Wähle die neueste Datei (nach Dateiname oder Änderungszeit)
    latest_html = max(html_files, key
