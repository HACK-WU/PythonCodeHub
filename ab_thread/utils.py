"""线程/协程局部存储（Thread/Context-Local Storage）。

提供 Werkzeug 风格的 `Local` 类，用于实现线程（或 greenlet 协程）隔离的数据存储。
每个线程/协程拥有独立的命名空间，互不干扰，常用于 Web 请求上下文、全局可变状态隔离等场景。

典型用法::

    from ab_thread.utils import local

    # 在主线程中设置属性
    local.user_id = 1001

    def worker():
        # 在子线程中访问的是独立命名空间
        assert not hasattr(local, "user_id")  # 子线程中不可见主线程的属性
        local.user_id = 2002

    import threading
    t = threading.Thread(target=worker)
    t.start()
    t.join()

    assert local.user_id == 1001  # 主线程数据不受影响
"""


try:
    from greenlet import getcurrent as get_ident
except ImportError:
    from _thread import get_ident

__all__ = ["local", "Local", "get_ident"]


class Localbase:
    __slots__ = ("__storage__", "__ident_func__")

    def __new__(cls, *args, **kwargs):
        self = object.__new__(cls, *args, **kwargs)
        object.__setattr__(self, "__storage__", {})
        object.__setattr__(self, "__ident_func__", get_ident)
        return self


class Local(Localbase):
    """
    线程局部存储类，继承自Localbase。

    内部维护线程/进程隔离的数据存储空间，通过唯一标识符（ident）实现不同线程间的数据隔离。
    支持属性访问、迭代操作和存储清理功能，确保多线程环境下数据访问的安全性。

    属性:
        __storage__ (dict): 嵌套字典存储结构，键为线程标识符，值为对应线程的数据字典
        __ident_func__ (callable): 获取当前线程/进程唯一标识符的函数
    """

    def __iter__(self):
        """
        获取当前线程/进程存储数据的迭代器。

        返回:
            iterator: 包含(key, value)元组的迭代器，若当前线程无存储数据则返回空迭代器

        处理流程:
            1. 获取当前线程唯一标识符
            2. 尝试返回对应存储字典的迭代器
            3. 捕获KeyError异常并返回空迭代器
        """
        ident = self.__ident_func__()
        try:
            return iter(list(self.__storage__[ident].items()))
        except KeyError:
            return iter([])

    def __release_local__(self):
        """
        释放当前线程/进程的本地存储空间。

        从存储字典中移除当前线程的标识符键值对，实现存储空间回收。
        该方法被clear()方法直接调用，也可在子类中单独调用。
        """
        self.__storage__.pop(self.__ident_func__(), None)

    def __getattr__(self, name):
        """
        获取线程局部变量的属性值。

        参数:
            name (str): 要获取的属性名称

        返回:
            any: 对应属性的值

        异常:
            AttributeError: 当指定属性不存在时抛出
        """
        ident = self.__ident_func__()
        try:
            return self.__storage__[ident][name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        """
        设置线程局部变量的属性值。

        参数:
            name (str): 要设置的属性名称
            value (any): 要设置的属性值

        异常:
            AttributeError: 当尝试修改只读属性(__storage__或__ident_func__)时抛出
        """
        if name in ("__storage__", "__ident_func__"):
            raise AttributeError(
                f"{self.__class__.__name__!r} object attribute '{name}' is read-only"
            )

        ident = self.__ident_func__()
        storage = self.__storage__
        if ident not in storage:
            storage[ident] = dict()
        storage[ident][name] = value

    def __delattr__(self, name):
        """
        删除线程局部变量的属性。

        参数:
            name (str): 要删除的属性名称

        异常:
            AttributeError: 当尝试删除只读属性或不存在的属性时抛出
        """
        if name in ("__storage__", "__ident_func__"):
            raise AttributeError(
                f"{self.__class__.__name__!r} object attribute '{name}' is read-only"
            )

        ident = self.__ident_func__()
        try:
            del self.__storage__[ident][name]
            if len(self.__storage__[ident]) == 0:
                self.__release_local__()
        except KeyError:
            raise AttributeError(name)

    def clear(self):
        """
        清空当前线程的所有局部存储数据。

        通过调用__release_local__()方法实现存储字典的完全释放，
        是释放线程资源的安全方式。
        """
        self.__release_local__()


local = Local()  # 创建Local类的实例
