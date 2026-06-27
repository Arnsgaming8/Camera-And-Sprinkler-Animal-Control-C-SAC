import os


blink_instance = None
active_blink = None
twofa_pending = False
twofa_pin = None
reauth_in_progress = False
last_poll = None
last_user_arm = {}


def get_config_path():
    override = os.environ.get("BABBS_CONFIG_DIR")
    if override:
        return os.path.join(override, "config.yml")
    return os.path.join(os.path.dirname(__file__), "config.yml")
