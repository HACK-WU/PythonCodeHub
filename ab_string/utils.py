import inflection


def camel_to_underscore(camel_str):
    """
    将驼峰式字符串转换为下划线格式。
    example:
    >>> camel_to_underscore("CamelCase")
    'camel_case'
    >>> camel_to_underscore("CamelCaseString")
    'camel_case_string'
    >>> camel_to_underscore("CamelCaseStringWithNumber123")
    'camel_case_string_with_number123'
    >>> camel_to_underscore("CamelCaseStringWithID")
    'camel_case_string_with_id'
    """
    return inflection.underscore(camel_str)


def strip_outer_quotes(s):
    """安全移除外层引号

    example usage:
    >>> strip_outer_quotes("aa ")
    'aa'
    >>> strip_outer_quotes("'bb'")
    'bb'
    >>> strip_outer_quotes("\"'mixed'\"")
    'mixed'
    """
    if not isinstance(s, str):
        return s
    s = s.strip()

    while len(s) > 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        s = s[1:-1]
        s = s.strip()
    return s
