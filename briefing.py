import os
import json
import requests
from bs4 import BeautifulSoup
from datetime import date, datetime, timedelta

# Pfad zum SCFI-Cache (relativ zum Script-Verzeichnis)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCFI_CACHE_FILE = os.path.join(BASE_DIR, "scfi_cache.json")

# SCFI-Cache laden
def load_scfi_cache():
    print(f"DEBUG - load_scfi_cache: Starting to load cache from {SCFI_CACHE_FILE}")
    try:
        if os.path.exists(SCFI_CACHE_FILE):
            with open(SCFI_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
                print(f"DEBUG - load_scfi_cache: Successfully loaded cache: {cache}")
                return cache
        else:
            print(f"DEBUG - load_scfi_cache: No cache file found at {SCFI_CACHE_FILE}")
            return {}
    except Exception as e:
        print(f"ERROR - load_scfi_cache: Failed to load cache: {str(e)}")
        return {}

# SCFI-Cache speichern
def save_scfi_cache(cache):
    print(f"DEBUG - save_scfi_cache: Starting to save cache to {SCFI_CACHE_FILE}")
    print(f"DEBUG - save_scfi_cache: Cache content: {cache}")
    try:
        os.makedirs(os.path.dirname(SCFI_CACHE_FILE), exist_ok=True)
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
    url = "https://en.sse.net.cn/indices/scfi_new.jsp"
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

        # HTML parsen
        soup = BeautifulSoup(response.text, "html.parser")
        print(f"DEBUG - fetch_scfi: Parsed HTML with BeautifulSoup")

        # Suche nach dem SCFI-Wert (angenommen, er ist in einem <td> oder <div> mit einer Zahl wie "xxxx.xx")
        scfi_value = None
        scfi_date = None
        table = soup.find("table", class_="table2")
        if table:
            print(f"DEBUG - fetch_scfi: Found table with class 'table2'")
            rows = table.find_all("tr")
            print(f"DEBUG - fetch_scfi: Found {len(rows)} rows in table")
            for row in rows:
                cells = row.find_all("td")
                if len(cells) >= 2:
                    date_text = cells[0].text.strip()
                    value_text = cells[1].text.strip()
                    print(f"DEBUG - fetch_scfi: Row data - Date: {date_text}, Value: {value_text}")
                    try:
                        # Versuche, das Datum zu parsen (erwartetes Format: YYYY-MM-DD oder DD/MM/YYYY)
                        parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
                        if parsed_date == date.today():
                            scfi_value = float(value_text)
                            scfi_date = parsed_date.strftime("%d%m%Y")
                            print(f"✅ DEBUG - fetch_scfi: Found SCFI value: {scfi_value}, Date: {scfi_date}")
                            break
                    except ValueError:
                        print(f"DEBUG - fetch_scfi: Could not parse date '{date_text}'")
                        continue
        else:
            print(f"❌ ERROR - fetch_scfi: No table with class 'table2' found")
            # Fallback: Suche nach einer Zahl im Text, die wie ein Index aussieht
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
                print(f"❌ ERROR - fetch_scfi: No cached SCFI value available")
                return None, None, None

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
        return None, None, None

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

# Hauptskript
if __name__ == "__main__":
    print("DEBUG - main: Starting script execution")
    briefing_content = generate_briefing()
    print(f"DEBUG - main: Briefing content:\n{briefing_content}")
    with open("scfi_test.txt", "w", encoding="utf-8") as f:
        f.write(briefing_content)
    print("DEBUG - main: Briefing written to scfi_test.txt")
