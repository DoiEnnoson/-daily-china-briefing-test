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
                # Änderung: Datum im Format DD.MM.YYYY
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
