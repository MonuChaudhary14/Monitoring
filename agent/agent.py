import psutil
import requests
import time

SERVER_ID = 1
BACKEND_URL = "http://127.0.0.1:8000/api/ingest/"

while True:
    data = {
        "server_id": SERVER_ID,
        "cpu_percent": psutil.cpu_percent(),
        "memory_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage('/').percent
    }

    try:
        requests.post(BACKEND_URL, json=data)
        print("Metric sent:", data)
    except Exception as e:
        print("Error:", e)

    time.sleep(5)