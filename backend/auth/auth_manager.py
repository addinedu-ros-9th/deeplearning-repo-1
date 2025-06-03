# backend/auth/auth_manager.py

import mysql.connector

class AuthManager:
    def __init__(self, db_config: dict):
        try:
            self.conn = mysql.connector.connect(**db_config)
            self.cursor = self.conn.cursor()
            print("[✅ DB 연결 성공]") # DB 연결 성공 메시지
        except mysql.connector.Error as err:
            print(f"[❌ DB 연결 실패] {err}") # DB 연결 실패 메시지
            raise

    # 사용자 인증 (id와 password만 사용)
    def verify_user(self, user_id: str, password: str):
        # SQL 쿼리: 'password'만 조회
        query = "SELECT password FROM users WHERE id = %s"
        self.cursor.execute(query, (user_id,))
        row = self.cursor.fetchone()
        if row:
            stored_password = row[0] # 비밀번호만 조회하므로 첫 번째 요소 (인덱스 0)
            if stored_password == password: # 현재는 평문 비교, 보안을 위해 해싱 필요
                print(f"[✅ 로그인 성공] {user_id}") # 로그인 성공 메시지
                return True # 성공 시 True 반환
            else:
                print(f"[⚠️ 비밀번호 불일치] {user_id}") # 비밀번호 불일치 메시지
        else:
            print(f"[❌ 사용자 없음] {user_id}") # 사용자 없음 메시지

        return False # 로그인 실패 시 False 반환

    # 연결 종료
    def close(self):
        self.cursor.close()
        self.conn.close()