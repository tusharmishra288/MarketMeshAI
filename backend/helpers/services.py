"""
services.py — Shared service singletons (cache manager, rate limiter, validator).
Imported by both orchestrator.py and route modules.
"""

import os
import sys

# Ensure backend/ is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.cache_manager import IntelligentCacheManager
from services.rate_limiter  import RateLimitManager
from services.validator     import MultiSourceValidator

cache_manager = IntelligentCacheManager(redis_host=os.getenv("REDIS_HOST", "localhost"))
rate_limiter  = RateLimitManager()
validator     = MultiSourceValidator()
