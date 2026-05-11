"""RWLock 读写锁单元测试。

主要通过 MagicMock 验证 Lua 脚本调用参数与本地状态同步，
不依赖真实 Redis。
"""

import threading
import unittest
from unittest.mock import MagicMock

from ab_lock.distributed_lock import RWLock


class TestRWLockRead(unittest.TestCase):
    def test_acquire_read_success(self):
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-r1", client=client, ttl=30)

        self.assertTrue(rw.acquire_read())
        self.assertEqual(rw.read_count, 1)
        self.assertTrue(rw.is_locked())

    def test_read_reentrant(self):
        # 同实例可重入读锁，计数累加
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-r2", client=client)

        rw.acquire_read()
        rw.acquire_read()
        rw.acquire_read()
        self.assertEqual(rw.read_count, 3)

    def test_acquire_read_blocked_by_write(self):
        # Lua 脚本返回 0 表示被写锁阻塞
        client = MagicMock()
        client.eval.return_value = 0
        rw = RWLock("res-r3", client=client)

        self.assertFalse(rw.acquire_read(_wait=0.01))
        self.assertEqual(rw.read_count, 0)

    def test_release_read_decrements_count(self):
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-r4", client=client)

        rw.acquire_read()
        rw.acquire_read()
        rw.release_read()
        self.assertEqual(rw.read_count, 1)

    def test_release_read_without_holding_raises(self):
        rw = RWLock("res-r5", client=MagicMock())
        with self.assertRaises(RuntimeError):
            rw.release_read()

    def test_release_read_lock_lost_resets_count(self):
        # Lua 返回 -1 表示 Redis 端已不存在（TTL 过期），本地计数应清零
        client = MagicMock()
        rw = RWLock("res-r6", client=client)

        client.eval.return_value = 1
        rw.acquire_read()
        rw.acquire_read()
        self.assertEqual(rw.read_count, 2)

        client.eval.return_value = -1
        result = rw.release_read()
        self.assertEqual(result, -1)
        self.assertEqual(rw.read_count, 0)


class TestRWLockWrite(unittest.TestCase):
    def test_acquire_write_success(self):
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-w1", client=client)

        self.assertTrue(rw.acquire_write())
        self.assertTrue(rw.holds_write)
        self.assertTrue(rw.is_locked())

    def test_acquire_write_blocked(self):
        client = MagicMock()
        client.eval.return_value = 0
        rw = RWLock("res-w2", client=client)

        self.assertFalse(rw.acquire_write(_wait=0.01))
        self.assertFalse(rw.holds_write)

    def test_release_write(self):
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-w3", client=client)

        rw.acquire_write()
        self.assertEqual(rw.release_write(), 1)
        self.assertFalse(rw.holds_write)

    def test_release_write_without_holding_raises(self):
        rw = RWLock("res-w4", client=MagicMock())
        with self.assertRaises(RuntimeError):
            rw.release_write()


class TestRWLockDowngrade(unittest.TestCase):
    def test_downgrade_success(self):
        # 持写锁时降级为读锁
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-d1", client=client)

        rw.acquire_write()
        self.assertTrue(rw.downgrade_to_read())
        self.assertFalse(rw.holds_write)
        self.assertEqual(rw.read_count, 1)

    def test_downgrade_without_write_lock_raises(self):
        rw = RWLock("res-d2", client=MagicMock())
        with self.assertRaises(RuntimeError):
            rw.downgrade_to_read()

    def test_downgrade_fail_when_token_mismatch(self):
        # Lua 返回 0 表示 token 不匹配（锁已丢失）
        client = MagicMock()
        rw = RWLock("res-d3", client=client)

        client.eval.return_value = 1
        rw.acquire_write()
        client.eval.return_value = 0
        self.assertFalse(rw.downgrade_to_read())
        # 本地状态视为已失去锁
        self.assertFalse(rw.holds_write)
        self.assertEqual(rw.read_count, 0)


class TestRWLockUpgrade(unittest.TestCase):
    def test_upgrade_success_when_sole_reader(self):
        # 本 token 是唯一读者 → 升级成功
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-u1", client=client)

        rw.acquire_read()
        self.assertTrue(rw.try_upgrade_to_write())
        self.assertTrue(rw.holds_write)
        self.assertEqual(rw.read_count, 0)

    def test_upgrade_fail_when_other_readers(self):
        # Lua 返回 0 表示仍有其他读者，本地状态保持不变
        client = MagicMock()
        rw = RWLock("res-u2", client=client)

        client.eval.return_value = 1
        rw.acquire_read()
        client.eval.return_value = 0  # 升级失败

        self.assertFalse(rw.try_upgrade_to_write())
        self.assertFalse(rw.holds_write)
        self.assertEqual(rw.read_count, 1)  # 读锁保留

    def test_upgrade_without_read_lock_raises(self):
        rw = RWLock("res-u3", client=MagicMock())
        with self.assertRaises(RuntimeError):
            rw.try_upgrade_to_write()


class TestRWLockContextManagers(unittest.TestCase):
    def test_read_lock_context(self):
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-ctx-r", client=client)

        with rw.read_lock() as r:
            self.assertIs(r, rw)
            self.assertEqual(rw.read_count, 1)
        self.assertEqual(rw.read_count, 0)

    def test_write_lock_context(self):
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-ctx-w", client=client)

        with rw.write_lock():
            self.assertTrue(rw.holds_write)
        self.assertFalse(rw.holds_write)

    def test_read_lock_context_timeout_raises(self):
        client = MagicMock()
        client.eval.return_value = 0  # 始终被阻塞
        rw = RWLock("res-ctx-fail", client=client)

        with self.assertRaises(TimeoutError):
            with rw.read_lock(_wait=0.01):
                pass

    def test_write_lock_releases_on_exception(self):
        # 临界区异常时，写锁仍应被释放
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-ctx-exc", client=client)

        with self.assertRaises(ValueError):
            with rw.write_lock():
                raise ValueError("business error")
        self.assertFalse(rw.holds_write)


class TestRWLockValidation(unittest.TestCase):
    def test_client_required(self):
        with self.assertRaises(ValueError):
            RWLock("res", client=None)


# ──────────────────────────────────────────────────────
# 本次修复引入的新增测试
# ──────────────────────────────────────────────────────
class TestRWLockTokenLifecycle(unittest.TestCase):
    """验证 token 在 acquire/release 周期中正确生成与清理。"""

    def test_acquire_read_failure_clears_token(self):
        # 读锁获取失败时，本地 token 应被清理
        client = MagicMock()
        client.eval.return_value = 0
        rw = RWLock("res-tok-r-fail", client=client)

        self.assertFalse(rw.acquire_read(_wait=0.01))
        self.assertIsNone(rw._token)

    def test_acquire_write_failure_clears_token(self):
        # 写锁获取失败时，本地 token 应被清理
        client = MagicMock()
        client.eval.return_value = 0
        rw = RWLock("res-tok-w-fail", client=client)

        self.assertFalse(rw.acquire_write(_wait=0.01))
        self.assertIsNone(rw._token)

    def test_write_release_clears_token_when_no_read(self):
        # 写锁释放后（无读锁），token 应被清理以便下次重新生成
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-tok-w-rel", client=client)

        rw.acquire_write()
        self.assertIsNotNone(rw._token)
        rw.release_write()
        self.assertIsNone(rw._token)

    def test_downgrade_failure_clears_token_and_state(self):
        # 降级失败（Lua 返回 0）时，holds_write 和 token 都应被清理
        client = MagicMock()
        rw = RWLock("res-tok-dg-fail", client=client)

        client.eval.return_value = 1
        rw.acquire_write()
        client.eval.return_value = 0  # 降级失败
        self.assertFalse(rw.downgrade_to_read())
        self.assertFalse(rw.holds_write)
        self.assertIsNone(rw._token)
        self.assertEqual(rw.read_count, 0)

    def test_token_regenerated_on_new_acquire_cycle(self):
        # 释放后再次获取，token 应该是新的
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-tok-regen", client=client)

        rw.acquire_read()
        token1 = rw._token
        rw.release_read()
        self.assertIsNone(rw._token)

        rw.acquire_read()
        token2 = rw._token
        self.assertNotEqual(token1, token2)


class TestRWLockUpgradeWithWait(unittest.TestCase):
    """验证 try_upgrade_to_write 在 _wait > 0 时的超时行为。"""

    def test_upgrade_times_out_when_always_blocked(self):
        # Lua 始终返回 0（有其他读者），_wait=0.05s 后超时返回 False
        client = MagicMock()
        rw = RWLock("res-upg-wait", client=client)

        client.eval.return_value = 1
        rw.acquire_read()
        client.eval.return_value = 0  # 仍有其他读者

        self.assertFalse(rw.try_upgrade_to_write(_wait=0.05, retry_interval=0.01))
        # 读锁状态不变
        self.assertEqual(rw.read_count, 1)
        self.assertFalse(rw.holds_write)


class TestRWLockThreadSafety(unittest.TestCase):
    """验证 RLock 保护下的多线程并发安全性。"""

    def test_concurrent_read_acquire_release(self):
        # 多线程并发获取/释放读锁，token 不应串
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-thread-r", client=client)

        errors = []

        def worker():
            try:
                for _ in range(50):
                    if rw.acquire_read(_wait=0.01):
                        rw.release_read()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    def test_concurrent_write_acquire_release(self):
        # 多线程并发获取/释放写锁
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-thread-w", client=client)

        errors = []

        def worker():
            try:
                for _ in range(20):
                    if rw.acquire_write(_wait=0.01):
                        rw.release_write()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])

    def test_properties_thread_safe(self):
        # 多线程并发读取 read_count / holds_write / is_locked 不应抛异常
        client = MagicMock()
        client.eval.return_value = 1
        rw = RWLock("res-thread-prop", client=client)
        rw.acquire_read()

        errors = []

        def reader():
            try:
                for _ in range(100):
                    _ = rw.read_count
                    _ = rw.holds_write
                    _ = rw.is_locked()
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
