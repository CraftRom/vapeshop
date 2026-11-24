"""`extra` keys must not collide with LogRecord attributes.

logging raises KeyError for them at runtime, so a successful XLSX import was
reported as interrupted because its summary used the key `created`.
"""
import ast
import logging
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
RESERVED = set(vars(logging.LogRecord('n', 0, 'p', 0, 'm', None, None))) | {'message', 'asctime'}


def test_no_log_call_passes_a_reserved_extra_key():
    offenders = []
    for path in BACKEND.rglob('*.py'):
        if {'qa', 'tests_pytest', '__pycache__'} & set(path.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.keyword) and node.arg == 'extra' and isinstance(node.value, ast.Dict):
                offenders += [f'{path.relative_to(BACKEND)}: {key.value}' for key in node.value.keys
                              if isinstance(key, ast.Constant) and key.value in RESERVED]
    assert offenders == []
