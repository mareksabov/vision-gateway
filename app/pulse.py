# app/pulse.py

import requests

url = "http://192.168.30.150:8080/pulse"

class Pulse:
    def __init__(self):
        pass

    def get_pulse_count(selft) -> int:
        response = requests.get(url)

        # Check status code
        if response.status_code == 200:
            # Convert response to JSON if possible
            data = response.json()
            if isinstance(data, dict) and "counter" in data:
                return data["counter"]

        else:
            print(f"Error: {response.status_code}")

        return 0