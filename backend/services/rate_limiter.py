"""
Rate Limit Manager
Manages API rate limits across multiple free-tier data sources
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Callable, Any

class RateLimitManager:
    """
    Manages rate limits for free-tier APIs
    Demonstrates production-grade API management for resume
    """
    
    def __init__(self):
        """Initialize rate limiters for each API source"""
        self.limits = {
            'finnhub': {
                'calls': deque(maxlen=60),
                'limit': 60,
                'window': 60  # 60 calls per minute
            },
            'alpha_vantage': {
                'calls': deque(maxlen=25),
                'limit': 25,
                'window': 86400  # 25 calls per day
            },
            'marketaux': {
                'calls': deque(maxlen=100),
                'limit': 100,
                'window': 86400  # 100 calls per day
            },
            'yfinance': {
                'calls': deque(maxlen=2000),
                'limit': 2000,
                'window': 3600  # 2000 calls per hour (soft limit)
            }
        }
    
    async def acquire(self, source: str) -> bool:
        """
        Acquire permission to make API call
        Waits if rate limit is reached
        """
        if source not in self.limits:
            return True  # Unknown source, allow
        
        limit_info = self.limits[source]
        
        while True:
            now = datetime.now()
            
            # Remove old calls outside the window
            while limit_info['calls'] and \
                  (now - limit_info['calls'][0]) > timedelta(seconds=limit_info['window']):
                limit_info['calls'].popleft()
            
            # Check if under limit
            if len(limit_info['calls']) < limit_info['limit']:
                limit_info['calls'].append(now)
                return True
            
            # Wait before retry
            wait_time = (limit_info['calls'][0] + timedelta(seconds=limit_info['window']) - now).total_seconds()
            print(f"Rate limit reached for {source}, waiting {wait_time:.1f}s")
            await asyncio.sleep(max(1, wait_time))
    
    async def call_with_limit(self, source: str, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with automatic rate limiting
        """
        await self.acquire(source)
        return await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
    
    def get_remaining(self, source: str) -> dict:
        """
        Get remaining API calls for a source
        """
        if source not in self.limits:
            return {'remaining': 'unlimited', 'limit': 'unlimited'}
        
        limit_info = self.limits[source]
        now = datetime.now()
        
        # Remove old calls
        while limit_info['calls'] and \
              (now - limit_info['calls'][0]) > timedelta(seconds=limit_info['window']):
            limit_info['calls'].popleft()
        
        remaining = limit_info['limit'] - len(limit_info['calls'])
        
        return {
            'remaining': remaining,
            'limit': limit_info['limit'],
            'window_seconds': limit_info['window'],
            'used': len(limit_info['calls'])
        }
    
    def get_all_status(self) -> dict:
        """
        Get status of all API rate limits
        """
        status = {}
        for source in self.limits.keys():
            status[source] = self.get_remaining(source)
        return status
