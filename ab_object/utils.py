def object_to_dict(obj):
    """
    python 对象递归转成字典
    """
    if isinstance(obj, dict):
        data = {}
        for k, v in list(obj.items()):
            data[k] = object_to_dict(v)
        return data
    elif hasattr(obj, "__iter__") and not isinstance(obj, str):
        return [object_to_dict(v) for v in obj]
    elif hasattr(obj, "__dict__"):
        data = {}
        for key in dir(obj):
            value = getattr(obj, key)
            if not key.startswith("_") and not callable(value):
                data[key] = object_to_dict(value)
        return data
    else:
        return obj
