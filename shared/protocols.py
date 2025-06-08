# shared/protocols.py
import json

# 요청 생성 (클라이언트 -> 서버)
def create_request(req_type: str, payload: dict) -> bytes:
    message = {"type": req_type, "payload": payload}
    return json.dumps(message).encode('utf-8')

# 응답 생성 (서버 -> 클라이언트)
def create_response(status: str, message: str, payload: dict = None) -> bytes:
    response = {"status": status, "message": message, "payload": payload or {}}
    return json.dumps(response).encode('utf-8')

# 메시지 파싱 (양쪽에서 사용)
def parse_message(data_bytes: bytes) -> dict:
    return json.loads(data_bytes.decode('utf-8'))