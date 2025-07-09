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
