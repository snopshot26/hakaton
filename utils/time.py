"""
Time utility functions
"""
import time


def get_current_time():
    """Get current Unix timestamp in seconds"""
    return time.time()


def sleep(seconds):
    """Sleep for specified seconds"""
    time.sleep(seconds)

