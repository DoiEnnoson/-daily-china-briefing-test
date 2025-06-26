import os
import glob
import re
import logging
from datetime import datetime
from bs4 import BeautifulSoup

# Logging einrichten
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('briefing_log.txt', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()

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
    latest_html = max(html_files, key=os.path.getmtime)
    logger.debug(f"Using latest HTML file: {latest_html}")
    
    # Extrahiere WCI-Wert und Prozentsatz
    wci_value, percent_change = extract_wci_from_html(latest_html)
    if not wci_value:
        logger.error("Failed to extract WCI value")
        return "Daily China Briefing: Failed to extract WCI data"
    
    # Erstelle den Bericht
    report_date = datetime.now().strftime("%d %b %Y")
    wci_text = f"WCI: {wci_value}"
    if percent_change:
        wci_text += f", {percent_change} w/w"
    
    report = f"""Daily China Briefing - {report_date}
{'=' * 50}
World Container Index
{'-' * 20}
{wci_text}
{'-' * 20}
[Weitere Inhalte hier einfügen]
"""
    
    logger.info("Generated briefing report")
    logger.debug(f"Report content:\n{report}")
    
    # Speichere den Bericht
    try:
        with open('daily_briefing.md', 'w', encoding='utf-8') as f:
            f.write(report)
        logger.info("Saved briefing to daily_briefing.md")
    except Exception as e:
        logger.error(f"Failed to save briefing: {str(e)}")
        return "Daily China Briefing: Error saving report"
    
    return report

if __name__ == "__main__":
    logger.debug("Starting main execution")
    report = generate_briefing()
    print(report)
    logger.debug("Briefing generation completed")
