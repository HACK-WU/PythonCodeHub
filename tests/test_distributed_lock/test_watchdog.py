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


# ──────────────────────────────────────────────────────
# 本次全面修复新增的边界测试
# ──────────────────────────────────────────────────────
from ab_lock.distributed_lock.watchdog import _parse_renew_result  # noqa: E402


class TestParseRenewResult(unittest.TestCase):
    """验证 _parse_renew_result 对各种返回值的鲁棒解析。"""

    def test_int_one_is_success(self):
        self.assertTrue(_parse_renew_result(1))

    def test_int_zero_is_failure(self):
        self.assertFalse(_parse_renew_result(0))

    def test_none_is_failure(self):
        self.assertFalse(_parse_renew_result(None))

    def test_bytes_one_is_success(self):
        self.assertTrue(_parse_renew_result(b"1"))

    def test_str_one_is_success(self):
        self.assertTrue(_parse_renew_result("1"))

    def test_unparseable_is_failure(self):
        self.assertFalse(_parse_renew_result("not-a-number"))
        self.assertFalse(_parse_renew_result(object()))


class TestSyncWatchdogParameterValidation(unittest.TestCase):
    """验证 SyncWatchdog 构造参数的边界校验。"""

    def test_ttl_must_be_positive(self):
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "k", "t", ttl=0)
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "k", "t", ttl=-1)

    def test_ttl_must_be_int(self):
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "k", "t", ttl=None)  # type: ignore[arg-type]

    def test_interval_zero_rejected(self):
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "k", "t", ttl=10, interval=0)

    def test_interval_negative_rejected(self):
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "k", "t", ttl=10, interval=-0.5)

    def test_interval_ge_ttl_rejected(self):
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "k", "t", ttl=1, interval=2)

    def test_max_renew_failures_must_be_at_least_one(self):
        with self.assertRaises(ValueError):
            SyncWatchdog(MagicMock(), "k", "t", ttl=10, interval=1, max_renew_failures=0)


class TestSyncWatchdogConsecutiveFailures(unittest.TestCase):
    """验证连续续期 RPC 失败超过阈值时触发 on_lost。"""

    def test_consecutive_failures_trigger_on_lost(self):
        client = MagicMock()
        client.eval.side_effect = ConnectionError("network down")
        callback = MagicMock()

        dog = SyncWatchdog(
            client,
            "res-fail",
            "tok",
            ttl=10,
            interval=0.02,
            on_lost=callback,
            max_renew_failures=2,
        )
        dog.start()
        # 等待至少 2 次连续失败（约 0.04s + 容错）
        time.sleep(0.2)
        dog.stop()

        callback.assert_called_once_with("res-fail")

    def test_failures_reset_on_success(self):
        # 一次失败后立即成功，不应触发 on_lost
        client = MagicMock()
        call_count = [0]

        def eval_side(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ConnectionError("flaky")
            return 1  # 后续都成功

        client.eval.side_effect = eval_side
        callback = MagicMock()

        dog = SyncWatchdog(
            client,
            "res-recover",
            "tok",
            ttl=10,
            interval=0.02,
            on_lost=callback,
            max_renew_failures=2,
        )
        dog.start()
        time.sleep(0.2)
        dog.stop()

        callback.assert_not_called()


class TestSyncWatchdogStopSuppressesOnLost(unittest.TestCase):
    """验证主动 stop 后即使 RPC 返回 0 也不触发 on_lost 误报。"""

    def test_stop_during_inflight_renew_no_callback(self):
        # 模拟续期 RPC 阻塞 0.1s 后返回 0；在阻塞期间调用 stop
        client = MagicMock()

        def slow_eval(*args, **kwargs):
            time.sleep(0.1)
            return 0  # token 不匹配

        client.eval.side_effect = slow_eval
        callback = MagicMock()

        dog = SyncWatchdog(
            client,
            "res-stop",
            "tok",
            ttl=10,
            interval=0.02,
            on_lost=callback,
        )
        dog.start()
        time.sleep(0.05)  # 让 RPC 进入飞行
        dog.stop(join_timeout=0.5)

        # 主动 stop 时即使解析到 token 不匹配也不应回调
        callback.assert_not_called()


class TestSyncWatchdogOnLostCallbackException(unittest.TestCase):
    """验证 on_lost 回调内部异常不会导致看门狗线程崩溃。"""

    def test_callback_exception_swallowed(self):
        client = MagicMock()
        client.eval.return_value = 0  # 直接进入 lost 分支

        def bad_callback(key):
            raise RuntimeError("user bug")

        dog = SyncWatchdog(
            client,
            "res-cbexc",
            "tok",
            ttl=10,
            interval=0.02,
            on_lost=bad_callback,
        )
        # 不应抛出异常
        dog.start()
        time.sleep(0.1)
        dog.stop()


class TestSyncWatchdogStartIdempotent(unittest.TestCase):
    """验证 start 幂等：重复调用只启一个线程，stop 后可重新 start。"""

    def test_repeated_start_single_thread(self):
        client = MagicMock()
        client.eval.return_value = 1
        dog = SyncWatchdog(client, "res-idem", "tok", ttl=10, interval=0.05)
        dog.start()
        first_thread = dog._thread
        dog.start()
        dog.start()
        # 重复 start 不会替换线程
        self.assertIs(dog._thread, first_thread)
        dog.stop()

    def test_restart_after_stop(self):
        client = MagicMock()
        client.eval.return_value = 1
        dog = SyncWatchdog(client, "res-restart", "tok", ttl=10, interval=0.05)
        dog.start()
        dog.stop()
        # stop 后再 start 应成功
        dog.start()
        self.assertIsNotNone(dog._thread)
        self.assertTrue(dog._thread.is_alive())
        dog.stop()


class TestAsyncWatchdogParameterValidation(unittest.TestCase):
    """验证 AsyncWatchdog 构造参数的边界校验。"""

    def test_ttl_positive(self):
        with self.assertRaises(ValueError):
            AsyncWatchdog(MagicMock(), "k", "t", ttl=0)

    def test_interval_zero_rejected(self):
        with self.assertRaises(ValueError):
            AsyncWatchdog(MagicMock(), "k", "t", ttl=10, interval=0)

    def test_max_renew_failures_at_least_one(self):
        with self.assertRaises(ValueError):
            AsyncWatchdog(MagicMock(), "k", "t", ttl=10, interval=1, max_renew_failures=0)


class TestAsyncWatchdogConsecutiveFailures(unittest.IsolatedAsyncioTestCase):
    """验证 AsyncWatchdog 连续 RPC 失败触发 on_lost。"""

    async def test_consecutive_failures_trigger_on_lost(self):
        async def eval_fail(*args, **kwargs):
            raise ConnectionError("down")

        client = MagicMock()
        client.eval = MagicMock(side_effect=eval_fail)
        callback = MagicMock()

        dog = AsyncWatchdog(
            client,
            "res-afail",
            "tok",
            ttl=10,
            interval=0.02,
            on_lost=callback,
            max_renew_failures=2,
        )
        await dog.start()
        await asyncio.sleep(0.2)
        await dog.stop()

        callback.assert_called_once_with("res-afail")


if __name__ == "__main__":
    unittest.main()
