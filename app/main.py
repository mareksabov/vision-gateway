# app/main.py
import os, time, logging
from app.utils import fetch_bgr, crop
from app.ocr_paddle import ocr_digits
from app.state import State
from app.mqtt_pub import Mqtt
from app.config import load_config

POLL  = float(os.getenv("POLL_INTERVAL_S", "5"))
DEBUG = os.getenv("APP_DEBUG", "0") == "1"

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
LOG = logging.getLogger("reader")


def digits_to_int(d: str) -> int:
    """Prevedie '0017588' -> 17588 (alebo 0, ak prázdne)."""
    d = (d or "").lstrip("0")
    return int(d) if d else 0


def nearest_bucket(val: int, t1: int, t2: int) -> str:
    """Vyberie, či je hodnota bližšie k T1 alebo T2."""
    return "t1" if abs(val - t1) <= abs(val - t2) else "t2"


def update_counter(st: State, key: str, new_val: int, init_val: int, max_step: int):
    """
    Monotónny čítač s limitom skoku.
    - neumožní pokles
    - neumožní jednorazový skok > max_step
    Vráti (stored_value, updated_bool, reason_str)
    """
    try:
        last = int(st.get(key, init_val))
    except Exception:
        last = init_val

    if new_val < last:
        return last, False, f"decrease {new_val}<{last}"
    step = new_val - last
    if step > max_step:
        return last, False, f"step {step}>{max_step}"
    st[key] = new_val
    return new_val, True, "ok"


def process_all(mqtt: Mqtt, cfg, st: State):
    g = cfg.get("global", {})
    conf_min   = float(g.get("conf_threshold", 0.60))
    upscale    = int(g.get("roi_upscale", 2))
    max_step   = int(g.get("max_step_kwh", 50))  # sanity limit na jednorazový skok

    for s in cfg["sensors"]:
        sid  = s["id"]
        base = s["mqtt_topic_base"]
        url  = s["snapshot_url"]

        try:
            LOG.debug("[%s] fetching %s", sid, url)
            img = fetch_bgr(url)

            if "roi_display" not in s:
                LOG.warning("[%s] missing roi_display", sid)
                continue

            x, y, w, h = map(int, s["roi_display"])
            roi = crop(img, (x, y, w, h))

            digits, conf = ocr_digits(roi, upscale=upscale)
            LOG.info("[%s] OCR digits='%s' conf=%.2f", sid, digits, conf)

            mqtt.pub(base, "ocr_raw", digits or "")
            mqtt.pub(base, "ocr_conf", f"{conf:.2f}")

            if not digits or conf < conf_min:
                LOG.info("[%s] conf %.2f < %.2f → skip update", sid, conf, conf_min)
                continue

            v = digits_to_int(digits)

            # načítaj stav so správnymi defaultmi
            init_t1 = int(s.get("initial_t1", 0))
            init_t2 = int(s.get("initial_t2", 0))
            last_t1 = int(st.get(f"{sid}.t1", init_t1))
            last_t2 = int(st.get(f"{sid}.t2", init_t2))
            LOG.debug("[%s] state before: t1=%s t2=%s", sid, last_t1, last_t2)

            bucket = nearest_bucket(v, last_t1, last_t2)

            if bucket == "t1":
                stored, updated, why = update_counter(
                    st, f"{sid}.t1", v, init_t1, max_step
                )
                if updated:
                    mqtt.pub(base, "t1", str(stored), retain=True)
                    last_t1 = stored
                    LOG.info("[%s] -> t1 := %s", sid, stored)
                else:
                    LOG.info("[%s] T1 ignore (%s)", sid, why)
            else:
                stored, updated, why = update_counter(
                    st, f"{sid}.t2", v, init_t2, max_step
                )
                if updated:
                    mqtt.pub(base, "t2", str(stored), retain=True)
                    last_t2 = stored
                    LOG.info("[%s] -> t2 := %s", sid, stored)
                else:
                    LOG.info("[%s] T2 ignore (%s)", sid, why)

            total = last_t1 + last_t2
            st[f"{sid}.total"] = total
            mqtt.pub(base, "total", str(total), retain=True)
            LOG.debug("[%s] state after:  t1=%s t2=%s total=%s", sid, last_t1, last_t2, total)

        except Exception as e:
            LOG.warning("[%s] iteration error: %s: %s", sid, e.__class__.__name__, e)


def main():
    cfg  = load_config("/app/config/sensors.yaml")
    st   = State("/app/state/state.json")
    mqtt = Mqtt()

    LOG.info("vision-reader started; poll=%.2fs", POLL)
    while True:
        t0 = time.time()
        try:
            process_all(mqtt, cfg, st)
            mqtt.loop(0.1)
        except Exception as e:
            LOG.error("top-level iteration error: %s: %s", e.__class__.__name__, e)
        dt = time.time() - t0
        if DEBUG:
            LOG.debug("loop done in %.3fs", dt)
        time.sleep(max(0.0, POLL - dt))


if __name__ == "__main__":
    main()
