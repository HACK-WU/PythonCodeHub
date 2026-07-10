import unittest

from ab_thread import ContextPropagator, InheritParentThread, ThreadPool, local


class _RecordingPropagator(ContextPropagator):
    """记录 capture/apply/cleanup 调用次数，用于验证生命周期。"""

    def __init__(self) -> None:
        self.captures = 0
        self.applies = 0
        self.cleanups = 0

    def capture(self) -> dict:
        self.captures += 1
        return {"state": self.captures}

    def apply(self, ctx: dict) -> None:
        self.applies += 1

    def cleanup(self) -> None:
        self.cleanups += 1


class TestInheritParentThread(unittest.TestCase):
    def tearDown(self) -> None:
        for key, _ in list(local):
            delattr(local, key)

    def test_inherits_parent_local(self):
        local.user_id = 1001
        seen: dict = {}

        def worker() -> None:
            seen["v"] = getattr(local, "user_id", None)

        t = InheritParentThread(target=worker)
        t.start()
        t.join()
        self.assertEqual(seen["v"], 1001)

    def test_child_writes_do_not_affect_parent(self):
        local.user_id = 1001
        seen: dict = {}

        def worker() -> None:
            seen["inherited"] = local.user_id
            local.user_id = 9999
            seen["child_val"] = local.user_id

        t = InheritParentThread(target=worker)
        t.start()
        t.join()
        self.assertEqual(seen["inherited"], 1001)
        self.assertEqual(seen["child_val"], 9999)
        self.assertEqual(local.user_id, 1001)  # 父线程不受影响

    def test_empty_propagators_disable_inheritance(self):
        # 验证 propagators=[] 不被回退为默认 [LocalPropagator()]
        local.user_id = 1001
        seen: dict = {}

        def worker() -> None:
            seen["has"] = hasattr(local, "user_id")

        t = InheritParentThread(target=worker, propagators=[])
        t.start()
        t.join()
        self.assertFalse(seen["has"])

    def test_target_exception_does_not_propagate(self):
        # 子线程内异常仅记录不向上抛，join 应正常完成
        def worker() -> None:
            raise RuntimeError("boom")

        t = InheritParentThread(target=worker)
        t.start()
        t.join()  # 不应抛异常

    def test_sync_and_unsync_called_once(self):
        rec = _RecordingPropagator()

        def worker() -> None:
            pass

        t = InheritParentThread(target=worker, propagators=[rec])
        t.start()
        t.join()
        self.assertEqual(rec.applies, 1)
        self.assertEqual(rec.cleanups, 1)


class TestThreadPool(unittest.TestCase):
    def tearDown(self) -> None:
        for key, _ in list(local):
            delattr(local, key)

    def test_map_async_propagates_local(self):
        local.v = "parent"

        def get_v(_: object) -> object:
            return getattr(local, "v", None)

        with ThreadPool(2) as pool:
            result = pool.map_async(get_v, [None, None, None]).get()
        self.assertEqual(result, ["parent", "parent", "parent"])

    def test_empty_propagators_no_inheritance(self):
        local.v = "parent"

        def has_v(_: object) -> bool:
            return hasattr(local, "v")

        with ThreadPool(2, propagators=[]) as pool:
            result = pool.map_async(has_v, [None]).get()
        self.assertEqual(result, [False])

    def test_apply_async_applies_and_cleans(self):
        rec = _RecordingPropagator()

        def work() -> int:
            return 1

        with ThreadPool(1, propagators=[rec]) as pool:
            pool.apply_async(work).get()
        self.assertEqual(rec.applies, 1)
        self.assertEqual(rec.cleanups, 1)

    def test_map_ignore_exception_returns_exception(self):
        def boom(_: object) -> None:
            raise ValueError("bad")

        with ThreadPool(2) as pool:
            results = pool.map_ignore_exception(boom, [1, 2], return_exception=True)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertIsInstance(r, ValueError)

    def test_map_ignore_exception_skips_on_failure(self):
        def task(x: int) -> int:
            if x == 1:
                return x
            raise ValueError("bad")

        with ThreadPool(2) as pool:
            results = pool.map_ignore_exception(task, [1, 2], return_exception=False)
        self.assertEqual(results, [1])  # 仅成功的任务入列

    def test_imap_preserves_order(self):
        local.v = "p"

        def get_v(_: object) -> object:
            return getattr(local, "v", None)

        with ThreadPool(2) as pool:
            result = list(pool.imap(get_v, [None, None]))
        self.assertEqual(result, ["p", "p"])

    def test_context_manager_closes_pool(self):
        pool = ThreadPool(1)
        with pool:
            pass
        # 关闭后不能再提交任务
        with self.assertRaises(Exception):
            pool.map_async(lambda: 1, [None]).get()


if __name__ == "__main__":
    unittest.main()
