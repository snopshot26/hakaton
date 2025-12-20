"""
Configuration settings for DatsJingleBang bot
"""
import os

# API Configuration
API_URL = os.getenv("API_URL", "https://games-test.datsteam.dev")
API_TOKEN = os.getenv("API_TOKEN", "02f42812-62c4-49d3-a1ff-19c6bdf1e683")

# Timing Configuration
TICK_DELAY = float(os.getenv("TICK_DELAY", "0.5"))  # seconds between ticks
TABLE_LOG_INTERVAL = int(os.getenv("TABLE_LOG_INTERVAL", "10"))  # ticks between table logs
BOOSTER_COOLDOWN = int(os.getenv("BOOSTER_COOLDOWN", "30"))  # seconds between booster attempts

# Gameplay Configuration
MAX_PATH_LENGTH = int(os.getenv("MAX_PATH_LENGTH", "10"))  # maximum path length for movement
FARM_COOLDOWN_TICKS = int(os.getenv("FARM_COOLDOWN_TICKS", "30"))  # ticks before re-farming same tile
MIN_BOMBER_SPACING = int(os.getenv("MIN_BOMBER_SPACING", "3"))  # minimum distance between friendly bombers
MIN_ACTION_INTERVAL = int(os.getenv("MIN_ACTION_INTERVAL", "2"))  # minimum ticks between bomber actions

