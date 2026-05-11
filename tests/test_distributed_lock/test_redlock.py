"""Redlock 算法单元测试。

通过 MagicMock 模拟多节点场景，验证多数派成功 / 失败、回滚、释放等行为。
"""

import threading
import time
import unittest
import warnings
from unittest.mock import MagicMock

from ab_lock.distributed_lock import Redlock


def _make_client(set_return=True, eval_return=1):
    """辅助：构造一个行为可控的 Redis 客户端 Mock。"""
    client = MagicMock()
    client.set.return_value = set_return
    client.eval.return_value = eval_return
    return client


class TestRedlock(unittest.TestCase):
    def test_acquire_success_on_all_nodes(self):
        # 所有节点都加锁成功
        clients = [_make_client(set_return=True) for _ in range(3)]
        lock = Redlock("res-1", clients=clients, ttl=10)

        self.assertTrue(lock.acquire())
        self.assertTrue(lock.is_locked())
        self.assertIsNotNone(lock.valid_until)
        # 每个节点都应被调用一次 SET NX
        for c in clients:
            c.set.assert_called_once()

    def test_acquire_success_on_quorum(self):
        # 3 节点中 2 个成功（达到多数派 N/2+1 = 2）
        clients = [
            _make_client(set_return=True),
            _make_client(set_return=True),
            _make_client(set_return=False),  # 第 3 个失败
        ]
        lock = Redlock("res-2", clients=clients, ttl=10)
        self.assertTrue(lock.acquire())

    def test_acquire_fail_below_quorum(self):
        # 3 节点只有 1 个成功（未达多数派），且应对所有节点发起回滚 DEL
        clients = [
            _make_client(set_return=True),
            _make_client(set_return=False),
            _make_client(set_return=False),
        ]
        lock = Redlock("res-3", clients=clients, ttl=10, retry_times=1)
        self.assertFalse(lock.acquire())
        # 回滚：所有节点都应收到 eval（Lua 释放）调用
        for c in clients:
            c.eval.assert_called()

    def test_acquire_retries(self):
        # 前两次失败，第三次成功
        call_count = [0]

        def set_side_effect(*args, **kwargs):
            call_count[0] += 1
            return call_count[0] >= 7  # 前 2 轮（3 节点 x 2 = 6 次）全失败，第 3 轮开始返回 True

        clients = []
        for _ in range(3):
            c = MagicMock()
            c.set.side_effect = set_side_effect
            c.eval.return_value = 1
            clients.append(c)

        lock = Redlock("res-4", clients=clients, ttl=10, retry_times=3, retry_delay=0.01)
        self.assertTrue(lock.acquire())

    def test_release_counts_successful_nodes(self):
        # 加锁成功后 release 返回实际释放的节点数
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock("res-5", clients=clients, ttl=10)
        lock.acquire()

        # 其中一个节点释放返回 0（token 不匹配），另外两个返回 1
        clients[0].eval.return_value = 0

        released = lock.release()
        self.assertEqual(released, 2)
        self.assertFalse(lock.is_locked())

    def test_release_when_not_held(self):
        # 未持锁时 release 返回 0，不调用 eval
        clients = [_make_client() for _ in range(3)]
        lock = Redlock("res-6", clients=clients)
        self.assertEqual(lock.release(), 0)

    def test_empty_clients_rejected(self):
        with self.assertRaises(ValueError):
            Redlock("res-7", clients=[])

    def test_node_exception_treated_as_failure(self):
        # 某节点抛出异常应被视为加锁失败，但不影响其他节点
        good = _make_client(set_return=True)
        bad = MagicMock()
        bad.set.side_effect = ConnectionError("node down")
        bad.eval.return_value = 0

        # 2 好 + 1 坏：多数派仍成立
        clients = [good, _make_client(set_return=True), bad]
        lock = Redlock("res-8", clients=clients, ttl=10)
        self.assertTrue(lock.acquire())

    def test_quorum_calculation(self):
        # N=5 时 quorum=3，N=7 时 quorum=4
        lock5 = Redlock("r5", clients=[_make_client() for _ in range(5)])
        self.assertEqual(lock5.quorum, 3)
        lock7 = Redlock("r7", clients=[_make_client() for _ in range(7)])
        self.assertEqual(lock7.quorum, 4)

    def test_with_statement(self):
        # BaseLock 的上下文管理器应能正常工作
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock("res-ctx", clients=clients, ttl=10)
        with lock:
            self.assertTrue(lock.is_locked())
        self.assertFalse(lock.is_locked())


# ──────────────────────────────────────────────────────
# 本次修复引入的新增测试
# ──────────────────────────────────────────────────────
class TestRedlockTokenPerAttempt(unittest.TestCase):
    """验证每次 acquire 重试轮次都重新生成 token。"""

    def test_different_token_on_each_attempt(self):
        # 前 2 轮失败，第 3 轮成功；通过跟踪 lock._token 在每次成功 acquire 时
        # 的值来间接验证（或通过观察 set 调用参数）
        # 简化方案：用 1 个节点 + quorum=1，这样每轮只 1 次 set
        clients = [_make_client(set_return=False)]  # 默认失败
        lock = Redlock("res-token", clients=clients, ttl=10, retry_times=3, retry_delay=0.01)

        tokens_seen = []
        clients[0].set

        def set_side_effect(name, token, **kwargs):
            tokens_seen.append(token)
            # 前 2 次（attempt 0, 1）返回 False，第 3 次（attempt 2）返回 True
            return len(tokens_seen) >= 3

        clients[0].set.side_effect = set_side_effect
        clients[0].eval.return_value = 1

        self.assertTrue(lock.acquire())

        # 3 次尝试，每次 token 不同
        self.assertEqual(len(tokens_seen), 3)
        self.assertNotEqual(tokens_seen[0], tokens_seen[1])
        self.assertNotEqual(tokens_seen[1], tokens_seen[2])


class TestRedlockNodeTimeoutDeprecation(unittest.TestCase):
    """验证 node_timeout 参数触发 DeprecationWarning。"""

    def test_node_timeout_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Redlock("res-dep", clients=[_make_client()], node_timeout=5.0)
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        self.assertEqual(len(dep_warnings), 1)
        self.assertIn("deprecated", str(dep_warnings[0].message).lower())

    def test_node_timeout_none_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Redlock("res-no-dep", clients=[_make_client()], node_timeout=None)
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        self.assertEqual(len(dep_warnings), 0)

    def test_node_timeout_default_no_warning(self):
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            Redlock("res-default", clients=[_make_client()])
        dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        self.assertEqual(len(dep_warnings), 0)


class TestRedlockStateLockThreadSafety(unittest.TestCase):
    """验证 _state_lock 对共享状态的线程安全保护。"""

    def test_concurrent_acquire_release(self):
        # 多线程并发 acquire/release，不应出现 token 泄漏或状态错位
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock("res-threadsafe", clients=clients, ttl=10, retry_times=1)
        errors = []

        def worker():
            try:
                for _ in range(20):
                    if lock.acquire():
                        # 持锁期间 is_locked 应为 True
                        if not lock.is_locked():
                            errors.append("is_locked returned False while holding lock")
                        lock.release()
                    # release 后应不再持锁
                    if lock._token is not None:
                        errors.append("_token not None after release")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    def test_valid_until_protected_by_lock(self):
        # valid_until 读取应在 _state_lock 内完成
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock("res-vu", clients=clients, ttl=10)
        lock.acquire()
        # 加锁后 valid_until 应为正值
        self.assertIsNotNone(lock.valid_until)
        lock.release()
        # 释放后应为 None
        self.assertIsNone(lock.valid_until)


class TestRedlockWatchdog(unittest.TestCase):
    """验证 Redlock 内置看门狗的多数派续期与丢失回调。"""

    def test_watchdog_renew_updates_valid_until(self):
        # 看门狗多数派续期成功后，valid_until 应被延后
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock(
            "res-wd-renew",
            clients=clients,
            ttl=1,
            enable_watchdog=True,
            watchdog_interval=0.05,
        )
        lock.acquire()
        vu_before = lock.valid_until
        time.sleep(0.15)  # 等看门狗续期 2-3 次
        vu_after = lock.valid_until
        lock.release()
        # 续期后 valid_until 应比刚加锁时更晚
        self.assertGreater(vu_after, vu_before)

    def test_watchdog_lost_triggers_callback(self):
        # 多数派续期失败 → on_lock_lost 被调用，看门狗线程退出
        # 前 2 节点续期返回 0（失败），第 3 个返回 1 → 1/3 < quorum(2)
        clients = [_make_client(set_return=True) for _ in range(3)]
        for c in clients[:2]:
            c.eval.return_value = 0  # 续期失败
        clients[2].eval.return_value = 1

        callback = MagicMock()
        lock = Redlock(
            "res-wd-lost",
            clients=clients,
            ttl=1,
            enable_watchdog=True,
            watchdog_interval=0.05,
            on_lock_lost=callback,
        )
        lock.acquire()
        time.sleep(0.2)  # 等看门狗触发续期并检测到丢失
        callback.assert_called_once_with("res-wd-lost")
        # 看门狗线程应已退出
        if lock._watchdog_thread is not None:
            self.assertFalse(lock._watchdog_thread.is_alive())
        lock.release()

    def test_watchdog_start_failure_rolls_back(self):
        # 看门狗启动失败（interval >= ttl）→ 回滚所有节点 + _token 为 None
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock(
            "res-wd-fail",
            clients=clients,
            ttl=1,
            enable_watchdog=True,
            watchdog_interval=2.0,  # interval > ttl → ValueError
        )
        with self.assertRaises(ValueError):
            lock.acquire()
        # _token 应被清空
        self.assertIsNone(lock._token)
        self.assertIsNone(lock._valid_until)
        # 所有节点应收到 DEL 回滚
        for c in clients:
            c.eval.assert_called()

    def test_stop_watchdog_join_timeout(self):
        # 验证 _stop_watchdog 使用 1.0s join timeout，而非 ttl
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock(
            "res-wd-stop",
            clients=clients,
            ttl=60,
            enable_watchdog=True,
            watchdog_interval=0.05,
        )
        lock.acquire()
        start = time.monotonic()
        lock.release()
        elapsed = time.monotonic() - start
        # release 不应阻塞超过 2s（1s join + 少量开销）
        self.assertLess(elapsed, 2.0)


class TestRedlockIsLockedExpiry(unittest.TestCase):
    """验证 is_locked 在 valid_until 过期后返回 False。"""

    def test_is_locked_false_after_valid_until(self):
        # 模拟：加锁成功但 valid_until 已过去
        clients = [_make_client(set_return=True, eval_return=1) for _ in range(3)]
        lock = Redlock("res-expired", clients=clients, ttl=10)
        lock.acquire()
        # 手动将 valid_until 设为过去
        with lock._state_lock:
            lock._valid_until = time.monotonic() - 1
        self.assertFalse(lock.is_locked())


if __name__ == "__main__":
    unittest.main()
