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

    return s
