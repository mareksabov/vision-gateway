import os, time, yaml, logging, math
from paho.mqtt import client as mqtt
from app.utils import fetch_bgr, crop
from app.ocr_paddle import ocr_digits
from app import state as ST

LOG = logging.getLogger("reader")
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s"
)

CFG = yaml.safe_load(open("config/sensors.yaml", "r"))
POLL = int(CFG.get("global", {}).get("poll_interval_s", 10))
CONF_MIN = float(CFG.get("global", {}).get("conf_threshold", 0.60))
UPSCALE = int(CFG.get("global", {}).get("roi_upscale", 2))

def mqtt_client():
    cli = mqtt.Client()
    user = os.getenv("MQTT_USER")
    pwd  = os.getenv("MQTT_PASS")
    if user: cli.username_pw_set(user, pwd or "")
    cli.connect(os.getenv("MQTT_HOST", "127.0.0.1"),
                int(os.getenv("MQTT_PORT", "1883")), 60)
    return cli

def publish(cli, base, key, val):
    topic = f"{base}/{key}"
    cli.publish(topic, str(val), qos=0, retain=False)

def nearest_bucket(val, t1, t2):
    """Vyberie T1 alebo T2 podľa menšej absolútnej odchýlky."""
    d1 = abs(val - t1)
    d2 = abs(val - t2)
    return ("t1" if d1 <= d2 else "t2")

def digits_to_int(d):
    # odstrihni leading zeros
    d = d.lstrip("0")
    return int(d) if d else 0

def loop_one_sensor(s, cli):
    sid = s["id"]
    base = s["mqtt_topic_base"]
    img = fetch_bgr(s["snapshot_url"])
    roi = crop(img, s["roi_display"])

    digits, conf = ocr_digits(roi, upscale=UPSCALE)
    publish(cli, base, "ocr_raw", digits or "")
    publish(cli, base, "ocr_conf", f"{conf:.2f}")

    if not digits or conf < CONF_MIN:
        LOG.info("[%s] low conf (%.2f) or empty. skip.", sid, conf)
        return

    val = digits_to_int(digits)
    st = ST.load(sid, s.get("initial_t1",0), s.get("initial_t2",0))

    bucket = nearest_bucket(val, st["t1"], st["t2"])

    # monotónnosť – neprepisovať späť menším číslom
    if val >= st[bucket]:
        st[bucket] = val
        st["last_good"] = {"bucket": bucket, "val": val, "conf": conf, "ts": time.time()}
        ST.save(sid, st)
        publish(cli, base, f"{bucket}", st[bucket])
        publish(cli, base, "total", st["t1"] + st["t2"])
        LOG.info("[%s] %s <- %s (conf %.2f)", sid, bucket, val, conf)
    else:
        LOG.info("[%s] %s candidate %s < stored %s → ignored",
                 sid, bucket, val, st[bucket])

def main():
    cli = mqtt_client()
    while True:
        for s in CFG["sensors"]:
            try:
                loop_one_sensor(s, cli)
            except Exception as e:
                LOG.warning("[%s] error: %s", s.get("id"), e)
        cli.loop(timeout=0.1)
        time.sleep(POLL)

if __name__ == "__main__":
    main()
