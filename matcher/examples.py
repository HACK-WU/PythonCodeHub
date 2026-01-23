"""
Tencent is pleased to support the open source community by making 蓝鲸智云 - 监控平台 (BlueKing - Monitor) available.
Copyright (C) 2017-2025 Tencent. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""

"""
维度匹配器使用示例

本文件演示了 ConditionMatcher 的各种使用场景。
"""

from matcher import ConditionMatcher, filter_items, match


def example_basic_usage():
    """示例1: 基本使用"""
    print("=" * 50)
    print("示例1: 基本使用")
    print("=" * 50)

    # 定义条件
    conditions = [
        {"field": "ip", "op": "eq", "value": "10.0.0.1"},
        {"field": "env", "op": "eq", "value": "prod"},
    ]

    # 创建匹配器
    matcher = ConditionMatcher(conditions)

    # 测试数据
    data1 = {"ip": "10.0.0.1", "env": "prod", "app": "api"}
    data2 = {"ip": "10.0.0.2", "env": "prod", "app": "web"}

    print("条件: IP=10.0.0.1 AND env=prod")
    print(f"数据1: {data1}")
    print(f"匹配结果: {matcher.match(data1)}")
    print(f"\n数据2: {data2}")
    print(f"匹配结果: {matcher.match(data2)}")
    print()


def example_or_conditions():
    """示例2: OR 条件"""
    print("=" * 50)
    print("示例2: OR 条件")
    print("=" * 50)

    conditions = [
        {"field": "level", "op": "eq", "value": "error"},
        {"field": "level", "op": "eq", "value": "critical", "logic": "or"},
    ]

    matcher = ConditionMatcher(conditions)

    test_data = [
        {"level": "error", "message": "Error occurred"},
        {"level": "critical", "message": "Critical issue"},
        {"level": "info", "message": "Info message"},
    ]

    print("条件: level=error OR level=critical")
    for data in test_data:
        result = matcher.match(data)
        print(f"数据: {data} -> 匹配: {result}")
    print()


def example_mixed_conditions():
    """示例3: 混合 AND/OR 条件"""
    print("=" * 50)
    print("示例3: 混合 AND/OR 条件")
    print("=" * 50)

    conditions = [
        {"field": "ip", "op": "in", "value": ["10.0.0.1", "10.0.0.2"]},
        {"field": "env", "op": "eq", "value": "prod"},
        {"field": "force", "op": "eq", "value": True, "logic": "or"},
    ]

    matcher = ConditionMatcher(conditions)

    test_data = [
        {"ip": "10.0.0.1", "env": "prod"},
        {"ip": "10.0.0.3", "env": "prod"},
        {"force": True},
        {"ip": "10.0.0.1", "env": "test"},
    ]

    print("条件: (ip IN [10.0.0.1, 10.0.0.2] AND env=prod) OR force=True")
    for data in test_data:
        result = matcher.match(data)
        print(f"数据: {data} -> 匹配: {result}")
    print()


def example_operators():
    """示例4: 各种操作符"""
    print("=" * 50)
    print("示例4: 各种操作符")
    print("=" * 50)

    # in 操作符
    print("in 操作符:")
    conditions = [{"field": "status", "op": "in", "value": ["active", "running"]}]
    matcher = ConditionMatcher(conditions)
    print(f"  {{'status': 'active'}} -> {matcher.match({'status': 'active'})}")
    print(f"  {{'status': 'stopped'}} -> {matcher.match({'status': 'stopped'})}")

    # 数值比较
    print("\n数值比较 (gt, gte, lt, lte):")
    conditions = [{"field": "cpu", "op": "gte", "value": 80}]
    matcher = ConditionMatcher(conditions)
    print(f"  {{'cpu': 90}} -> {matcher.match({'cpu': 90})}")
    print(f"  {{'cpu': 70}} -> {matcher.match({'cpu': 70})}")

    # 正则匹配
    print("\n正则匹配:")
    conditions = [{"field": "alert_name", "op": "regex", "value": "CPU.*过高"}]
    matcher = ConditionMatcher(conditions)
    print(f"  {{'alert_name': 'CPU使用率过高'}} -> {matcher.match({'alert_name': 'CPU使用率过高'})}")
    print(f"  {{'alert_name': '内存使用率过高'}} -> {matcher.match({'alert_name': '内存使用率过高'})}")

    # 前缀/后缀匹配
    print("\n前缀匹配:")
    conditions = [{"field": "path", "op": "startswith", "value": "/api/"}]
    matcher = ConditionMatcher(conditions)
    print(f"  {{'path': '/api/users'}} -> {matcher.match({'path': '/api/users'})}")
    print(f"  {{'path': '/web/index'}} -> {matcher.match({'path': '/web/index'})}")
    print()


def example_nested_fields():
    """示例5: 嵌套字段"""
    print("=" * 50)
    print("示例5: 嵌套字段")
    print("=" * 50)

    conditions = [
        {"field": "host.os_type", "op": "eq", "value": "linux"},
        {"field": "host.cpu_cores", "op": "gte", "value": 8},
        {"field": "tags.env", "op": "eq", "value": "prod"},
    ]

    matcher = ConditionMatcher(conditions)

    data = {
        "host": {"os_type": "linux", "cpu_cores": 16, "memory": 32},
        "tags": {"env": "prod", "team": "backend"},
    }

    print("条件: host.os_type=linux AND host.cpu_cores>=8 AND tags.env=prod")
    print(f"数据: {data}")
    print(f"匹配结果: {matcher.match(data)}")
    print()


def example_filter_list():
    """示例6: 过滤列表"""
    print("=" * 50)
    print("示例6: 过滤列表")
    print("=" * 50)

    alerts = [
        {"id": 1, "ip": "10.0.0.1", "level": "error", "message": "Connection timeout"},
        {"id": 2, "ip": "10.0.0.2", "level": "info", "message": "Request successful"},
        {"id": 3, "ip": "10.0.0.1", "level": "critical", "message": "Service down"},
        {"id": 4, "ip": "10.0.0.3", "level": "warning", "message": "High CPU usage"},
    ]

    conditions = [
        {"field": "ip", "op": "eq", "value": "10.0.0.1"},
        {"field": "level", "op": "in", "value": ["error", "critical"]},
    ]

    matcher = ConditionMatcher(conditions)
    result = matcher.filter(alerts)

    print("原始告警列表:")
    for alert in alerts:
        print(f"  {alert}")

    print("\n条件: ip=10.0.0.1 AND level IN [error, critical]")
    print("过滤结果:")
    for alert in result:
        print(f"  {alert}")
    print()


def example_convenience_functions():
    """示例7: 便捷函数"""
    print("=" * 50)
    print("示例7: 便捷函数")
    print("=" * 50)

    # 使用 match 函数
    print("使用 match() 快捷函数:")
    result = match({"ip": "10.0.0.1", "env": "prod"}, [{"field": "ip", "op": "eq", "value": "10.0.0.1"}])
    print(f"  匹配结果: {result}")

    # 使用 filter_items 函数
    print("\n使用 filter_items() 快捷函数:")
    items = [{"id": 1, "status": "active"}, {"id": 2, "status": "inactive"}, {"id": 3, "status": "active"}]

    result = filter_items(items, [{"field": "status", "op": "eq", "value": "active"}])
    print(f"  过滤结果: {result}")
    print()


def example_alert_dispatch():
    """示例8: 告警分派场景"""
    print("=" * 50)
    print("示例8: 告警分派场景")
    print("=" * 50)

    # 分派规则: (IP在白名单 AND 环境是生产) OR (告警级别是致命)
    conditions = [
        {"field": "ip", "op": "in", "value": ["10.0.0.1", "10.0.0.2", "10.0.0.3"]},
        {"field": "env", "op": "eq", "value": "prod"},
        {"field": "level", "op": "eq", "value": "critical", "logic": "or"},
    ]

    matcher = ConditionMatcher(conditions)

    alerts = [
        {"id": 1, "ip": "10.0.0.1", "env": "prod", "level": "warning", "desc": "CPU高"},
        {"id": 2, "ip": "10.0.0.5", "env": "test", "level": "critical", "desc": "服务宕机"},
        {"id": 3, "ip": "10.0.0.5", "env": "test", "level": "info", "desc": "正常"},
        {"id": 4, "ip": "10.0.0.2", "env": "prod", "level": "error", "desc": "内存告警"},
    ]

    print("分派规则: (IP在[10.0.0.1-3] AND env=prod) OR level=critical")
    print("\n告警列表及分派结果:")
    for alert in alerts:
        matched = matcher.match(alert)
        status = "✓ 分派" if matched else "✗ 跳过"
        print(f"  {status} - ID:{alert['id']}, IP:{alert['ip']}, Env:{alert['env']}, Level:{alert['level']}")
    print()


def example_get_jsonlogic_rule():
    """示例9: 查看转换后的 JsonLogic 规则"""
    print("=" * 50)
    print("示例9: 查看 JsonLogic 规则")
    print("=" * 50)

    conditions = [
        {"field": "ip", "op": "eq", "value": "10.0.0.1"},
        {"field": "env", "op": "eq", "value": "prod"},
        {"field": "force", "op": "eq", "value": True, "logic": "or"},
    ]

    matcher = ConditionMatcher(conditions)

    print("原始条件配置:")
    for cond in conditions:
        print(f"  {cond}")

    print("\n转换后的 JsonLogic 规则:")
    import json

    print(json.dumps(matcher.get_jsonlogic_rule(), indent=2, ensure_ascii=False))
    print()


def main():
    """运行所有示例"""
    examples = [
        example_basic_usage,
        example_or_conditions,
        example_mixed_conditions,
        example_operators,
        example_nested_fields,
        example_filter_list,
        example_convenience_functions,
        example_alert_dispatch,
        example_get_jsonlogic_rule,
    ]

    for example in examples:
        example()
        input("按回车继续下一个示例...")
        print("\n")


if __name__ == "__main__":
    main()
