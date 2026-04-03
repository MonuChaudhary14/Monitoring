import psutil
import requests
import time
import socket
import os

URL_BASE = "http://127.0.0.1:8000/api"

def register():
    hostname = socket.gethostname()
    ip = socket.gethostbyname(hostname)

    response = requests.post(
        f"{URL_BASE}/register/",
        json={
            "name": hostname,
            "ip_address": ip
        }
    )

    data = response.json()
    print("Register response:", data)
    return data["api_key"]


def get_api_key():
    if os.path.exists("api_key.txt"):
        with open("api_key.txt", "r") as f:
            print("Using existing API key")
            return f.read().strip()

    print("Registering new server...")
    api_key = register()

    with open("api_key.txt", "w") as f:
        f.write(api_key)

    return api_key

def run_agent():
    API_KEY = get_api_key()

    while True:
        data = {
            "cpu_percent": psutil.cpu_percent(),
            "memory_percent": psutil.virtual_memory().percent,
            "disk_percent": psutil.disk_usage('/').percent
        }

        try:
            response = requests.post(
                f"{URL_BASE}/ingest/",
                json=data,
                headers={
                    "Content-Type": "application/json",
                    "X-API-KEY": API_KEY
                }
            )

            print("Metric sent:", data, "| Response:", response.json())

        except Exception as e:
            print("Error:", e)

        time.sleep(5)

if __name__ == "__main__":
    run_agent()