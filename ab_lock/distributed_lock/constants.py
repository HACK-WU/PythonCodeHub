"""分布式锁模块的内置常量。

本模块刻意不引用任何外部业务常量（如 alarm_backends.constants.CONST_MINUTES），
以保证 distributed_lock 包的零业务耦合特性。
"""

# 锁的默认过期时间（秒），防止持锁方异常退出后锁永久占用
DEFAULT_TTL = 60
