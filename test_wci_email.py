import os
import re
import logging
import imaplib
import email
import smtplib
import json
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from email.header import decode_header
from bs4 import BeautifulSoup
import glob

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

# Pfade
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WCI_CACHE_FILE = os.path.join(BASE_DIR, "WCI", "wci_cache.json")

def load_wci_cache():
    """Lädt den WCI-Cache oder initialisiert ihn als leer, wenn nicht vorhanden."""
    logger.debug(f"Loading cache from {WCI_CACHE_FILE}")
    try:
        os.makedirs(os.path.dirname(WCI_CACHE_FILE), exist_ok=True)
        if os.path.exists(WCI_CACHE_FILE):
            with open(WCI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                logger.debug(f"Successfully loaded cache: {cache}")
                return cache
        logger.debug(f"No cache file found at {WCI_CACHE_FILE}, initializing empty cache")
        cache = {}
        save_wci_cache(cache)  # Leere Cache-Datei erstellen
        return cache
    except Exception as e:
        logger.error(f"Failed to load cache: {str(e)}, initializing empty cache")
        cache = {}
        save_wci_cache(cache)
        return cache

def save_wci_cache(cache):
    """Speichert den WCI-Cache."""
    logger.debug(f"Saving cache to {WCI_CACHE_FILE}: {cache}")
    try:
        os.makedirs(os.path.dirname(WCI_CACHE_FILE), exist_ok=True)
        with open(WCI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        logger.info(f"Successfully wrote cache to {WCI_CACHE_FILE}")
    except Exception as e:
        logger.error(f"Failed to save cache: {str(e)}")
        raise

def fetch_wci_email():
    """Holt die neueste Drewry-E-Mail und speichert den HTML-Inhalt."""
    logger.debug("Starting email fetch")
    try:
        env_vars = os.getenv('DREWRY')
        if not env_vars:
            logger.error("DREWRY environment variable not set")
            raise Exception("DREWRY not set")

        gmail_user = None
        gmail_pass = None
        for var in env_vars.split(';'):
            key, value = var.split('=', 1)
            if key.strip() == 'GMAIL_USER':
                gmail_user = value.strip()
            elif key.strip() == 'GMAIL_PASS':
                gmail
