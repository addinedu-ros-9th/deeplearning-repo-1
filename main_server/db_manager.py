# =====================================================================================
# FILE: main_server/db_manager.py
#
# PURPOSE:
#   - 시스템의 모든 데이터베이스(MySQL) 관련 상호작용을 전담하는 관리자.
#   - 효율적이고 안정적인 DB 연결을 위해 커넥션 풀(Connection Pool)을 생성하고 관리.
#   - GUI로부터 TCP 연결을 통해 요청을 수신하고, 요청 종류에 따라 적절한 DB 작업을 수행.
#   - 주요 처리 요청:
#     1. 로그인 인증 (login_request): 사용자 ID/PW를 검증하고 결과를 반환.
#     2. 로그 조회 (get_logs): 특정 조건에 맞는 이벤트 로그 목록을 DB에서 조회하여 반환.
#
# 주요 로직:
#   1. DB 커넥션 풀 초기화 (_init_db_pool):
#      - 스레드 환경에서 안전하게 DB 연결을 재사용할 수 있도록 커넥션 풀을 생성.
#   2. GUI 요청 처리 (_handle_gui_connection):
#      - GUI로부터 4바이트 길이 헤더가 포함된 JSON 요청을 수신.
#      - 요청 JSON의 'cmd' 필드를 확인하여 'login_request'와 'get_logs'를 분기 처리.
#   3. 로그인 처리 (_handle_login_request):
#      - 커넥션 풀에서 연결을 가져와 사용자의 ID/PW가 일치하는지 DB에 질의.
#      - 인증 결과를 JSON으로 생성하여 GUI에 전송.
#   4. 로그 조회 처리 (_handle_get_logs_request):
#      - GUI가 보낸 필터 조건(case_type, is_checked 등)을 바탕으로 동적 SQL 쿼리를 생성.
#      - DB에서 로그 데이터를 조회한 후, 인터페이스 명세서에 맞는 JSON 형식으로 가공하여 전송.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import socket # 네트워크 통신을 위한 소켓 모듈 임포트
import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import json # JSON 데이터 처리를 위한 모듈 임포트
import struct # 바이너리 데이터(길이 헤더) 처리를 위한 모듈 임포트
from mysql.connector import pooling # MySQL 커넥션 풀링을 위한 모듈 임포트
import datetime # 날짜/시간 관련 함수를 사용하기 위한 모듈 임포트


# -------------------------------------------------------------------------------------
# [섹션 2] DBManager 클래스 정의
# -------------------------------------------------------------------------------------
class DBManager(threading.Thread):
    """
    데이터베이스 연결 및 쿼리 실행을 관리하는 클래스.
    """
    def __init__(self, host, port, db_config):
        super().__init__()
        self.name = "DBManagerThread" # 스레드 이름 설정
        self.running = True # 스레드 실행 상태를 제어하는 플래그

        # 네트워크 및 DB 설정
        self.host = host # GUI의 요청을 수신할 호스트 주소
        self.port = port # GUI의 요청을 수신할 포트
        self.db_config = db_config # DB 커넥션 풀 생성을 위한 설정 정보
        self.pool = None # DB 커넥션 풀을 저장할 변수

    def run(self): # 스레드가 시작될 때 호출되는 메인 루프
        """DB 커넥션 풀을 초기화하고, GUI의 연결 요청을 대기합니다."""
        # 1. DB 커넥션 풀 생성
        self._init_db_pool()
        if not self.pool:
            self.running = False
            return

        # 2. TCP 서버 소켓 설정
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        print(f"[{self.name}] GUI의 DB 요청 수신 대기 중... (Port: {self.port})")

        # 3. GUI 연결 수락 루프
        while self.running:
            try:
                client_socket, addr = self.server_socket.accept()
                print(f"[{self.name}] GUI DB 클라이언트 연결됨: {addr}")
                handler_thread = threading.Thread(target=self._handle_gui_connection, args=(client_socket, addr))
                handler_thread.daemon = True
                handler_thread.start()
            except socket.error:
                if not self.running: break
        
        print(f"[{self.name}] 스레드 종료.")

    def _init_db_pool(self):
        """MySQL 커넥션 풀을 생성합니다."""
        try:
            print(f"[{self.name}] DB 커넥션 풀 생성 시도...")
            self.pool = pooling.MySQLConnectionPool(pool_name="neighbot_pool",
                                                     pool_size=5,
                                                     **self.db_config)
            print(f"[{self.name}] DB 커넥션 풀 생성 완료.")
        except Exception as e:
            print(f"[{self.name}] 치명적 오류: DB 커넥션 풀 생성 실패 - {e}")

    def _handle_gui_connection(self, conn, addr):
        """GUI 클라이언트로부터의 요청을 받아 처리하고 응답합니다."""
        try:
            while self.running:
                header = conn.recv(4)
                if not header: break
                
                msg_len = struct.unpack('>I', header)[0]
                data = conn.recv(msg_len)
                request_json = json.loads(data.decode('utf-8'))
                
                # 요청 JSON의 'cmd' 값에 따라 다른 핸들러 호출
                cmd = request_json.get('cmd')
                if cmd == 'login_request':
                    self._handle_login_request(conn, request_json)
                elif cmd == 'get_logs':
                    self._handle_get_logs_request(conn, request_json)
                else:
                    # 유효하지 않은 명령에 대한 응답
                    response = {'result': 'failed', 'reason': 'Invalid command'}
                    self._send_response(conn, response)

        except (ConnectionResetError, BrokenPipeError):
            print(f"[{self.name}] GUI({addr})와 연결이 비정상적으로 끊어졌습니다.")
        except Exception as e:
            print(f"[{self.name}] GUI({addr}) 요청 처리 중 오류: {e}")
        finally:
            conn.close()

    def _handle_login_request(self, conn, request_json):
        """사용자 로그인 요청을 처리합니다."""
        user_id = request_json.get('user_id')
        password = request_json.get('password')
        response = {'result': 'failed'} # 기본 실패 응답
        
        connection = self.pool.get_connection()
        cursor = connection.cursor(dictionary=True)
        try:
            # 사용자 테이블에서 ID와 PW가 일치하는 관리자 계정 조회
            query = "SELECT user_name FROM users WHERE user_id = %s AND password = %s AND is_admin = 1"
            cursor.execute(query, (user_id, password))
            user = cursor.fetchone()
            
            if user:
                response['result'] = 'succeed'
                response['user_name'] = user['user_name']
        finally:
            cursor.close()
            connection.close() # 커넥션을 풀에 반환
        
        self._send_response(conn, response)

    def _handle_get_logs_request(self, conn, request_json):
        """로그 조회 요청을 처리하고, 필터에 맞는 로그 목록을 반환합니다."""
        filters = request_json.get('filters', {})
        response = {'cmd': 'log_list_response', 'logs': []}
        
        connection = self.pool.get_connection()
        cursor = connection.cursor(dictionary=True)
        try:
            # 기본 쿼리문
            query = "SELECT * FROM cases WHERE 1=1"
            params = []
            
            # 필터 조건에 따라 동적으로 WHERE 절 추가
            if 'case_type' in filters:
                query += " AND case_type = %s"
                params.append(filters['case_type'])
            if 'is_checked' in filters:
                query += " AND is_checked = %s"
                params.append(filters['is_checked'])
            if 'timestamp_range' in filters:
                query += " AND timestamp BETWEEN %s AND %s"
                params.extend(filters['timestamp_range'])
            
            # 정렬 조건 추가
            query += f" ORDER BY {request_json.get('order_by', 'timestamp')} {request_json.get('order', 'DESC')}"
            
            cursor.execute(query, tuple(params))
            logs = cursor.fetchall()
            
            # DB에서 조회한 datetime 객체를 문자열로 변환
            for log in logs:
                for key, value in log.items():
                    if isinstance(value, datetime.datetime):
                        log[key] = value.strftime('%Y-%m-%dT%H:%M:%S')
            response['logs'] = logs

        except Exception as e:
            print(f"[{self.name}] 로그 조회 중 오류: {e}")
        finally:
            cursor.close()
            connection.close()
        
        self._send_response(conn, response)
        
    def _send_response(self, conn, response_data):
        """처리 결과를 JSON으로 변환하여 GUI에 전송합니다."""
        try:
            response_bytes = json.dumps(response_data).encode('utf-8')
            header = struct.pack('>I', len(response_bytes))
            conn.sendall(header + response_bytes)
        except Exception as e:
            print(f"[{self.name}] GUI에 응답 전송 실패: {e}")

    def stop(self):
        """스레드를 안전하게 종료합니다."""
        self.running = False
        if hasattr(self, 'server_socket'):
            self.server_socket.close()
        print(f"[{self.name}] 종료 요청 수신.")