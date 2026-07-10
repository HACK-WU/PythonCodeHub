import gc
import threading
import unittest
import weakref

from ab_thread.local import Local, local


class TestLocal(unittest.TestCase):
    """测试 Local 线程局部存储类"""

    def test_set_and_get_attr(self):
        """测试设置与获取属性"""
        obj = Local()
        obj.name = "alice"
        obj.count = 3
        self.assertEqual(obj.name, "alice")
        self.assertEqual(obj.count, 3)

    def test_get_missing_attr_raises(self):
        """测试获取不存在的属性抛出 AttributeError"""
        obj = Local()
        with self.assertRaises(AttributeError):
            _ = obj.not_exist

    def test_del_attr(self):
        """测试删除属性"""
        obj = Local()
        obj.name = "bob"
        del obj.name
        with self.assertRaises(AttributeError):
            _ = obj.name

    def test_del_last_attr_releases_storage(self):
        """测试删除最后一个属性后回收当前线程的存储空间"""
        obj = Local()
        obj.name = "bob"
        ident = obj.__ident_func__()
        self.assertIn(ident, obj.__storage__)
        del obj.name
        self.assertNotIn(ident, obj.__storage__)

    def test_iter(self):
        """测试迭代当前线程存储的键值对"""
        obj = Local()
        obj.a = 1
        obj.b = 2
        items = dict(obj)
        self.assertEqual(items, {"a": 1, "b": 2})

    def test_iter_empty(self):
        """测试无数据时可迭代出空序列"""
        obj = Local()
        self.assertEqual(list(obj), [])

    def test_clear(self):
        """测试 clear 清空当前线程数据"""
        obj = Local()
        obj.a = 1
        obj.b = 2
        obj.clear()
        self.assertEqual(list(obj), [])
        with self.assertRaises(AttributeError):
            _ = obj.a

    def test_readonly_attr_protection(self):
        """测试只读属性不可修改/删除"""
        obj = Local()
        with self.assertRaises(AttributeError):
            obj.__storage__ = {}
        with self.assertRaises(AttributeError):
            obj.__ident_func__ = None
        with self.assertRaises(AttributeError):
            del obj.__storage__

    def test_contains_and_get(self):
        """测试 in 判断与 get 默认值"""
        obj = Local()
        obj.a = 1
        self.assertIn("a", obj)
        self.assertNotIn("missing", obj)
        self.assertEqual(obj.get("a"), 1)
        self.assertEqual(obj.get("missing"), None)
        self.assertEqual(obj.get("missing", 0), 0)

    def test_custom_ident_func(self):
        """测试通过构造函数注入自定义 ident 函数实现上下文隔离"""
        current = ["ctx-1"]
        obj = Local(ident_func=lambda: current[0])
        obj.value = "one"
        self.assertEqual(obj.value, "one")
        # 切换 ident 返回值后命名空间随之切换，旧数据不可见
        current[0] = "ctx-2"
        self.assertNotIn("value", obj)
        with self.assertRaises(AttributeError):
            _ = obj.value
        # 切回原 ident 仍可见原数据
        current[0] = "ctx-1"
        self.assertEqual(obj.value, "one")

    def test_custom_ident_func_weakrefable_uses_weakkeydict(self):
        """自定义 ident 返回可弱引用对象时，存储用 WeakKeyDictionary（保留自动回收）。"""

        class Ctx:
            pass

        ctx = Ctx()  # 自定义类实例默认可弱引用（object() 不可）
        obj = Local(ident_func=lambda: ctx)
        self.assertIsInstance(obj.__storage__, weakref.WeakKeyDictionary)
        obj.value = 1
        self.assertEqual(obj.value, 1)

    def test_custom_ident_func_non_weakrefable_uses_dict(self):
        """自定义 ident 返回不可弱引用的值（如 str）时，存储退化为普通 dict。"""
        obj = Local(ident_func=lambda: "ctx-1")
        self.assertNotIsInstance(obj.__storage__, weakref.WeakKeyDictionary)
        self.assertIsInstance(obj.__storage__, dict)
        obj.value = 1
        self.assertEqual(obj.value, 1)

    def test_auto_cleanup_after_thread_exit(self):
        """测试线程结束后其存储空间被自动回收（避免线程 id 复用串扰）"""
        obj = Local()

        def worker():
            obj.worker_val = "x"

        t = threading.Thread(target=worker)
        t.start()
        t.join()

        # 释放对 worker 线程对象的引用并强制回收，WeakKeyDictionary 自动移除条目
        del t
        gc.collect()

        # worker 线程的命名空间应已被回收（WeakKeyDictionary 无 __eq__，用 len 判空）
        self.assertEqual(len(obj.__storage__), 0)

    def test_storage_keyed_by_owner_object(self):
        """存储键应为所有者对象（Thread/greenlet），而非整数线程 id。

        这是避免线程 id 复用串扰的核心不变量：不同执行单元对象天然不同，
        即便 OS 复用整数线程 id 也不会发生键冲突。
        """
        obj = Local()
        obj.x = 1
        keys = list(obj.__storage__.keys())
        self.assertEqual(len(keys), 1)
        try:
            import greenlet  # noqa: F401

            import greenlet as _g

            self.assertIsInstance(keys[0], _g.greenlet)
        except ImportError:
            self.assertIsInstance(keys[0], threading.Thread)

    def test_no_contamination_when_old_thread_retained(self):
        """旧 Thread 对象仍被引用时，新线程不得读到其遗留数据。

        回归测试：旧实现以整数线程 id 为键、以 Thread 对象为回收目标，二者生命周期
        分裂。当旧 Thread 对象被外部引用阻止回收、而新线程复用了同一整数线程 id
        时，新线程会读到旧数据。改用所有者对象为键后，不同 Thread 对象天然隔离。
        """
        obj = Local()
        held = []

        def worker():
            obj.secret = "old"

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        held.append(t)  # 故意保留旧 Thread 对象，阻止回收钩子触发

        seen = {}

        def worker2():
            seen["has_old"] = hasattr(obj, "secret")
            obj.secret = "new"
            seen["new_val"] = obj.secret

        t2 = threading.Thread(target=worker2)
        t2.start()
        t2.join()

        self.assertFalse(seen["has_old"])
        self.assertEqual(seen["new_val"], "new")
        del held

    def test_thread_isolation(self):
        """测试不同线程之间的数据隔离"""
        results = {}

        def worker():
            # 子线程是独立命名空间，应看不到主线程设置的属性
            self.assertFalse(hasattr(local, "user_id"))
            local.user_id = 2002
            results["worker"] = local.user_id

        local.user_id = 1001
        t = threading.Thread(target=worker)
        t.start()
        t.join()

        self.assertEqual(results["worker"], 2002)
        # 主线程数据不受影响
        self.assertEqual(local.user_id, 1001)

    def test_module_level_local(self):
        """测试模块级单例 local 的基本读写"""
        local.temp_value = "hello"
        self.assertEqual(local.temp_value, "hello")
        del local.temp_value
        with self.assertRaises(AttributeError):
            _ = local.temp_value


if __name__ == "__main__":
    unittest.main()
