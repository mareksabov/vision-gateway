import json, os, threading, tempfile, shutil

class State:
    """
    Jednoduchá perzistentná key-value „state“ s JSON súborom.
    Použitie:
        st = State("/app/state/state.json")
        x  = st.get("electricity_main.t1", 0)
        st["electricity_main.t1"] = 12345
    """
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        # inicializácia prázdneho JSON, ak neexistuje
        if not os.path.exists(self.path):
            self._atomic_write({})

    def _atomic_write(self, obj: dict):
        d = os.path.dirname(self.path)
        fd, tmp = tempfile.mkstemp(prefix=".state.", dir=d)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(obj, f)
            shutil.move(tmp, self.path)
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _read(self) -> dict:
        with open(self.path, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}

    def _write(self, data: dict):
        self._atomic_write(data)

    # --- verejné API ---
    def get(self, key: str, default=None):
        with self._lock:
            data = self._read()
            return data.get(key, default)

    def __getitem__(self, key: str):
        with self._lock:
            data = self._read()
            return data[key]

    def __setitem__(self, key: str, value):
        with self._lock:
            data = self._read()
            data[key] = value
            self._write(data)

    def update(self, **kwargs):
        with self._lock:
            data = self._read()
            data.update(kwargs)
            self._write(data)
