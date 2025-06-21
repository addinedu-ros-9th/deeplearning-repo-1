# shared/message_types.py

# 메시지 유형 상수 (JSON 기반 or JSON+Binary 혼합)
LOGIN_REQUEST         = "login_request"
LOGIN_RESPONSE        = "login_response"
GET_LOGS              = "get_logs"
LOG_LIST_RESPONSE     = "log_list_response"
DETECTION_RESULT      = "detection_result"
MERGED_RESULT         = "merged_result"
FRAME_HEADER          = "frame_header"

# 메시지 설명
MESSAGE_TYPE_DESCRIPTIONS = {
    LOGIN_REQUEST: "로그인 인증 요청",
    LOGIN_RESPONSE: "로그인 결과 응답",
    GET_LOGS: "로그 조회 요청",
    LOG_LIST_RESPONSE: "로그 목록 응답",
    DETECTION_RESULT: "AI 분석 결과",
    MERGED_RESULT: "AI 분석 + 영상 통합 결과",
    FRAME_HEADER: "프레임 메타정보 헤더 (JSON + Binary 혼합용)"
}

# 메시지 타입 → JSON 스키마 파일명 매핑
MESSAGE_TYPE_SCHEMA_MAP = {
    LOGIN_REQUEST: "login_request.schema.json",
    LOGIN_RESPONSE: "login_response.schema.json",
    GET_LOGS: "get_logs.schema.json",
    LOG_LIST_RESPONSE: "log_list_response.schema.json",
    DETECTION_RESULT: "detection_result.schema.json",
    MERGED_RESULT: "merged_result.schema.json",
    FRAME_HEADER: "frame_header.schema.json"
}
