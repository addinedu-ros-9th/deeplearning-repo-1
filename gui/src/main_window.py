# gui/src/main_window.py

# ... (기존 import문들) ...
from PyQt5.QtWidgets import QMainWindow, QTabWidget, QLabel, QApplication, QAction, QMessageBox #
from PyQt5.QtCore import QTimer, QSize #
from PyQt5 import uic #
import os #

# MonitoringTab 클래스를 임포트합니다.
from gui.tabs.monitoring_tab import MonitoringTab # 경로가 맞는지 확인해주세요.


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "main_window.ui") #
        uic.loadUi(ui_path, self) #
        
        self.setWindowTitle("Patrol Robot System NeighBot - 메인 시스템") #
        self.setMinimumSize(1300, 750) #
        
        self.tabWidget = self.findChild(QTabWidget, "tabWidget") #
        self.init_tabs() #
        self.init_exit_action() #

    def init_tabs(self):
        """메인 윈도우의 탭들을 초기화합니다."""
        if not self.tabWidget: #
            print("[오류] 탭 위젯을 찾을 수 없습니다.") #
            return #
        
        self.tabWidget.setMinimumSize(1280, 680) #
        
        while self.tabWidget.count() > 0: #
            self.tabWidget.removeTab(0) #
            
        # MonitoringTab 인스턴스 생성 및 추가
        self.monitoring_tab_widget = MonitoringTab(self) # self를 부모로 전달
        self.tabWidget.addTab(self.monitoring_tab_widget, "Main Monitoring")
        
        # 나머지 플레이스홀더 탭 추가 (기존 방식 유지)
        self.tabWidget.addTab(QLabel("미션 관리 탭 (구현 예정)"), "Mission Management") #
        self.tabWidget.addTab(QLabel("이벤트 로그 탭 (구현 예정)"), "Event Log") #
        self.tabWidget.addTab(QLabel("설정 탭 (구현 예정)"), "Settings") #
        
    def init_exit_action(self): #
        exit_action = self.findChild(QAction, "actionExit") #
        if exit_action: #
            exit_action.triggered.connect(self.show_exit_confirmation) #
        else: #
            print("[경고] 'actionExit' 메뉴 액션을 찾을 수 없습니다. UI 파일을 확인하세요.") #

    def show_exit_confirmation(self): #
        reply = QMessageBox.question(self, '종료 확인', #
                                     '정말 애플리케이션을 종료하시겠습니까?', #
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No) #

        if reply == QMessageBox.Yes: #
            QApplication.instance().quit() #

    def closeEvent(self, event): #
        self.show_exit_confirmation() #
        event.ignore() #

    # ... (refresh_battery_status 메서드는 필요 없으므로 주석 처리 또는 삭제) ...