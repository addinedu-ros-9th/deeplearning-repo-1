# =====================================================================================
# FILE: main_server/system_manager.py
#
# PURPOSE:
#   - 메인 서버 애플리케이션의 전체 동작을 총괄하는 컨트롤 타워(Control Tower) 역할.
#   - ImageManager, EventAnalyzer, DataMerger, DBManager, RobotCommander 등 시스템의
#     핵심 컴포넌트들을 생성.
#   - 컴포넌트 간 데이터 통신을 위한 공유 큐(Queue)와 상태 객체(robot_status)를
#     생성하고 연결해주는 '배선' 작업을 수행.
#   - 모든 컴포넌트 스레드의 생명주기(시작, 종료)를 관리.
#   - 서버 프로그램을 실행하는 메인 진입점(Entry Point)으로 기능함.
#
# 주요 로직:
#   1. 전역 설정:
#      - 로봇, AI 서버, GUI, DB Manager 등 각 컴포넌트의 네트워크 주소와 포트를 정의.
#   2. SystemManager 클래스 (컨트롤 타워):
#      - 데이터 흐름을 위한 공유 큐들과 로봇의 상태 및 녹화 신호를 공유할 'robot_status' 딕셔너리를 생성.
#      - ImageManager, EventAnalyzer, DataMerger, DBManager, RobotCommander 등 모든
#        핵심 컴포넌트 인스턴스를 생성하고, 생성된 공유 자원과 네트워크 설정을 인자로 전달하여 연결.
#      - 생성된 컴포넌트 인스턴스들을 스레드 리스트로 관리.
#      - start(): 모든 컴포넌트 스레드를 시작.
#      - stop(): 모든 컴포넌트 스레드에 종료 신호를 보내고, 각 스레드가 안전하게 종료될 때까지 대기(join).
#   3. 실행 진입점 (__main__):
#      - SystemManager 인스턴스를 생성.
#      - 시스템 시작을 위해 manager.start() 호출.
#      - KeyboardInterrupt(Ctrl+C)가 발생할 때까지 메인 스레드를 대기.
#      - 인터럽트 발생 시 manager.stop()을 호출하여 전체 시스템을 안전하게 종료.
# =====================================================================================
# 실행 방법: 1. ~/dev_ws/deeplearning-repo-1$ python3 -m main_server.system_manager
#           2. ~/dev_ws/deeplearning-repo-1/ai_server$ python detection_manager.py
#           3. ~/dev_ws/deeplearning-repo-1$ python3 -m gui.neighbot_gui
# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import time # 시간 관련 함수를 사용하기 위한 모듈 임포트
import queue # 큐(Queue) 자료구조를 사용하기 위한 모듈 임포트
from .image_manager import ImageManager # ImageManager 클래스 임포트
from .event_analyzer import EventAnalyzer # EventAnalyzer 클래스 임포트
from .data_merger import DataMerger # DataMerger 클래스 임포트
from .db_manager import DBManager # DBManager 클래스 임포트
from .robot_commander import RobotCommander # RobotCommander 클래스 임포트

# -------------------------------------------------------------------------------------
# [섹션 2] 전역 설정 (네트워크 주소 및 포트)
# -------------------------------------------------------------------------------------
# --- 로봇 관련 설정 ---
ROBOT_HOST = "192.168.0.3" # 실제 로봇의 IP 주소
IMAGE_RECV_PORT = 9001 # 로봇의 ImageSender로부터 이미지를 수신할 포트
ROBOT_CONTROLLER_PORT = 9008 # RobotCommander가 로봇의 RobotController로 제어 명령을 보낼 포트

# --- AI 서버 관련 설정 ---
AI_SERVER_HOST = "127.0.0.1" # AI 서버 IP 주소 (여기서는 로컬호스트)
AI_SERVER_PORT = 9002 # ImageManager가 AI 서버로 이미지를 전달할 포트
ANALYSIS_RECV_PORT = 9003 # EventAnalyzer가 AI 서버로부터 분석 결과를 수신할 포트

# --- GUI 클라이언트 관련 설정 ---
GUI_HOST = "127.0.0.1" # GUI 클라이언트가 실행되는 IP 주소 (여기서는 로컬호스트)
GUI_MERGER_PORT = 9004 # DataMerger가 GUI 클라이언트로 데이터를 전송할 포트
GUI_ROBOT_COMMANDER_PORT = 9006 # RobotCommander가 GUI로부터 제어 명령을 수신할 포트

# --- DB Manager 관련 설정 ---
DB_MANAGER_HOST = '0.0.0.0' # 모든 IP에서의 접속을 허용
DB_MANAGER_PORT = 9005      # GUI가 로그인/로그 저장을 위해 접속할 포트

# -------------------------------------------------------------------------------------
# [섹션 3] SystemManager 클래스 정의
# -------------------------------------------------------------------------------------
class SystemManager:
    """
    시스템의 모든 컴포넌트를 생성, 연결하고 생명주기를 관리하는 메인 클래스.
    """
    def __init__(self): # 생성자 정의
        # --- DB 접속 정보 ---
        DB_CONFIG = { # 데이터베이스 접속 설정 딕셔너리
            'user': 'root', # DB 사용자 이름
            'password': 'qwer1234!@#$', # DB 비밀번호
            'host': '34.47.96.177', # DB 서버 호스트 주소
            'database': 'neighbot_db', # 사용할 데이터베이스 이름
            'raise_on_warnings': True # 경고 발생 시 예외를 발생시킬지 여부
        }
        
        # --- 공유 자원 생성 ---
        # 로봇의 현재 상태('state'), 목표 마커('target_marker_id'), 녹화 종료 신호('recording_stop_signal')를
        # 모든 스레드가 공유하기 위한 딕셔너리 객체.
        self.robot_status = {
            'state': 'idle', 
            'target_marker_id': None,
            'recording_stop_signal': None # DBManager가 DataMerger에 녹화 종료/파일명 변경을 알리는 신호
        }
        print(f"[🚦 시스템 상태] SystemManager: 초기 상태를 '{self.robot_status['state']}'(으)로 설정")

        # --- 데이터 전달용 큐 생성 ---
        self.aruco_result_queue = queue.Queue() # ImageManager -> RobotCommander (ArUco 마커 탐지 결과)
        self.image_for_merger_queue = queue.Queue() # ImageManager -> DataMerger (카메라 이미지)
        self.event_result_queue = queue.Queue() # EventAnalyzer -> DataMerger (AI 분석 결과)

        # --- 컴포넌트 인스턴스 생성 및 연결 ---
        # 각 컴포넌트(스레드)를 초기화하고, 필요한 공유 자원(큐, 상태 객체)과 설정을 주입.
        self.image_manager = ImageManager(
            listen_port=IMAGE_RECV_PORT, # 로봇 이미지 수신 포트
            ai_server_addr=(AI_SERVER_HOST, AI_SERVER_PORT), # AI 서버 주소
            image_for_merger_queue=self.image_for_merger_queue, # DataMerger로 이미지를 보낼 큐
            robot_status=self.robot_status, # 공유할 로봇 상태 객체
            aruco_result_queue=self.aruco_result_queue # ArUco 결과를 보낼 큐
        )
        
        self.event_analyzer = EventAnalyzer(
            listen_port=ANALYSIS_RECV_PORT, # AI 서버 분석 결과 수신 포트
            output_queue=self.event_result_queue, # DataMerger로 이벤트 결과를 보낼 큐
            robot_status=self.robot_status # 공유할 로봇 상태 객체
        )
        
        self.data_merger = DataMerger(
            image_queue=self.image_for_merger_queue, # ImageManager로부터 이미지 받을 큐
            event_queue=self.event_result_queue, # EventAnalyzer로부터 이벤트 받을 큐
            gui_listen_addr=(GUI_HOST, GUI_MERGER_PORT), # GUI로 결과를 보낼 주소
            robot_status=self.robot_status # 공유할 로봇 상태 객체
        )
        
        # DBManager에 robot_status 객체를 전달하여, 특정 DB 저장 요청 시
        # DataMerger의 녹화 프로세스를 제어할 수 있도록 함.
        self.db_manager = DBManager(
            host=DB_MANAGER_HOST, # DB Manager 리스닝 주소
            port=DB_MANAGER_PORT, # DB Manager 리스닝 포트
            db_config=DB_CONFIG, # DB 접속 정보
            robot_status=self.robot_status # 공유할 로봇 상태 객체
        )

        self.robot_commander = RobotCommander(
            gui_listen_port=GUI_ROBOT_COMMANDER_PORT, # GUI로부터 제어 명령을 받을 포트
            robot_controller_addr=(ROBOT_HOST, ROBOT_CONTROLLER_PORT), # 로봇 컨트롤러 주소
            robot_status=self.robot_status, # 공유할 로봇 상태 객체
            aruco_result_queue=self.aruco_result_queue # ArUco 결과를 받을 큐
        )

        # 생성된 스레드 객체들을 리스트로 관리하여 일괄 시작/종료 처리
        self.threads = [
            self.image_manager,
            self.event_analyzer,
            self.data_merger,
            self.db_manager,
            self.robot_commander
        ]
        
    def start(self): # 모든 컴포넌트 스레드를 시작하는 메서드
        print("SystemManager: Starting all component threads...")
        for thread in self.threads: # 관리 중인 스레드 리스트를 순회하며
            thread.start() # 각 스레드를 시작
        print("SystemManager: All component threads started.")

    def stop(self): # 모든 컴포넌트 스레드를 안전하게 종료하는 메서드
        print("\nSystemManager: Stopping all component threads...")
        for thread in self.threads: # 관리 중인 스레드 리스트를 순회하며
            # 각 스레드 객체에 'stop' 메서드가 있는지 확인 (안전한 종료를 위함)
            if hasattr(thread, 'stop') and callable(getattr(thread, 'stop')):
                thread.stop() # 'stop' 메서드를 호출하여 스레드의 메인 루프를 탈출하도록 함
        
        for thread in self.threads: # 다시 모든 스레드를 순회하며
            thread.join() # 해당 스레드가 완전히 종료될 때까지 메인 스레드가 대기
        print("SystemManager: All component threads stopped.")

# -------------------------------------------------------------------------------------
# [섹션 4] 실행 진입점
# -------------------------------------------------------------------------------------
if __name__ == "__main__": # 이 스크립트가 직접 실행되었을 때만 아래 코드 블록을 실행
    manager = SystemManager() # SystemManager 인스턴스 생성
    try:
        manager.start() # 시스템의 모든 컴포넌트 스레드 시작
        # 메인 스레드는 프로그램이 종료되지 않도록 무한 루프를 돌며 대기
        while True:
            time.sleep(1) # CPU 사용량을 줄이기 위해 1초간 대기
    except KeyboardInterrupt: # 사용자가 Ctrl+C를 눌러 종료 신호를 보낼 경우
        print("\n[System Manager] KeyboardInterrupt 수신. 시스템을 종료합니다.")
    finally: # 예외 발생 여부와 상관없이 항상 실행
        manager.stop() # 시스템의 모든 컴포넌트 스레드를 안전하게 종료
        print("[System Manager] System shutdown completed.")