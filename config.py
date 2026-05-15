import os

class CF:
    BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
    API_ID     = int(os.environ.get("API_ID", "0"))
    API_HASH   = os.environ.get("API_HASH", "")

    # Read OWNER_IDS and LOGS from environment if possible, otherwise fallback
    try:
        OWNER_IDS = [int(x) for x in os.environ.get("OWNER_IDS", "6209797666").split(",") if x.strip()]
    except Exception:
        OWNER_IDS = [6209797666]

    try:
        LOGS = int(os.environ.get("LOGS", "-1003849706641"))
    except Exception:
        LOGS = -1003849706641

    DB_PATH    = os.environ.get("DB_PATH",    "bw_bot.db")

    JOIN_PATTERN = [(5, 30*60)]  # (joins, wait_seconds) repeating — 30 min fixed gap
    JOIN_DELAY   = (8, 18)
    MSG_DELAY    = (3, 8)
    FLOOD_EXTRA  = (60, 120)

    @classmethod
    def is_owner(cls, uid: int) -> bool:
        return uid in cls.OWNER_IDS
