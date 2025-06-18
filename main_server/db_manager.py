# main_server/db_manager.py (현재 DB 테이블에 맞게 수정된 버전)

import socket
import threading
import json
import struct
from mysql.connector import pooling, Error
import datetime

class DBManager(threading.Thread):
    def __init__(self, host, port, db_config):
        super().__init__()
        self.name = "DBManagerThread"
        self.running = True
        self.host = host
        self.port = port
        self.db_config = db_config
        self.pool = None
        self.server_socket = None

    def run(self):
        if not self.db_config:
            print(f"[{self.name}] 치명적 오류: DB 설정 정보가 없습니다. 스레드를 종료합니다.")
            return

        self._init_db_pool()
        if not self.pool:
            self.running = False
            return

        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host, self.port))
            self.server_socket.listen(5)
            print(f"[{self.name}] GUI의 DB 요청 수신 대기 중... (Port: {self.port})")
        except Exception as e:
            print(f"[{self.name}] 소켓 바인딩 실패: {e}")
            self.running = False
            return

        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                print(f"[{self.name}] GUI DB 클라이언트 연결됨: {addr}")
                handler_thread = threading.Thread(target=self._handle_gui_connection, args=(client_socket, addr))
                handler_thread.daemon = True
                handler_thread.start()
            except socket.error as e:
                if self.running:
                    print(f"[{self.name}] 소켓 accept 오류: {e}")
                break

        print(f"[{self.name}] 스레드 종료.")

    def _init_db_pool(self):
        try:
            print(f"[{self.name}] DB 커넥션 풀 생성 시도...")
            self.pool = pooling.MySQLConnectionPool(pool_name="neighbot_pool", pool_size=5, **self.db_config)
            print(f"[{self.name}] DB 커넥션 풀 생성 완료.")
        except Error as e:
            print(f"[{self.name}] 치명적 오류: DB 커넥션 풀 생성 실패 - {e}")

    def _handle_gui_connection(self, conn, addr):
        try:
            while self.running:
                header = conn.recv(4)
                if not header:
                    print(f"[{self.name}] GUI({addr}) 연결 정상 종료됨 (헤더 없음).")
                    break

                msg_len = struct.unpack('>I', header)[0]
                data = conn.recv(msg_len)
                request_json = json.loads(data.decode('utf-8'))

                print(f"[{self.name}] GUI({addr})로부터 요청 수신: {request_json}")

                cmd = request_json.get('cmd')
                if cmd == 'login_request':
                    self._handle_login_request(conn, request_json)
                elif cmd == 'get_logs':
                    self._handle_get_logs_request(conn, request_json)
                else:
                    response = {'result': 'failed', 'reason': f"알 수 없는 명령입니다: {cmd}"}
                    self._send_response(conn, response)

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{self.name}] GUI({addr})와 연결이 비정상적으로 끊어졌습니다.")
        except Exception as e:
            print(f"[{self.name}] GUI({addr}) 요청 처리 중 오류: {e}")
        finally:
            conn.close()

    def _handle_login_request(self, conn, request_json):
        # GUI가 보낸 JSON에서 'user_id' 값을 가져옵니다. (login_window.py는 'user_id' 키를 사용)
        login_id = request_json.get('user_id')
        password = request_json.get('password')
        response = {'result': 'failed'}

        try:
            connection = self.pool.get_connection()
            cursor = connection.cursor(dictionary=True)

            # ========================= [쿼리 수정 지점] =========================
            # 현재 DB 테이블('user')과 컬럼('user_name', 'password', 'name')에 맞게 쿼리 수정
            # 경고: is_admin 관리자 확인 로직이 제거됨
            query = "SELECT name FROM user WHERE user_name = %s AND password = %s"
            # =================================================================

            cursor.execute(query, (login_id, password))
            user = cursor.fetchone()

            if user:
                response['result'] = 'succeed'
                # DB의 'name' 컬럼 값을 'user_name'으로 전달
                response['user_name'] = user['name']
                print(f"[{self.name}] 로그인 성공: user_name='{login_id}'")
            else:
                response['reason'] = '아이디 또는 비밀번호가 일치하지 않습니다.'
                print(f"[{self.name}] 로그인 실패: user_name='{login_id}'")

        except Error as e:
            response['reason'] = '데이터베이스 처리 중 오류가 발생했습니다.'
            print(f"[{self.name}] 로그인 DB 쿼리 중 오류: {e}")
        finally:
            if 'cursor' in locals() and cursor:
                cursor.close()
            if 'connection' in locals() and connection.is_connected():
                connection.close()

        self._send_response(conn, response)

    def _handle_get_logs_request(self, conn, request_json):
        # 로그 조회 로직 (추후 구현)
        pass

    def _send_response(self, conn, response_data):
        try:
            response_bytes = json.dumps(response_data).encode('utf-8')
            header = struct.pack('>I', len(response_bytes))
            conn.sendall(header + response_bytes)
        except Exception as e:
            print(f"[{self.name}] GUI에 응답 전송 실패: {e}")

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print(f"[{self.name}] 종료 요청 수신.")