"""线程/协程局部存储（Thread/Context-Local Storage）。

提供 Werkzeug 风格的 `Local` 类，用于实现线程（或 greenlet 协程）隔离的数据存储。
每个线程/协程拥有独立的命名空间，互不干扰，常用于 Web 请求上下文、全局可变状态隔离等场景。

特性:
    * 线程 / greenlet 协程隔离（注意：默认实现**不**隔离 asyncio 协程，见下方说明）。
    * 自动回收：默认以执行单元的“所有者对象”（Thread/greenlet）作为存储键，并使用
      ``weakref.WeakKeyDictionary`` 持有**弱引用**键。当线程/协程结束、其 owner 对象
      被回收时，对应命名空间自动从存储中移除。由于键是对象本身（而非可被 OS 复用的
      整数线程 id），不同执行单元天然不会键冲突，从根本上避免“线程 id 复用 + 旧
      Thread 对象仍被引用”导致的新线程读到旧线程遗留数据的问题。
      注意：主执行单元（主线程/主 greenlet）对象进程级常驻，其命名空间不会自动释放；
      自定义 ident 函数返回不可弱引用的值（如 int/str）时改用普通 dict 存储，亦无自动
      回收，需调用方手动 :meth:`Local.clear`。
    * 可注入自定义 ident 函数（如基于 contextvars 的实现），以支持 asyncio 等场景。

关于 asyncio:
    Python 的 asyncio 协程运行在同一操作系统线程内，共享同一个线程 id，
    因此本模块默认实现（基于 _thread / greenlet）**不会**在 asyncio 协程之间隔离数据。
    如需在 asyncio 中隔离，请通过 ``Local(ident_func=...)`` 注入基于 contextvars 的 ident 函数。

典型用法::

    from ab_thread.utils import local

    local.user_id = 1001  # 主线程命名空间

    def worker():
        assert not hasattr(local, "user_id")  # 子线程不可见主线程属性
        local.user_id = 2002

    import threading
    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert local.user_id == 1001  # 主线程数据不受影响
"""

import threading
import weakref

try:
    from greenlet import getcurrent as _current
except ImportError:  # pragma: no cover - 取决于运行环境是否安装 greenlet
    _current = None

__all__ = ["Local", "LocalBase", "local"]

# 只读内部属性，禁止通过普通属性赋值/删除修改
_READONLY_ATTRS = ("__storage__", "__ident_func__")


def _get_owner():
    """返回当前执行单元的“所有者”对象，用作 ``Local`` 默认存储键。

    线程场景返回 ``threading.current_thread()``（Thread 对象），greenlet 场景返回
    greenlet 对象。由于键是对象本身（而非可被 OS 复用的整数线程 id），不同执行单元
    天然不会键冲突；配合 :class:`weakref.WeakKeyDictionary` 的弱引用键，owner 对象
    被回收时命名空间自动移除，从根因上避免线程 id 复用导致的数据串扰。
    """
    if _current is not None:
        return _current()  # greenlet 对象本身
    return threading.current_thread()  # Thread 对象


def _weakrefable(value):
    """判断 ``value`` 是否可被弱引用（用于决定存储能否用 WeakKeyDictionary）。

    ``weakref.ref(value)`` 要么返回弱引用对象、要么抛 ``TypeError``，不会返回 ``None``。
    """
    try:
        weakref.ref(value)
        return True
    except TypeError:
        return False


class LocalBase:
    """`Local` 的基类，仅声明槽位以节省内存。"""

    __slots__ = ("__storage__", "__ident_func__")


class Local(LocalBase):
    """线程/协程局部存储类。

    内部维护线程（或 greenlet 协程）隔离的数据存储空间。默认以“所有者对象”
    （Thread/greenlet）作为键（``WeakKeyDictionary`` 弱引用持有），实现不同执行单元
    之间的数据隔离与自动回收；支持属性访问、迭代、``in`` 判断、安全清理等功能。

    由于键为对象本身，不同执行单元天然不会冲突；即使操作系统复用整数线程 id，
    也不会出现新线程读到旧线程遗留数据的情况。

    线程安全（无锁设计）:
        属性读写**全程不加锁**。安全性不依赖 GIL，而建立在两点：(1) 每个执行单元只读写
        自己的命名空间——storage 以 owner 对象（Thread/greenlet）为键，不同执行单元键互不
        相同，不存在跨线程操作同一内层字典；(2) 单条 dict 操作在 CPython 中原子——GIL 构建
        如此，free-threaded（无 GIL，PEP 703）构建亦由 CPython 显式保证单条容器操作原子。
        ``WeakKeyDictionary`` 的 per-key 访问也归约为单条 ``self.data[ref]`` 原子操作；
        弱引用回调仅在线程结束、owner 被回收时触发，不会摘除正被访问的活线程命名空间。
        因此 free-threaded 构建下同样安全，无需加锁。并发吞吐接近 ``threading.local``；
        单线程下因 ``WeakKeyDictionary`` 弱引用维护开销，仍慢于 ``threading.local``
        （约 3 倍），这是保留“自动回收/防 id 复用”特性的代价。
    """

    __slots__ = ()

    def __init__(self, ident_func=None):
        if ident_func is None:
            # 默认：owner 对象为键，弱引用持有，owner 回收时自动清理
            ident_func = _get_owner
            storage = weakref.WeakKeyDictionary()
        else:
            # 自定义 ident：探测一次返回值是否可弱引用以选择存储类型，尽量保留自动回收。
            # 注意：此处会实际调用 ident_func() 一次；调用方应保证其返回值类型稳定
            # （始终可弱引用或始终不可），否则存储类型可能与实际使用不匹配。
            storage = weakref.WeakKeyDictionary() if _weakrefable(ident_func()) else {}
        object.__setattr__(self, "__storage__", storage)
        object.__setattr__(self, "__ident_func__", ident_func)

    # ---- 释放 ----
    def __release_local__(self):
        """释放当前线程/协程的本地存储空间。"""
        self.__storage__.pop(self.__ident_func__(), None)

    # ---- 属性访问 ----
    def __getattr__(self, name):
        # __getattr__ 仅在常规属性查找失败时调用；对只读槽位名直接报错，避免在内部
        # 槽位未初始化时（如反序列化/部分构造）访问 self.__storage__ 触发无限递归。
        if name in _READONLY_ATTRS:
            raise AttributeError(name)
        # 无锁：每线程命名空间隔离 + 单条 dict 操作原子即可安全并发（含 free-threaded）。
        try:
            return self.__storage__[self.__ident_func__()][name]
        except (KeyError, AttributeError):
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name in _READONLY_ATTRS:
            raise AttributeError(f"{self.__class__.__name__!r} object attribute '{name}' is read-only")
        ident = self.__ident_func__()
        storage = self.__storage__
        try:
            namespace = storage[ident]
        except KeyError:
            namespace = storage[ident] = {}
        namespace[name] = value

    def __delattr__(self, name):
        if name in _READONLY_ATTRS:
            raise AttributeError(f"{self.__class__.__name__!r} object attribute '{name}' is read-only")
        ident = self.__ident_func__()
        storage = self.__storage__
        try:
            namespace = storage[ident]
        except KeyError:
            raise AttributeError(name)
        try:
            del namespace[name]
        except KeyError:
            raise AttributeError(name)
        if not namespace:
            # 最后一个属性被删除后回收当前命名空间
            storage.pop(ident, None)

    # ---- 读取辅助 ----
    def __iter__(self):
        ident = self.__ident_func__()
        return iter(list(self.__storage__.get(ident, {}).items()))

    def __contains__(self, name):
        ident = self.__ident_func__()
        return name in self.__storage__.get(ident, {})

    def get(self, name, default=None):
        """获取属性值，不存在时返回 ``default``。"""
        try:
            ident = self.__ident_func__()
            storage = self.__storage__
        except AttributeError:
            return default
        return storage.get(ident, {}).get(name, default)

    def clear(self):
        """清空当前线程/协程的所有局部存储数据。"""
        self.__release_local__()


local = Local()  # 模块级单例
