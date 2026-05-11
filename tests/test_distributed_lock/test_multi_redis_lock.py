"""MultiRedisLock 单元测试。"""

import unittest
from unittest.mock import MagicMock

from ab_lock.distributed_lock import MultiRedisLock


class TestMultiRedisLock(unittest.TestCase):
    def _make_pipeline(self, results):
        """构造一个 mock pipeline，execute 返回指定结果。"""
        pipeline = MagicMock()
        pipeline.execute.return_value = results
        return pipeline

    def test_acquire_partial_success(self):
        # 模拟 3 个 key 中 2 个加锁成功
        pipeline = self._make_pipeline([True, False, True])
        client = MagicMock()
        client.pipeline.return_value = pipeline

        lock = MultiRedisLock(["k1", "k2", "k3"], client=client, ttl=10)
        success_keys = lock.acquire()

        self.assertIsInstance(success_keys, set)
        self.assertEqual(len(success_keys), 2)
        client.pipeline.assert_called_once_with(transaction=False)

    def test_acquire_returns_copy(self):
        # acquire 应返回副本，修改返回值不影响内部状态
        pipeline = self._make_pipeline([True])
        client = MagicMock()
        client.pipeline.return_value = pipeline

        lock = MultiRedisLock(["k1"], client=client)
        result = lock.acquire()
        result.add("injected-key")

        # 内部状态不应被外部修改影响
        self.assertNotIn("injected-key", lock._lock_success_keys)

    def test_acquire_empty_keys(self):
        client = MagicMock()
        lock = MultiRedisLock([], client=client)
        result = lock.acquire()
        self.assertIsInstance(result, set)
        self.assertEqual(result, set())
        client.pipeline.assert_not_called()

    def test_release_only_own_keys(self):
        # 准备一个加锁成功的 lock 实例
        pipeline = self._make_pipeline([True, True])
        client = MagicMock()
        client.pipeline.return_value = pipeline

        lock = MultiRedisLock(["k1", "k2"], client=client)
        lock.acquire()

        # 模拟 Lua 脚本：第一个 key 返回 1（token 匹配，成功删除），
        # 第二个 key 返回 0（token 不匹配）
        client.eval.side_effect = [1, 0]

        deleted = lock.release()
        # 只有 eval 返回 1 的 key 被计入 deleted
        self.assertEqual(len(deleted), 1)
        self.assertEqual(client.eval.call_count, 2)

    def test_release_no_success_keys(self):
        client = MagicMock()
        lock = MultiRedisLock(["k1"], client=client)
        # 未调用 acquire，_lock_success_keys 为空
        self.assertIsNone(lock.release())
        client.eval.assert_not_called()

    def test_release_clears_internal_state(self):
        # release 后内部 _lock_success_keys 应被清空
        pipeline = self._make_pipeline([True])
        client = MagicMock()
        client.pipeline.return_value = pipeline
        client.eval.return_value = 1

        lock = MultiRedisLock(["k1"], client=client)
        lock.acquire()
        self.assertTrue(len(lock._lock_success_keys) > 0)

        lock.release()
        self.assertEqual(len(lock._lock_success_keys), 0)

    def test_is_locked(self):
        pipeline = self._make_pipeline([True, False])
        client = MagicMock()
        client.pipeline.return_value = pipeline

        lock = MultiRedisLock(["k1", "k2"], client=client)
        lock.acquire()

        success_keys = list(lock._lock_success_keys)
        self.assertTrue(lock.is_locked(success_keys[0]))
        # 未加锁成功的 key
        all_keys = {"k1", "k2"}
        not_locked = (all_keys - set(success_keys)).pop()
        self.assertFalse(lock.is_locked(not_locked))
        self.assertFalse(lock.is_locked("not-exists"))

    def test_with_statement(self):
        # with 语句应自动 acquire / release
        pipeline = self._make_pipeline([True, True])
        client = MagicMock()
        client.pipeline.return_value = pipeline
        client.eval.return_value = 1

        lock = MultiRedisLock(["k1", "k2"], client=client)
        with lock as l:
            self.assertIs(l, lock)
            self.assertTrue(len(lock._lock_success_keys) > 0)
        # 退出 with 后，release 被调用，内部状态清空
        self.assertEqual(len(lock._lock_success_keys), 0)

    def test_client_required(self):
        with self.assertRaises(ValueError):
            MultiRedisLock(["k1"], client=None)


if __name__ == "__main__":
    unittest.main()
