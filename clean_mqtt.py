#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import ssl
import sys
import time
from typing import Set

import paho.mqtt.client as mqtt
from paho.mqtt.client import MQTTMessage


DEFAULT_PREFIX = "ha/electricity/#"


def parse_args():
    p = argparse.ArgumentParser(
        description=(
            "Vyhľadá všetky RETAINED správy pod daným topic prefixom a vymaže ich "
            "(publish s retain=True a prázdnym payloadom)."
        )
    )
    p.add_argument("--host", required=True, help="MQTT broker host / IP")
    p.add_argument("--port", type=int, default=1883, help="MQTT broker port (1883/8883)")
    p.add_argument("--username", help="MQTT používateľ")
    p.add_argument("--password", help="MQTT heslo")
    p.add_argument("--tls", action="store_true", help="Použiť TLS (typicky port 8883)")
    p.add_argument("--insecure", action="store_true", help="TLS bez overenia certifikátu (iba na test!)")
    p.add_argument("--cafile", help="Cesta k CA certifikátu (ak treba)")
    p.add_argument("--certfile", help="Client cert (ak treba mTLS)")
    p.add_argument("--keyfile", help="Client key (ak treba mTLS)")
    p.add_argument("--prefix", default=DEFAULT_PREFIX, help="Topic prefix (napr. ha/electricity/#)")
    p.add_argument("--qos", type=int, default=1, choices=[0, 1, 2], help="QoS pre sub/pub")
    p.add_argument("--discover-seconds", type=float, default=2.0,
                   help="Ako dlho čakať na retained správy pri discovery (s)")
    p.add_argument("--dry-run", action="store_true", help="Nemaž – iba vypíš, čo by sa mazalo")
    p.add_argument("--verbose", "-v", action="store_true", help="Viac logov")
    return p.parse_args()


class RetainedCleaner:
    def __init__(self, args: argparse.Namespace):
        self.args = args

        # Paho 2.x – používame novú Callback API verziu, aby zmizlo varovanie
        self.client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)

        if args.username:
            self.client.username_pw_set(args.username, args.password or "")

        if args.tls:
            ctx = ssl.create_default_context(cafile=args.cafile) if args.cafile else ssl.create_default_context()
            if args.certfile and args.keyfile:
                ctx.load_cert_chain(certfile=args.certfile, keyfile=args.keyfile)
            if args.insecure:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
            self.client.tls_set_context(ctx)

        # Callbacky pre 2.x (MQTT v3.1.1/v5 kompatibilné signatúry)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

        self.retained_topics: Set[str] = set()
        self.connected = False
        self.connect_rc = None

    # -------- MQTT callbacks --------
    def on_connect(self, client, userdata, flags, reason_code, properties=None, *args, **kwargs):
        # reason_code môže byť int alebo objekt – skúsime int
        try:
            rc = int(reason_code)
        except Exception:
            rc = reason_code
        self.connect_rc = rc
        self.connected = (rc == 0)
        if self.args.verbose:
            msg = mqtt.error_string(rc) if isinstance(rc, int) else str(rc)
            print(f"[connect] rc={rc} ({msg})")

    def on_disconnect(self, client, userdata, reason_code=0, properties=None, *args, **kwargs):
        if self.args.verbose:
            try:
                rc = int(reason_code)
            except Exception:
                rc = reason_code
            print(f"[disconnect] rc={rc}")

    def on_message(self, client, userdata, msg: MQTTMessage):
        # Pri subscribe na prefix broker pošle RETAINED správy (msg.retain == True)
        if msg.retain:
            self.retained_topics.add(msg.topic)
            if self.args.verbose:
                print(f"[retained] {msg.topic} (payload {len(msg.payload)} B)")

    # -------- High-level flow --------
    def run(self):
        try:
            self.client.connect(self.args.host, self.args.port, keepalive=30)
        except Exception as e:
            print(f"Chyba pri connect: {e}", file=sys.stderr)
            sys.exit(2)

        self.client.loop_start()

        # Počkaj max 5s na spojenie
        t0 = time.time()
        while not self.connected and time.time() - t0 < 5.0:
            time.sleep(0.05)

        if not self.connected:
            print(f"Nepodarilo sa pripojiť k MQTT brokeru (rc={self.connect_rc}).", file=sys.stderr)
            self.client.disconnect()
            self.client.loop_stop()
            sys.exit(2)

        # 1) Discovery (subscribe na prefix, čakáme na retained)
        if self.args.verbose:
            print(f"[subscribe] {self.args.prefix} (QoS {self.args.qos})")

        res = self.client.subscribe(self.args.prefix, qos=self.args.qos)
        if isinstance(res, tuple):
            rc, mid = res
            if self.args.verbose:
                print(f"[subscribe] rc={rc}, mid={mid}")

        time.sleep(self.args.discover_seconds)

        self.client.unsubscribe(self.args.prefix)

        if self.retained_topics:
            print("Nájdené RETAINED topicy:")
            for t in sorted(self.retained_topics):
                print(f"  - {t}")
        else:
            print("Nenašli sa žiadne retained správy pod zadaným prefixom.")

        # 2) Mazanie
        if self.retained_topics and not self.args.dry_run:
            print("\nMazanie… (retain + prázdny payload)")
            for t in sorted(self.retained_topics):
                info = self.client.publish(t, payload=b"", qos=self.args.qos, retain=True)
                info.wait_for_publish()
                if self.args.verbose:
                    print(f"[deleted] {t} (rc={info.rc})")

            # Overenie – krátke opätovné discovery
            self.retained_topics.clear()
            self.client.subscribe(self.args.prefix, qos=self.args.qos)
            time.sleep(1.0)
            self.client.unsubscribe(self.args.prefix)

            if not self.retained_topics:
                print("\n✅ Hotovo: pod prefixom už nezostali žiadne retained správy.")
            else:
                print("\n⚠️ Niektoré retained správy sa stále objavujú (možno ich znovu publikuje nejaký zdroj):")
                for t in sorted(self.retained_topics):
                    print(f"  - {t}")
        elif self.args.dry_run and self.retained_topics:
            print("\n(dry-run) Nič som nezmazal. Spusti bez --dry-run, ak chceš zmazať.")

        # Upratanie (odpoj najprv, potom zastav loop)
        self.client.disconnect()
        self.client.loop_stop()


def main():
    args = parse_args()
    cleaner = RetainedCleaner(args)
    cleaner.run()


if __name__ == "__main__":
    main()
