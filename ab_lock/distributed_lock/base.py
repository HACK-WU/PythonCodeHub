"""分布式锁基类。"""

from .constants import DEFAULT_TTL


class BaseLock:
    """分布式锁抽象基类，定义统一的接口与上下文管理协议。

    职责：
    1. 统一构造参数（name / ttl）
    2. 声明 acquire / release 抽象方法，由子类实现具体加锁与释放逻辑
    3. 提供 __enter__ / __exit__ 协议，支持 with 语句自动加锁/释放
    """

    def __init__(self, name: str, ttl: int | None = None):
        """初始化锁。

        参数:
            name: 锁的唯一标识名称，用于在存储后端区分不同的锁
            ttl:  锁的过期时间（秒），默认 DEFAULT_TTL（60 秒），
                  防止持锁方异常退出后锁永久占用
        """
        self.name = name
        self.ttl = ttl or DEFAULT_TTL

    def acquire(self, _wait=None):
        """尝试获取锁，子类必须实现。"""
        raise NotImplementedError

    def release(self):
        """释放锁，子类必须实现。"""
        raise NotImplementedError

    def __enter__(self):
        """进入 with 代码块时自动获取锁，返回锁实例本身。

        异常:
            TimeoutError: 加锁失败时抛出，避免在未持锁的情况下执行临界区代码
        """
        if not self.acquire():
            raise TimeoutError(f"Failed to acquire lock: {self.name}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """退出 with 代码块时自动释放锁，无论是否发生异常。"""
        self.release()
