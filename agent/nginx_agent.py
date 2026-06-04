import os
import time
import re
import requests
from datetime import datetime
import socket
import platform

URL_BASE = "http://127.0.0.1:8099/api"
LOG_FILE = "/var/log/nginx/access.log"

# Regex for the custom combined_with_host format
LOG_PATTERN = re.compile(
    r'(?P<ip>[\d\.\:a-fA-F]+)\s+-\s+(?P<user>.*?)\s+\[(?P<time>.*?)\]\s+'
    r'"(?P<method>\S+)\s+(?P<endpoint>\S+)\s+(?P<protocol>\S+)"\s+'
    r'(?P<status>\d+)\s+(?P<bytes>\d+)\s+"(?P<referer>.*?)"\s+'
    r'"(?P<agent>.*?)"\s+"(?P<host>.*?)"'
)

def register_server():
    try:
        name = platform.node() or "Nginx-Server"
        ip = "127.0.0.1"
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except:
            pass

        response = requests.post(f"{URL_BASE}/register/", json={
            "name": f"{name} (Nginx Agent)",
            "ip_address": ip
        })
        if response.status_code == 200:
            api_key = response.json().get("api_key")
            with open("api_key.txt", "w") as f:
                f.write(api_key)
            print(f"Registered new server. API Key: {api_key}")
            return api_key
        else:
            print("Failed to register server:", response.text)
            exit(1)
    except Exception as e:
        print("Registration error:", e)
        exit(1)

def get_api_key():
    if os.path.exists("api_key.txt"):
        with open("api_key.txt", "r") as f:
            return f.read().strip()
    print("API key not found, registering this agent with the backend...")
    return register_server()

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
