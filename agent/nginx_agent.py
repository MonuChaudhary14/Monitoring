import os
import time
import re
import requests
from datetime import datetime

URL_BASE = "http://127.0.0.1:8099/api"
LOG_FILE = "/var/log/nginx/access.log"

# Regex for the custom combined_with_host format
LOG_PATTERN = re.compile(
    r'(?P<ip>[\d\.\:a-fA-F]+)\s+-\s+(?P<user>.*?)\s+\[(?P<time>.*?)\]\s+'
    r'"(?P<method>\S+)\s+(?P<endpoint>\S+)\s+(?P<protocol>\S+)"\s+'
    r'(?P<status>\d+)\s+(?P<bytes>\d+)\s+"(?P<referer>.*?)"\s+'
    r'"(?P<agent>.*?)"\s+"(?P<host>.*?)"'
)

def get_api_key():
    while not os.path.exists("api_key.txt"):
        print("Waiting for api_key.txt (start agent.py first to register)...")
        time.sleep(5)
    with open("api_key.txt", "r") as f:
        return f.read().strip()

def parse_nginx_time(time_str):
    # Example: 04/Jun/2026:20:20:20 +0000
    try:
        dt = datetime.strptime(time_str, "%d/%b/%Y:%H:%M:%S %z")
        return dt.isoformat()
    except Exception:
        return None

def follow(file):
    file.seek(0, 2)
    while True:
        line = file.readline()
        if not line:
            time.sleep(0.5)
            continue
        yield line

def run_nginx_agent():
    api_key = get_api_key()
    
    if not os.path.exists(LOG_FILE):
        print(f"Waiting for {LOG_FILE} to be created...")
        while not os.path.exists(LOG_FILE):
            time.sleep(5)
            
    print(f"Tailing {LOG_FILE}...")
    
    batch = []
    last_send_time = time.time()
    
    with open(LOG_FILE, "r") as f:
        for line in follow(f):
            match = LOG_PATTERN.match(line)
            if match:
                data = match.groupdict()
                
                log_entry = {
                    "endpoint": data["endpoint"],
                    "method": data["method"],
                    "status_code": int(data["status"]),
                    "source": data["host"],
                    "ip_address": data["ip"],
                    "requested_at": parse_nginx_time(data["time"])
                }
                batch.append(log_entry)
            
            # Send batch every 5 seconds or if it gets too large
            if len(batch) >= 100 or (time.time() - last_send_time > 5 and len(batch) > 0):
                try:
                    response = requests.post(
                        f"{URL_BASE}/ingest-logs/",
                        json={"logs": batch},
                        headers={
                            "Content-Type": "application/json",
                            "X-API-KEY": api_key
                        }
                    )
                    print(f"Sent {len(batch)} logs | Response: {response.status_code}")
                except Exception as e:
                    print(f"Error sending logs: {e}")
                
                batch = []
                last_send_time = time.time()

if __name__ == "__main__":
    run_nginx_agent()
