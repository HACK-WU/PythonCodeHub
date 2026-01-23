"""
Tencent is pleased to support the open source community by making 蓝鲸智云 - 监控平台 (BlueKing - Monitor) available.
Copyright (C) 2017-2025 Tencent. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at http://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""

import pytest

from matcher import ConditionMatcher, filter_items, match


class TestConditionMatcher:
    """测试 ConditionMatcher 类"""

    def test_basic_eq_match(self):
        """测试基本的等于匹配"""
        conditions = [{"field": "ip", "op": "eq", "value": "10.0.0.1"}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"ip": "10.0.0.1"}) is True
        assert matcher.match({"ip": "10.0.0.2"}) is False

    def test_multiple_and_conditions(self):
        """测试多个 AND 条件"""
        conditions = [
            {"field": "ip", "op": "eq", "value": "10.0.0.1"},
            {"field": "env", "op": "eq", "value": "prod"},
        ]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"ip": "10.0.0.1", "env": "prod"}) is True
        assert matcher.match({"ip": "10.0.0.1", "env": "test"}) is False
        assert matcher.match({"ip": "10.0.0.2", "env": "prod"}) is False

    def test_or_conditions(self):
        """测试 OR 条件"""
        conditions = [
            {"field": "level", "op": "eq", "value": "error"},
            {"field": "level", "op": "eq", "value": "critical", "logic": "or"},
        ]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"level": "error"}) is True
        assert matcher.match({"level": "critical"}) is True
        assert matcher.match({"level": "info"}) is False

    def test_mixed_and_or_conditions(self):
        """测试混合 AND/OR 条件"""
        conditions = [
            {"field": "ip", "op": "eq", "value": "10.0.0.1"},
            {"field": "env", "op": "eq", "value": "prod"},
            {"field": "force", "op": "eq", "value": True, "logic": "or"},
        ]
        matcher = ConditionMatcher(conditions)

        # (ip == 10.0.0.1 AND env == prod) OR (force == True)
        assert matcher.match({"ip": "10.0.0.1", "env": "prod"}) is True
        assert matcher.match({"force": True}) is True
        assert matcher.match({"ip": "10.0.0.1", "env": "test"}) is False

    def test_in_operator(self):
        """测试 in 操作符"""
        conditions = [{"field": "ip", "op": "in", "value": ["10.0.0.1", "10.0.0.2", "10.0.0.3"]}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"ip": "10.0.0.1"}) is True
        assert matcher.match({"ip": "10.0.0.2"}) is True
        assert matcher.match({"ip": "10.0.0.4"}) is False

    def test_not_in_operator(self):
        """测试 not_in 操作符"""
        conditions = [{"field": "env", "op": "not_in", "value": ["test", "dev"]}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"env": "prod"}) is True
        assert matcher.match({"env": "test"}) is False
        assert matcher.match({"env": "dev"}) is False

    def test_neq_operator(self):
        """测试不等于操作符"""
        conditions = [{"field": "status", "op": "neq", "value": "disabled"}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"status": "active"}) is True
        assert matcher.match({"status": "disabled"}) is False

    def test_numeric_comparison(self):
        """测试数值比较操作符"""
        # 大于
        conditions = [{"field": "cpu", "op": "gt", "value": 80}]
        matcher = ConditionMatcher(conditions)
        assert matcher.match({"cpu": 90}) is True
        assert matcher.match({"cpu": 70}) is False

        # 大于等于
        conditions = [{"field": "cpu", "op": "gte", "value": 80}]
        matcher = ConditionMatcher(conditions)
        assert matcher.match({"cpu": 80}) is True
        assert matcher.match({"cpu": 79}) is False

        # 小于
        conditions = [{"field": "memory", "op": "lt", "value": 90}]
        matcher = ConditionMatcher(conditions)
        assert matcher.match({"memory": 85}) is True
        assert matcher.match({"memory": 95}) is False

        # 小于等于
        conditions = [{"field": "memory", "op": "lte", "value": 90}]
        matcher = ConditionMatcher(conditions)
        assert matcher.match({"memory": 90}) is True
        assert matcher.match({"memory": 91}) is False

    def test_include_operator(self):
        """测试子串包含操作符"""
        conditions = [{"field": "message", "op": "include", "value": "error"}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"message": "this is an error message"}) is True
        assert matcher.match({"message": "success"}) is False

    def test_regex_operator(self):
        """测试正则匹配操作符"""
        conditions = [{"field": "alert_name", "op": "regex", "value": "CPU.*过高"}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"alert_name": "CPU使用率过高"}) is True
        assert matcher.match({"alert_name": "内存使用率过高"}) is False

    def test_startswith_operator(self):
        """测试前缀匹配操作符"""
        conditions = [{"field": "path", "op": "startswith", "value": "/api/"}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"path": "/api/users"}) is True
        assert matcher.match({"path": "/web/index"}) is False

    def test_endswith_operator(self):
        """测试后缀匹配操作符"""
        conditions = [{"field": "filename", "op": "endswith", "value": ".log"}]
        matcher = ConditionMatcher(conditions)

        assert matcher.match({"filename": "app.log"}) is True
        assert matcher.match({"filename": "app.txt"}) is False

    def test_nested_field_path(self):
        """测试嵌套字段路径"""
        conditions = [
            {"field": "host.os_type", "op": "eq", "value": "linux"},
            {"field": "tags.env", "op": "eq", "value": "prod"},
        ]
        matcher = ConditionMatcher(conditions)

        data = {"host": {"os_type": "linux"}, "tags": {"env": "prod"}}
        assert matcher.match(data) is True

        data = {"host": {"os_type": "windows"}, "tags": {"env": "prod"}}
        assert matcher.match(data) is False

    def test_filter_method(self):
        """测试 filter 方法"""
        conditions = [{"field": "level", "op": "eq", "value": "error"}]
        matcher = ConditionMatcher(conditions)

        items = [
            {"id": 1, "level": "error"},
            {"id": 2, "level": "info"},
            {"id": 3, "level": "error"},
            {"id": 4, "level": "warning"},
        ]

        result = matcher.filter(items)
        assert len(result) == 2
        assert result[0]["id"] == 1
        assert result[1]["id"] == 3

    def test_first_method(self):
        """测试 first 方法"""
        conditions = [{"field": "status", "op": "eq", "value": "active"}]
        matcher = ConditionMatcher(conditions)

        items = [
            {"id": 1, "status": "inactive"},
            {"id": 2, "status": "active"},
            {"id": 3, "status": "active"},
        ]

        result = matcher.first(items)
        assert result is not None
        assert result["id"] == 2

        # 测试没有匹配的情况
        items = [{"id": 1, "status": "inactive"}]
        result = matcher.first(items)
        assert result is None

    def test_empty_conditions(self):
        """测试空条件（应该匹配所有）"""
        matcher = ConditionMatcher([])
        assert matcher.match({"any": "data"}) is True

    def test_missing_field(self):
        """测试字段不存在的情况"""
        conditions = [{"field": "nonexistent", "op": "eq", "value": "value"}]
        matcher = ConditionMatcher(conditions)

        # 字段不存在应该返回 False
        assert matcher.match({"other": "value"}) is False

    def test_get_jsonlogic_rule(self):
        """测试获取 JsonLogic 规则"""
        conditions = [
            {"field": "ip", "op": "eq", "value": "10.0.0.1"},
            {"field": "env", "op": "eq", "value": "prod"},
        ]
        matcher = ConditionMatcher(conditions)

        rule = matcher.get_jsonlogic_rule()
        assert "and" in rule or "==" in rule  # 应该包含逻辑操作符


class TestConvenienceFunctions:
    """测试便捷函数"""

    def test_match_function(self):
        """测试 match 快捷函数"""
        result = match({"ip": "10.0.0.1"}, [{"field": "ip", "op": "eq", "value": "10.0.0.1"}])
        assert result is True

        result = match({"ip": "10.0.0.2"}, [{"field": "ip", "op": "eq", "value": "10.0.0.1"}])
        assert result is False

    def test_filter_items_function(self):
        """测试 filter_items 快捷函数"""
        items = [
            {"id": 1, "level": "error"},
            {"id": 2, "level": "info"},
            {"id": 3, "level": "error"},
        ]

        result = filter_items(items, [{"field": "level", "op": "eq", "value": "error"}])
        assert len(result) == 2
        assert all(item["level"] == "error" for item in result)


class TestRealWorldScenarios:
    """测试真实场景"""

    def test_alert_dispatch_scenario(self):
        """测试告警分派场景"""
        # 模拟告警分派规则：
        # (IP 在列表中 AND 环境是生产) OR (告警级别是致命)
        conditions = [
            {"field": "ip", "op": "in", "value": ["10.0.0.1", "10.0.0.2"]},
            {"field": "env", "op": "eq", "value": "prod"},
            {"field": "level", "op": "eq", "value": "critical", "logic": "or"},
        ]
        matcher = ConditionMatcher(conditions)

        # 满足第一组条件
        alert1 = {"ip": "10.0.0.1", "env": "prod", "level": "warning"}
        assert matcher.match(alert1) is True

        # 满足第二组条件
        alert2 = {"ip": "10.0.0.3", "env": "test", "level": "critical"}
        assert matcher.match(alert2) is True

        # 都不满足
        alert3 = {"ip": "10.0.0.3", "env": "test", "level": "info"}
        assert matcher.match(alert3) is False

    def test_log_filtering_scenario(self):
        """测试日志过滤场景"""
        conditions = [
            {"field": "level", "op": "in", "value": ["error", "critical"]},
            {"field": "message", "op": "regex", "value": "(timeout|failed|exception)"},
        ]
        matcher = ConditionMatcher(conditions)

        logs = [
            {"level": "error", "message": "Connection timeout"},
            {"level": "info", "message": "Request successful"},
            {"level": "error", "message": "Invalid parameter"},
            {"level": "critical", "message": "Database connection failed"},
        ]

        result = matcher.filter(logs)
        # 应该匹配第1和第4条日志
        assert len(result) == 2

    def test_cmdb_host_filtering(self):
        """测试 CMDB 主机过滤场景"""
        conditions = [
            {"field": "host.os_type", "op": "eq", "value": "linux"},
            {"field": "host.cpu_cores", "op": "gte", "value": 8},
            {"field": "tags.env", "op": "in", "value": ["prod", "staging"]},
        ]
        matcher = ConditionMatcher(conditions)

        hosts = [
            {"host": {"os_type": "linux", "cpu_cores": 16}, "tags": {"env": "prod"}},
            {"host": {"os_type": "linux", "cpu_cores": 4}, "tags": {"env": "prod"}},
            {"host": {"os_type": "windows", "cpu_cores": 16}, "tags": {"env": "prod"}},
            {"host": {"os_type": "linux", "cpu_cores": 8}, "tags": {"env": "test"}},
        ]

        result = matcher.filter(hosts)
        assert len(result) == 1  # 只有第一台主机满足所有条件


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
