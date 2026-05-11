"""Redlock 算法单元测试。

通过 MagicMock 模拟多节点场景，验证多数派成功 / 失败、回滚、释放等行为。
"""

import unittest
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


if __name__ == "__main__":
    unittest.main()
