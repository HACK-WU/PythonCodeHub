"""集中存放分布式锁使用的 Lua 脚本。

将脚本提取到独立模块，避免在多个锁实现之间重复定义，
同时方便后续做 SCRIPT LOAD / EVALSHA 优化。
"""

# 校验 token → 删除 key 的原子脚本
# KEYS[1] = 锁 key
# ARGV[1] = 当前实例 token
# 返回 1 表示成功删除，0 表示 token 不匹配（锁已被他人持有或已过期）
RELEASE_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""

# 校验 token → 续期 TTL 的原子脚本（看门狗使用）
# KEYS[1] = 锁 key
# ARGV[1] = 当前实例 token
# ARGV[2] = 新的 TTL（毫秒）
# 返回 1 表示成功续期，0 表示 token 不匹配（锁已被他人持有或已过期）
RENEW_LUA = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("pexpire", KEYS[1], ARGV[2])
end
return 0
"""
