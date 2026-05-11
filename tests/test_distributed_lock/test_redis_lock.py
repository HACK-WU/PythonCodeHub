"""RedisLock 单元测试。

通过 unittest.mock.MagicMock 模拟 Redis 客户端，验证锁的核心行为，
无需启动真实 Redis 服务。
"""

import unittest
from unittest.mock import MagicMock

from ab_lock.distributed_lock import RedisLock


class TestRedisLock(unittest.TestCase):
    def test_acquire_success(self):
        # SET NX 返回 True 表示加锁成功
        client = MagicMock()
        client.set.return_value = True

        lock = RedisLock("res-1", client=client, ttl=30)
        self.assertTrue(lock.acquire())
        # 验证使用了 nx=True 与 ex=ttl
        args, kwargs = client.set.call_args
        self.assertEqual(args[0], "res-1")
        self.assertEqual(kwargs.get("ex"), 30)
        self.assertTrue(kwargs.get("nx"))

    def test_acquire_failure_when_competing(self):
        # SET NX 始终返回 False 模拟竞争失败
        client = MagicMock()
        client.set.return_value = False

        lock = RedisLock("res-2", client=client)
        self.assertFalse(lock.acquire(_wait=0.01))

    def test_release_success(self):
        client = MagicMock()
        client.set.return_value = True
        # Lua 脚本返回 1 表示成功删除
        client.eval.return_value = 1

        lock = RedisLock("res-3", client=client)
        lock.acquire()

        result = lock.release()
        self.assertEqual(result, 1)
        # 验证 eval 被正确调用（Lua 脚本, numkeys=1, key, token）
        client.eval.assert_called_once()
        call_args = client.eval.call_args[0]
        self.assertEqual(call_args[1], 1)  # numkeys
        self.assertEqual(call_args[2], "res-3")  # key

    def test_release_skip_when_token_mismatch(self):
        # Lua 脚本返回 0 表示 token 不匹配
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 0

        lock = RedisLock("res-4", client=client)
        lock.acquire()

        result = lock.release()
        self.assertEqual(result, 0)

    def test_release_skip_when_not_acquired(self):
        # 未持锁直接释放应返回 False，且不调用 eval
        client = MagicMock()
        lock = RedisLock("res-5", client=client)
        self.assertFalse(lock.release())
        client.eval.assert_not_called()

    def test_release_clears_token(self):
        # release 后 _token 应被置空，防止重复释放
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = RedisLock("res-clear", client=client)
        lock.acquire()
        self.assertIsNotNone(lock._token)

        lock.release()
        self.assertIsNone(lock._token)

        # 再次调用 release 应直接返回 False
        self.assertFalse(lock.release())

    def test_with_statement(self):
        # with 语句应自动 acquire / release
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = RedisLock("res-6", client=client)
        with lock as l:
            self.assertIs(l, lock)
        client.eval.assert_called_once()

    def test_with_statement_raises_on_failure(self):
        # with 语句在加锁失败时应抛出 TimeoutError
        client = MagicMock()
        client.set.return_value = False

        lock = RedisLock("res-fail", client=client)
        with self.assertRaises(TimeoutError):
            with lock:
                pass  # 不应到达此处

    def test_client_required(self):
        # client 为 None 时必须抛出 ValueError
        with self.assertRaises(ValueError):
            RedisLock("res-7", client=None)

    def test_is_locked(self):
        # is_locked 仅反映本地 token 状态
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = RedisLock("res-locked", client=client)
        self.assertFalse(lock.is_locked())

        lock.acquire()
        self.assertTrue(lock.is_locked())

        lock.release()
        self.assertFalse(lock.is_locked())

    def test_exit_preserves_original_exception_when_release_fails(self):
        # 临界区有异常 + release 失败时，原始异常优先，不被覆盖
        client = MagicMock()
        client.set.return_value = True
        client.eval.side_effect = ConnectionError("redis down")

        lock = RedisLock("res-exit", client=client)
        with self.assertRaises(ValueError) as cm:
            with lock:
                raise ValueError("business error")
        self.assertEqual(str(cm.exception), "business error")

    def test_exit_propagates_release_error_when_no_original_exception(self):
        # 临界区无异常时，release 失败应正常向上抛出
        client = MagicMock()
        client.set.return_value = True
        client.eval.side_effect = ConnectionError("redis down")

        lock = RedisLock("res-exit-clean", client=client)
        with self.assertRaises(ConnectionError):
            with lock:
                pass


# ──────────────────────────────────────────────────────
# 本次修复引入的新增测试
# ──────────────────────────────────────────────────────
class TestRedisLockWatchdogRollback(unittest.TestCase):
    """验证看门狗启动失败时的回滚逻辑：_token 不应被写入。"""

    def test_watchdog_start_failure_no_token_leak(self):
        # 模拟看门狗启动失败：SyncWatchdog.__init__ 中 interval >= ttl 触发 ValueError
        client = MagicMock()
        client.set.return_value = True
        client.eval.return_value = 1

        lock = RedisLock(
            "res-wd-rollback",
            client=client,
            ttl=1,
            enable_watchdog=True,
            watchdog_interval=5.0,  # interval > ttl → ValueError
        )
        with self.assertRaises(ValueError):
            lock.acquire()

        # 看门狗启动失败后 _token 应为 None（修复前会泄漏）
        self.assertIsNone(lock._token)
        # Redis 端应收到 DEL 回滚
        client.eval.assert_called()


if __name__ == "__main__":
    unittest.main()
