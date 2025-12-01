# src/utils/logger.py

import logging
import os
from config import get_config

def setup_logger(name):
    """Set up logger with console and optional file output for Lambda."""

    config = get_config()
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # Prevent duplicate handlers in AWS Lambda's repeated invocations
    if logger.hasHandlers():
        return logger

    # Console handler (CloudWatch)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    logger.addHandler(console_handler)

    # File handler for Lambda (use /tmp/logs)
    try:
        log_dir = "/tmp/logs"  # Only writable location in Lambda
        os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(f"{log_dir}/app.log")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        logger.addHandler(file_handler)
    except OSError as e:
        logger.warning(f"Could not create log file: {e}")

    return logger