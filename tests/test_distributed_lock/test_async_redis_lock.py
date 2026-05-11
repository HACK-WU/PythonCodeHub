"""AsyncRedisLock 单元测试。

通过 unittest.mock.AsyncMock 模拟异步 Redis 客户端，验证：
- 异步 acquire / release 行为
- async with 自动加解锁
- 加锁失败时抛出 TimeoutError
- 释放使用 Lua 脚本
- is_locked 查询
- __aexit__ 不吃掉原始异常
"""

import unittest
from unittest.mock import AsyncMock

from ab_lock.distributed_lock import AsyncRedisLock


class TestAsyncRedisLock(unittest.IsolatedAsyncioTestCase):
    async def test_acquire_success(self):
        client = AsyncMock()
        client.set.return_value = True

        lock = AsyncRedisLock("res-1", client=client, ttl=30)
        self.assertTrue(await lock.acquire())

        # 验证 SET 调用参数
        args, kwargs = client.set.call_args
        self.assertEqual(args[0], "res-1")
        self.assertEqual(kwargs.get("ex"), 30)
        self.assertTrue(kwargs.get("nx"))

    async def test_acquire_failure_when_competing(self):
        client = AsyncMock()
        client.set.return_value = False

        lock = AsyncRedisLock("res-2", client=client)
        self.assertFalse(await lock.acquire(_wait=0.01))

    async def test_release_success(self):
        client = AsyncMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = AsyncRedisLock("res-3", client=client)
        await lock.acquire()
        result = await lock.release()

        self.assertEqual(result, 1)
        client.eval.assert_awaited_once()
        # 验证 eval 参数：脚本 + numkeys=1 + key + token
        args = client.eval.call_args[0]
        self.assertEqual(args[1], 1)
        self.assertEqual(args[2], "res-3")

    async def test_release_skip_when_not_acquired(self):
        client = AsyncMock()
        lock = AsyncRedisLock("res-4", client=client)

        result = await lock.release()
        # 修复后统一返回类型为 int：未持锁 → 返回 0
        self.assertEqual(result, 0)
        client.eval.assert_not_called()

    async def test_release_clears_token(self):
        client = AsyncMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = AsyncRedisLock("res-clear", client=client)
        await lock.acquire()
        self.assertIsNotNone(lock._token)

        await lock.release()
        self.assertIsNone(lock._token)
        # 重复 release 应直接返回 0（未持锁）
        self.assertEqual(await lock.release(), 0)

    async def test_async_with_statement(self):
        client = AsyncMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = AsyncRedisLock("res-with", client=client)
        async with lock as l:
            self.assertIs(l, lock)
            self.assertIsNotNone(lock._token)
        # 退出 async with 后已释放
        self.assertIsNone(lock._token)
        client.eval.assert_awaited_once()

    async def test_async_with_raises_on_failure(self):
        client = AsyncMock()
        client.set.return_value = False

        lock = AsyncRedisLock("res-fail", client=client)
        with self.assertRaises(TimeoutError):
            async with lock:
                pass  # 不应到达

    async def test_async_with_releases_on_exception(self):
        # 临界区抛异常时，锁仍应被释放
        client = AsyncMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = AsyncRedisLock("res-exc", client=client)
        with self.assertRaises(ValueError):
            async with lock:
                raise ValueError("boom")
        client.eval.assert_awaited_once()

    async def test_client_required(self):
        with self.assertRaises(ValueError):
            AsyncRedisLock("res-x", client=None)

    async def test_is_locked(self):
        # 验证 is_locked 仅反映本地 token 状态，不发起网络调用
        client = AsyncMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = AsyncRedisLock("res-locked", client=client)
        self.assertFalse(lock.is_locked())

        await lock.acquire()
        self.assertTrue(lock.is_locked())

        await lock.release()
        self.assertFalse(lock.is_locked())

    async def test_acquire_non_blocking_only_tries_once(self):
        # _wait=0 默认非阻塞：失败后只调用一次 set，不进入 sleep
        client = AsyncMock()
        client.set.return_value = False

        lock = AsyncRedisLock("res-nb", client=client)
        result = await lock.acquire()  # 默认 _wait=0

        self.assertFalse(result)
        self.assertEqual(client.set.call_count, 1)

    async def test_acquire_retries_within_wait_window(self):
        # _wait > 0 时，首次失败后应重试，需能看到多次 set 调用
        client = AsyncMock()
        # 前两次失败，第三次成功
        client.set.side_effect = [False, False, True]

        lock = AsyncRedisLock("res-retry", client=client)
        result = await lock.acquire(_wait=0.1, retry_interval=0.005)

        self.assertTrue(result)
        self.assertEqual(client.set.call_count, 3)

    async def test_aexit_preserves_original_exception_when_release_fails(self):
        # 临界区抛异常且 release 也抛异常时，应保留原始异常
        client = AsyncMock()
        client.set.return_value = True
        # release 调用 eval 时抛出连接错误
        client.eval.side_effect = ConnectionError("redis down")

        lock = AsyncRedisLock("res-aexit", client=client)
        with self.assertRaises(ValueError) as cm:
            async with lock:
                raise ValueError("business error")
        # 原始业务异常优先，不被 release 异常覆盖
        self.assertEqual(str(cm.exception), "business error")

    async def test_aexit_propagates_release_error_when_no_original_exception(self):
        # 临界区无异常但 release 抛出时，release 的异常应正常向上抛出
        client = AsyncMock()
        client.set.return_value = True
        client.eval.side_effect = ConnectionError("redis down")

        lock = AsyncRedisLock("res-aexit-clean", client=client)
        with self.assertRaises(ConnectionError):
            async with lock:
                pass


# ──────────────────────────────────────────────────────
# 本次修复引入的新增测试
# ──────────────────────────────────────────────────────
class TestAsyncRedisLockWatchdogRollback(unittest.IsolatedAsyncioTestCase):
    """验证异步锁看门狗启动失败时的回滚逻辑：_token 不应被写入。"""

    async def test_watchdog_start_failure_no_token_leak(self):
        # 模拟看门狗启动失败：interval >= ttl 触发 ValueError
        client = AsyncMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = AsyncRedisLock(
            "res-async-wd-rollback",
            client=client,
            ttl=1,
            enable_watchdog=True,
            watchdog_interval=5.0,  # interval > ttl
        )
        with self.assertRaises(ValueError):
            await lock.acquire()

        # _token 应为 None
        self.assertIsNone(lock._token)
        # Redis 端应收到 DEL 回滚
        client.eval.assert_awaited()


if __name__ == "__main__":
    unittest.main()
