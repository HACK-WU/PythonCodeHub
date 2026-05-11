"""Watchdog（同步 + 异步）单元测试。

不依赖真实 Redis，通过 MagicMock + 时间缩放验证续期与停止逻辑。
"""

import asyncio
import time
import unittest
from unittest.mock import MagicMock

from ab_lock.distributed_lock import AsyncWatchdog, RedisLock, SyncWatchdog
from ab_lock.distributed_lock.async_redis_lock import AsyncRedisLock


# ──────────────────────────────────────────────────────
# SyncWatchdog
# ──────────────────────────────────────────────────────
class TestSyncWatchdog(unittest.TestCase):
    def test_renew_called_periodically(self):
        # 续期应被周期性触发：ttl=1s、interval=0.05s，运行 0.2s 应至少 2 次
        client = MagicMock()
        client.eval.return_value = 1

        dog = SyncWatchdog(client, "res-1", "tok-1", ttl=1, interval=0.05)
        dog.start()
        time.sleep(0.2)
        dog.stop()

        self.assertGreaterEqual(client.eval.call_count, 2)
        # 验证 eval 调用参数正确（numkeys=1, key, token, ttl_ms）
        args = client.eval.call_args[0]
        self.assertEqual(args[1], 1)
        self.assertEqual(args[2], "res-1")
        self.assertEqual(args[3], "tok-1")
        self.assertEqual(args[4], 1000)  # 1s = 1000ms

    def test_stop_is_idempotent(self):
        # stop 可多次调用而不报错
        client = MagicMock()
        client.eval.return_value = 1
        dog = SyncWatchdog(client, "res-2", "tok", ttl=1, interval=0.05)
        dog.start()
        dog.stop()
        dog.stop()  # 第二次不应抛异常

    def test_stops_when_token_lost(self):
        # 当续期发现 token 不匹配（返回 0），看门狗自动停止且回调被触发
        client = MagicMock()
        client.eval.return_value = 0  # 模拟 token 已失效

        callback = MagicMock()
        dog = SyncWatchdog(client, "res-3", "tok", ttl=1, interval=0.05, on_lost=callback)
        dog.start()
        time.sleep(0.15)
        dog.stop()

        callback.assert_called_once_with("res-3")
        # 已停止后 eval 不应继续增加
        count = client.eval.call_count
        time.sleep(0.1)
        self.assertEqual(client.eval.call_count, count)

    def test_interval_must_be_less_than_ttl(self):
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "res", "tok", ttl=1, interval=2)

    def test_renew_exception_does_not_stop_watchdog(self):
        # 续期抛异常（如网络抖动）时看门狗不应直接退出，而是继续下一轮
        client = MagicMock()
        call_count = [0]

        def eval_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("network flaky")
            return 1

        client.eval.side_effect = eval_side_effect
        dog = SyncWatchdog(client, "res-4", "tok", ttl=1, interval=0.05)
        dog.start()
        time.sleep(0.2)
        dog.stop()

        # 第一次异常之后仍有更多调用发生
        self.assertGreaterEqual(call_count[0], 2)


# ──────────────────────────────────────────────────────
# RedisLock 集成 watchdog
# ──────────────────────────────────────────────────────
class TestRedisLockWatchdog(unittest.TestCase):
    def test_acquire_starts_watchdog(self):
        # enable_watchdog=True 时，acquire 成功会启动看门狗线程
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = RedisLock("res-w1", client=client, ttl=1, enable_watchdog=True)
        lock.acquire()

        self.assertIsNotNone(lock._watchdog)
        # 给一点时间让续期线程跑起来
        time.sleep(0.5)
        # ttl/3 ≈ 0.33s，0.5s 内至少续期 1 次
        self.assertGreaterEqual(client.eval.call_count, 1)
        lock.release()
        # release 后看门狗应被清除
        self.assertIsNone(lock._watchdog)

    def test_release_stops_watchdog(self):
        # release 时看门狗应停止，之后不再续期
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = RedisLock("res-w2", client=client, ttl=1, enable_watchdog=True, watchdog_interval=0.05)
        lock.acquire()
        time.sleep(0.15)  # 让看门狗跑几次
        lock.release()
        count_after_release = client.eval.call_count

        time.sleep(0.2)
        # release 之后 eval 不再增加（除了 release 本身那次）
        self.assertEqual(client.eval.call_count, count_after_release)

    def test_no_watchdog_when_disabled(self):
        # 默认 enable_watchdog=False 时 _watchdog 应始终为 None
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = RedisLock("res-w3", client=client)
        lock.acquire()
        self.assertIsNone(lock._watchdog)
        lock.release()


# ──────────────────────────────────────────────────────
# AsyncWatchdog
# ──────────────────────────────────────────────────────
class TestAsyncWatchdog(unittest.IsolatedAsyncioTestCase):
    async def test_renew_called_periodically(self):
        # 续期周期性触发
        async def eval_return(*args, **kwargs):
            return 1

        client = MagicMock()
        client.eval = MagicMock(side_effect=eval_return)

        dog = AsyncWatchdog(client, "res-a1", "tok", ttl=1, interval=0.05)
        await dog.start()
        await asyncio.sleep(0.2)
        await dog.stop()

        self.assertGreaterEqual(client.eval.call_count, 2)

    async def test_stops_when_token_lost(self):
        async def eval_return(*args, **kwargs):
            return 0  # 模拟 token 失效

        client = MagicMock()
        client.eval = MagicMock(side_effect=eval_return)
        callback = MagicMock()

        dog = AsyncWatchdog(client, "res-a2", "tok", ttl=1, interval=0.05, on_lost=callback)
        await dog.start()
        await asyncio.sleep(0.15)
        await dog.stop()

        callback.assert_called_once_with("res-a2")

    async def test_async_redis_lock_watchdog(self):
        # AsyncRedisLock 集成 watchdog 的端到端测试
        async def set_ret(*args, **kwargs):
            return True

        async def eval_ret(*args, **kwargs):
            return 1

        client = MagicMock()
        client.set = MagicMock(side_effect=set_ret)
        client.eval = MagicMock(side_effect=eval_ret)

        lock = AsyncRedisLock("res-a3", client=client, ttl=1, enable_watchdog=True, watchdog_interval=0.05)
        await lock.acquire()
        self.assertIsNotNone(lock._watchdog)
        await asyncio.sleep(0.15)
        # 至少续期 2 次（0.15s / 0.05s = 3）
        self.assertGreaterEqual(client.eval.call_count, 2)
        await lock.release()
        self.assertIsNone(lock._watchdog)


# ──────────────────────────────────────────────────────
# 本次修复引入的新增测试
# ──────────────────────────────────────────────────────
class TestAsyncWatchdogStartFailure(unittest.IsolatedAsyncioTestCase):
    """验证 AsyncWatchdog.start 失败时 _stop_event 被正确清理。"""

    async def test_start_failure_clears_stop_event(self):
        # 模拟 create_task 失败（事件循环已关闭等场景）
        # 由于在正常测试环境下 create_task 不会失败，通过 patch 模拟
        client = MagicMock()

        async def eval_return(*args, **kwargs):
            return 1

        client.eval = MagicMock(side_effect=eval_return)
        dog = AsyncWatchdog(client, "res-start-fail", "tok", ttl=1, interval=0.05)

        # 正常 start 应成功
        await dog.start()
        self.assertIsNotNone(dog._stop_event)
        self.assertIsNotNone(dog._task)
        await dog.stop()

        # 模拟 create_task 抛异常
        import asyncio as _asyncio

        with unittest.mock.patch.object(_asyncio, "create_task", side_effect=RuntimeError("loop closed")):
            dog2 = AsyncWatchdog(client, "res-start-fail2", "tok", ttl=1, interval=0.05)
            with self.assertRaises(RuntimeError):
                await dog2.start()
            # _stop_event 应被清理为 None
            self.assertIsNone(dog2._stop_event)
            self.assertIsNone(dog2._task)


if __name__ == "__main__":
    unittest.main()
