"""
Logging system for DatsJingleBang bot
"""
import logging
import sys


class SystemLogger:
    """System-level logger for technical messages"""
    
    def __init__(self):
        self.logger = logging.getLogger("system")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter(
                '%(asctime)s [SYSTEM] %(message)s',
                datefmt='%H:%M:%S'
            ))
            self.logger.addHandler(handler)
    
    def info(self, message):
        self.logger.info(message)
    
    def error(self, message):
        self.logger.error(message)
    
    def warning(self, message):
        self.logger.warning(message)


class GameLogger:
    """Game-level logger for gameplay messages with emojis"""
    
    def __init__(self):
        self.logger = logging.getLogger("game")
        self.logger.setLevel(logging.INFO)
        
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter(
                '%(asctime)s [GAME] %(message)s',
                datefmt='%H:%M:%S'
            ))
            self.logger.addHandler(handler)
    
    def info(self, message):
        self.logger.info(message)
    
    def bomb(self, message):
        """Log bomb-related actions"""
        self.logger.info(f"💣 {message}")
    
    def farming(self, message):
        """Log farming actions"""
        self.logger.info(f"🌾 {message}")
    
    def death(self, message):
        """Log death events"""
        self.logger.info(f"💀 {message}")
    
    def movement(self, message):
        """Log movement actions"""
        self.logger.info(f"➡️ {message}")
    
    def booster(self, message):
        """Log booster purchases"""
        self.logger.info(f"🛒 {message}")
    
    def danger(self, message):
        """Log danger warnings"""
        self.logger.info(f"⚠️ {message}")

