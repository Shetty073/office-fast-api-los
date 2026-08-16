from arq import create_pool
from arq.connections import RedisSettings, ArqRedis
from typing import Optional
from app.core import config

_arq_redis_pool: Optional[ArqRedis] = None

def get_redis_settings() -> RedisSettings:
    return RedisSettings(
        host=config.REDIS_HOST,
        port=config.REDIS_PORT,
        password=config.REDIS_PASSWORD,
        database=config.REDIS_DATABASE
    )

async def init_redis_pool() -> ArqRedis:
    global _arq_redis_pool
    if _arq_redis_pool is None:
        _arq_redis_pool = await create_pool(get_redis_settings())
    return _arq_redis_pool

async def close_redis_pool():
    global _arq_redis_pool
    if _arq_redis_pool is not None:
        await _arq_redis_pool.close()
        _arq_redis_pool = None

async def get_arq_redis() -> ArqRedis:
    global _arq_redis_pool
    if _arq_redis_pool is None:
        _arq_redis_pool = await create_pool(get_redis_settings())
    return _arq_redis_pool
