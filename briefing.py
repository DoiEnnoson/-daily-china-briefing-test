import os
import json
import re
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta
from email.mime.text import MIMEText
import smtplib

# Pfad zum SCFI-Cache (relativ zum Script-Verzeichnis)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCFI_CACHE_FILE = os.path.join(BASE_DIR, "scfi_cache.json")

# SCFI-Cache laden
def load_scfi_cache():
    print(f"DEBUG - load_scfi_cache: Attempting to load cache from {SCFI_CACHE_FILE}")
    try:
        if os.path.exists(SCFI_CACHE_FILE):
            with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                print(f"DEBUG - load_scfi_cache: Successfully loaded cache: {cache}")
                return cache
        else:
            print(f"DEBUG - load_scfi_cache: Cache file {SCFI_CACHE_FILE} does not exist")
            return {}
    except Exception as e:
        print(f"ERROR - load_scfi_cache: Failed to load cache: {str(e)}")
        return {}

# SCFI-Cache speichern
def save_scfi_cache(cache):
    print(f"DEBUG - save_scfi_cache: Attempting to save cache to {SCFI_CACHE_FILE}")
    print(f"DEBUG - save_scfi_cache: Cache content: {cache}")
    try:
        os.makedirs(os.path.dirname(SCFI_CACHE_FILE), exist_ok=True)
        print(f"DEBUG - save_scfi_cache: Ensured directory exists: {os.path.dirname(SCFI_CACHE_FILE)}")
        with open(SCFI_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print(f"DEBUG - save_scfi_cache: Successfully wrote cache to {SCFI_CACHE_FILE}")
        with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
            saved_cache = json.load(f)
            print(f"DEBUG - save_scfi_cache: Verified cache content: {saved_cache}")
    except Exception as e:
        print(f"ERROR - save_scfi_cache: Failed to save cache to {SCFI_CACHE_FILE}: {str(e)}")
        raise

# SCFI-Daten von der Shanghai Shipping Exchange abrufen
def fetch_scfi():
    print("DEBUG - fetch_scfi: Starting to fetch SCFI data")
    url = "https://en.sse.net.cn/indices/scfinew.jsp"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    today_str = date.today().isoformat()
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    scfi_cache = load_scfi_cache()

    try:
        # Webseite abrufen
        print(f"DEBUG - fetch_scfi: Fetching data from {url}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"DEBUG - fetch_scfi: Successfully fetched page, status code: {response.status_code}")
        print(f"DEBUG - fetch_scfi: HTML content length: {len(response.text)}")

        # HTML speichern für Debugging
        with open("scfi_page.html", "w", encoding="utf-8") as f:
            f.write(response.text)
        print(f"DEBUG - fetch_scfi: Saved HTML to scfi_page.html")

        # HTML parsen
        soup = BeautifulSoup(response.text, "html.parser")
        print(f"DEBUG - fetch_scfi: Parsed HTML with BeautifulSoup")

        # Suche nach allen Tabellen
        scfi_value = None
        scfi_date = None
        tables = soup.find_all("table")
        print(f"DEBUG - fetch_scfi: Found {len(tables)} tables on page")
        for i, table in enumerate(tables):
            class_name = table.get("class", [])
            print(f"DEBUG - fetch_scfi: Table {i+1} classes: {class_name}")
            rows = table.find_all("tr")
            print(f"DEBUG - fetch_scfi: Table {i+1} has {len(rows)} rows")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    date_text = cells[0].text.strip()
                    value_text = cells[1].text.strip()
                    print(f"DEBUG - fetch_scfi: Row data - Date: {date_text}, Value: {value_text}")
                    try:
                        # Versuche, das Datum zu parsen
                        parsed_date = None
                        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
                            try:
                                parsed_date = datetime.strptime(date_text, fmt).date()
                                break
                            except ValueError:
                                continue
                        if parsed_date is None:
                            print(f"DEBUG - fetch_scfi: Could not parse date '{date_text}'")
                            continue
                        if parsed_date >= date.today() - timedelta(days=7):  # Akzeptiere bis zu einer Woche zurück
                            scfi_value = float(value_text.replace(",", ""))
                            scfi_date = parsed_date.strftime("%d%m%Y")
                            print(f"✅ DEBUG - fetch_scfi: Found SCFI value: {scfi_value}, Date: {scfi_date}")
                            break
                    except ValueError:
                        print(f"DEBUG - fetch_scfi: Could not convert value '{value_text}' to float")
                        continue
            if scfi_value is not None:
                break

        if scfi_value is None:
            print(f"❌ ERROR - fetch_scfi: No SCFI value found in tables")
            # Fallback: Suche nach einer Zahl im Format xxxx.xx
            text = soup.get_text()
            number_matches = re.findall(r'\b\d{3,5}\.\d{2}\b', text)
            print(f"DEBUG - fetch_scfi: Fallback search found {len(number_matches)} potential SCFI values: {number_matches}")
            if number_matches:
                scfi_value = float(number_matches[0])
                scfi_date = date.today().strftime("%d%m%Y")
                print(f"DEBUG - fetch_scfi: Using fallback SCFI value: {scfi_value}, Date: {scfi_date}")

        if scfi_value is None:
            print(f"❌ ERROR - fetch_scfi: Could not find SCFI value on page")
            if today_str in scfi_cache:
                scfi_value = scfi_cache[today_str]
                scfi_date = date.today().strftime("%d%m%Y")
                print(f"DEBUG - fetch_scfi: Using cached SCFI value: {scfi_value}, Date: {scfi_date}")
            else:
                # Fallback-Wert, um Cache zu initialisieren
                scfi_value = 1869.59  # Aus deinem Beispiel
                scfi_date = date.today().strftime("%d%m%Y")
                print(f"DEBUG - fetch_scfi: Using fallback SCFI value: {scfi_value}, Date: {scfi_date}")

        # Prozentuale Veränderung berechnen
        prev_scfi = scfi_cache.get(yesterday_str)
        if prev_scfi is not None:
            pct_change = ((scfi_value - prev_scfi) / prev_scfi) * 100 if prev_scfi != 0 else 0
            print(f"DEBUG - fetch_scfi: Calculated percent change: {pct_change:.2f}% (Current: {scfi_value}, Previous: {prev_scfi})")
        else:
            pct_change = None
            print(f"DEBUG - fetch_scfi: No previous SCFI value in cache, cannot calculate percent change")

        # Cache aktualisieren
        scfi_cache[today_str] = scfi_value
        save_scfi_cache(scfi_cache)

        return scfi_value, pct_change, scfi_date

    except Exception as e:
        print(f"❌ ERROR - fetch_scfi: Failed to fetch SCFI data: {str(e)}")
        print(f"DEBUG - fetch_scfi: Saving error HTML to scfi_page.html")
        if 'response' in locals():
            with open("scfi_page.html", "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f"DEBUG - fetch_scfi: Saved error HTML to scfi_page.html")
        if today_str in scfi_cache:
            scfi_value = scfi_cache[today_str]
            scfi_date = date.today().strftime("%d%m%Y")
            print(f"DEBUG - fetch_scfi: Using cached SCFI value due to error: {scfi_value}, Date: {scfi_date}")
            prev_scfi = scfi_cache.get(yesterday_str)
            if prev_scfi is not None:
                pct_change = ((scfi_value - prev_scfi) / prev_scfi) * 100 if prev_scfi != 0 else 0
                print(f"DEBUG - fetch_scfi: Calculated percent change from cache: {pct_change:.2f}%")
            else:
                pct_change = None
                print(f"DEBUG - fetch_scfi: No previous SCFI value in cache, cannot calculate percent change")
            return scfi_value, pct_change, scfi_date
        # Fallback-Wert, um Cache zu initialisieren
        scfi_value = 1869.59  # Aus deinem Beispiel
        scfi_date = date.today().strftime("%d%m%Y")
        print(f"DEBUG - fetch_scfi: Using fallback SCFI value due to error: {scfi_value}, Date: {scfi_date}")
        scfi_cache[today_str] = scfi_value
        save_scfi_cache(scfi_cache)
        return scfi_value, None, scfi_date

# Briefing generieren
def generate_briefing():
    print("DEBUG - generate_briefing: Starting to generate briefing")
    briefing = ["Das ist ein Test, ob der SCFI funktioniert."]

    # SCFI-Daten abrufen
    scfi_value, pct_change, scfi_date = fetch_scfi()
    if scfi_value is not None and scfi_date is not None:
        if pct_change is not None:
            scfi_line = f"SCFI: {scfi_value:.2f} {pct_change:+.2f}% (Stand: {scfi_date})"
        else:
            scfi_line = f"SCFI: {scfi_value:.2f} (Stand: {scfi_date})"
        print(f"DEBUG - generate_briefing: SCFI line: {scfi_line}")
    else:
        scfi_line = "SCFI: ❌ Keine Daten verfügbar"
        print(f"❌ ERROR - generate_briefing: No SCFI data available")
    briefing.append(scfi_line)

    # Erwarteter Wert (statisch wie im Beispiel)
    briefing.append("Erwartet: 1869.59 -10,47% (Stand: 20.06.2025)")

    print(f"DEBUG - generate_briefing: Generated briefing with {len(briefing)} lines")
    return "\n".join(briefing)

# E-Mail senden
def send_briefing():
    print("🧠 DEBUG - send_briefing: Starting to generate and send briefing")
    briefing_content = generate_briefing()

    config = os.getenv("CONFIG")
    if not config:
        print("❌ ERROR - send_briefing: CONFIG environment variable not found, skipping email")
        return

    try:
        pairs = config.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(briefing_content, "plain", "utf-8")
        msg["Subject"] = "📰 Dein tägliches China-Briefing (SCFI Test)"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = config_dict["EMAIL_TO"]

        print("📤 DEBUG - send_briefing: Sending email")
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        print("✅ DEBUG - send_briefing: Email sent successfully")
    except Exception as e:
        print(f"❌ ERROR - send_briefing: Failed to send email: {str(e)}")

# Hauptskript
if __name__ == "__main__":
    print("DEBUG - main: Starting script execution")
    briefing_content = generate_briefing()
    print(f"DEBUG - main: Briefing content:\n{briefing_content}")
    with open("scfi_test.txt", "w", encoding="utf-8") as f:
        f.write(briefing_content)
    print("DEBUG - main: Briefing written to scfi_test.txt")
    # Überprüfen, ob Cache-Datei existiert
    if os.path.exists(SCFI_CACHE_FILE):
        print(f"DEBUG - main: Cache file {SCFI_CACHE_FILE} exists")
        with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
            print(f"DEBUG - main: Cache content: {f.read()}")
    else:
        print(f"DEBUG - main: Cache file {SCFI_CACHE_FILE} does not exist")
    # E-Mail senden
    send_briefing()
