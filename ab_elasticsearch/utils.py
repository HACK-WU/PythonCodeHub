import re


def escape_query_string(query_string: str | list, many=False) -> str | list:
    r"""
     '+ - = && || > < ! ( ) { } [ ] ^ " ~ * ? : \ /' 等字符在query string中具有特殊含义,
     需要转义
    参考文档: https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-query-string-query

    example:
        >>> escape_query_string("hello world")
        'hello\\ world'
        >>> escape_query_string("hello world +")
        'hello\\ world\\ \\+'
        >>> escape_query_string("hello world -")
        'hello\\ world\\ \\-'
        >>> escape_query_string("hello world =")
        'hello\\ world\\ \\='

    :param query_string: 需要转义的查询字符串
    :return: 转义后的查询字符串
    """
    if many is True and not isinstance(query_string, list):
        query_string = [query_string]

    regex = r'([+\-=&|><!(){}[\]^"~*?\\:\/ ])'
    special_chars = re.compile(regex)
    escaped_special_chars = re.compile(rf"\\({regex})")

    def escape_char(s):
        if not isinstance(s, str):
            return s

        # 避免双重转义:先移除已有转义
        s = escaped_special_chars.sub(r"\1", s)

        return special_chars.sub(r"\\\1", str(s))

    if not many:
        return escape_char(query_string)
    return [escape_char(value) for value in query_string]
