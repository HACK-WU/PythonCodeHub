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

        # 因为 acquire 中对 keys 做了 set 去重，顺序不确定
        # 但由于 pipeline 接收的顺序就是 list(set(keys))，结果索引与之一致
        self.assertEqual(len(success_keys), 2)
        client.pipeline.assert_called_once_with(transaction=False)

    def test_acquire_empty_keys(self):
        client = MagicMock()
        lock = MultiRedisLock([], client=client)
        self.assertEqual(lock.acquire(), [])
        client.pipeline.assert_not_called()

    def test_release_only_own_keys(self):
        # 准备一个加锁成功的 lock 实例
        pipeline = self._make_pipeline([True, True])
        client = MagicMock()
        client.pipeline.return_value = pipeline

        lock = MultiRedisLock(["k1", "k2"], client=client)
        lock.acquire()

        # mget 返回：第一个 token 与本实例一致，第二个被他人占用
        success_keys_list = list(lock._lock_success_keys)
        client.mget.return_value = [
            lock._token if k == success_keys_list[0] else "other-token" for k in success_keys_list
        ]

        deleted = lock.release()
        self.assertEqual(deleted, [success_keys_list[0]])
        client.delete.assert_called_once_with(success_keys_list[0])

    def test_release_no_success_keys(self):
        client = MagicMock()
        lock = MultiRedisLock(["k1"], client=client)
        # 未调用 acquire，_lock_success_keys 为空
        self.assertIsNone(lock.release())
        client.mget.assert_not_called()
        client.delete.assert_not_called()

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

    def test_client_required(self):
        with self.assertRaises(ValueError):
            MultiRedisLock(["k1"], client=None)


if __name__ == "__main__":
    unittest.main()
