"""
缓存核心模块

从 drf_resource.resources.cache 抽取的缓存核心实现，
去除所有外部强依赖（Django / drf_resource / ab_hash），
通过可插拔后端和用户解析器实现框架无关。

核心组件:
    - CacheTypeItem: 缓存类型定义
    - BaseCacheType: 缓存类型基类
    - DefaultCacheType: 默认缓存类型
    - BaseUsingCache: 使用缓存基类
    - DefaultUsingCache: 默认使用缓存实现
    - using_cache: 缓存装饰器（DefaultUsingCache 别名）
    - CacheResource: 支持缓存的 Resource Mixin
    - configure: 全局配置缓存后端和用户信息提供者
"""

import abc
import functools
import hashlib
import json
import logging
import zlib
from collections.abc import Callable
from typing import Any

from ab_cache.using_cache.backends import BaseCacheBackend

logger = logging.getLogger(__name__)


# ============================================================================
# 工具函数（内置，不依赖外部包）
# ============================================================================

_BASE_TYPES = (str, int, float, bool, type(None))


def count_md5(
    content: Any,
    dict_sort: bool = True,
    list_sort: bool = True,
    _path_ids: tuple = None,
) -> str:
    """
    安全计算结构化数据 MD5，自动处理深度嵌套与循环引用。

    参数:
        content: 待计算 MD5 的任意类型数据
        dict_sort: 是否对字典的键进行排序
        list_sort: 是否对列表/元组/集合进行排序
        _path_ids: 内部参数，用于检测循环引用

    返回值:
        str: 32 位十六进制 MD5 哈希值
    """
    if _path_ids is None:
        _path_ids = ()

    obj_id = id(content)

    if obj_id in _path_ids:
        return "circular_ref_hash"

    if isinstance(content, _BASE_TYPES):
        return f"base:{hash(content)}"

    hasher = hashlib.md5()

    try:
        _path_ids = _path_ids + (obj_id,)

        if isinstance(content, dict):
            keys = sorted(content) if dict_sort else content.keys()
            for k in keys:
                hasher.update(f"k:{k!s}|v:".encode())
                hasher.update(count_md5(content[k], dict_sort, list_sort, _path_ids).encode())

        elif isinstance(content, list | tuple | set):
            items = sorted(content, key=_stable_order_key) if list_sort else content
            for item in items:
                hasher.update(b"item:")
                hasher.update(count_md5(item, dict_sort, list_sort, _path_ids).encode())
                hasher.update(b"|")

        elif callable(content):
            hasher.update(f"fn:{content.__name__}".encode())

        else:
            hasher.update(f"obj:{type(content).__name__}".encode())

        return hasher.hexdigest()

    finally:
        _path_ids = _path_ids[:-1]


def _stable_order_key(x: Any) -> str:
    """生成类型安全的排序键，规避不同类型间的比较冲突"""
    type_flag = {str: "s", int: "i", float: "f", bool: "b"}.get(type(x), f"o_{type(x).__name__[0]}")
    return f"{type_flag}:{x!r}"


# ============================================================================
# 缓存类型定义
# ============================================================================


class CacheTypeItem:
    """
    缓存类型定义
    """

    def __init__(self, key, timeout, user_related=None, label=""):
        """
        :param key: 缓存名称
        :param timeout: 缓存超时，单位：s
        :param user_related: 是否用户相关
        :param label: 详细说明
        """
        self.key = key
        self.timeout = timeout
        self.label = label
        self.user_related = user_related

    def __call__(self, timeout):
        return CacheTypeItem(self.key, timeout, self.user_related, self.label)


class BaseCacheType:
    """
    缓存类型基类

    使用示例:
        class MyCacheType(BaseCacheType):
            user = CacheTypeItem(key="user", timeout=60, user_related=True)
            backend = CacheTypeItem(key="backend", timeout=60, user_related=False)
    """

    pass


class DefaultCacheType(BaseCacheType):
    user = CacheTypeItem(key="user", timeout=60, user_related=True)
    backend = CacheTypeItem(key="backend", timeout=60, user_related=False)


# ============================================================================
# 缓存装饰器
# ============================================================================


class BaseUsingCache:
    """
    使用缓存基类
    """

    def __call__(self, target_fun: Callable) -> Callable:
        """
        返回经过缓存装饰的函数。
        """

        @functools.wraps(target_fun)
        def cached_wrapper(*args, **kwargs):
            return_value = self._cached(target_fun, args, kwargs)
            return return_value

        @functools.wraps(target_fun)
        def refresh_wrapper(*args, **kwargs):
            return_value = self._refresh(target_fun, args, kwargs)
            return return_value

        @functools.wraps(target_fun)
        def cacheless_wrapper(*args, **kwargs):
            return_value = self._cacheless(target_fun, args, kwargs)
            return return_value

        # 为函数设置各种调用模式
        default_wrapper = cached_wrapper
        default_wrapper.cached = cached_wrapper
        default_wrapper.refresh = refresh_wrapper
        default_wrapper.cacheless = cacheless_wrapper

        return default_wrapper

    def _cached(self, target_fun, args, kwargs):
        raise NotImplementedError

    def _refresh(self, target_fun, args, kwargs):
        raise NotImplementedError

    def _cacheless(self, target_fun, args, kwargs):
        raise NotImplementedError


class DefaultUsingCache(BaseUsingCache):
    min_length = 15
    preset = 6
    key_prefix = "cache"
    default_user_info = "backend"
    # 哨兵值，用于区分"缓存不存在"和"缓存的值是None"
    _CACHE_MISS = object()

    def __init__(
        self,
        cache_type: CacheTypeItem,
        backend_cache_type: CacheTypeItem | None = None,
        user_related: bool | None = None,
        compress: bool | None = True,
        cache_write_trigger: Callable[[Any], bool] = lambda res: True,
        func_key_generator: Callable[[Callable], str] | None = None,
        cache_backend: BaseCacheBackend | None = None,
        user_info_provider: Callable[[], str] | None = None,
    ) -> None:
        """
        :param cache_type: 缓存类型
        :param backend_cache_type: 后台缓存类型，当 username=="backend" 时优先使用
        :param user_related: 是否与用户关联
        :param compress: 是否进行压缩
        :param cache_write_trigger: 缓存函数，当函数返回 true 时，则进行缓存
        :param func_key_generator: 函数标识 key 的生成逻辑
        :param cache_backend: 缓存后端实例，若为 None 则使用全局默认后端
        :param user_info_provider: 用户信息提供函数，若为 None 则使用全局默认逻辑
        """
        self.cache_type = cache_type
        self.backend_cache_type = backend_cache_type
        self.compress = compress
        self.cache_write_trigger = cache_write_trigger
        self.func_key_generator = func_key_generator or self._default_func_key_generator
        self._cache_backend = cache_backend
        self._user_info_provider = user_info_provider

        # 先看用户是否提供了 user_related 参数
        # 若无，则查看 cache_type 是否提供了 user_related 参数
        # 若都没有定义，则 user_related 默认为 False
        if user_related is not None:
            self.user_related = user_related
        elif getattr(cache_type, "user_related", None) is not None:
            self.user_related = self.cache_type.user_related
        else:
            self.user_related = False

    @property
    def cache_backend(self) -> BaseCacheBackend:
        """懒加载缓存后端"""
        if self._cache_backend is None:
            self._cache_backend = _get_default_cache_backend()
        return self._cache_backend

    def _refresh(self, target_fun: Callable, args: tuple, kwargs: dict) -> Any:
        """
        【强制刷新模式】
        不使用缓存的数据，将函数执行返回结果回写缓存
        """
        user_info = self.get_user_info()
        using_cache_type = self.get_using_cache_type(user_info)
        cache_key = self.generate_cache_key(target_fun, args, kwargs, user_info, using_cache_type)

        return_value = self._cacheless(target_fun, args, kwargs)

        if cache_key and using_cache_type and self.cache_write_trigger(return_value):
            self.set_value(cache_key, return_value, using_cache_type.timeout)

        return return_value

    def _cacheless(self, target_fun: Callable, args: tuple, kwargs: dict) -> Any:
        """
        【忽略缓存模式】
        忽略缓存机制，直接执行函数，返回结果不回写缓存
        """
        return target_fun(*args, **kwargs)

    def _cached(self, target_fun: Callable, args: tuple, kwargs: dict) -> Any:
        """
        【默认缓存模式】
        先检查缓存是否存在
        若存在，则直接返回缓存内容
        若不存在，则执行函数，并将结果回写到缓存中
        """
        if self.is_use_cache():
            cache_key = self.generate_cache_key(target_fun, args, kwargs)
        else:
            cache_key = None

        if cache_key:
            # 使用哨兵值来区分"缓存不存在"和"缓存值是None"
            return_value = self.get_value(cache_key, default=self._CACHE_MISS)

            if return_value is self._CACHE_MISS:
                # 缓存不存在，需要刷新
                return_value = self._refresh(target_fun, args, kwargs)
        else:
            return_value = self._cacheless(target_fun, args, kwargs)
        return return_value

    def is_use_cache(self) -> bool:
        """是否使用缓存"""
        return True

    @staticmethod
    def _default_func_key_generator(func: Callable) -> str:
        """
        默认的函数 key 生成器，安全地处理各种可调用对象。
        """
        # 优先使用 __module__ 和 __name__
        if hasattr(func, "__module__") and hasattr(func, "__name__"):
            return f"{func.__module__}.{func.__name__}"
        # 对于类实例（如 Resource），使用类名
        elif hasattr(func, "__class__"):
            cls = func.__class__
            if hasattr(cls, "__module__") and hasattr(cls, "__name__"):
                return f"{cls.__module__}.{cls.__name__}"
        # 兜底：使用类型名称
        return f"{type(func).__name__}"

    def get_user_info(self) -> str:
        """
        运行时动态获取用户信息。
        优先使用实例级 user_info_provider，
        其次使用全局默认 user_info_provider，
        最后回退到 default_user_info。
        """
        if self._user_info_provider is not None:
            try:
                return self._user_info_provider()
            except Exception as e:
                logger.error(f"get user info from provider error: {e}")
                return self.default_user_info

        username = self.default_user_info
        if self.user_related:
            try:
                username = _get_default_user_info()
            except Exception as e:
                logger.error(f"get user info error: {e}")
                username = self.default_user_info
        return username

    def get_using_cache_type(self, user_info: str | None = None) -> CacheTypeItem | None:
        """
        根据当前用户获取适当的缓存类型。

        首先检查当前用户是否为 'backend'，如果是，则根据
        backend_cache_type 或 cache_type 属性确定缓存类型。
        """
        if user_info is None:
            user_info = self.get_user_info()

        using_cache_type = self.cache_type

        if user_info == self.default_user_info:
            using_cache_type = self.backend_cache_type or self.cache_type

        if using_cache_type:
            if not isinstance(using_cache_type, CacheTypeItem):
                raise TypeError("param 'cache_type' must be an instance of <ab_cache.using_cache.cache.CacheTypeItem>")

        return using_cache_type

    def generate_cache_key(
        self,
        target_fun: Callable,
        args: tuple,
        kwargs: dict,
        user_info: str | None = None,
        using_cache_type: CacheTypeItem | None = None,
    ) -> str | None:
        """
        生成缓存 key。
        运行时动态获取用户信息和缓存类型，确保每次调用生成正确的缓存 key。

        :param target_fun: 目标函数
        :param args: 位置参数
        :param kwargs: 关键字参数
        :param user_info: 用户信息（可选，避免重复获取）
        :param using_cache_type: 缓存类型（可选，避免重复获取）
        """
        if user_info is None:
            user_info = self.get_user_info()
        if using_cache_type is None:
            using_cache_type = self.get_using_cache_type()

        if using_cache_type:
            return (
                f"{self.key_prefix}:{using_cache_type.key}:{self.func_key_generator(target_fun)}"
                f":{count_md5(args)}:{count_md5(kwargs)}:{user_info}"
            )

        return None

    def get_value(self, cache_key: str, default: Any = None) -> Any:
        value = self.cache_backend.get(cache_key)

        if value is None:
            return default

        if self.compress:
            # 尝试先解压（长值被 zlib 压缩过）
            # 短值可能只有 JSON 序列化而未经 zlib 压缩
            decompressed = False
            if isinstance(value, bytes):
                try:
                    value = zlib.decompress(value).decode("utf-8")
                    decompressed = True
                except (zlib.error, TypeError):
                    # 可能是未压缩的 bytes
                    try:
                        value = value.decode("utf-8")
                    except (UnicodeDecodeError, AttributeError):
                        pass

            # 反序列化 JSON
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as e:
                    if decompressed:
                        logger.warning(f"Failed to deserialize cache value for key {cache_key}: {e}")
                        return default

        return value

    def set_value(self, key, value, timeout=60) -> bool:
        if self.compress:
            try:
                value = json.dumps(value)
            except Exception:
                logger.exception(f"[Cache]不支持序列化的类型: {type(value)}")
                return False

            if len(value) > self.min_length:
                value = zlib.compress(value.encode("utf-8"))  # noqa

        try:
            self.cache_backend.set(key, value, timeout)
        except Exception as e:
            # 缓存出错不影响主流程
            logger.exception(f"存缓存[key:{key}]时报错：{e}\n value: {value!r}")
            return False
        return True


# 默认缓存装饰器
using_cache = DefaultUsingCache


# ============================================================================
# CacheResource 类
# ============================================================================


class CacheResource(metaclass=abc.ABCMeta):
    """
    支持缓存的 resource，开发环境下缓存默认不生效。

    注意：此类设计为 Mixin，应与 Resource 基类一起使用。
    实际使用时继承顺序应为：class MyResource(CacheResource, Resource)

    属性:
        cache_type: 缓存类型，启用缓存需要设置此属性或 backend_cache_type 属性
        backend_cache_type: 后台缓存类型，当 username=="backend" 时优先使用
        cache_user_related: 缓存是否与用户关联
        cache_compress: 是否使用压缩（默认 True）

    使用示例:
        class MyResource(CacheResource, Resource):
            cache_type = CacheTypeItem(timeout=60)

            def perform_request(self, validated_request_data):
                return {"data": "result"}
    """

    # 缓存类型，启用缓存需要设置 cache_type 或 backend_cache_type 属性
    cache_type = None
    # 后台缓存类型，当 username=="backend" 时，缓存类型优先使用 backend_cache_type
    backend_cache_type = None
    # 缓存是否与用户关联，cache_user_related=False 时，默认 username="backend"
    cache_user_related = None
    # 是否使用压缩
    cache_compress = True

    def __init__(self, *args, **kwargs):
        # 若 cache_type 为 None 则视为关闭缓存功能
        if self._need_cache_wrap():
            self._wrap_request()
        super().__init__(*args, **kwargs)

    def _need_cache_wrap(self):
        """
        判断是否需要缓存装饰器包装的函数。
        """
        need_cache = False

        if self.cache_type is not None:
            if not isinstance(self.cache_type, CacheTypeItem):
                raise TypeError("param 'cache_type' must be aninstance of <ab_cache.using_cache.cache.CacheTypeItem>")
            need_cache = True

        if self.backend_cache_type is not None:
            if not isinstance(self.backend_cache_type, CacheTypeItem):
                raise TypeError("param 'cache_type' must be aninstance of <ab_cache.using_cache.cache.CacheTypeItem>")
            need_cache = True

        return need_cache

    def _wrap_request(self):
        """
        将原有的 request 方法替换为支持缓存的 request 方法
        """

        def func_key_generator(resource):
            key = f"{resource.__self__.__class__.__module__}.{resource.__self__.__class__.__name__}"
            return key

        self.request = using_cache(
            cache_type=self.cache_type,
            backend_cache_type=self.backend_cache_type,
            user_related=self.cache_user_related,
            compress=self.cache_compress,
            cache_write_trigger=self.cache_write_trigger,
            func_key_generator=func_key_generator,
        )(self.request)

    def cache_write_trigger(self, res):
        """
        缓存写入触发条件
        """
        return True


# ============================================================================
# 全局默认后端 & 用户解析 —— 延迟初始化，按需配置
# ============================================================================

_default_cache_backend: BaseCacheBackend | None = None
_default_user_info_provider: Callable[[], str] | None = None


def configure(
    cache_backend: BaseCacheBackend | None = None,
    user_info_provider: Callable[[], str] | None = None,
) -> None:
    """
    全局配置 ab_cache.using_cache 的默认后端和用户信息提供者。

    :param cache_backend: 缓存后端实例，实现 BaseCacheBackend 接口
    :param user_info_provider: 返回当前用户标识的函数

    使用示例:
        from ab_cache.using_cache import configure
        from ab_cache.using_cache.backends import DictCacheBackend

        configure(
            cache_backend=DictCacheBackend(),
            user_info_provider=lambda: "current_user",
        )
    """
    global _default_cache_backend, _default_user_info_provider
    if cache_backend is not None:
        _default_cache_backend = cache_backend
    if user_info_provider is not None:
        _default_user_info_provider = user_info_provider


def _get_default_cache_backend() -> BaseCacheBackend:
    """获取全局默认缓存后端"""
    global _default_cache_backend
    if _default_cache_backend is not None:
        return _default_cache_backend

    raise RuntimeError(
        "未配置缓存后端。请在使用前调用 ab_cache.using_cache.configure(cache_backend=...) 设置缓存后端实例。"
    )


def _get_default_user_info() -> str:
    """获取全局默认用户信息"""
    if _default_user_info_provider is not None:
        return _default_user_info_provider()

    raise RuntimeError(
        "未配置用户信息提供者。请在使用前调用 "
        "ab_cache.using_cache.configure(user_info_provider=...) "
        "设置用户信息提供函数。"
    )
