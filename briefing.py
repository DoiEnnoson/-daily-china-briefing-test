import requests
import json
import os
import smtplib
from email.mime.text import MIMEText
from datetime import date, datetime, timedelta

def load_scfi_cache():
    cache_file = "scfi_cache.json"
    try:
        with open(cache_file, "r") as f:
            cache = json.load(f)
            for key, value in cache.items():
                if isinstance(value, (int, float)):
                    cache[key] = {"value": float(value), "api_date": key}
            print(f"Cache-Inhalt: {cache}")
            return cache
    except FileNotFoundError:
        print("Cache-Datei nicht gefunden, leerer Cache wird verwendet")
        return {}
    except Exception as e:
        print(f"❌ Fehler beim Laden des Cache: {str(e)}")
        return {}

def save_scfi_cache(cache):
    cache_file = "scfi_cache.json"
    try:
        with open(cache_file, "w") as f:
            json.dump(cache, f, indent=2)
        print("Cache erfolgreich gespeichert")
    except Exception as e:
        print(f"❌ Fehler beim Speichern des Cache: {str(e)}")
        raise

def fetch_scfi():
    url = "https://en.sse.net.cn/currentIndex?indexName=scfi"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"}
    today_str = date.today().isoformat()
    cache = load_scfi_cache()

    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        if data.get("status") == 0:
            raise Exception(data.get("msg"))

        scfi_data = data.get("data", {})
        current_date = scfi_data.get("currentDate")
        line_data_list = scfi_data.get("lineDataList", [])

        if not line_data_list:
            raise Exception("Keine Daten in der API-Antwort")

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
            scfi_date = date.today().strftime("%d.%m.%Y")

        print(f"SCFI-Wert {scfi_value:.2f} per API ausgelesen (Datum: {scfi_date})")

        pct_change = None
        if last_value is not None:
            pct_change = ((scfi_value - last_value) / last_value) * 100 if last_value != 0 else 0

        latest_cache_date = max(cache.keys(), default=None)
        should_save = True
        if latest_cache_date:
            latest_entry = cache[latest_cache_date]
            if latest_entry["value"] == scfi_value and latest_entry["api_date"] == current_date:
                should_save = False
                print("Kein Cache-Update nötig (Wert und Datum unverändert)")

        if should_save:
            cache[today_str] = {"value": scfi_value, "api_date": current_date}
            save_scfi_cache(cache)

        return scfi_value, pct_change, scfi_date, None

    except Exception as e:
        print(f"❌ Fehler beim Abrufen der SCFI-Daten: {str(e)}")
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
                    print(f"SCFI-Wert {scfi_value:.2f} aus Cache verwendet (Datum: {scfi_date})")
                    warning_message = f"API nicht erreichbar, Cache-Wert {scfi_value} (Datum: {api_date_str}) genutzt"
                    return scfi_value, None, scfi_date, warning_message
                else:
                    warning_message = f"API nicht erreichbar, Cache-Wert {scfi_value} zu alt (Datum: {api_date_str})"
            except ValueError:
                warning_message = f"API nicht erreichbar, Cache-Datum ungültig (Datum: {api_date_str})"

        scfi_value = 1869.59
        scfi_date = date.today().strftime("%d.%m.%Y")
        warning_message = warning_message or "API ausgefallen, kein Cache verfügbar, Fallback 1869.59 genutzt"
        print(f"SCFI-Wert {scfi_value:.2f} als Fallback verwendet (Datum: {scfi_date})")
        return scfi_value, None, scfi_date, warning_message

def send_warning_email(warning_message):
    try:
        config = os.getenv("CONFIG")
        if not config:
            raise Exception("CONFIG-Umgebungsvariable fehlt")

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

        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        print("Warn-E-Mail erfolgreich gesendet")
    except Exception as e:
        print(f"❌ Fehler beim Senden der Warn-E-Mail: {str(e)}")
        raise

def generate_briefing():
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

        scfi_line = f"[SCFI](https://en.sse.net.cn/indices/scfinew.jsp): {scfi_value:.2f} {arrow} ({pct_change_str}%, Stand {scfi_date})"
        wci_line = f"WCI: 2584.00 ↓ (-8.00%, Stand {date.today().strftime('%d.%m.%Y')})"
        iaca_line = f"IACA: 875.00 ↑ (+2.00%, Stand {date.today().strftime('%d.%m.%Y')})"

        briefing_lines = [
            "### Frachtraten Indizies",
            scfi_line,
            wci_line,
            iaca_line
        ]
        briefing = "\n".join(briefing_lines)
        print(f"Briefing erstellt:\n{briefing}")
        return briefing
    except Exception as e:
        print(f"❌ Fehler beim Erstellen des Briefings: {str(e)}")
        raise

def send_briefing():
    try:
        briefing = generate_briefing()
        config = os.getenv("CONFIG")
        if not config:
            raise Exception("CONFIG-Umgebungsvariable fehlt")

        pairs = config.split(";")
        config_dict = dict(pair.split("=", 1) for pair in pairs)
        msg = MIMEText(briefing, "plain", "utf-8")
        msg["Subject"] = "📰 Dein tägliches China-Briefing (SCFI Test)"
        msg["From"] = config_dict["EMAIL_USER"]
        msg["To"] = config_dict["EMAIL_TO"]

        with smtplib.SMTP(config_dict["EMAIL_HOST"], int(config_dict["EMAIL_PORT"])) as server:
            server.starttls()
            server.login(config_dict["EMAIL_USER"], config_dict["EMAIL_PASSWORD"])
            server.send_message(msg)
        print("Briefing-E-Mail erfolgreich gesendet")
    except Exception as e:
        print(f"❌ Fehler beim Senden der E-Mail: {str(e)}")
        raise

def main():
    print("Skript wird ausgeführt")
    try:
        briefing = generate_briefing()
        with open("scfi_test.txt", "w") as f:
            f.write(briefing)
        print("Briefing in scfi_test.txt geschrieben")
        
        cache_file = "scfi_cache.json"
        if os.path.exists(cache_file):
            with open(cache_file, "r") as f:
                print(f"Cache-Inhalt nach Ausführung: {json.load(f)}")
        else:
            print("Cache-Datei existiert nicht")
        
        send_briefing()
    except Exception as e:
        print(f"❌ Fehler im Skript: {str(e)}")
        raise

if __name__ == "__main__":
    main()
