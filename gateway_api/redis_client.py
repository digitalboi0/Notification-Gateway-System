
import logging
from django.conf import settings
from redis.asyncio import Redis

logger = logging.getLogger(__name__)


REDIS_URL = settings.REDIS_URL

if REDIS_URL:
    
    async def get_redis_client():
        """Get async Redis client"""
        return await Redis.from_url(
            REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            max_connections=50
        )


    import redis
    _redis_pool = redis.ConnectionPool.from_url(
        REDIS_URL,
        max_connections=50,
        retry_on_timeout=True,
        socket_keepalive=True,
        decode_responses=True
    )
    
    def get_redis():
        return redis.Redis(connection_pool=_redis_pool)
        
else:
    
    class MockAsyncRedis:
        def __init__(self):
            self.data = {}
        
        async def get(self, key):
            return self.data.get(key)
        
        async def setex(self, key, expiry, value):
            self.data[key] = value
            return True
        
        async def set(self, key, value, ex=None):
            self.data[key] = value
            if ex:
                
                pass
            return True
        
        async def incr(self, key):
            self.data[key] = self.data.get(key, 0) + 1
            return self.data[key]
        
        async def expire(self, key, seconds):
            return True
            
        async def decr(self, key):
            self.data[key] = self.data.get(key, 0) - 1
            return self.data[key]
        
        async def exists(self, key):
            return key in self.data
            
        async def delete(self, key):
            if key in self.data:
                del self.data[key]
                return 1
            return 0
            
        async def close(self):
            self.data.clear()
    
    
    _mock_redis = MockAsyncRedis()
    
    async def get_redis_client():
        """Get async mock Redis client"""
        return _mock_redis