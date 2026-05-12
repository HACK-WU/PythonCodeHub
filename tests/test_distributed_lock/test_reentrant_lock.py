"""ReentrantRedisLock 单元测试。

通过 unittest.mock.MagicMock 模拟 Redis 客户端，验证可重入语义：
- 同实例多次 acquire 计数累加
- release 计数递减，归零时才真正删除
- 不同 token 之间互斥
"""

import unittest
from unittest.mock import MagicMock

from ab_lock.distributed_lock import ReentrantRedisLock


class TestReentrantRedisLock(unittest.TestCase):
    def test_first_acquire_success(self):
        # Lua 脚本返回 1 表示加锁成功
        client = MagicMock()
        client.eval.return_value = 1

        lock = ReentrantRedisLock("res-1", client=client, ttl=30)
        self.assertTrue(lock.acquire())
        self.assertEqual(lock.lock_count, 1)
        self.assertTrue(lock.is_locked())

    def test_reentrant_acquire_increments_count(self):
        # 多次 acquire，本地计数应递增
        client = MagicMock()
        client.eval.return_value = 1

        lock = ReentrantRedisLock("res-2", client=client)
        lock.acquire()
        lock.acquire()
        lock.acquire()

        self.assertEqual(lock.lock_count, 3)
        # eval 被调用 3 次（每次 acquire 都会发起脚本调用）
        self.assertEqual(client.eval.call_count, 3)

    def test_acquire_failure_when_held_by_others(self):
        # Lua 脚本返回 0 表示被他人持有
        client = MagicMock()
        client.eval.return_value = 0

        lock = ReentrantRedisLock("res-3", client=client)
        self.assertFalse(lock.acquire(wait=0.01))
        self.assertEqual(lock.lock_count, 0)
        self.assertFalse(lock.is_locked())

    def test_release_decrements_count(self):
        # 加锁 3 次，释放 1 次后剩余计数为 2
        client = MagicMock()
        # 3 次 acquire 都返回 1，第一次 release 返回剩余计数 2
        client.eval.side_effect = [1, 1, 1, 2]

        lock = ReentrantRedisLock("res-4", client=client)
        lock.acquire()
        lock.acquire()
        lock.acquire()
        result = lock.release()

        self.assertEqual(result, 2)
        self.assertEqual(lock.lock_count, 2)

    def test_release_to_zero_deletes_lock(self):
        # 加锁 1 次，释放 1 次后计数归零
        client = MagicMock()
        client.eval.side_effect = [1, 0]  # acquire 返回 1，release 返回 0

        lock = ReentrantRedisLock("res-5", client=client)
        lock.acquire()
        result = lock.release()

        self.assertEqual(result, 0)
        self.assertEqual(lock.lock_count, 0)
        self.assertFalse(lock.is_locked())

    def test_release_without_acquire_raises(self):
        # 未加锁直接 release 应抛出 RuntimeError
        client = MagicMock()
        lock = ReentrantRedisLock("res-6", client=client)

        with self.assertRaises(RuntimeError):
            lock.release()
        client.eval.assert_not_called()

    def test_release_returns_minus_one_when_lock_lost(self):
        # 模拟锁因 TTL 过期被他人占用：Lua 返回 -1
        client = MagicMock()
        # acquire 成功，但释放时 Redis 端已无该 token
        client.eval.side_effect = [1, -1]

        lock = ReentrantRedisLock("res-7", client=client)
        lock.acquire()
        result = lock.release()

        self.assertEqual(result, -1)
        # 修复后的行为：Redis 端已丢失 → 强制清零本地计数，避免状态泄漏
        self.assertEqual(lock.lock_count, 0)
        self.assertFalse(lock.is_locked())

    def test_release_after_lock_lost_can_reacquire(self):
        # 验证状态泄漏修复：锁丢失后 release 应能重新 acquire
        client = MagicMock()
        # 1) acquire 成功 → 2) release 返回 -1（锁丢失）→ 3) 重新 acquire 成功
        client.eval.side_effect = [1, -1, 1]

        lock = ReentrantRedisLock("res-recover", client=client)
        lock.acquire()
        lock.release()
        # 本地状态已清零，可以重新加锁
        self.assertTrue(lock.acquire())
        self.assertEqual(lock.lock_count, 1)

    def test_release_passes_ttl_for_renewal(self):
        # 验证 release 会传递 ttl_ms，以便 Lua 脚本在 remaining > 0 时续期
        client = MagicMock()
        # 两次 acquire 成功，一次 release 返回剩余 1
        client.eval.side_effect = [1, 1, 1]

        lock = ReentrantRedisLock("res-ttl", client=client, ttl=10)
        lock.acquire()
        lock.acquire()
        lock.release()

        # 最后一次 eval 即 release 调用，参数为：脚本 + numkeys=1 + key + token + ttl_ms
        release_args = client.eval.call_args_list[-1][0]
        self.assertEqual(release_args[1], 1)  # numkeys
        self.assertEqual(release_args[2], "res-ttl")  # KEYS[1]
        self.assertEqual(release_args[3], lock._token)  # ARGV[1] = token
        self.assertEqual(release_args[4], 10000)  # ARGV[2] = ttl_ms

    def test_with_statement_reentrant(self):
        # 嵌套 with 模拟重入
        client = MagicMock()
        # 2 次 acquire 都成功，2 次 release：第一次返回 1，第二次返回 0
        client.eval.side_effect = [1, 1, 1, 0]

        lock = ReentrantRedisLock("res-8", client=client)
        with lock as outer:
            self.assertEqual(outer.lock_count, 1)
            with lock as inner:
                self.assertEqual(inner.lock_count, 2)
                self.assertIs(inner, outer)
            # 内层 with 退出，计数 -1
            self.assertEqual(lock.lock_count, 1)
        # 外层 with 退出，计数归零
        self.assertEqual(lock.lock_count, 0)

    def test_with_statement_raises_on_failure(self):
        # with 加锁失败应抛出 TimeoutError
        client = MagicMock()
        client.eval.return_value = 0

        lock = ReentrantRedisLock("res-fail", client=client)
        with self.assertRaises(TimeoutError):
            with lock:
                pass

    def test_acquire_passes_correct_args_to_eval(self):
        # 验证 eval 调用参数：脚本 + numkeys=1 + key + token + ttl_ms
        client = MagicMock()
        client.eval.return_value = 1

        lock = ReentrantRedisLock("my-key", client=client, ttl=10)
        lock.acquire()

        args = client.eval.call_args[0]
        self.assertEqual(args[1], 1)  # numkeys
        self.assertEqual(args[2], "my-key")  # KEYS[1]
        self.assertEqual(args[3], lock._token)  # ARGV[1] = token
        self.assertEqual(args[4], 10000)  # ARGV[2] = ttl_ms

    def test_client_required(self):
        with self.assertRaises(ValueError):
            ReentrantRedisLock("res-x", client=None)


if __name__ == "__main__":
    unittest.main()
