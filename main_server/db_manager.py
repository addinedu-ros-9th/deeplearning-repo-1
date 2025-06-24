# main_server/db_manager.py (수정 완료)

import socket
import threading
import json
import struct
import mysql.connector
from datetime import datetime

# GUI로부터 로그 전체 조회 요청 시 사용될 명령어 코드
GET_LOGS = b'\x0c'

class DBManager(threading.Thread):
    def __init__(self, host, port, db_config: dict, robot_status):
        super().__init__()
        self.name = "DBManager"
        self.host = host
        self.port = port
        self.db_config = db_config
        self.robot_status = robot_status  # ImageManager에 녹화 종료 신호를 보내기 위한 공유 객체
        self.server_socket = None
        self.running = True
        print(f"[{self.name}] 초기화. {host}:{port} 에서 GUI 연결을 대기합니다.")

    def _get_connection(self):
        """DB 커넥션을 생성하고 반환합니다."""
        return mysql.connector.connect(**self.db_config, autocommit=False)

    def run(self):
        """서버 소켓을 열고 GUI 클라이언트의 연결을 기다리는 메인 루프입니다."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"[{self.name}] 스레드 시작.")
        while self.running:
            try:
                conn, addr = self.server_socket.accept()
                # 각 클라이언트 연결을 별도의 스레드로 처리
                client_thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
                client_thread.start()
            except socket.error:
                if not self.running: break
        print(f"[{self.name}] 스레드 종료.")

    def handle_client(self, conn: socket.socket, addr):
        """연결된 클라이언트로부터의 요청을 받아 종류에 따라 처리합니다."""
        print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
        try:
            # 먼저 4바이트를 읽어 요청의 종류를 파악 (MSG_PEEK로 데이터는 남겨둠)
            peek_data = conn.recv(4, socket.MSG_PEEK)
            if not peek_data: return

            # 'CMD'로 시작하면 로그 조회 요청
            if peek_data.startswith(b'CMD'):
                cmd_data = conn.recv(1024) # 명령어 수신
                command_code = cmd_data[3:4]
                if command_code == GET_LOGS:
                    self._process_get_logs_request(conn)
            # 그렇지 않으면 JSON 기반 요청 (로그인 또는 로그 저장)
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
        """사용자 로그인 요청을 처리합니다."""
        user_id = request_data.get('id')
        password = request_data.get('password')
        is_success, user_name = self._verify_user(user_id, password)

        response = {
            "id": user_id,
            "name": user_name, # 인터페이스 명세에 따라 name 키 사용
            "result": "succeed" if is_success else "fail"
        }
        response_bytes = json.dumps(response, ensure_ascii=False).encode('utf-8')
        header = struct.pack('>I', len(response_bytes))

        print(f"[✈️ TCP 전송] {self.name} -> GUI: 로그인 응답: {response}")
        conn.sendall(header + response_bytes)

    def _verify_user(self, user_id: str, password: str) -> tuple[bool, str | None]:
        """DB에서 사용자 ID와 비밀번호를 검증합니다."""
        db_conn = None
        try:
            db_conn = self._get_connection()
            cursor = db_conn.cursor(dictionary=True)
            query = "SELECT password, name FROM user WHERE id = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()
            if result and result['password'] == password:
                user_full_name = result['name']
                print(f"[{self.name}] DB: '{user_id}' ({user_full_name}) 인증 성공")
                return True, user_full_name
            print(f"[{self.name}] DB: '{user_id}' 인증 실패")
            return False, None
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (사용자 인증): {err}")
            return False, None
        finally:
            if db_conn and db_conn.is_connected():
                db_conn.close()

    def _get_location_id(self, cursor, location_name: str) -> int | None:
        """장소 이름('A', 'B', 'BASE')으로 location 테이블의 id를 조회합니다."""
        if not location_name or location_name == 'unknown': return None
        try:
            query = "SELECT id FROM location WHERE name = %s"
            cursor.execute(query, (location_name,))
            result = cursor.fetchone()
            return result['id'] if result else None
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (location_id 조회): {err}")
            return None

    def _get_user_id_by_name(self, cursor, user_name: str) -> str | None:
        """[신규] 사용자 이름으로 user 테이블의 id를 조회합니다."""
        if not user_name: return None
        try:
            query = "SELECT id FROM user WHERE name = %s"
            cursor.execute(query, (user_name,))
            result = cursor.fetchone()
            return result['id'] if result else None
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (user_id 조회): {err}")
            return None

    def _generate_paths(self, detection_type: str, start_time_str: str) -> tuple[str | None, str | None]:
        """탐지 타입과 시작 시간을 기반으로 이미지/비디오 저장 경로를 생성합니다."""
        try:
            dt_obj = datetime.fromisoformat(start_time_str.replace("+00:00", ""))
            timestamp_str = dt_obj.strftime('%Y%m%d_%H%M%S')
            image_path = f"images/{detection_type}_{timestamp_str}.jpg"
            video_path = f"videos/{detection_type}_{timestamp_str}.mp4"
            return image_path, video_path
        except (ValueError, TypeError) as e:
            print(f"[{self.name}] 시간 파싱 오류: {e}. 경로를 null로 설정합니다.")
            return None, None

    def _process_case_log_insert(self, request_data: dict):
        """GUI로부터 받은 사건 로그를 DB에 저장합니다."""
        print(f"[{self.name}] DB: 사건 로그 저장 요청 수신. {len(request_data.get('logs',[]))}건")
        db_conn = None
        try:
            db_conn = self._get_connection()
            cursor = db_conn.cursor(dictionary=True)

            for log_entry in request_data.get('logs', []):
                # [핵심 수정] GUI에서 받은 이름(location, user)을 DB에 저장할 ID로 변환
                location_id = self._get_location_id(cursor, log_entry.get('location'))
                user_id = self._get_user_id_by_name(cursor, log_entry.get('user_id'))

                if location_id is None:
                    print(f"[{self.name}] 저장 실패: 유효하지 않은 location '{log_entry.get('location')}'")
                    continue
                if user_id is None:
                    print(f"[{self.name}] 저장 실패: 유효하지 않은 user_id '{log_entry.get('user_id')}'")
                    continue

                image_path, video_path = self._generate_paths(log_entry.get('detection_type'), log_entry.get('start_time'))

                # [핵심] '무시' 또는 '사건 종료' 시 ImageManager에 녹화 종료 및 파일명 변경 신호 전송
                if log_entry.get('is_ignored') == 1 or log_entry.get('is_case_closed') == 1:
                    stop_signal = {'final_image_path': image_path, 'final_video_path': video_path}
                    self.robot_status['recording_stop_signal'] = stop_signal
                    print(f"[{self.name}] ➡️ ImageManager: 녹화 종료 신호 전송 (파일명: {video_path})")

                query = """
                    INSERT INTO case_log (
                        case_type, detection_type, robot_id, location_id, user_id,
                        image_path, video_path, is_ignored, is_119_reported, is_112_reported,
                        is_illegal_warned, is_danger_warned, is_emergency_warned, is_case_closed,
                        start_time, end_time
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                params = (
                    log_entry.get('case_type'), log_entry.get('detection_type'),
                    log_entry.get('robot_id'), location_id, user_id, image_path, video_path,
                    log_entry.get('is_ignored'), log_entry.get('is_119_reported'), log_entry.get('is_112_reported'),
                    log_entry.get('is_illegal_warned'), log_entry.get('is_danger_warned'),
                    log_entry.get('is_emergency_warned'), log_entry.get('is_case_closed'),
                    log_entry.get('start_time'), log_entry.get('end_time')
                )
                cursor.execute(query, params)

            db_conn.commit()
            print(f"[{self.name}] DB: 사건 로그 저장 완료.")
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (사건 로그 저장): {err}")
            if db_conn: db_conn.rollback()
        finally:
            if db_conn and db_conn.is_connected():
                db_conn.close()

    def _process_get_logs_request(self, conn: socket.socket):
        """DB에서 전체 로그를 조회하여 GUI로 전송합니다."""
        print("-----------------------------------------------------")
        print(f"[✅ TCP 수신] GUI -> {self.name}: 로그 조회 요청")
        db_conn = None
        try:
            db_conn = self._get_connection()
            cursor = db_conn.cursor(dictionary=True)

            # [핵심 수정] location과 user 테이블을 JOIN하여 id가 아닌 name을 가져옴
            query = """
                SELECT
                    cl.id, cl.case_type, cl.detection_type, cl.robot_id,
                    u.name AS user_id,
                    l.name AS location,
                    cl.image_path, cl.video_path, cl.is_ignored, cl.is_119_reported,
                    cl.is_112_reported, cl.is_illegal_warned, cl.is_danger_warned,
                    cl.is_emergency_warned, cl.is_case_closed, cl.start_time, cl.end_time
                FROM case_log cl
                JOIN location l ON cl.location_id = l.id
                JOIN user u ON cl.user_id = u.id
                ORDER BY cl.start_time DESC
            """
            cursor.execute(query)
            logs = cursor.fetchall()

            # Datetime 객체를 JSON으로 직렬화 가능한 ISO 형식의 문자열로 변환
            for row in logs:
                for key in ['start_time', 'end_time']:
                    if row.get(key) and isinstance(row[key], datetime):
                        row[key] = row[key].isoformat()

            response_data = {"logs": logs}
            response_bytes = json.dumps(response_data, ensure_ascii=False, default=str).encode('utf-8')
            header = struct.pack('>I', len(response_bytes))

            conn.sendall(header + response_bytes)
            print(f"[✈️ TCP 전송] {self.name} -> GUI: {len(logs)}개의 로그 데이터 전송 완료")
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (로그 조회): {err}")
        finally:
            if db_conn and db_conn.is_connected():
                db_conn.close()

    def stop(self):
        """스레드를 안전하게 종료합니다."""
        self.running = False
        if self.server_socket:
            # 더미 클라이언트 연결을 만들어 accept()에서 블록된 서버 소켓을 깨움
            try:
                dummy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                dummy_socket.connect((self.host, self.port))
                dummy_socket.close()
            except socket.error:
                pass # 서버가 이미 닫혔을 수 있음
            self.server_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")