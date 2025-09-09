import json, os, threading

_lock = threading.Lock()
STATE_DIR = os.path.join(os.getcwd(), "state")
os.makedirs(STATE_DIR, exist_ok=True)

def _path(sensor_id): return os.path.join(STATE_DIR, f"{sensor_id}.json")

def load(sensor_id, default_t1=0, default_t2=0):
    with _lock:
        p = _path(sensor_id)
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    return json.load(f)
            except:
                pass
        # init
        st = {"t1": int(default_t1), "t2": int(default_t2), "last_good": None}
        save(sensor_id, st)
        return st

def save(sensor_id, st):
    with _lock:
        with open(_path(sensor_id), "w") as f:
            json.dump(st, f)
