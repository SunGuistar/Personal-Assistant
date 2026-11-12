"""晨报 LLM 输出的 JSON 对象契约；不将非法输出静默视为正文。"""
import json


def _reject_constant(value):
    raise ValueError("non-standard JSON constant")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_json_object(content: str) -> dict:
    if not isinstance(content, str):
        raise ValueError("模型输出必须为有效 JSON 对象")
    try:
        result = json.loads(content, parse_constant=_reject_constant, object_pairs_hook=_unique_object)
    except ValueError:
        raise ValueError("模型输出必须为有效 JSON 对象") from None
    if not isinstance(result, dict):
        raise ValueError("模型输出必须为 JSON 对象")
    return result
