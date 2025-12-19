"""
Main entry point for DatsJingleBang bot
"""
import sys
from core.api import APIClient
from core.logger import SystemLogger
from core.tick import TickLoop
import config

logger = SystemLogger()


def main():
    """Main function"""
    print("Running in HEADLESS DEBUG MODE")
    
    # Validate configuration
    if not config.API_TOKEN:
        logger.error("API_TOKEN not set. Please set it as an environment variable.")
        sys.exit(1)
    
    if not config.API_URL:
        logger.error("API_URL not set. Please set it as an environment variable.")
        sys.exit(1)
    
    logger.info(f"Initializing bot with API URL: {config.API_URL}")
    logger.info(f"Tick delay: {config.TICK_DELAY}s")
    logger.info(f"Table log interval: {config.TABLE_LOG_INTERVAL} ticks")
    logger.info(f"Max path length: {config.MAX_PATH_LENGTH}")
    
    # Initialize API client
    api_client = APIClient(config.API_URL, config.API_TOKEN)
    
    # Initialize tick loop
    tick_loop = TickLoop(api_client)
    
    # Run forever
    tick_loop.run()


if __name__ == "__main__":
    main()

