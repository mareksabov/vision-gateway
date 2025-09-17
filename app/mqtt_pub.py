# app/mqtt_pub.py
import os
import time
import logging
from paho.mqtt import client as mqtt

LOG = logging.getLogger("mqtt")

class Mqtt:
    def __init__(self):
        host = os.getenv("MQTT_HOST", "127.0.0.1")
        port = int(os.getenv("MQTT_PORT", "1883"))
        user = os.getenv("MQTT_USER", "")
        pwd  = os.getenv("MQTT_PASS", "")
        self._host, self._port = host, port

        self._cli = mqtt.Client()
        if user:
            self._cli.username_pw_set(user, pwd)

        # voliteľné callbacks pre debug
        self._cli.on_disconnect = self._on_disc

        self._connect()

    def _connect(self):
        while True:
            try:
                rc = self._cli.connect(self._host, self._port, 60)
                if rc == 0:
                    LOG.info("MQTT connected to %s:%s", self._host, self._port)
                    break
                else:
                    LOG.warning("MQTT connect rc=%s; retrying...", rc)
            except Exception as e:
                LOG.warning("MQTT connect error: %s; retrying in 3s", e)
            time.sleep(3)

    def _on_disc(self, client, userdata, rc):
        if rc != 0:
            LOG.warning("MQTT unexpected disconnect rc=%s, reconnecting...", rc)
            try:
                self._connect()
            except Exception as e:
                LOG.error("MQTT reconnect failed: %s", e)

    def pub(self, base_topic: str, key: str, value: str, retain: bool=False):
        topic = f"{base_topic}/{key}"
        try:
            self._cli.publish(topic, payload=str(value), qos=0, retain=retain)
        except Exception as e:
            LOG.warning("MQTT publish error (%s): %s → reconnect & retry", topic, e)
            self._connect()
            self._cli.publish(topic, payload=str(value), qos=0, retain=retain)

    def loop(self, timeout: float = 0.1):
        # volaj v hlavnej slučke, aby sa držalo spojenie
        try:
            self._cli.loop(timeout=timeout)
        except Exception:
            pass
