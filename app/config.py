# app/config.py
import yaml

def load_config(path: str):
    with open(path, "r") as f:
        cfg = yaml.safe_load(f)
    if "global" not in cfg:
        cfg["global"] = {}
    if "sensors" not in cfg or not isinstance(cfg["sensors"], list):
        cfg["sensors"] = []
    return cfg
