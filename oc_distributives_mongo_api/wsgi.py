import os
import logging
from time import sleep
from mongoengine import connect
from .app import create_app
from .config import Config

_settings = dict()

for _s in ["url", "user", "password", "name", "connect_attempts"]:
    _env = "_".join(["mongo", _s]).upper()
    _v = os.getenv(_env)

    if not _v:
        raise ValueError("Environment '%s' is not set" % _env)

    _settings[_s] = int(_v) if _s == "connect_attempts" else _v

_i = 0
while True:
    try:
        connect(
                _settings["name"],
                host=_settings["url"],
                username=_settings["user"],
                password=_settings["password"],
                authentication_source="admin")
        break
    except Exception as _err:
        if _i >= _settings["connect_attempts"]:
            raise

        logging.exception(_err)

        _i += 1
        sleep(_i)

app = create_app(Config)

# additional tricks for logging
if __name__ != "__main__":
    gunicorn_logger = logging.getLogger("gunicorn.error")
    logging.basicConfig(format='[%(asctime)s] [%(levelname)s] %(message)s', level=gunicorn_logger.level)
