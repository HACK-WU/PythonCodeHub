import re


def escape_query_string(query_string: str) -> str:
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
    value = re.sub(
        r'([+\-=&|><!(){}[\]^"~*?\\:\/ ])',
        lambda match: "\\" + match.group(0),
        query_string.strip(),
    )
    return value
