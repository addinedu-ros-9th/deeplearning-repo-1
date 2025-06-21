# main_server/db_manager.py (수정된 최종 버전)

import socket
import threading
import json
import struct
import mysql.connector

class DBManager(threading.Thread):
    """
    GUI로부터의 TCP/IP 연결을 처리하고, 데이터베이스와 통신하여
    사용자 인증(로그인) 및 기타 DB 관련 작업을 수행합니다.
    """
    def __init__(self, host, port, db_config: dict):
        super().__init__()
        self.host = host
        self.port = port
        self.db_config = db_config
        self.server_socket = None
        self.running = True
        print(f"[DB Manager] 초기화. {host}:{port} 에서 GUI 연결을 대기합니다.")

    def _get_connection(self):
        """데이터베이스 커넥션을 생성합니다."""
        return mysql.connector.connect(**self.db_config)

    def verify_user(self, user_id_from_gui: str, password: str) -> (bool, str):
        """
        사용자 ID와 비밀번호를 검증합니다.
        성공 시 (True, 사용자 이름), 실패 시 (False, None)을 반환합니다.
        """
        conn = None
        try:
            conn = self._get_connection()
            
            # [수정된 핵심]
            # 1. 실제 DB 컬럼명인 `user_name`으로 WHERE 절을 수정합니다.
            # 2. 로그인 성공 시 반환할 이름은 `name` 컬럼에서 가져옵니다.
            query = "SELECT password, name FROM user WHERE user_name = %s"
            
            cursor = conn.cursor()
            # 쿼리에 GUI로부터 받은 로그인 ID(user_id_from_gui)를 사용
            cursor.execute(query, (user_id_from_gui,))
            result = cursor.fetchone()
            
            # result[0]은 password, result[1]은 name
            if result and result[0] == password:
                user_full_name = result[1] # '이승훈'과 같은 실명을 가져옴
                print(f"[DB] '{user_id_from_gui}' ({user_full_name}) 인증 성공")
                return True, user_full_name
            
            print(f"[DB] '{user_id_from_gui}' 인증 실패: ID 또는 비밀번호 불일치")
            return False, None
        except mysql.connector.Error as err:
            print(f"[DB 오류] {err}")
            return False, None
        finally:
            if conn and conn.is_connected():
                conn.close()

    def handle_client(self, conn: socket.socket, addr):
        """연결된 GUI 클라이언트의 요청을 처리하는 메소드"""
        print(f"[DB Manager] GUI 클라이언트 연결됨: {addr}")
        try:
            while self.running:
                len_bytes = conn.recv(4)
                if not len_bytes:
                    break
                
                msg_len = struct.unpack('>I', len_bytes)[0]
                data_bytes = conn.recv(msg_len)
                request_data = json.loads(data_bytes.decode('utf-8'))
                
                print(f"[DB Manager] GUI로부터 수신: {request_data}")

                user_id = request_data.get('user_id')
                password = request_data.get('password')

                is_success, user_name = self.verify_user(user_id, password)

                response = {
                    "user_name": user_name, # 인터페이스 명세서에 따라 사용자 이름을 담아줌
                    "result": "succeed" if is_success else "fail"
                }
                
                response_bytes = json.dumps(response).encode('utf-8')
                response_len = struct.pack('>I', len(response_bytes))
                conn.sendall(response_len + response_bytes)

        except (ConnectionResetError, struct.error):
            # 클라이언트가 연결을 끊었을 때 발생하는 정상적인 오류일 수 있음
            pass
        except Exception as e:
            print(f"[DB Manager] 클라이언트 처리 중 오류 발생: {e}")
        finally:
            print(f"[DB Manager] GUI 클라이언트 연결 종료: {addr}")
            conn.close()

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)

        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                client_thread = threading.Thread(target=self.handle_client, args=(conn, addr))
                client_thread.start()
            except socket.error:
                break
        
        if self.server_socket:
            self.server_socket.close()

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print("[DB Manager] 종료 신호 수신. 서버를 중지합니다.")