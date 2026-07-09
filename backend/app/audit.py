import logging
import os

# Set up a dedicated audit logger that writes to a file
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "audit.log")

audit_logger = logging.getLogger("audit")
audit_logger.setLevel(logging.INFO)

# Avoid adding duplicate handlers on reload
if not audit_logger.handlers:
    handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s | %(message)s")
    handler.setFormatter(formatter)
    audit_logger.addHandler(handler)


def log_event(event: str, user_email: str = "system", details: str = ""):
    """Write a structured audit event to the log file."""
    message = f"{event} | user={user_email} | {details}"
    audit_logger.info(message)