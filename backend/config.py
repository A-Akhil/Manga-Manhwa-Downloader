from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.yaml"

_defaults = {
    "download": {
        "max_concurrent_downloads": 10,
        "timeout": 30,
        "retry_attempts": 3,
        "output_dir": "./downloads",
    },

    "source": {
        "base_url": "https://ww2.mangafreak.me"
    },

    "server": {
        "host": "0.0.0.0",
        "port": 8000
    }
}


def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            user = yaml.safe_load(f) or {}
        return {**_defaults, **user}
    return _defaults


config = load_config()