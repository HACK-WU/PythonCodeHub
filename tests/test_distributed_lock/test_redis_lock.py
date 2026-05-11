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


if __name__ == "__main__":
    unittest.main()
