"""Redis-backed admission control for DSH agent runs.

PostgreSQL remains the run-history source of truth. Redis owns only short-lived
queue and lease state so every Backend replica observes the same limits.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from redis.asyncio import Redis

from app.config import settings


class AgentQueueFullError(RuntimeError):
    """The shared waiting queue has reached capacity."""


class AgentQueueTimeoutError(RuntimeError):
    """A run did not receive a permit before its queue deadline."""


_ACQUIRE_SCRIPT = r"""
local queue = KEYS[1]
local queue_users = KEYS[2]
local active = KEYS[3]
local active_users = KEYS[4]
local user_prefix = ARGV[1]
local run_id = ARGV[2]
local user_id = ARGV[3]
local now = tonumber(ARGV[4])
local lease_until = tonumber(ARGV[5])
local global_limit = tonumber(ARGV[6])
local user_limit = tonumber(ARGV[7])
local queue_limit = tonumber(ARGV[8])
local queue_expiry = tonumber(ARGV[9])

local expired = redis.call('ZRANGEBYSCORE', active, '-inf', now)
for _, member in ipairs(expired) do
  local owner = redis.call('HGET', active_users, member)
  redis.call('ZREM', active, member)
  redis.call('HDEL', active_users, member)
  if owner then redis.call('ZREM', user_prefix .. owner, member) end
end
local stale = redis.call('ZRANGEBYSCORE', queue, '-inf', queue_expiry)
for _, member in ipairs(stale) do
  redis.call('ZREM', queue, member)
  redis.call('HDEL', queue_users, member)
end

if redis.call('ZSCORE', active, run_id) then return {1, 0} end
if not redis.call('ZSCORE', queue, run_id) then
  if redis.call('ZCARD', queue) >= queue_limit then return {-2, 0} end
  redis.call('ZADD', queue, 'NX', now, run_id)
  redis.call('HSET', queue_users, run_id, user_id)
end
if redis.call('ZCARD', active) >= global_limit then
  local rank = redis.call('ZRANK', queue, run_id)
  return {0, rank and rank + 1 or 1}
end

local candidates = redis.call('ZRANGE', queue, 0, queue_limit - 1)
local selected = nil
for _, member in ipairs(candidates) do
  local owner = redis.call('HGET', queue_users, member)
  if owner then
    local user_key = user_prefix .. owner
    redis.call('ZREMRANGEBYSCORE', user_key, '-inf', now)
    if redis.call('ZCARD', user_key) < user_limit then
      selected = member
      break
    end
  end
end
if selected == run_id then
  redis.call('ZREM', queue, run_id)
  redis.call('HDEL', queue_users, run_id)
  redis.call('ZADD', active, lease_until, run_id)
  redis.call('HSET', active_users, run_id, user_id)
  redis.call('ZADD', user_prefix .. user_id, lease_until, run_id)
  redis.call('EXPIRE', user_prefix .. user_id, 3600)
  return {1, 0}
end
local rank = redis.call('ZRANK', queue, run_id)
return {0, rank and rank + 1 or 1}
"""

_HEARTBEAT_SCRIPT = r"""
local active = KEYS[1]
local active_users = KEYS[2]
local user_prefix = ARGV[1]
local run_id = ARGV[2]
local lease_until = tonumber(ARGV[3])
local owner = redis.call('HGET', active_users, run_id)
if not owner or not redis.call('ZSCORE', active, run_id) then return 0 end
redis.call('ZADD', active, lease_until, run_id)
redis.call('ZADD', user_prefix .. owner, lease_until, run_id)
redis.call('EXPIRE', user_prefix .. owner, 3600)
return 1
"""

_RELEASE_SCRIPT = r"""
local queue = KEYS[1]
local queue_users = KEYS[2]
local active = KEYS[3]
local active_users = KEYS[4]
local user_prefix = ARGV[1]
local run_id = ARGV[2]
local owner = redis.call('HGET', active_users, run_id)
redis.call('ZREM', queue, run_id)
redis.call('HDEL', queue_users, run_id)
redis.call('ZREM', active, run_id)
redis.call('HDEL', active_users, run_id)
if owner then redis.call('ZREM', user_prefix .. owner, run_id) end
return 1
"""

StatusCallback = Callable[[str, int | None], Awaitable[None]]


class AgentAdmission:
    _PREFIX = "ai-platform:agent-admission:"

    def __init__(self) -> None:
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True)
        self.queue_key = f"{self._PREFIX}queue"
        self.queue_users_key = f"{self._PREFIX}queue-users"
        self.active_key = f"{self._PREFIX}active"
        self.active_users_key = f"{self._PREFIX}active-users"
        self.user_prefix = f"{self._PREFIX}user:"

    async def _release(self, run_id: str) -> None:
        await self.redis.eval(
            _RELEASE_SCRIPT, 4,
            self.queue_key, self.queue_users_key, self.active_key, self.active_users_key,
            self.user_prefix, run_id,
        )

    async def _heartbeat(self, run_id: str) -> None:
        while True:
            await asyncio.sleep(settings.agent_heartbeat_seconds)
            lease_until = int((time.time() + settings.agent_lease_seconds) * 1000)
            renewed = await self.redis.eval(
                _HEARTBEAT_SCRIPT, 2, self.active_key, self.active_users_key,
                self.user_prefix, run_id, lease_until,
            )
            if not renewed:
                return

    @asynccontextmanager
    async def permit(
        self, run_id: str, user_id: str, on_status: StatusCallback | None = None,
    ) -> AsyncIterator[None]:
        started = time.monotonic()
        heartbeat: asyncio.Task[None] | None = None
        last_position: int | None = None
        try:
            while True:
                now_ms = int(time.time() * 1000)
                result = await self.redis.eval(
                    _ACQUIRE_SCRIPT, 4,
                    self.queue_key, self.queue_users_key, self.active_key, self.active_users_key,
                    self.user_prefix, run_id, user_id, now_ms,
                    now_ms + settings.agent_lease_seconds * 1000,
                    settings.agent_global_concurrency, settings.agent_user_concurrency,
                    settings.agent_queue_max,
                    now_ms - settings.agent_queue_wait_seconds * 1000,
                )
                code, position = int(result[0]), int(result[1])
                if code == -2:
                    raise AgentQueueFullError("智能体等待队列已满，请稍后重试")
                if code == 1:
                    if on_status:
                        await on_status("running", None)
                    heartbeat = asyncio.create_task(self._heartbeat(run_id), name=f"agent-lease:{run_id}")
                    break
                if on_status and position != last_position:
                    await on_status("queued", position)
                    last_position = position
                if time.monotonic() - started >= settings.agent_queue_wait_seconds:
                    raise AgentQueueTimeoutError(
                        f"智能体排队超过 {settings.agent_queue_wait_seconds} 秒，请稍后重试"
                    )
                await asyncio.sleep(0.75)
            yield
        finally:
            if heartbeat is not None:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            # The lease expires quickly, so a temporary Redis outage must not mask
            # the original run result. Best-effort release is sufficient here.
            with suppress(Exception):
                await self._release(run_id)


agent_admission = AgentAdmission()
