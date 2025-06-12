# main_server/db_manager.py

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

    def verify_user(self, user_id: str, password: str) -> (bool, str):
        """
        사용자 ID와 비밀번호를 검증합니다.
        Interface Specification(Index 2)에 따라 성공 시 (True, 사용자 이름),
        실패 시 (False, None)을 반환합니다.
        """
        conn = None
        try:
            conn = self._get_connection()
            # 로그인 성공 시 사용자 이름을 가져오기 위해 쿼리 수정
            query = "SELECT password, user_name FROM users WHERE id = %s"
            cursor = conn.cursor()
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            
            if result and result[0] == password:
                user_name = result[1]
                print(f"[DB] '{user_id}' ({user_name}) 인증 성공")
                return True, user_name
            
            print(f"[DB] '{user_id}' 인증 실패: ID 또는 비밀번호 불일치")
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
                # 1. 길이 수신 (4바이트)
                len_bytes = conn.recv(4)
                if not len_bytes:
                    break
                
                msg_len = struct.unpack('>I', len_bytes)[0]
                
                # 2. 실제 JSON 데이터 수신
                data_bytes = conn.recv(msg_len)
                request_data = json.loads(data_bytes.decode('utf-8'))
                
                print(f"[DB Manager] GUI로부터 수신: {request_data}")

                # 3. 로그인 요청 처리 (Interface Specification Index 1)
                user_id = request_data.get('user_id')
                password = request_data.get('password')

                is_success, user_name = self.verify_user(user_id, password)

                # 4. 응답 데이터 생성 (Interface Specification Index 2)
                response = {
                    "user_name": user_name,
                    "result": "succeed" if is_success else "fail"
                }
                
                # 5. GUI에 응답 전송
                response_bytes = json.dumps(response).encode('utf-8')
                response_len = struct.pack('>I', len(response_bytes))
                conn.sendall(response_len + response_bytes)

        except ConnectionResetError:
            print(f"[DB Manager] GUI 클라이언트 연결이 초기화되었습니다: {addr}")
        except Exception as e:
            print(f"[DB Manager] 클라이언트 처리 중 오류 발생: {e}")
        finally:
            print(f"[DB Manager] GUI 클라이언트 연결 종료: {addr}")
            conn.close()

    def run(self):
        """TCP 서버를 시작하고 GUI 클라이언트의 연결을 수락합니다."""
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
        """서버 실행을 중지합니다."""
        self.running = False
        if self.server_socket:
            # accept() 대기 상태를 강제로 해제하기 위해 소켓을 닫습니다.
            self.server_socket.close()
        print("[DB Manager] 종료 신호 수신. 서버를 중지합니다.")