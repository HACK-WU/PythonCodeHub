"""RedisLock 单元测试。

通过 unittest.mock.MagicMock 模拟 Redis 客户端，验证锁的核心行为，
无���启动真实 Redis 服务。
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
        client.delete.return_value = 1

        lock = RedisLock("res-3", client=client)
        lock.acquire()
        # GET 返回与本实例一致的 token
        client.get.return_value = lock._token

        result = lock.release()
        self.assertEqual(result, 1)
        client.delete.assert_called_once_with("res-3")

    def test_release_skip_when_token_mismatch(self):
        # token 不匹配时不删除 key，防止误删
        client = MagicMock()
        client.set.return_value = True
        lock = RedisLock("res-4", client=client)
        lock.acquire()

        client.get.return_value = "other-token"
        self.assertFalse(lock.release())
        client.delete.assert_not_called()

    def test_release_skip_when_not_acquired(self):
        # 未持锁直接释放应返回 False，且不调用 delete
        client = MagicMock()
        lock = RedisLock("res-5", client=client)
        self.assertFalse(lock.release())
        client.delete.assert_not_called()

    def test_with_statement(self):
        # with 语句应自动 acquire / release
        client = MagicMock()
        client.set.return_value = True
        client.delete.return_value = 1

        lock = RedisLock("res-6", client=client)
        with lock as l:
            self.assertIs(l, lock)
            client.get.return_value = lock._token
        client.delete.assert_called_once_with("res-6")

    def test_client_required(self):
        # client 为 None 时必须抛出 ValueError
        with self.assertRaises(ValueError):
            RedisLock("res-7", client=None)


if __name__ == "__main__":
    unittest.main()
