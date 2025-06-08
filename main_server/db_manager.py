# main_server/db_manager.py
import mysql.connector

class DBManager:
    def __init__(self, db_config: dict):
        self.db_config = db_config

    def _get_connection(self):
        return mysql.connector.connect(**self.db_config)

    def verify_user(self, user_id: str, password: str) -> bool:
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            query = "SELECT password FROM users WHERE id = %s"
            cursor.execute(query, (user_id,))
            row = cursor.fetchone()
            if row and row[0] == password:
                print(f"[DB] '{user_id}' 인증 성공")
                return True
            print(f"[DB] '{user_id}' 인증 실패")
            return False
        except mysql.connector.Error as err:
            print(f"[DB 오류] {err}")
            return False
        finally:
            if conn and conn.is_connected():
                conn.close()