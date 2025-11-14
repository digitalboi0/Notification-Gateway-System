
import aio_pika
import asyncio
from django.conf import settings

_connection = None
_channel = None
_lock = asyncio.Lock()

async def get_channel():
    global _connection, _channel
    async with _lock:
        if _channel is None or _channel.is_closed:
            _connection = await aio_pika.connect_robust(settings.RABBITMQ_URL)
            _channel = await _connection.channel()
            
            
            await _channel.declare_exchange(
                'notifications.direct',
                aio_pika.ExchangeType.DIRECT,
                durable=True
            )
            
            await _channel.declare_exchange(
                'dlx.notifications',
                aio_pika.ExchangeType.DIRECT,
                durable=True
            )
    return _channel

async def close_connection():
    global _connection, _channel
    if _channel:
        await _channel.close()
    if _connection:
        await _connection.close()
    _channel = None
    _connection = None