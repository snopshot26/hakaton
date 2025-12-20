"""
Entry point for DatsJingleBang bot
"""
import os
import sys
import time
import logging
from src.client import APIClient
from src.bot import Bot

# Configure logging (suppress debug by default) and write to file per run
LOG_FORMAT = '%(asctime)s [%(levelname)s] %(message)s'
LOG_DATEFMT = '%H:%M:%S'

log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, f"bot_{int(time.time())}.log")

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt=LOG_DATEFMT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file, encoding="utf-8")
    ]
)
# Silence noisy libs
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("src.planner").setLevel(logging.INFO)

logger = logging.getLogger(__name__)


def main():
    """Main entry point"""
    # Get configuration from environment
    base_url = os.getenv("BASE_URL", "https://games-test.datsteam.dev")
    api_key = os.getenv("API_KEY", os.getenv("API_TOKEN", "02f42812-62c4-49d3-a1ff-19c6bdf1e683"))
    use_bearer = os.getenv("USE_BEARER", "false").lower() == "true"
    
    if not api_key:
        logger.error("API_KEY or API_TOKEN environment variable not set")
        sys.exit(1)
    
    logger.info(f"Starting bot with BASE_URL={base_url}")
    logger.info(f"Using {'Authorization: Bearer' if use_bearer else 'X-Auth-Token'} header")
    logger.info("Running in production mode")
    
    # Initialize client and bot
    client = APIClient(base_url, api_key, use_bearer=use_bearer)
    bot = Bot(client)
    
    # Run bot
    bot.run()


if __name__ == "__main__":
    main()
