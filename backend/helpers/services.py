"""
services.py — Shared service singletons (rate limiter, validator).

Cache layer: Redis has been removed. Caching is handled entirely by the
L1 in-memory dict in helpers/cache_helpers.py. The cache_manager import
is kept as a no-op stub so existing call-sites compile without change.

Persistence layer:
  - CLOUD (GCP): Firestore via google-cloud-firestore (ADC from VM service account)
  - LOCAL:        In-memory dict (data lost on process restart)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.cache_manager import IntelligentCacheManager
from services.rate_limiter  import RateLimitManager
from services.validator     import MultiSourceValidator

# No-op stub — Redis removed; L1 in-memory cache (cache_helpers) is the only tier
cache_manager = IntelligentCacheManager()
rate_limiter  = RateLimitManager()
validator     = MultiSourceValidator()
