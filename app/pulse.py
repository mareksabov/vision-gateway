# app/pulse.py

import requests

class Pulse:
    def __init__(self):
        pass

    def get_pulse_count(self, pulseUrl) -> int:
        response = requests.get(pulseUrl)

        # Check status code
        if response.status_code == 200:
            # Convert response to JSON if possible
            data = response.json()
            if isinstance(data, dict) and "counter" in data:
                return data["counter"]

        else:
            print(f"Error: {response.status_code}")

        return 0