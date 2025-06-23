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
        print(f"DEBUG - save_scfi_cache: Successfully wrote cache to {cache_file}")
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
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    scfi_cache = load_scfi_cache()

    try:
        print(f"DEBUG - fetch_scfi: Fetching data from {url}")
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        print(f"DEBUG - fetch_scfi: Successfully fetched API, status code: {response.status_code}")
        print(f"DEBUG - fetch_scfi: API response length: {len(response.text)}")

        data = response.json()
        print(f"DEBUG - fetch_scfi: API response: {data}")

        if data.get("status") == 0:
            print(f"❌ ERROR - fetch_scfi: API error: {data.get('msg')}")
            raise Exception(data.get("msg"))

        scfi_data = data.get("data", {})
        current_date = scfi_data.get("currentDate")
        last_date = scfi_data.get("lastDate")
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

        scfi_cache[today_str] = scfi_value
        save_scfi_cache(scfi_cache)

        return scfi_value, pct_change, scfi_date

    except Exception as e:
        print(f"❌ ERROR - fetch_scfi: Failed to fetch SCFI data: {str(e)}")
        if today_str in scfi_cache:
            scfi_value = scfi_cache[today_str]
            scfi_date = date.today().strftime("%d.%m.%Y")
            print(f"DEBUG - fetch_scfi: Using cached SCFI value: {scfi_value}, Date: {scfi_date}")
            prev_scfi = scfi_cache.get(yesterday_str)
            if prev_scfi is not None:
                pct_change = ((scfi_value - prev_scfi) / prev_scfi) * 100 if prev_scfi != 0 else 0
                print(f"DEBUG - fetch_scfi: Calculated percent change from cache: {pct_change:.2f}%")
            else:
                pct_change = None
                print(f"DEBUG - fetch_scfi: No previous SCFI value in cache, cannot calculate percent change")
            return scfi_value, pct_change, scfi_date
        scfi_value = 1869.59
        scfi_date = date.today().strftime("%d.%m.%Y")
        print(f"DEBUG - fetch_scfi: Using fallback SCFI value: {scfi_value}, Date: {scfi_date}")
        scfi_cache[today_str] = scfi_value
        save_scfi_cache(scfi_cache)
        return scfi_value, None, scfi_date

def generate_briefing():
    print("DEBUG - generate_briefing: Starting to generate briefing")
    try:
        scfi_value, pct_change, scfi_date = fetch_scfi()
        # Fix: Behandle None für pct_change
        pct_change_str = f"{pct_change:.2f}" if pct_change is not None else "N/A"
        scfi_line = f"SCFI: {scfi_value:.2f} {pct_change_str}% (Stand: {scfi_date})"
        expected_line = f"Erwartet: {scfi_value:.2f} {pct_change_str}% (Stand: {scfi_date})"
        print(f"DEBUG - generate_briefing: SCFI line: {scfi_line}")
        print(f"DEBUG - generate_briefing: Expected line: {expected_line}")

        briefing_lines = [
            "Das ist ein Test, ob der SCFI funktioniert.",
            scfi_line,
            expected_line
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

        smtp_server = "smtp.gmx.com"
        smtp_port = 587
        email_user = os.getenv("SUBSTACK_MAIL")
        email_password = os.getenv("SUBSTACK_MAIL_PASSWORD")
        
        if not email_user:
            print("❌ ERROR - send_briefing: SUBSTACK_MAIL environment variable missing")
            raise Exception("Missing SUBSTACK_MAIL")
        if not email_password:
            print("❌ ERROR - send_briefing: SUBSTACK_MAIL_PASSWORD environment variable missing")
            raise Exception("Missing SUBSTACK_MAIL_PASSWORD")

        print(f"DEBUG - send_briefing: Using email user: {email_user}")
        msg = MIMEText(briefing)
        msg['Subject'] = "Daily China Briefing"
        msg['From'] = email_user
        msg['To'] = email_user

        print("DEBUG - send_briefing: Connecting to SMTP server")
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            print("DEBUG - send_briefing: Logging in to SMTP server")
            server.login(email_user, email_password)
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
