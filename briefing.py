import requests
import json
import os
import smtplib
from email.mime.text import MIMEText
from datetime import date, datetime, timedelta

def load_scfi_cache():
    cache_file = "scfi_cache.json"
    print(f"DEBUG - load_scfi_cache: Attempting to load cache from {cache_file}")
    try:
        with open(cache_file, "r") as f:
            cache = json.load(f)
            print(f"DEBUG - load_scfi_cache: Successfully loaded cache: {cache}")
            return cache
    except FileNotFoundError:
        print("DEBUG - load_scfi_cache: Cache file not found, returning empty cache")
        return {}
    except Exception as e:
        print(f"❌ ERROR - load_scfi_cache: Failed to load cache: {str(e)}")
        return {}

def save_scfi_cache(cache):
    cache_file = "scfi_cache.json"
    print(f"DEBUG - save_scfi_cache: Attempting to save cache to {cache_file}")
    print(f"DEBUG - save_scfi_cache: Cache content: {cache}")
    try:
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"DEBUG - save_scfi_cache: Successfully written cache to {cache_file}")
        with open(cache_file, "r") as f:
            print(f"DEBUG - save_scfi_cache: Verified cache content: {json.load(f)}")
    except Exception as e:
        print(f"❌ ERROR - save_scfi_cache: Failed to save cache: {str(e)}")
        raise

def fetch_scfi():
    print("DEBUG - fetch_scfi: Starting to fetch SCFI data")
    url = "https://en.sse.net.cn/currentIndex?indexName=scfi"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    today_str = date.today().isoformat()
    cache = load_scfi_cache()

    try:
        print(f"DEBUG - fetch_scfi: Fetching data from {url}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"DEBUG - fetch_scfi: Successfully fetched API, status code: {response.status_code}")
        data = response.json()
        print(f"DEBUG - fetch_scfi: API response: {data}")

        if data.get("status") == 0:
            print(f"❌ ERROR - fetch_scfi: API error: {data.get('msg')}")
            raise Exception(data.get("msg"))

        scfi_data = data.get("data", {})
        current_date = scfi_data.get("currentDate")
        line_data_list = scfi_data.get("lineDataList", [])

        if not line_data_list:
            print("❌ ERROR - fetch_scfi: No lineDataList found in API response")
            raise Exception("No lineDataList in API response")

        scfi_value = float(line_data_list[0]["currentContent"])
        last_value = float(line_data_list[0]["lastContent"])
        scfi_date = None

        for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
            try:
                scfi_date = datetime.strptime(current_date, fmt).strftime("%d.%m.%Y")
                break
            except ValueError:
                continue
        if scfi_date is None:
            print(f"DEBUG - fetch_scfi: Could not parse date '{current_date}', using today")
            scfi_date = date.today().strftime("%d.%m.%Y")

        print(f"✅ DEBUG - fetch_scfi: Found SCFI value: {scfi_value}, Date: {scfi_date}")

        pct_change = None
        if last_value is not None:
            pct_change = ((scfi_value - last_value) / last_value) * 100 if last_value != 0 else 0
            print(f"DEBUG - fetch_scfi: Calculated percent change: {pct_change:.2f}% (Current: {scfi_value}, Previous: {last_value})")

        latest_cache_date = max(cache.keys(), default=None)
        should_save = True
        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            if latest_entry["value"] == scfi_value and latest_entry["api_date"] == current_date:
                should_save = False
                print("DEBUG - fetch_scfi: No change in value or api_date, skipping cache save")

        if should_save:
            cache[today_str] = {"value": scfi_value, "api_date": current_date}
            save_scfi_cache(cache)

        return scfi_value, pct_change, scfi_date, None

    except Exception as e:
        print(f"❌ ERROR - fetch_scfi: Failed to fetch SCFI data: {str(e)}")
        warning_message = None
        latest_cache_date = max(cache.keys(), default=None)
        ten_days_ago = (date.today() - timedelta(days=10)).isoformat()

        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            scfi_value = latest_entry["value"]
            api_date_str = latest_entry["api_date"]
            scfi_date = None

            for fmt in ["%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"]:
                try:
                    scfi_date = datetime.strptime(api_date_str, fmt).strftime("%d.%m.%Y")
                    break
                except ValueError:
                    continue
            if scfi_date is None:
                scfi_date = date.today().strftime("%d.%m.%Y")

            try:
                api_date = datetime.strptime(api_date_str, "%Y-%m-%d")
                if api_date >= datetime.strptime(ten_days_ago, "%Y-%m-%d"):
                    print(f"DEBUG - fetch_scfi: Using cached SCFI value: {scfi_value}, Date: {scfi_date}")
                    warning_message = f"API nicht erreichbar, Cache-Wert {scfi_value} (api_date: {api_date_str}) genutzt"
                    return scfi_value, None, scfi_date, warning_message
                else:
                    warning_message = f"API nicht erreichbar, Cache-Wert {scfi_value} zu alt (api_date: {api_date_str})"
            except ValueError:
                warning_message = f"API nicht erreichbar, Cache-Datum ungültig (api_date: {api_date_str})"

        scfi_value = 1869.59
        scfi_date = date.today().strftime("%d.%m.%Y")
        warning_message = warning_message or "API ausgefallen, kein Cache verfügbar, Fallback 1869.59 genutzt"
        print(f"DEBUG - fetch_scfi: Using fallback SCFI value: {scfi_value}, Date: {scfi_date}")
        cache[today_str] = {"value": scfi_value, "api_date": today_str}
        save_scfi_cache(cache)
        return scfi_value, None, scfi_date, warning_message

def send_warning_email(warning_message):
    print("📩 DEBUG - send_warning_email: Preparing to send warning email")
    try:
        config = os.getenv("CONFIG")
        if not config:
            print("❌ ERROR - send_warning_email: CONFIG environment variable not found")
            raise Exception("Missing CONFIG")

        pairs = config.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(
            f"Problem: API-Ausfall oder veralteter Cache\nDetails: {warning_message}\nDatum: {date.today().strftime('%Y-%m-%d')}",
            "plain",
            "utf-8"
        )
        msg["Subject"] = "China-Briefing SCFI API-Warnung"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = "hadobrockmeyer@gmail.com"

        print("DEBUG - send_warning_email: Connecting to SMTP server")
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            print("DEBUG - send_warning_email: Logging in to SMTP server")
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            print("DEBUG - send_warning_email: Sending warning email")
            server.send_message(msg)
            print("✅ DEBUG - send_warning_email: Warning email sent successfully")
    except Exception as e:
        print(f"❌ ERROR - send_warning_email: Failed to send warning email: {str(e)}")
        raise

def generate_briefing():
    print("DEBUG - generate_briefing: Starting to generate briefing")
    try:
        scfi_value, pct_change, scfi_date, warning_message = fetch_scfi()
        if warning_message:
            send_warning_email(warning_message)

        arrow = "→"
        pct_change_str = "0.00"
        if pct_change is not None:
            pct_change_str = f"{pct_change:.2f}"
            if pct_change > 0:
                arrow = "↑"
            elif pct_change < 0:
                arrow = "↓"

        scfi_line = f"SCFI (https://en.sse.net.cn/indices/scfinew.jsp): {scfi_value:.2f} {arrow} ({pct_change_str}%, Stand {scfi_date})"
        wci_line = f"WCI: 2584.00 ↓ (-8.00%, Stand {date.today().strftime('%d.%m.%Y')})"
        iaca_line = f"IACA: 875.00 ↑ (+2.00%, Stand {date.today().strftime('%d.%m.%Y')})"

        briefing_lines = [
            "### Frachtraten Indizies",
            scfi_line,
            wci_line,
            iaca_line
        ]
        print(f"DEBUG - generate_briefing: Generated briefing with {len(briefing_lines)} lines")
        return "\n".join(briefing_lines)
    except Exception as e:
        print(f"❌ ERROR - generate_briefing: Failed to generate briefing: {str(e)}")
        raise

def send_briefing():
    print("📤 DEBUG - send_briefing: Starting to generate and send briefing")
    try:
        briefing = generate_briefing()
        print(f"DEBUG - send_briefing: Briefing content: {briefing}")

        config = os.getenv("CONFIG")
        if not config:
            print("❌ ERROR - send_briefing: CONFIG environment variable not found")
            raise Exception("Missing CONFIG")

        pairs = config.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(briefing, "plain", "utf-8")
        msg["Subject"] = "📰 Dein tägliches China-Briefing (SCFI Test)"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = config_dict["EMAIL_TO"]

        print("DEBUG - send_briefing: Connecting to SMTP server")
        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            print("DEBUG - send_briefing: Logging in to SMTP server")
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            print("DEBUG - send_briefing: Sending email")
            server.send_message(msg)
            print("✅ DEBUG - send_briefing: Email sent successfully")
    except Exception as e:
        print(f"❌ ERROR - send_briefing: Failed to send email: {str(e)}")
        raise

def main():
    print("DEBUG - main: Starting script execution")
    try:
        briefing = generate_briefing()
        print(f"DEBUG - main: Briefing content:\n{briefing}")
        with open("scfi_test.txt", "w") as f:
            f.write(briefing)
        print("DEBUG - main: Briefing written to scfi_test.txt")
        
        cache_file = "scfi_cache.json"
        if os.path.exists(cache_file):
            print(f"DEBUG - main: Cache file {cache_file} exists")
            with open(cache_file, "r") as f:
                print(f"DEBUG - main: Cache content: {f.read()}")
        else:
            print(f"DEBUG - main: Cache file {cache_file} does not exist")
        
        send_briefing()
    except Exception as e:
        print(f"❌ ERROR - main: Script failed: {str(e)}")
        raise

if __name__ == "__main__":
    main()
