# =====================================================================================
# FILE: main_server/system_manager.py
#
# PURPOSE:
#   - 메인 서버 애플리케이션의 전체 동작을 총괄하는 컨트롤 타워(Control Tower) 역할.
#   - ImageManager, EventAnalyzer, DataMerger 등 시스템의 핵심 컴포넌트들을 생성.
#   - 컴포넌트 간 데이터 통신을 위한 공유 큐(Queue)를 생성하고 연결해주는 '배선' 작업을 수행.
#   - 모든 컴포넌트 스레드의 생명주기(시작, 종료)를 관리.
#   - 서버 프로그램을 실행하는 메인 진입점(Entry Point)으로 기능함.
# =====================================================================================

# -------------------------------------------------------------------------------------
# [섹션 1] 모듈 임포트
# -------------------------------------------------------------------------------------
import threading
import time
import queue
from .image_manager import ImageManager
from .event_analyzer import EventAnalyzer
from .data_merger import DataMerger
# [추가] DBManager를 임포트합니다.
from .db_manager import DBManager

# -------------------------------------------------------------------------------------
# [섹션 2] 전역 설정 (네트워크 주소 및 포트)
# -------------------------------------------------------------------------------------

# 로봇으로부터 이미지 수신을 위한 리스닝 주소
SYSTEM_HOST = "0.0.0.0"
IMAGE_RECV_PORT = 9001

# 이미지를 전달할 AI 서버의 주소
AI_SERVER_HOST = "127.0.0.1"
AI_SERVER_PORT = 9002

# AI 서버로부터 분석 결과 수신을 위한 리스닝 주소
ANALYSIS_RECV_PORT = 9003

# Merger가 최종 결과를 전송할 GUI의 주소
GUI_HOST = "127.0.0.1"
GUI_PORT = 9004

# [추가] DB Manager를 위한 네트워크 설정
DB_MANAGER_HOST = '0.0.0.0' # 모든 IP에서 접속 허용
DB_MANAGER_PORT = 9005      # GUI가 로그인 시 접속할 포트

# -------------------------------------------------------------------------------------
# [섹션 3] SystemManager 클래스 정의
# -------------------------------------------------------------------------------------
class SystemManager:
    """
    데이터 흐름을 제어하기 위해 각 컴포넌트를 생성하고 연결하는 메인 클래스.
    """
    def __init__(self):
        # [추가] DB 접속 정보 (보안을 위해 별도 파일로 분리하는 것을 강력히 권장)
        DB_CONFIG = {
            'user': 'root',
            'password': 'qwer1234!@#$',
            'host': '34.47.96.177',
            'database': 'neighbot_db',
            'raise_on_warnings': True
        }
        
        # 데이터 공유 큐 생성
        self.image_for_merger_queue = queue.Queue()
        self.event_result_queue = queue.Queue()

        # 컴포넌트 인스턴스 생성
        image_manager = ImageManager(listen_port=IMAGE_RECV_PORT,
                                       ai_server_addr=(AI_SERVER_HOST, AI_SERVER_PORT),
                                       output_queue=self.image_for_merger_queue)
        
        event_analyzer = EventAnalyzer(listen_port=ANALYSIS_RECV_PORT,
                                         output_queue=self.event_result_queue)
        
        merger = DataMerger(image_queue=self.image_for_merger_queue,
                              event_queue=self.event_result_queue,
                              gui_addr=(GUI_HOST, GUI_PORT))
        
        # [추가] DBManager 인스턴스 생성
        db_manager = DBManager(host=DB_MANAGER_HOST, port=DB_MANAGER_PORT, db_config=DB_CONFIG)
        
        # 생성된 스레드들을 리스트로 관리
        self.threads = [image_manager, event_analyzer, merger, db_manager]
        
    def start(self):
        print("SystemManager: Starting all component threads...")
        for thread in self.threads:
            thread.start()
        print("SystemManager: All component threads started.")

    def stop(self):
        print("SystemManager: Stopping all component threads...")
        for thread in self.threads:
            if hasattr(thread, 'stop') and callable(getattr(thread, 'stop')):
                thread.stop()
        
        for thread in self.threads:
            thread.join() 
        print("SystemManager: All component threads stopped.")

# -------------------------------------------------------------------------------------
# [섹션 4] 실행 진입점
# -------------------------------------------------------------------------------------

if __name__ == "__main__":
    manager = SystemManager()
    try:
        manager.start()
        # 메인 스레드가 KeyboardInterrupt를 받을 때까지 대기
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[System Manager] KeyboardInterrupt 수신. 시스템을 종료합니다.")
        manager.stop()
        print("[System Manager] System shutdown completed.")