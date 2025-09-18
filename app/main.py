# app/main.py
import os, time, logging
from app.utils import fetch_bgr, crop
from app.ocr_paddle import ocr_digits
from app.state import State
# from app.mqtt_pub import Mqtt
from app.mqtt_pub_dev import Mqtt
from app.config import load_config
from app.pulse import Pulse

DEBUG    = os.getenv("APP_DEBUG", "0") == "1"
CFG_PATH = "/app/config/sensors.yaml"

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
LOG = logging.getLogger("reader")

last_published = 0
last_get_pulse = 0
last_pulse_value = -1


def digits_to_int(d: str) -> int:
    d = (d or "").lstrip("0")
    return int(d) if d else 0

def nearest_bucket(val: int, t1: int, t2: int) -> str:
    return "t1" if abs(val - t1) <= abs(val - t2) else "t2"

def poll_from(cfg) -> float:
    """
    Env POLL_INTERVAL_S má prednosť. Ak nie je, berie sa z configu
    global.poll_interval_s. Fallback 5.
    """
    g = cfg.get("global", {})
    cfg_poll = g.get("poll_interval_s", 5)
    return float(os.getenv("POLL_INTERVAL_S", str(cfg_poll)))

def process_ocr(mqtt: "Mqtt", cfg: dict, st: "State"):
    """
    OCR-only spracovanie. NEPOSIELA MQTT.
    - ukladá celé kWh do st[*.t1], st[*.t2], st[*.total]
    - aplikuje "brzdu" (max_step) a zabraňuje regresii
    - pripravuje metadáta pre budúce pulzy (bucket, posledné OCR)
    """
    g = cfg.get("global", {})
    conf_min = float(g.get("conf_threshold", 0.60))
    upscale  = int(g.get("roi_upscale", 2))
    max_step = int(g.get("max_step_kwh", 50))  # limit skoku (kWh)

    for s in cfg["sensors"]:
        sid  = s["id"]
        base = s["mqtt_topic_base"]   # zostáva kvôli logike inde; tu sa neposiela
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

            # ulož surové OCR metadáta (užitočné na diagnostiku / UI)
            st[f"{sid}.ocr_raw"]  = digits or ""
            st[f"{sid}.ocr_conf"] = float(f"{conf:.2f}")

            if not digits or conf < conf_min:
                LOG.info("[%s] conf %.2f < %.2f → skip update", sid, conf, conf_min)
                # necháme predchádzajúce hodnoty bez zmeny
                continue

            v = digits_to_int(digits)

            # načítaj stav so správnymi defaultmi
            last_t1 = int(st.get(f"{sid}.t1", int(s.get("initial_t1", 0))))
            last_t2 = int(st.get(f"{sid}.t2", int(s.get("initial_t2", 0))))
            LOG.debug("[%s] state before: t1=%s t2=%s", sid, last_t1, last_t2)

            bucket = nearest_bucket(v, last_t1, last_t2)  # "t1" alebo "t2"
            st[f"{sid}.last_bucket"] = bucket  # pomôcka do budúcna (pulzy)

            def accept_update(last_val: int, new_val: int) -> bool:
                # zakáž regresiu
                if new_val < last_val:
                    LOG.warning("[%s] %s regression %s→%s → ignore", sid, bucket, last_val, new_val)
                    return False
                # anti-skok brzda
                if (new_val - last_val) > max_step:
                    LOG.warning("[%s] %s jump %s→%s > %s kWh → ignore",
                                sid, bucket, last_val, new_val, max_step)
                    return False
                return True

            updated = False
            if bucket == "t1":
                if accept_update(last_t1, v):
                    st[f"{sid}.t1_ocr"] = v
                    last_t1 = v
                    updated = True
                    LOG.info("[%s] -> t1_ocr := %s", sid, v)
                    last_ocr_value = -1 # reset pulses
            else:
                if accept_update(last_t2, v):
                    st[f"{sid}.t2_ocr"] = v
                    last_t2 = v
                    updated = True
                    LOG.info("[%s] -> t2_ocr := %s", sid, v)
                    last_ocr_value = -1 # reset pulses

            # # prepočítaj total vždy z internej pravdy (publish sa rieši vo flush-i)
            # total = last_t1 + last_t2
            # st[f"{sid}.total"] = total
            # LOG.debug("[%s] state after:  t1=%s t2=%s total=%s", sid, last_t1, last_t2, total)

            # # diagnostické značky pre ďalšie kroky (pulzy budú vedieť, že pribudla kotva)
            # if updated:
            #     st[f"{sid}.last_ocr_value"] = v
            #     st[f"{sid}.last_ocr_bucket"] = bucket

        except Exception as e:
            LOG.warning("[%s] iteration error: %s: %s", sid, e.__class__.__name__, e)


def process_pulse(mqtt: "Mqtt", cfg: dict, st: "State", pulse: Pulse):
    """
    Zatiaľ no-op (žiadna nová funkcionalita). V ďalšom kroku sem doplníme čítanie /pulse
    a interpoláciu t1_live/t2_live tak, aby to nezasahovalo do existujúcich tém.
    """

    global last_get_pulse
    global last_pulse_value

    weight_of_pulse = 1/1000
    is_t1 = True

    if(time.time() - last_get_pulse > 5):
        count = pulse.get_pulse_count()
        if(last_pulse_value == -1):
            last_pulse_value = count
            return
        
        delta = count - last_pulse_value

        for s in cfg["sensors"]:
            sid   = s["id"]

            if(is_t1):
                t1 = float(_st_get(st, f"{sid}.t1", 0))
                t1 += delta * weight_of_pulse
                st[f"{sid}.t1"] = t1
                print(f"New t1: {t1}")
            else:
                t2 = float(_st_get(st, f"{sid}.t2", 0))
                t2 += delta * weight_of_pulse
                st[f"{sid}.t2"] = t2


        last_pulse_value = count
        last_get_pulse = time.time()
    else:
        pass

def process_all(mqtt: Mqtt, cfg, st: State, pulse: Pulse):
    """
    Backward-compatible wrapper: najprv OCR, potom (neskôr) pulzy.
    Ponechávame názov, aby nič inde neprasklo.
    """
    process_ocr(mqtt, cfg, st)
    process_pulse(mqtt, cfg, st, pulse)    

    process_data(cfg, st)

    flush_mqtt(mqtt, cfg, st)

# Helper: bezpečné načítanie s defaultom
def _st_get(st, key, default):
    return st.get(key, default)

def process_data(cfg: dict, st: "State"):
    for s in cfg["sensors"]:
        sid   = s["id"]
        t1_ocr = int(_st_get(st, f"{sid}.t1_ocr", 0))
        t2_ocr = int(_st_get(st, f"{sid}.t2_ocr", 0))
        t1 = float(_st_get(st, f"{sid}.t1", 0))
        t2 = float(_st_get(st, f"{sid}.t2", 0))

        def fix_with_ocr(ocr: int, t: float) -> float:
            return t if int(t) >= ocr else float(ocr)
            if(int(t) >= ocr):
                return t
            else:
                print(f"Fixing with ocr: {ocr} => t: {t}")
                return float(ocr)

        t1 = fix_with_ocr(t1_ocr, t1)
        t2 = fix_with_ocr(t2_ocr, t2)

        st[f"{sid}.t1"] = t1
        st[f"{sid}.t2"] = t2

# Publikačný flush: posiela len ak T1/T2 narástli
def flush_mqtt(mqtt: "Mqtt", cfg: dict, st: "State"):
    """
    Číta vypočítané hodnoty (st[*.t1], st[*.t2]) a porovná ich s publikovanými
    (st[*.t1_pub], st[*.t2_pub]). Pošle len nárasty. Total pošle iba ak sa
    publikovalo T1 alebo T2. Témy a retain ostávajú ako doteraz.
    """

    global last_published

    for s in cfg["sensors"]:
        sid   = s["id"]
        base  = s["mqtt_topic_base"]

        # aktuálne vypočítané celé kWh (OCR drží pravdu / pulzy nič nemenia celé kWh)
        t1_cur = float(_st_get(st, f"{sid}.t1", int(s.get("initial_t1", 0))))
        t2_cur = float(_st_get(st, f"{sid}.t2", int(s.get("initial_t2", 0))))

        # už publikované hodnoty (monotónne)
        t1_pub = float(_st_get(st, f"{sid}.t1_pub", 0))
        t2_pub = float(_st_get(st, f"{sid}.t2_pub", 0))

        t1_cur = round(t1_cur, 4)
        t2_cur = round(t2_cur, 4)

        published_any = False

        # T1: publikuj len ak narástlo
        if t1_cur > t1_pub:
            mqtt.pub(base, "t1", str(t1_cur), retain=True)
            st[f"{sid}.t1_pub"] = t1_cur
            published_any = True
        # T2: publikuj len ak narástlo
        if t2_cur > t2_pub:
            mqtt.pub(base, "t2", str(t2_cur), retain=True)
            st[f"{sid}.t2_pub"] = t2_cur
            published_any = True

        # Total: pošli iba ak sa publikovalo T1 alebo T2 v tomto cykle
        if published_any:
            total_cur = t1_cur + t2_cur
            total_cur = int(total_cur)
            mqtt.pub(base, "total", str(total_cur), retain=True)
            st[f"{sid}.total_pub"] = total_cur
            last_published = time.time()
        else:
            if time.time() - last_published > 5:
                total_cur = t1_cur + t2_cur
                mqtt.pub(base, "t1", str(t1_cur), retain=True)
                mqtt.pub(base, "t2", str(t2_cur), retain=True)
                mqtt.pub(base, "total", str(total_cur), retain=True)
                last_published = time.time()

        # (Voliteľné) diagnostika: ak OCR „stiahlo“ hodnotu pod publikovanú,
        # nepublikujeme späť – energia sa nemá znižovať. Môžeš si len lognúť:
        # if t1_cur < t1_pub or t2_cur < t2_pub: log.warn("OCR correction below published; keeping published monotonic.")

def main():
    cfg = load_config(CFG_PATH)
    cfg_mtime = os.path.getmtime(CFG_PATH)
    st   = State("/app/state/state.json")
    mqtt = Mqtt()
    pulse = Pulse()

    poll = poll_from(cfg)
    LOG.info("vision-reader started; poll=%.2fs", poll)

    while True:
        t0 = time.time()
        try:
            # --- HOT RELOAD ---
            try:
                m = os.path.getmtime(CFG_PATH)
                if m != cfg_mtime:
                    cfg = load_config(CFG_PATH)
                    cfg_mtime = m
                    poll = poll_from(cfg)  # prepočítaj po reloade
                    LOG.info("config reloaded; poll=%.2fs", poll)
            except FileNotFoundError:
                LOG.warning("config file missing: %s", CFG_PATH)
            # -------------------

            process_all(mqtt, cfg, st, pulse)
            mqtt.loop(0.1)
        except Exception as e:
            LOG.error("top-level iteration error: %s: %s", e.__class__.__name__, e)
        dt = time.time() - t0
        if DEBUG:
            LOG.debug("loop done in %.3fs", dt)
        time.sleep(max(0.0, poll - dt))

if __name__ == "__main__":
    main()
