import logging
import os


def setup_logger():
    """Sets up a logger that writes to both console and a log file."""
    # Get LOG_FILE from config, fall back gracefully if config isn't ready yet
    try:
        from config import LOG_FILE
    except (ImportError, AttributeError):
        LOG_FILE = "bot.log"

    os.makedirs("logs", exist_ok=True)

    logger = logging.getLogger("TelegramBot")
    logger.setLevel(logging.DEBUG)

    # Avoid adding duplicate handlers if setup_logger is called multiple times
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Console Handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    # File Handler
    file_handler = logging.FileHandler(f"logs/{LOG_FILE}", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    logger.addHandler(console_handler)
    logger.addHandler(file_handler)

    return logger


logger = setup_logger()
