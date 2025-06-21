# shared/validators.py

import json
import os
from jsonschema import validate, ValidationError

from shared.message_types import MESSAGE_TYPE_SCHEMA_MAP

# 기본 스키마 폴더 (shared/schemas/)
SCHEMA_DIR = os.path.join(os.path.dirname(__file__), "schemas")

def load_schema(type_key: str) -> dict:
    """
    주어진 메시지 타입(type 또는 cmd)에 해당하는 JSON 스키마 파일을 로드
    """
    schema_file = MESSAGE_TYPE_SCHEMA_MAP.get(type_key)
    if not schema_file:
        raise ValueError(f"❌ 스키마 매핑이 존재하지 않음: '{type_key}'")

    schema_path = os.path.join(SCHEMA_DIR, schema_file)
    if not os.path.exists(schema_path):
        raise FileNotFoundError(f"❌ 스키마 파일을 찾을 수 없음: {schema_path}")

    with open(schema_path, encoding="utf-8") as f:
        return json.load(f)

def validate_message(json_data: dict) -> bool:
    """
    JSON 메시지가 해당 스키마에 맞는지 검증
    메시지 내부에 'type' 또는 'cmd' 필드를 반드시 포함해야 함
    """
    # 메시지 타입 키 추출
    type_key = json_data.get("type") or json_data.get("cmd")
    if not type_key:
        raise ValueError("❌ 메시지에 'type' 또는 'cmd' 필드가 없습니다.")

    # 해당 스키마 로드 및 검증
    schema = load_schema(type_key)

    try:
        validate(instance=json_data, schema=schema)
        return True
    except ValidationError as e:
        raise ValueError(f"❌ JSON 스키마 유효성 오류: {e.message}")
