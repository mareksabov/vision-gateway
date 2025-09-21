# app/ema_setup.py
import requests
import time
from collections import deque

class EmaSetup:
    URL = "http://192.168.30.150:8080/config"
    # zmena konštánt:
    TIMER = 0.5           # požadovaný interval odberu (s)
    SAMPLE_TIMEOUT = 0.3  # timeout HTTP < TIMER, inak sa perioda nafukuje
    WINDOW_SECONDS = 60
    MIN_SAMPLES = 10       # pri 1 Hz dá ~6 s dát na prvý výpočet
    MIN_CLUSTER_GAP = 1.0   # min. rozdiel centroidov, aby sme verili 2-klastrovej delbe

    is_running = False

    def __init__(self):
        # kĺzavé okno (timestamp, value)
        self.window = deque()
        # prahy s hysteréziou
        self.threshold_off = None
        self.threshold_on = None
        # posledný známy stav (len ak chceš vyhodnocovať ON/OFF)
        self.state = None  # "ON" / "OFF" / None

    def run(self):
        self.is_running = True
        self.process()

    def stop(self):
        self.is_running = False

    def _push_sample(self, value, now=None):
        now = now or time.time()
        self.window.append((now, value))
        # vyhodiť staré vzorky mimo okno
        cutoff = now - self.WINDOW_SECONDS
        while self.window and self.window[0][0] < cutoff:
            self.window.popleft()

    def _compute_thresholds(self):
        if len(self.window) < self.MIN_SAMPLES:
            return

        values = [v for _, v in self.window]
        vmin, vmax = min(values), max(values)
        if vmax - vmin < 1e-6:
            return

        # 1D k-means
        c0, c1 = float(vmin), float(vmax)
        for _ in range(10):
            g0, g1 = [], []
            mid = (c0 + c1) / 2.0
            for x in values:
                (g0 if x <= mid else g1).append(x)
            if not g0:
                g0 = [min(values)]
            if not g1:
                g1 = [max(values)]
            n0, n1 = sum(g0) / len(g0), sum(g1) / len(g1)
            if abs(n0 - c0) < 1e-6 and abs(n1 - c1) < 1e-6:
                break
            c0, c1 = n0, n1

        lo, hi = sorted([c0, c1])
        if (hi - lo) < self.MIN_CLUSTER_GAP:
            return

        t = int((lo + hi) / 2)
        new_off, new_on = t, t + 1

        # iba ak sa niečo zmenilo
        if new_off != self.threshold_off or new_on != self.threshold_on:
            self.threshold_off, self.threshold_on = new_off, new_on
            # print(f"[THR] OFF={self.threshold_off}, ON={self.threshold_on}")

            # pošleme POST s JSON
            payload = {"th_on": self.threshold_on, "th_off": self.threshold_off}
            try:
                r = requests.post(self.URL, json=payload, timeout=1.0)
                # print(f"[POST] {payload} -> {r.status_code}")
            except requests.RequestException as e:
                print(f"[POST ERROR] {e}")

    def _update_state(self, ema_R):
        """Voliteľne: vyhodnotí stav LED podľa hysterézie a drží stabilný stav."""
        if self.threshold_off is None or self.threshold_on is None:
            return  # prahy ešte nemáme

        if self.state in (None, "OFF"):
            # prechod do ON až po prekročení threshold_on
            if ema_R >= self.threshold_on:
                self.state = "ON"
        if self.state == "ON":
            # prechod do OFF až po poklese pod threshold_off
            if ema_R <= self.threshold_off:
                self.state = "OFF"

    def process(self):
        # pevný „metronóm“ cez monotonic time
        next_tick = time.monotonic()
        while self.is_running:
            now_mono = time.monotonic()
            # ak sme skôr, dospíme do presného času tiknutia
            if now_mono < next_tick:
                time.sleep(next_tick - now_mono)
            # nastav ďalší tick ešte pred I/O, aby drift nebol kumulatívny
            next_tick += self.TIMER

            try:
                # rýchly timeout, nech to nebrzdí periodu
                response = requests.get(self.URL, timeout=self.SAMPLE_TIMEOUT)
                if response.status_code == 200:
                    data = response.json()
                    ema_R = data.get("ema_R")
                    if ema_R is None:
                        continue

                    # 1) vzorka do okna
                    now_wall = time.time()
                    self._push_sample(ema_R, now=now_wall)

                    # 2) prah z okna (10 s)
                    self._compute_thresholds()

                    # 3) voliteľná hysterézia
                    self._update_state(ema_R)

                    # log s časom, nech vidíš presnú periodu
                    # print(
                    #     f"{time.strftime('%H:%M:%S')} ema_R={ema_R}  "
                    #     f"thr_off={self.threshold_off} thr_on={self.threshold_on}  state={self.state}"
                    # )

            except requests.Timeout:
                # tiché vynechanie – udržíme periodu
                print("HTTP timeout")
                continue
            except requests.RequestException as e:
                print(f"HTTP error: {e}")
            except ValueError as e:
                print(f"JSON error: {e}")
