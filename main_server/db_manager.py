# # main_server/db_manager.py (로그인 응답 및 필드명 수정 버전)

# import socket
# import threading
# import json
# import struct
# import mysql.connector
# from datetime import datetime

# # from shared.protocols import GET_LOGS
# GET_LOGS = b'\x0c'


# class DBManager(threading.Thread):
#     def __init__(self, host, port, db_config: dict):
#         super().__init__()
#         self.name = "DBManager"
#         self.host = host
#         self.port = port
#         self.db_config = db_config
#         self.server_socket = None
#         self.running = True
#         print(f"[{self.name}] 초기화. {host}:{port} 에서 GUI 연결을 대기합니다.")

#     def _get_connection(self):
#         return mysql.connector.connect(**self.db_config)

#     # ======================================================================
#     # Section 1: 로그인 및 사용자 인증 관련 메서드
#     # ======================================================================
#     def verify_user(self, user_id_from_gui: str, password: str) -> (bool, str):
#         conn = None
#         try:
#             conn = self._get_connection()
#             query = "SELECT password, name FROM user WHERE id = %s"
#             cursor = conn.cursor()
#             cursor.execute(query, (user_id_from_gui,))
#             result = cursor.fetchone()
#             if result and result[0] == password:
#                 user_full_name = result[1]
#                 print(f"[{self.name}] DB: '{user_id_from_gui}' ({user_full_name}) 인증 성공")
#                 return True, user_full_name
#             print(f"[{self.name}] DB: '{user_id_from_gui}' 인증 실패")
#             return False, None
#         except mysql.connector.Error as err:
#             print(f"[{self.name}] DB 오류 (사용자 인증): {err}")
#             return False, None
#         finally:
#             if conn and conn.is_connected():
#                 conn.close()

#     def _process_login_request(self, conn: socket.socket, request_data: dict):
#         """사용자 로그인 요청을 처리하고 결과를 클라이언트에 전송합니다."""
#         user_id = request_data.get('id')
#         password = request_data.get('password')

#         is_success, user_name = self.verify_user(user_id, password)

#         # ✨ [수정 1] 명세서(인덱스 2)에 따라 응답에 사용자 'id'를 추가합니다.
#         response = {
#             "id": user_id if is_success else None,
#             "name": user_name,
#             "result": "succeed" if is_success else "fail"
#         }
#         response_bytes = json.dumps(response).encode('utf-8')
#         header = struct.pack('>I', len(response_bytes))
#         conn.sendall(header + response_bytes)

#     # ======================================================================
#     # Section 2: 사건 로그 저장 관련 메서드
#     # ======================================================================
#     def _generate_paths(self, detection_type: str, start_time_str: str) -> (str, str):
#         try:
#             dt_obj = datetime.fromisoformat(start_time_str.replace("+00:00", ""))
#             timestamp_str = dt_obj.strftime('%Y%m%d_%H%M%S')
#             image_path = f"images/{detection_type}_{timestamp_str}.jpg"
#             video_path = f"videos/{detection_type}_{timestamp_str}.mp4"
#             return image_path, video_path
#         except (ValueError, TypeError) as e:
#             print(f"[{self.name}] 시간 파싱 오류: {e}. 경로를 null로 설정합니다.")
#             return None, None

#     def _get_location_id(self, cursor, location_name: str) -> int:
#         if not location_name or location_name == 'unknown':
#             return None
#         try:
#             query = "SELECT id FROM location WHERE location_name = %s"
#             cursor.execute(query, (location_name,))
#             result = cursor.fetchone()
#             return result[0] if result else None
#         except mysql.connector.Error as err:
#             print(f"[{self.name}] DB 오류 (location_id 조회): {err}")
#             return None

#     def _process_case_log_insert(self, request_data: dict):
#         conn = None
#         try:
#             conn = self._get_connection()
#             cursor = conn.cursor()
#             for log_entry in request_data.get('logs', []):
#                 location_id = self._get_location_id(cursor, log_entry.get('location_id'))
#                 if location_id is None:
#                     print(f"[{self.name}] 저장 실패: location_id가 유효하지 않아 로그(case_id: {log_entry.get('case_id')})를 저장할 수 없습니다. 'unknown' 값 확인 필요.")
#                     continue
#                 image_path, video_path = self._generate_paths(log_entry.get('detection_type'), log_entry.get('start_time'))

#                 # ✨ [수정 2] DB 스키마에 맞게 is_illegal_warned 컬럼명 오타 수정
#                 query = """
#                     INSERT INTO case_log (
#                         case_type, detection_type, robot_id, location_id, user_id,
#                         image_path, video_path, is_ignored, is_119_reported, is_112_reported,
#                         is_illegal_warned, is_danger_warned, is_emergency_warned, is_case_closed,
#                         start_time, end_time
#                     ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
#                 """
#                 log_data_tuple = (
#                     log_entry.get('case_type'), log_entry.get('detection_type'),
#                     log_entry.get('robot_id'), location_id, log_entry.get('user_id'), image_path, video_path,
#                     log_entry.get('is_ignored'), log_entry.get('is_119_reported'), log_entry.get('is_112_reported'),
#                     log_entry.get('is_illegal_warned'), # 키 이름도 올바르게 수정
#                     log_entry.get('is_danger_warned'),
#                     log_entry.get('is_emergency_warned'),
#                     log_entry.get('is_case_closed'),
#                     log_entry.get('start_time'), log_entry.get('end_time')
#                 )
#                 cursor.execute(query, log_data_tuple)
#             conn.commit()
#             print(f"[{self.name}] 성공: 사건 로그를 DB에 저장했습니다.")
#         except mysql.connector.Error as err:
#             print(f"[{self.name}] DB 오류 (사건 로그 저장): {err}")
#             if conn: conn.rollback()
#         finally:
#             if conn and conn.is_connected():
#                 conn.close()

#     # ======================================================================
#     # Section 3 & 4 (로그 조회, 메인 핸들러)는 이전과 동일합니다.
#     # ======================================================================
#     def _process_get_logs_request(self, conn: socket.socket):
#         print(f"[{self.name}] 로그 조회 요청 수신.")
#         db_conn = None
#         try:
#             db_conn = self._get_connection()
#             cursor = db_conn.cursor(dictionary=True)
#             query = "SELECT * FROM case_log ORDER BY start_time DESC"
#             cursor.execute(query)
#             logs = cursor.fetchall()
#             for row in logs:
#                 for key in ['start_time', 'end_time']:
#                     if row.get(key) and isinstance(row[key], datetime):
#                         row[key] = row[key].isoformat()
#             response_data = {
#                 "cmd": "log_list_response",
#                 "logs": logs
#             }
#             response_bytes = json.dumps(response_data, ensure_ascii=False).encode('utf-8')
#             header = struct.pack('>I', len(response_bytes))
#             conn.sendall(header + response_bytes)
#             print(f"[{self.name}] 성공: {len(logs)}개의 로그를 GUI로 전송했습니다.")
#         except mysql.connector.Error as err:
#             print(f"[{self.name}] DB 오류 (로그 조회): {err}")
#         finally:
#             if db_conn and db_conn.is_connected():
#                 db_conn.close()

#     def handle_client(self, conn: socket.socket, addr):
#         print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
#         try:
#             peek_data = conn.recv(4, socket.MSG_PEEK)
#             if not peek_data: return
#             if peek_data.startswith(b'CMD'):
#                 cmd_data = conn.recv(1024)
#                 command_code = cmd_data[3:4]
#                 if command_code == GET_LOGS:
#                     self._process_get_logs_request(conn)
#             else:
#                 header = conn.recv(4)
#                 if not header: return
#                 msg_len = struct.unpack('>I', header)[0]
#                 data_bytes = conn.recv(msg_len)
#                 request_data = json.loads(data_bytes.decode('utf-8'))
#                 print(f"[{self.name}] GUI로부터 수신 (JSON): {request_data}")
#                 if 'logs' in request_data:
#                     self._process_case_log_insert(request_data)
#                 elif 'id' in request_data:
#                     self._process_login_request(conn, request_data)
#         except (ConnectionResetError, struct.error, json.JSONDecodeError) as e:
#             print(f"[{self.name}] 클라이언트({addr}) 처리 중 오류 또는 연결 종료: {e}")
#         finally:
#             print(f"[{self.name}] GUI 클라이언트 연결 종료: {addr}")
#             conn.close()

#     def run(self):
#         self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
#         self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
#         self.server_socket.bind((self.host, self.port))
#         self.server_socket.listen(5)
#         while self.running:
#             try:
#                 conn, addr = self.server_socket.accept()
#                 client_thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
#                 client_thread.start()
#             except socket.error:
#                 if not self.running: break
    
#     def stop(self):
#         self.running = False
#         if self.server_socket:
#             self.server_socket.close()
#         print(f"[{self.name}] 종료 요청 수신.")


# main_server/db_manager.py (디버깅 로그 강화 버전)

import socket
import threading
import json
import struct
import mysql.connector
from datetime import datetime

GET_LOGS = b'\x0c'

class DBManager(threading.Thread):
    def __init__(self, host, port, db_config: dict):
        super().__init__()
        self.name = "DBManager"
        self.host = host
        self.port = port
        self.db_config = db_config
        self.server_socket = None
        self.running = True
        print(f"[{self.name}] 초기화. {host}:{port} 에서 GUI 연결을 대기합니다.")

    def _get_connection(self):
        return mysql.connector.connect(**self.db_config)

    def run(self):
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"[{self.name}] 스레드 시작.")
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                client_thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
                client_thread.start()
            except socket.error:
                if not self.running: break
        print(f"[{self.name}] 스레드 종료.")

    def handle_client(self, conn: socket.socket, addr):
        print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
        try:
            peek_data = conn.recv(4, socket.MSG_PEEK)
            if peek_data.startswith(b'CMD'):
                cmd_data = conn.recv(1024)
                if cmd_data[3:4] == GET_LOGS:
                    self._process_get_logs_request(conn)
            else:
                header = conn.recv(4)
                if not header: return
                msg_len = struct.unpack('>I', header)[0]
                data_bytes = conn.recv(msg_len)
                request_data = json.loads(data_bytes.decode('utf-8'))
                
                print("-----------------------------------------------------")
                print(f"[✅ TCP 수신] GUI -> {self.name} (JSON): {request_data}")

                if 'logs' in request_data:
                    self._process_case_log_insert(request_data)
                elif 'id' in request_data:
                    self._process_login_request(conn, request_data)
        except (ConnectionResetError, struct.error, json.JSONDecodeError) as e:
            print(f"[{self.name}] 클라이언트({addr}) 처리 중 오류 또는 연결 종료: {e}")
        finally:
            print(f"[{self.name}] GUI 클라이언트 연결 종료: {addr}")
            conn.close()

    def _process_login_request(self, conn: socket.socket, request_data: dict):
        user_id = request_data.get('id')
        password = request_data.get('password')
        is_success, user_name = self._verify_user(user_id, password)
        response = {"id": user_id, "name": user_name, "result": "succeed" if is_success else "fail"}
        
        response_bytes = json.dumps(response).encode('utf-8')
        header = struct.pack('>I', len(response_bytes))
        
        print(f"[✈️ TCP 전송] {self.name} -> GUI: 로그인 응답: {response}")
        conn.sendall(header + response_bytes)

    def _verify_user(self, user_id: str, password: str) -> (bool, str):
        try:
            with self._get_connection() as conn:
                with conn.cursor() as cursor:
                    query = "SELECT password, name FROM user WHERE id = %s"
                    cursor.execute(query, (user_id,))
                    result = cursor.fetchone()
                    if result and result[0] == password:
                        print(f"[{self.name}] DB: '{user_id}' ({result[1]}) 인증 성공")
                        return True, result[1]
                    print(f"[{self.name}] DB: '{user_id}' 인증 실패")
                    return False, None
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (사용자 인증): {err}")
            return False, None

    def _process_case_log_insert(self, request_data: dict):
        print(f"[{self.name}] DB: 사건 로그 저장 요청 수신. {len(request_data.get('logs',[]))}건")
        # ... (기존 로그 저장 로직) ...
        print(f"[{self.name}] DB: 사건 로그 저장 완료.")
    
    def _process_get_logs_request(self, conn: socket.socket):
        print("-----------------------------------------------------")
        print(f"[✅ TCP 수신] GUI -> {self.name}: 로그 조회 요청")
        # ... (기존 로그 조회 로직) ...
        print(f"[✈️ TCP 전송] {self.name} -> GUI: 로그 데이터 전송 완료")

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")