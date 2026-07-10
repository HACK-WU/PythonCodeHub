import unittest

from ab_thread import (
    ContextPropagator,
    LocalPropagator,
    capture_context,
    local,
    run_with_context,
)


class _RecordingPropagator(ContextPropagator):
    """用于断言 capture/apply/cleanup 调用关系的传播器。"""

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


class TestLocalPropagator(unittest.TestCase):
    def tearDown(self) -> None:
        for key, _ in list(local):
            delattr(local, key)

    def test_capture_returns_current_local_items(self):
        local.a = 1
        local.b = "x"
        ctx = LocalPropagator().capture()
        self.assertIn(("a", 1), ctx)
        self.assertIn(("b", "x"), ctx)

    def test_capture_snapshot_is_decoupled(self):
        local.a = 1
        prop = LocalPropagator()
        ctx = prop.capture()
        local.a = 2  # 修改原始 local 不应影响已拍快照
        prop.apply(ctx)
        self.assertEqual(local.a, 1)
        del local.a

    def test_apply_sets_attributes(self):
        LocalPropagator().apply([("k", "v")])
        self.assertEqual(local.k, "v")
        del local.k

    def test_cleanup_removes_seed_attributes(self):
        local.seed = 1
        LocalPropagator().cleanup()
        self.assertNotIn("seed", local)

    def test_cleanup_removes_worker_written_attributes(self):
        # cleanup 应清除运行期间新增的属性，避免泄漏到后续复用
        local.seed = 1
        local.extra = 2
        LocalPropagator().cleanup()
        self.assertNotIn("seed", local)
        self.assertNotIn("extra", local)


class TestCaptureContext(unittest.TestCase):
    def test_capture_context_pairs_propagator_with_ctx(self):
        p1 = _RecordingPropagator()
        p2 = _RecordingPropagator()
        captured = capture_context([p1, p2])
        self.assertEqual(len(captured), 2)
        self.assertIs(captured[0][0], p1)
        self.assertEqual(captured[0][1], {"state": 1})
        self.assertEqual(p1.captures, 1)
        self.assertEqual(p2.captures, 1)

    def test_capture_context_empty(self):
        self.assertEqual(capture_context([]), [])


class TestRunWithContext(unittest.TestCase):
    def tearDown(self) -> None:
        for key, _ in list(local):
            delattr(local, key)

    def test_run_with_context_returns_and_cleans_up(self):
        prop = _RecordingPropagator()
        captured = capture_context([prop])
        result = run_with_context(lambda: 42, captured)
        self.assertEqual(result, 42)
        self.assertEqual(prop.applies, 1)
        self.assertEqual(prop.cleanups, 1)

    def test_run_with_context_propagates_local(self):
        local.value = "inherited"
        captured = capture_context([LocalPropagator()])
        seen: dict = {}
        run_with_context(lambda: seen.setdefault("v", local.value), captured)
        self.assertEqual(seen["v"], "inherited")
        self.assertNotIn("value", local)


class TestContextPropagatorABC(unittest.TestCase):
    def test_cannot_instantiate_abstract(self):
        with self.assertRaises(TypeError):
            ContextPropagator()


if __name__ == "__main__":
    unittest.main()
