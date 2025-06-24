# main_server/db_manager.py (디버깅 로그 강화 및 로직 복구 완료 버전)

import socket
import threading
import json
import struct
import mysql.connector
from datetime import datetime

# from shared.protocols import GET_LOGS
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
            # 먼저 어떤 종류의 요청인지 확인 (CMD 또는 JSON)
            peek_data = conn.recv(4, socket.MSG_PEEK)
            if not peek_data: return

            if peek_data.startswith(b'CMD'):
                cmd_data = conn.recv(1024) # CMD 데이터 전체 수신
                command_code = cmd_data[3:4]
                if command_code == GET_LOGS:
                    self._process_get_logs_request(conn)
            else:
                # JSON 데이터 처리
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

        response = {
            "id": user_id if is_success else None,
            "name": user_name,
            "result": "succeed" if is_success else "fail"
        }
        response_bytes = json.dumps(response).encode('utf-8')
        header = struct.pack('>I', len(response_bytes))
        
        print(f"[✈️ TCP 전송] {self.name} -> GUI: 로그인 응답: {response}")
        conn.sendall(header + response_bytes)

    def _verify_user(self, user_id: str, password: str) -> tuple[bool, str]:
        conn = None
        try:
            conn = self._get_connection()
            query = "SELECT password, name FROM user WHERE id = %s"
            cursor = conn.cursor()
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            if result and result[0] == password:
                user_full_name = result[1]
                print(f"[{self.name}] DB: '{user_id}' ({user_full_name}) 인증 성공")
                return True, user_full_name
            print(f"[{self.name}] DB: '{user_id}' 인증 실패")
            return False, None
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (사용자 인증): {err}")
            return False, None
        finally:
            if conn and conn.is_connected():
                conn.close()

    def _generate_paths(self, detection_type: str, start_time_str: str) -> tuple[str, str]:
        try:
            dt_obj = datetime.fromisoformat(start_time_str.replace("+00:00", ""))
            timestamp_str = dt_obj.strftime('%Y%m%d_%H%M%S')
            image_path = f"images/{detection_type}_{timestamp_str}.jpg"
            video_path = f"videos/{detection_type}_{timestamp_str}.mp4"
            return image_path, video_path
        except (ValueError, TypeError) as e:
            print(f"[{self.name}] 시간 파싱 오류: {e}. 경로를 null로 설정합니다.")
            return None, None

    def _get_location_id(self, cursor, location_name: str) -> int:
        if not location_name or location_name == 'unknown':
            return None
        try:
            query = "SELECT id FROM location WHERE location_name = %s"
            cursor.execute(query, (location_name,))
            result = cursor.fetchone()
            return result[0] if result else None
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (location_id 조회): {err}")
            return None

    def _process_case_log_insert(self, request_data: dict):
        print(f"[{self.name}] DB: 사건 로그 저장 요청 수신. {len(request_data.get('logs',[]))}건")
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            for log_entry in request_data.get('logs', []):
                location_id = self._get_location_id(cursor, log_entry.get('location_id'))
                if location_id is None:
                    print(f"[{self.name}] 저장 실패: location_id가 유효하지 않아 로그(case_id: {log_entry.get('case_id')})를 저장할 수 없습니다.")
                    continue
                image_path, video_path = self._generate_paths(log_entry.get('detection_type'), log_entry.get('start_time'))

                query = """
                    INSERT INTO case_log (
                        case_type, detection_type, robot_id, location_id, user_id,
                        image_path, video_path, is_ignored, is_119_reported, is_112_reported,
                        is_illegal_warned, is_danger_warned, is_emergency_warned, is_case_closed,
                        start_time, end_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                log_data_tuple = (
                    log_entry.get('case_type'), log_entry.get('detection_type'),
                    log_entry.get('robot_id'), location_id, log_entry.get('user_id'), image_path, video_path,
                    log_entry.get('is_ignored'), log_entry.get('is_119_reported'), log_entry.get('is_112_reported'),
                    log_entry.get('is_illegal_warned'),
                    log_entry.get('is_danger_warned'),
                    log_entry.get('is_emergency_warned'),
                    log_entry.get('is_case_closed'),
                    log_entry.get('start_time'), log_entry.get('end_time')
                )
                cursor.execute(query, log_data_tuple)
            conn.commit()
            print(f"[{self.name}] DB: 사건 로그 저장 완료.")
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (사건 로그 저장): {err}")
            if conn: conn.rollback()
        finally:
            if conn and conn.is_connected():
                conn.close()

    def _process_get_logs_request(self, conn: socket.socket):
        print("-----------------------------------------------------")
        print(f"[✅ TCP 수신] GUI -> {self.name}: 로그 조회 요청")
        db_conn = None
        try:
            db_conn = self._get_connection()
            cursor = db_conn.cursor(dictionary=True)
            query = "SELECT * FROM case_log ORDER BY start_time DESC"
            cursor.execute(query)
            logs = cursor.fetchall()
            for row in logs:
                for key in ['start_time', 'end_time']:
                    if row.get(key) and isinstance(row[key], datetime):
                        row[key] = row[key].isoformat()
            response_data = {
                "cmd": "log_list_response",
                "logs": logs
            }
            response_bytes = json.dumps(response_data, ensure_ascii=False).encode('utf-8')
            header = struct.pack('>I', len(response_bytes))
            conn.sendall(header + response_bytes)
            print(f"[✈️ TCP 전송] {self.name} -> GUI: {len(logs)}개의 로그 데이터 전송 완료")
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (로그 조회): {err}")
        finally:
            if db_conn and db_conn.is_connected():
                db_conn.close()

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")