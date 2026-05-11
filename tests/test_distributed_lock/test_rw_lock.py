"""RWLock 读写锁单元测试。

主要通过 MagicMock 验证 Lua 脚本调用参数与本地状态同步，
不依赖真实 Redis。
"""

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


if __name__ == "__main__":
    unittest.main()
