# =====================================================================================
# FILE: main_server/system_manager.py
#
# PURPOSE:
#   - 메인 서버 애플리케이션의 전체 동작을 총괄하는 컨트롤 타워(Control Tower) 역할.
#   - ImageManager, EventAnalyzer, DataMerger 등 시스템의 핵심 컴포넌트들을 생성.
#   - 컴포넌트 간 데이터 통신을 위한 공유 큐(Queue)를 생성하고 연결해주는 '배선' 작업을 수행.
#   - 모든 컴포넌트 스레드의 생명주기(시작, 종료)를 관리.
#   - 서버 프로그램을 실행하는 메인 진입점(Entry Point)으로 기능함.
#
# 주요 로직:
#   1. 전역 설정:
#      - 로봇, AI 서버, GUI, DB Manager 등 각 컴포넌트의 네트워크 주소와 포트를 정의.
#   2. SystemManager 클래스 (컨트롤 타워):
#      - 데이터 흐름을 위한 공유 큐(image_for_merger_queue, event_result_queue)를 생성.
#      - ImageManager, EventAnalyzer, DataMerger, DBManager 등 모든 핵심 컴포넌트 인스턴스를 생성하고, 생성된 큐와 네트워크 설정을 인자로 전달하여 연결.
#      - 생성된 컴포넌트 인스턴스들을 스레드 리스트로 관리.
#      - start(): 모든 컴포넌트 스레드를 시작.
#      - stop(): 모든 컴포넌트 스레드에 종료 신호를 보내고, 각 스레드가 안전하게 종료될 때까지 대기(join).
#   3. 실행 진입점 (__main__):
#      - SystemManager 인스턴스를 생성.
#      - 시스템 시작을 위해 manager.start() 호출.
#      - KeyboardInterrupt(Ctrl+C)가 발생할 때까지 메인 스레드를 대기.
#      - 인터럽트 발생 시 manager.stop()을 호출하여 전체 시스템을 안전하게 종료.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import threading # 스레드 기능을 사용하기 위한 모듈 임포트
import time # 시간 관련 함수를 사용하기 위한 모듈 임포트
import queue # 큐(Queue) 자료구조를 사용하기 위한 모듈 임포트
from .image_manager import ImageManager # ImageManager 클래스 임포트
from .event_analyzer import EventAnalyzer # EventAnalyzer 클래스 임포트
from .data_merger import DataMerger # DataMerger 클래스 임포트
# [추가] DBManager를 임포트합니다.
from .db_manager import DBManager # DBManager 클래스 임포트

# -------------------------------------------------------------------------------------
# [섹션 2] 전역 설정 (네트워크 주소 및 포트)
# -------------------------------------------------------------------------------------

# 로봇으로부터 이미지 수신을 위한 리스닝 주소
SYSTEM_HOST = "0.0.0.0" # 모든 네트워크 인터페이스에서 수신
IMAGE_RECV_PORT = 9001 # 로봇 이미지를 받을 포트

# 이미지를 전달할 AI 서버의 주소
AI_SERVER_HOST = "127.0.0.1" # AI 서버 IP 주소 (여기서는 로컬호스트)
AI_SERVER_PORT = 9002 # AI 서버 포트

# AI 서버로부터 분석 결과 수신을 위한 리스닝 주소
ANALYSIS_RECV_PORT = 9003 # AI 서버 분석 결과를 받을 포트

# Merger가 최종 결과를 전송할 GUI의 주소
GUI_HOST = "127.0.0.1" # GUI 클라이언트 IP 주소 (여기서는 로컬호스트)
GUI_PORT = 9004 # GUI 클라이언트에 데이터를 보낼 포트

# [추가] DB Manager를 위한 네트워크 설정
DB_MANAGER_HOST = '0.0.0.0' # 모든 IP에서 접속 허용
DB_MANAGER_PORT = 9005      # GUI가 로그인 시 접속할 포트

# -------------------------------------------------------------------------------------
# [섹션 3] SystemManager 클래스 정의
# -------------------------------------------------------------------------------------
class SystemManager: # 시스템의 전체 컴포넌트를 관리하는 클래스
    """
    데이터 흐름을 제어하기 위해 각 컴포넌트를 생성하고 연결하는 메인 클래스.
    """
    def __init__(self): # 생성자 정의
        # [추가] DB 접속 정보 (보안을 위해 별도 파일로 분리하는 것을 강력히 권장)
        DB_CONFIG = { # 데이터베이스 접속 설정 딕셔너리
            'user': 'root', # DB 사용자 이름
            'password': 'qwer1234!@#$', # DB 비밀번호
            'host': '34.47.96.177', # DB 서버 IP 주소
            'database': 'neighbot_db', # 사용할 데이터베이스 이름
            'raise_on_warnings': True # 경고 발생 시 예외 발생 여부
        }
        
        # 데이터 공유 큐 생성
        self.image_for_merger_queue = queue.Queue() # ImageManager에서 DataMerger로 이미지를 전달할 큐
        self.event_result_queue = queue.Queue() # EventAnalyzer에서 DataMerger로 이벤트 결과를 전달할 큐

        # 컴포넌트 인스턴스 생성 및 큐 연결
        image_manager = ImageManager(listen_port=IMAGE_RECV_PORT, # 로봇 이미지 수신 포트 설정
                                       ai_server_addr=(AI_SERVER_HOST, AI_SERVER_PORT), # AI 서버 주소 설정
                                       output_queue=self.image_for_merger_queue) # DataMerger로 보낼 큐 연결
        
        event_analyzer = EventAnalyzer(listen_port=ANALYSIS_RECV_PORT, # AI 서버 분석 결과 수신 포트 설정
                                         output_queue=self.event_result_queue) # DataMerger로 보낼 큐 연결
        
        merger = DataMerger(image_queue=self.image_for_merger_queue, # ImageManager로부터 이미지 받을 큐 연결
                              event_queue=self.event_result_queue, # EventAnalyzer로부터 이벤트 받을 큐 연결
                              gui_addr=(GUI_HOST, GUI_PORT)) # GUI로 결과 보낼 주소 설정
        
        # [추가] DBManager 인스턴스 생성
        db_manager = DBManager(host=DB_MANAGER_HOST, port=DB_MANAGER_PORT, db_config=DB_CONFIG) # DBManager 인스턴스 생성 및 설정

        # 생성된 스레드들을 리스트로 관리
        self.threads = [image_manager, event_analyzer, merger, db_manager] # 모든 컴포넌트 스레드를 리스트에 추가
        
    def start(self): # 모든 컴포넌트 스레드를 시작하는 메서드
        print("SystemManager: Starting all component threads...") # 시작 메시지 출력
        for thread in self.threads: # 스레드 리스트의 각 스레드에 대해
            thread.start() # 스레드 시작
        print("SystemManager: All component threads started.") # 시작 완료 메시지 출력

    def stop(self): # 모든 컴포넌트 스레드를 안전하게 종료하는 메서드
        print("SystemManager: Stopping all component threads...") # 종료 메시지 출력
        for thread in self.threads: # 스레드 리스트의 각 스레드에 대해
            if hasattr(thread, 'stop') and callable(getattr(thread, 'stop')): # 스레드가 'stop' 메서드를 가지고 있다면
                thread.stop() # 해당 스레드의 stop 메서드 호출
        
        for thread in self.threads: # 다시 각 스레드에 대해
            thread.join() # 해당 스레드가 종료될 때까지 대기 (join)
        print("SystemManager: All component threads stopped.") # 종료 완료 메시지 출력

# -------------------------------------------------------------------------------------
# [섹션 4] 실행 진입점
# -------------------------------------------------------------------------------------

if __name__ == "__main__": # 스크립트가 직접 실행될 때만 아래 코드 실행
    manager = SystemManager() # SystemManager 인스턴스 생성
    try:
        manager.start() # 시스템의 모든 컴포넌트 스레드 시작
        # 메인 스레드가 KeyboardInterrupt를 받을 때까지 대기
        while True: # 무한 루프
            time.sleep(1) # 1초마다 대기 (CPU 점유율 낮춤)
    except KeyboardInterrupt: # 사용자가 Ctrl+C를 눌러 KeyboardInterrupt 발생 시
        print("\n[System Manager] KeyboardInterrupt 수신. 시스템을 종료합니다.") # 인터럽트 수신 메시지 출력
        manager.stop() # 시스템의 모든 컴포넌트 스레드 종료
        print("[System Manager] System shutdown completed.") # 시스템 종료 완료 메시지 출력