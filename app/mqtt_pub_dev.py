class Mqtt:
    def __init__(self):
        print("mqtt_pub.__init__()")

    def _connect(self):
        print("mqtt_pub._connect()")

    def _on_disc(self, client, userdata, rc):
        print("mqtt._on_disc()")

    def pub(self, base_topic: str, key: str, value: str, retain: bool = False):
        # Použi f-string, nech sa bool správne prevedie na text
        print(f"TOPIC: {base_topic} KEY: {key} VALUE: {value} RETAIN: {retain}")

    def loop(self, timeout: float = 0.1):
        return
