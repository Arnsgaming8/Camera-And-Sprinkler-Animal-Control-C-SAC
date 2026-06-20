import os
import sys


def get_config_path():
    if getattr(sys, "frozen", False):
        d = os.path.join(os.path.expanduser("~"), ".babbs")
    else:
        d = os.path.dirname(os.path.abspath(__file__))
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "config.yml")


blink_instance = None
active_blink = None
twofa_pin = None
twofa_pending = False
reauth_in_progress = False
last_poll = None
