"""AptJeeves 2.0 Application."""

import logging
from .config import get_langfuse_client

_root_logger = logging.getLogger("aptjeeves")
if not _root_logger.handlers: 
    _fh = logging.FileHandler("aptjeeves_debug.log") 
    _fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")) 
    _root_logger.addHandler(_fh) 
    _root_logger.setLevel(logging.DEBUG)

# Initialize Langfuse for tracing across all entrypoints (CLI, API).
# This must happen before any other modules are imported that might use it.
get_langfuse_client()