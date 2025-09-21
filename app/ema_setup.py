# app/ema_setup.py
import requests
import time
from collections import deque

class EmaSetup:
    URL = "http://192.168.30.150:8080/config"

    # vzorkovanie
    TIMER = 0.9
    SAMPLE_TIMEOUT = 0.3

    # okno na výpočet prahov
    WINDOW_SECONDS = 180
    MIN_SAMPLES = 10
    MIN_CLUSTER_GAP = 1.0

    # riadenie prepočtu/postovania
    RECOMPUTE_INTERVAL = 180      # min. odstup medzi prepočtami (s)
    POST_MIN_INTERVAL = 15        # min. odstup medzi POST (s)

    # detekcia skoku
    JUMP_ABS = 8                  # absolútny prah skoku
    JUMP_PCT = 0.35               # relatívny prah skoku (35 %)
    EMA_ALPHA = 0.2               # hladkosť krátkodobej EMA na detekciu skokov

    is_running = False

    def __init__(self):
        self.window = deque()
        self.threshold_off = None
        self.threshold_on = None
        self.state = None  # "ON"/"OFF"/None

        # riadenie periodicity
        self.last_ema_time = 0
        self.last_threshold_update = 0
        self.last_post_time = 0

        # krátkodobá EMA na detekciu skoku
        self.short_ema = None

    def run(self):
        self.is_running = True

    def stop(self):
        self.is_running = False

    def _push_sample(self, value, now=None):
        now = now or time.time()
        self.window.append((now, value))
        cutoff = now - self.WINDOW_SECONDS
        while self.window and self.window[0][0] < cutoff:
            self.window.popleft()
        # krátkodobá EMA na detekciu skokov
        if self.short_ema is None:
            self.short_ema = float(value)
        else:
            self.short_ema = (1 - self.EMA_ALPHA) * self.short_ema + self.EMA_ALPHA * float(value)

    def _should_recompute(self, ema_R, now):
        """Rozhodne, či spustiť prepočet prahov teraz."""
        # 1) časový interval
        if (now - self.last_threshold_update) >= self.RECOMPUTE_INTERVAL:
            return True

        # 2) veľký skok proti krátkodobej EMA
        if self.short_ema is not None:
            diff = abs(float(ema_R) - self.short_ema)
            if diff >= self.JUMP_ABS:
                return True
            if self.short_ema > 0 and (diff / max(self.short_ema, 1e-6)) >= self.JUMP_PCT:
                return True

        return False

    def _post_thresholds_if_needed(self, now):
        """Pošli POST len ak prešlo dosť času od posledného POSTu."""
        if (now - self.last_post_time) < self.POST_MIN_INTERVAL:
            return
        payload = {"th_on": self.threshold_on, "th_off": self.threshold_off}
        try:
            r = requests.post(self.URL, json=payload, timeout=1.0)
            # voliteľný log:
            # print(f"[POST] {payload} -> {r.status_code}")
            self.last_post_time = now
        except requests.RequestException as e:
            print(f"[POST ERROR] {e}")

    def _compute_thresholds(self):
        if len(self.window) < self.MIN_SAMPLES:
            return False  # nič sa nezmenilo

        values = [v for _, v in self.window]
        vmin, vmax = min(values), max(values)
        if vmax - vmin < 1e-6:
            return False

        # 1D k-means (k=2)
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
            return False

        t = int((lo + hi) / 2)
        new_off, new_on = t, t + 1

        if new_off != self.threshold_off or new_on != self.threshold_on:
            self.threshold_off, self.threshold_on = new_off, new_on
            return True

        return False

    def _update_state(self, ema_R):
        if self.threshold_off is None or self.threshold_on is None:
            return
        if self.state in (None, "OFF"):
            if ema_R >= self.threshold_on:
                self.state = "ON"
        if self.state == "ON":
            if ema_R <= self.threshold_off:
                self.state = "OFF"

    def tick(self):
        # pevná perioda cez obyčajný čas – stačí, keď voláš tick často
        if (time.time() - self.last_ema_time) <= self.TIMER:
            return

        now = time.time()
        try:
            response = requests.get(self.URL, timeout=self.SAMPLE_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                ema_R = data.get("ema_R")
                if ema_R is None:
                    self.last_ema_time = now
                    return

                # 1) vzorka do okna + krátkodobá EMA
                self._push_sample(ema_R, now=now)

                # 2) rozhodni, či momentálne prepočítať prahy
                if self._should_recompute(ema_R, now):
                    changed = self._compute_thresholds()
                    if changed:
                        self.last_threshold_update = now
                        # 3) pošleme POST (s debounce)
                        self._post_thresholds_if_needed(now)

                # 4) voliteľne udržuj ON/OFF
                self._update_state(ema_R)

                # voliteľný log:
                # print(f"{time.strftime('%H:%M:%S')} ema_R={ema_R} thr_off={self.threshold_off} thr_on={self.threshold_on} state={self.state}")

        except requests.Timeout:
            print("HTTP timeout")
        except requests.RequestException as e:
            print(f"HTTP error: {e}")
        except ValueError as e:
            print(f"JSON error: {e}")
        finally:
            self.last_ema_time = now
