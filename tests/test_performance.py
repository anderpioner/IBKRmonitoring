import requests
import time
import json

API_URL = "http://127.0.0.1:8000/api/data"
ACCOUNT_ID = "DU7908819"  # Adjust as needed or fetch from /api/status

def test_performance():
    payload = {
        "accountId": ACCOUNT_ID,
        "maPeriod": 20
    }
    
    print(f"Testing performance for {API_URL}...")
    
    for i in range(5):
        start_time = time.time()
        try:
            response = requests.post(API_URL, json=payload, timeout=65)
            duration = time.time() - start_time
            
            if response.status_code == 200:
                data = response.json()
                encoding = response.headers.get("Content-Encoding", "None")
                print(f"Request {i+1}: Success - Time: {duration:.2f}s - Encoding: {encoding} - LastUpdate: {data.get('lastUpdate')}")
            else:
                print(f"Request {i+1}: Failed - Status: {response.status_code} - {response.text}")
        except Exception as e:
            print(f"Request {i+1}: Error - {e}")
        
        time.sleep(1)

if __name__ == "__main__":
    # Note: This script assumes the server is running.
    # In a real scenario, I would start the server in the background first.
    test_performance()
