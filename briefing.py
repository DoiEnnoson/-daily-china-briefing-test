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
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    scfi_cache = load_scfi_cache()

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
        last_date = scfi_data.get("lastDate")
        line_data_list = scfi_data.get("lineDataList", [])

        if not line_data_list:
            print("❌ ERROR - fetch_scfi: No lineDataList found in API response")
            raise Exception("No lineDataList in API response")

        scfi_value = float(line_data
