# gui/src/main_window.py
import os
from PyQt5.QtWidgets import QMainWindow, QTabWidget, QLabel, QApplication, QAction, QMessageBox, QVBoxLayout, QWidget # QVBoxLayout, QWidget 추가
from PyQt5 import uic

# 각 탭의 내용을 구성하는 클래스들을 임포트합니다.
from gui.tabs.monitoring_tab import MonitoringTab
# Mission Management 탭을 위한 클래스도 만들어야 합니다 (예: MissionManagementTab). 여기서는 임시로 처리합니다.
# from gui.tabs.mission_management_tab import MissionManagementTab # 추후 이 클래스를 만들고 임포트

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # main_window.ui 파일 로드 (경로는 기존과 동일하게 프로젝트 구조에 맞게 설정)
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "main_window.ui")
        uic.loadUi(ui_path, self)
        
        self.setWindowTitle("Patrol Robot System NeighBot - 메인 시스템")
        # self.setMinimumSize(1300, 750) # 이 값은 main_window.ui에서도 설정 가능합니다.
        
        # Qt Designer에서 QTabWidget의 objectName을 "tabWidget"으로 하셨으므로, 아래 코드는 유효합니다.
        self.tabWidget = self.findChild(QTabWidget, "tabWidget") #
        
        self.init_tabs() # 수정된 init_tabs 메서드 호출
        self.init_exit_action()

    def init_tabs(self):
        """
        main_window.ui에 정의된 탭 페이지들을 찾아 각 페이지에 적절한 내용을 채웁니다.
        """
        if not self.tabWidget:
            print("[오류] 'tabWidget'을 main_window.ui에서 찾을 수 없습니다.")
            return

        # 1. "Main Monitoring" 탭 (main_window.ui에서 objectName="main_tab"으로 정의된 페이지)
        main_monitoring_page_widget = self.tabWidget.findChild(QWidget, "main_tab") #
        if main_monitoring_page_widget:
            # MonitoringTab 클래스의 인스턴스 생성 (이 클래스는 monitoring_tab.ui를 로드하여 자신의 UI를 구성)
            self.monitoring_tab_content = MonitoringTab(self) # 부모를 self (MainWindow)로 설정 가능
            
            # MonitoringTab의 내용물(self.monitoring_tab_content)을 main_tab 페이지의 레이아웃에 추가합니다.
            main_monitoring_page_widget.layout().addWidget(self.monitoring_tab_content)
        else:
            print("[경고] 'main_tab' 페이지를 main_window.ui에서 찾을 수 없습니다.")

        # 2. "Mission Management" 탭 (main_window.ui에서 objectName="manage_tab"으로 정의된 페이지)
        mission_management_page_widget = self.tabWidget.findChild(QWidget, "manage_tab") #
        if mission_management_page_widget:
            # TODO: MissionManagementTab 클래스를 만들고, 해당 클래스가 mission_management_tab.ui를 로드하도록 구현해야 합니다.
            # 여기서는 임시로 QLabel을 사용합니다.
            # self.mission_management_tab_content = MissionManagementTab(self) # 실제 구현 시
            self.mission_management_tab_content = QLabel("Mission Management 탭의 내용 (MissionManagementTab으로 교체 예정)", self)
            
            mission_management_page_widget.layout().addWidget(self.mission_management_tab_content)
        else:
            print("[경고] 'manage_tab' 페이지를 main_window.ui에서 찾을 수 없습니다.")

    def init_exit_action(self):
        exit_action = self.findChild(QAction, "actionExit")
        if exit_action:
            exit_action.triggered.connect(self.show_exit_confirmation)
        else:
            print("[경고] 'actionExit' 메뉴 액션을 찾을 수 없습니다. UI 파일을 확인하세요.")

    def show_exit_confirmation(self):
        reply = QMessageBox.question(self, '종료 확인',
                                     '정말 애플리케이션을 종료하시겠습니까?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            # 카메라 스레드 등 자원 정리 코드가 있다면 여기서 호출하는 것이 좋습니다.
            if hasattr(self, 'monitoring_tab_content') and self.monitoring_tab_content.camera_thread and self.monitoring_tab_content.camera_thread.isRunning():
                 print("메인 윈도우 종료 시 카메라 스레드 중지 시도")
                 self.monitoring_tab_content.camera_thread.stop()
                 self.monitoring_tab_content.camera_thread.wait(500) # 필요시 대기 시간 조절
            QApplication.instance().quit()

    def closeEvent(self, event):
        self.show_exit_confirmation() # 종료 확인 다이얼로그 표시
        event.ignore() # 기본 종료 이벤트 무시 (다이얼로그에서 Yes를 눌러야 종료됨)