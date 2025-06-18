# shared/protocols.py

# ===== 명령어 바이트 상수 =====
PROCEED            = b'\x01'  # 상황 진행
IGNORE             = b'\x02'  # 무시
FIRE_REPORT        = b'\x03'  # 119 신고
POLICE_REPORT      = b'\x04'  # 112 신고
ILLEGAL_WARNING    = b'\x05'  # 위법 경고 (흡연 등)
DANGER_WARNING     = b'\x06'  # 위험 경고 (칼, 총 등)
EMERGENCY_WARNING  = b'\x07'  # 응급 경고 (쓰러짐 등)
CASE_CLOSED        = b'\x08'  # 사건 종료
MOVE_TO_A          = b'\x09'  # A 지역 이동
MOVE_TO_B          = b'\x0A'  # B 지역 이동
RETURN_TO_BASE     = b'\x0B'  # BASE 지역 복귀
GET_LOGS           = b'\x0C'  # 로그 전체 데이터 조회

# ===== 문자열 명령어 → 바이트 코드 매핑 =====
CMD_MAP = {
    "PROCEED":            PROCEED,
    "IGNORE":             IGNORE,
    "FIRE_REPORT":        FIRE_REPORT,
    "POLICE_REPORT":      POLICE_REPORT,
    "ILLEGAL_WARNING":    ILLEGAL_WARNING,
    "DANGER_WARNING":     DANGER_WARNING,
    "EMERGENCY_WARNING":  EMERGENCY_WARNING,
    "CASE_CLOSED":        CASE_CLOSED,
    "MOVE_TO_A":          MOVE_TO_A,
    "MOVE_TO_B":          MOVE_TO_B,
    "RETURN_TO_BASE":     RETURN_TO_BASE,
    "GET_LOGS":           GET_LOGS,
}

# ===== 바이트 코드 → 문자열 명령어 역매핑 =====
CMD_REVERSE_MAP = {v: k for k, v in CMD_MAP.items()}

# ===== (선택) 설명 딕셔너리 =====
CMD_DESCRIPTION = {
    "PROCEED":            "사용자가 상황 처리를 진행하기로 선택",
    "IGNORE":             "사용자가 별도 조치 없이 무시",
    "FIRE_REPORT":        "소방/응급 상황으로 119에 신고",
    "POLICE_REPORT":      "범죄 상황으로 112에 신고",
    "ILLEGAL_WARNING":    "위법(흡연 등) 요소에 대한 경고",
    "DANGER_WARNING":     "위험(칼, 총) 요소에 대한 경고",
    "EMERGENCY_WARNING":  "응급(쓰러짐 등) 요소에 대한 경고",
    "CASE_CLOSED":        "상황이 종료되어 사건을 마무리",
    "MOVE_TO_A":          "로봇이 A 지역으로 이동",
    "MOVE_TO_B":          "로봇이 B 지역으로 이동",
    "RETURN_TO_BASE":     "로봇이 BASE 지역으로 이동",
    "GET_LOGS":           "전체 로그 데이터를 요청",
}
