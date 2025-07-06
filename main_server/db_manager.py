# =====================================================================================
# FILE: main_server/db_manager.py
#
# PURPOSE:
#   - 시스템의 모든 데이터베이스 관련 작업을 전담하는 '데이터베이스 게이트웨이'.
#   - GCP Cloud SQL 데이터베이스와의 연결, 쿼리 실행, 트랜잭션 관리를 수행.
#   - GUI 클라이언트로부터 오는 요청을 처리하기 위한 전용 TCP 서버를 운영.
#   - 주요 기능은 사용자 로그인 인증, 사건 로그(case_log) 저장, 전체 로그 조회.
#   - GUI와 DB 사이의 데이터 표현 방식 차이를 변환. (예: GUI의 'A지역' -> DB의 'location_id=1')
#   - 사건이 종료되어 로그를 저장할 때, DataMerger에 녹화 종료 및 파일명 변경을
#     지시하는 신호를 보내는 중요한 역할을 함.
#
# 주요 로직:
#   1. 서버 운영 및 요청 분류 (run, handle_client):
#      - 지정된 포트에서 GUI의 TCP 연결을 상시 대기.
#      - 클라이언트 연결 시, 수신 데이터의 첫 부분을 확인(peek)하여 요청의 종류를 판별.
#        - 'CMD'로 시작하는 바이너리 데이터: 로그 조회 요청 (_process_get_logs_request)
#        - JSON 데이터 (길이 헤더 포함): 로그인 요청 또는 로그 저장 요청.
#   2. 사용자 로그인 처리 (_process_login_request, _verify_user):
#      - GUI로부터 사용자 ID와 비밀번호를 포함한 JSON을 수신.
#      - _verify_user 메서드에서 user 테이블을 조회하여 인증 수행.
#      - 인증 결과를 'succeed', 'id_error', 'password_error'와 같이 구체적으로 구분하여
#        GUI에 응답, 사용자에게 명확한 피드백을 제공.
#   3. 사건 로그 저장 (_process_case_log_insert):
#      - GUI로부터 사건 처리 결과를 담은 JSON 로그 데이터를 수신.
#      - DB에 저장하기 전, GUI에서 받은 위치 이름('A'), 사용자 이름('김민수') 등을
#        DB의 외래 키(FK)인 ID 값으로 변환하는 전처리 수행 (_get_location_id, _get_user_id_by_name).
#      - 사건의 시작 시간을 기반으로 이미지/비디오 파일의 최종 저장 경로를 생성.
#      - [핵심] 공유 객체 `robot_status['recording_stop_signal']`에 최종 파일 경로를 설정하여,
#        DataMerger 스레드에 녹화를 중단하고 임시 파일의 이름을 최종 이름으로 변경하도록 신호를 보냄.
#      - 전처리된 데이터를 case_log 테이블에 INSERT.
#   4. 로그 조회 및 전송 (_process_get_logs_request):
#      - GUI로부터 로그 조회 명령(GET_LOGS)을 수신.
#      - case_log 테이블을 location, user 테이블과 JOIN하여, DB에 저장된 ID 값들을
#        다시 GUI에 표시될 이름으로 변환하여 조회.
#      - 조회된 전체 로그 목록을 JSON 형식으로 패키징하여 GUI에 전송.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket # TCP/IP 통신을 위한 소켓 모듈
import threading # 다중 스레딩 기능을 위한 모듈
import json # JSON 형식 데이터 처리를 위한 모듈
import struct # 바이너리 데이터 패킹/언패킹을 위한 모듈
import mysql.connector # MySQL 데이터베이스 연결을 위한 모듈
from datetime import datetime # 날짜 및 시간 처리를 위한 모듈

# -------------------------------------------------------------------------------------
# [섹션 2] 전역 상수 정의
# -------------------------------------------------------------------------------------
# GUI로부터 로그 전체 조회 요청 시 사용될 명령어 코드 (Byte)
GET_LOGS = b'\x0c'

# -------------------------------------------------------------------------------------
# [섹션 3] DBManager 클래스 정의
# -------------------------------------------------------------------------------------
class DBManager(threading.Thread):
    def __init__(self, host, port, db_config: dict, robot_status):
        super().__init__()
        self.name = "DBManager"
        self.host = host # 서버가 리슨할 호스트 주소
        self.port = port # 서버가 리슨할 포트 번호
        self.db_config = db_config # DB 연결 정보 딕셔너리
        self.robot_status = robot_status # 녹화 종료 신호를 보내기 위한 공유 객체
        self.server_socket = None # 서버 소켓 객체
        self.running = True # 스레드 실행 상태 플래그
        print(f"[{self.name}] 초기화. {host}:{port} 에서 GUI 연결을 대기합니다.")

    def _get_connection(self):
        """DB 커넥션을 생성하고 반환합니다."""
        # autocommit=False로 설정하여 트랜잭션 관리를 직접 수행
        return mysql.connector.connect(**self.db_config, autocommit=False)

    def run(self):
        """서버 소켓을 열고 GUI 클라이언트의 연결을 기다리는 메인 루프."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"[{self.name}] 스레드 시작.")
        while self.running:
            try:
                conn, addr = self.server_socket.accept() # 클라이언트 연결 수락
                # 각 클라이언트 연결을 별도의 스레드로 처리하여 동시 요청에 대응
                client_thread = threading.Thread(target=self.handle_client, args=(conn, addr), daemon=True)
                client_thread.start()
            except socket.error:
                if not self.running: break
        print(f"[{self.name}] 스레드 종료.")

    def handle_client(self, conn: socket.socket, addr):
        """연결된 클라이언트로부터의 요청을 받아 종류에 따라 처리합니다."""
        print(f"[{self.name}] GUI 클라이언트 연결됨: {addr}")
        try:
            # 먼저 4바이트를 읽어 요청의 종류를 파악 (MSG_PEEK로 데이터는 소켓 버퍼에 남겨둠)
            peek_data = conn.recv(4, socket.MSG_PEEK)
            if not peek_data: return

            # 'CMD'로 시작하면 로그 조회 요청으로 판단
            if peek_data.startswith(b'CMD'):
                cmd_data = conn.recv(1024) # 명령어 수신
                command_code = cmd_data[3:4] # 실제 명령어 코드 추출
                if command_code == GET_LOGS:
                    self._process_get_logs_request(conn)
            # 그렇지 않으면 JSON 기반 요청(로그인 또는 로그 저장)으로 판단
            else:
                header = conn.recv(4) # 4바이트 길이 헤더 수신
                if not header: return
                msg_len = struct.unpack('>I', header)[0] # 헤더에서 메시지 길이 추출
                data_bytes = conn.recv(msg_len) # 메시지 길이만큼 데이터 수신
                request_data = json.loads(data_bytes.decode('utf-8')) # JSON 파싱

                print("-----------------------------------------------------")
                print(f"[✅ TCP 수신] GUI -> {self.name} (JSON): {request_data}")

                if 'logs' in request_data: # 'logs' 키가 있으면 로그 저장 요청
                    self._process_case_log_insert(request_data)
                elif 'id' in request_data: # 'id' 키가 있으면 로그인 요청
                    self._process_login_request(conn, request_data)

        except (ConnectionResetError, struct.error, json.JSONDecodeError) as e:
            print(f"[{self.name}] 클라이언트({addr}) 처리 중 오류 또는 연결 종료: {e}")
        finally:
            print(f"[{self.name}] GUI 클라이언트 연결 종료: {addr}")
            conn.close()

    def _process_login_request(self, conn: socket.socket, request_data: dict):
        """사용자 로그인 요청을 처리하고 결과를 응답합니다."""
        user_id = request_data.get('id')
        password = request_data.get('password')
        # DB에서 사용자 검증 후, 'succeed', 'id_error', 'password_error' 중 하나의 결과와 사용자 이름을 받음
        result_status, user_name = self._verify_user(user_id, password)
        response = {
            "id": user_id,
            "name": user_name,
            "result": result_status # 검증 결과를 그대로 담아 응답
        }
        response_bytes = json.dumps(response, ensure_ascii=False).encode('utf-8')
        header = struct.pack('>I', len(response_bytes)) # 응답 헤더 생성

        print(f"[✈️ TCP 전송] {self.name} -> GUI: 로그인 응답: {response}")
        conn.sendall(header + response_bytes) # GUI로 응답 전송

    def _verify_user(self, user_id: str, password: str) -> tuple[str, str | None]:
        """DB에서 사용자 ID와 비밀번호를 검증하고, 그 결과를 구체적인 문자열로 반환합니다."""
        db_conn = None
        try:
            db_conn = self._get_connection()
            cursor = db_conn.cursor(dictionary=True)
            query = "SELECT password, name FROM user WHERE id = %s"
            cursor.execute(query, (user_id,))
            result = cursor.fetchone()

            if not result: # ID가 존재하지 않는 경우
                print(f"[{self.name}] DB: '{user_id}' 인증 실패 - 존재하지 않는 ID")
                return "id_error", None

            if result['password'] == password: # 비밀번호가 일치하는 경우
                user_full_name = result['name']
                print(f"[{self.name}] DB: '{user_id}' ({user_full_name}) 인증 성공")
                return "succeed", user_full_name
            else: # 비밀번호가 틀린 경우
                print(f"[{self.name}] DB: '{user_id}' 인증 실패 - 비밀번호 불일치")
                return "password_error", None

        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (사용자 인증): {err}")
            return "fail", None # DB 오류 시 일반 실패로 처리
        finally:
            if db_conn and db_conn.is_connected():
                db_conn.close()

    def _get_location_id(self, cursor, location_name: str) -> int | None:
        """장소 이름('A', 'B')으로 location 테이블의 id를 조회합니다."""
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
        """사용자 이름으로 user 테이블의 id(PK)를 조회합니다."""
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
        """탐지 타입과 시작 시간을 기반으로 이미지/비디오 저장 경로 문자열을 생성합니다."""
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
                # GUI에서 받은 이름(location, user)을 DB에 저장할 ID로 변환
                location_id = self._get_location_id(cursor, log_entry.get('location'))
                user_id = self._get_user_id_by_name(cursor, log_entry.get('user_id'))

                if location_id is None or user_id is None:
                    print(f"[{self.name}] 저장 실패: 유효하지 않은 location 또는 user_id")
                    continue

                # 최종 파일 경로 생성
                image_path, video_path = self._generate_paths(log_entry.get('detection_type'), log_entry.get('start_time'))

                # '무시' 또는 '사건 종료' 시 DataMerger에 녹화 종료 신호 전송
                if log_entry.get('is_ignored') == 1 or log_entry.get('is_case_closed') == 1:
                    stop_signal = {'final_image_path': image_path, 'final_video_path': video_path}
                    self.robot_status['recording_stop_signal'] = stop_signal
                    print(f"[{self.name}] ➡️ DataMerger: 녹화 종료 신호 전송 (파일명: {video_path})")

                # DB에 로그를 삽입하는 쿼리
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

            db_conn.commit() # 모든 로그 삽입 후 트랜잭션 커밋
            print(f"[{self.name}] DB: 사건 로그 저장 완료.")
        except mysql.connector.Error as err:
            print(f"[{self.name}] DB 오류 (사건 로그 저장): {err}")
            if db_conn: db_conn.rollback() # 오류 발생 시 롤백
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

            # location과 user 테이블을 JOIN하여 id가 아닌 실제 이름(name)을 가져옴
            query = """
                SELECT
                    cl.id AS case_id, cl.case_type, cl.detection_type, cl.robot_id,
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
            # accept()에서 블록된 서버 소켓을 깨우기 위해 더미 클라이언트 연결을 생성
            try:
                dummy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                dummy_socket.connect((self.host, self.port))
                dummy_socket.close()
            except socket.error:
                pass # 서버가 이미 닫혔을 수 있음
            self.server_socket.close()
        print(f"\n[{self.name}] 종료 요청 수신.")