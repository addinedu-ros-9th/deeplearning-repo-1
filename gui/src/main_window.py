# gui/src/main_window.py
import os
from PyQt5.QtWidgets import QMainWindow, QTabWidget, QLabel, QApplication, QAction, QMessageBox, QWidget
from PyQt5 import uic

# [경로 수정]
# main_window.py는 src 폴더 안에 있으므로,
# 형제 폴더인 tabs 폴더 안의 monitoring_tab 모듈을 임포트합니다.
from ..tabs.monitoring_tab import MonitoringTab 

# Mission Management 탭을 위한 클래스도 만들어야 합니다 (예: MissionManagementTab).
# from tabs.mission_management_tab import MissionManagementTab # 추후 이 클래스를 만들고 임포트

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        # ui 파일 경로는 현재 파일 위치(__file__)를 기준으로 재계산됩니다.
        ui_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui", "main_window.ui")
        uic.loadUi(ui_path, self)
        
        self.setWindowTitle("Patrol Robot System NeighBot - 메인 시스템")
        self.setFixedSize(1280, 960)
        
        # Qt Designer에서 정의한 QTabWidget을 찾습니다.
        self.tabWidget = self.findChild(QTabWidget, "tabWidget")
        
        self.init_tabs()
        self.init_exit_action()

    def init_tabs(self):
        """
        main_window.ui에 미리 정의된 탭 페이지들을 찾아 각 페이지에 적절한 위젯을 채웁니다.
        이 로직은 이전과 동일합니다.
        """
        if not self.tabWidget:
            print("[오류] 'tabWidget'을 main_window.ui에서 찾을 수 없습니다.")
            return

        # 1. "Main Monitoring" 탭 채우기 (ui 파일의 objectName: main_tab)
        main_monitoring_page = self.tabWidget.findChild(QWidget, "main_tab")
        if main_monitoring_page:
            self.monitoring_tab_content = MonitoringTab(self)
            # main_tab의 레이아웃에 MonitoringTab 위젯을 추가
            main_monitoring_page.layout().addWidget(self.monitoring_tab_content)
        else:
            print("[경고] 'main_tab' 페이지를 찾을 수 없습니다.")

        # 2. "Mission Management" 탭 채우기 (ui 파일의 objectName: manage_tab)
        logdata_management_page = self.tabWidget.findChild(QWidget, "manage_tab")
        if logdata_management_page:
            # TODO: MissionManagementTab 클래스를 만들고 아래 코드의 주석을 해제하세요.
            # self.logdata_management_tab_content = MissionManagementTab(self)
            self.logdata_management_tab_content = QLabel("Logdata Management 탭 (구현 예정)", self)
            logdata_management_page.layout().addWidget(self.logdata_management_tab_content)
        else:
            print("[경고] 'manage_tab' 페이지를 찾을 수 없습니다.")

        # 3. "System Settings" 탭 채우기 (ui 파일의 objectName: system_tab)
        system_settings_page = self.tabWidget.findChild(QWidget, "system_tab")
        if system_settings_page:
            # TODO: SettingsTab 클래스를 만들고 아래 코드의 주석을 해제하세요.
            self.system_settings_tab_content = QLabel("System Settings 탭 (구현 예정)", self)
            system_settings_page.layout().addWidget(self.system_settings_tab_content)
        else:
            print("[경고] 'system_tab' 페이지를 찾을 수 없습니다.")

    def init_exit_action(self):
        """
        메뉴의 '종료' 액션을 찾아 함수와 연결합니다. 이전과 동일합니다.
        """
        exit_action = self.findChild(QAction, "actionExit")
        if exit_action:
            exit_action.triggered.connect(self.show_exit_confirmation)
        else:
            print("[경고] 'actionExit' 메뉴를 찾을 수 없습니다.")

    def show_exit_confirmation(self):
        """
        종료 확인 대화상자를 표시합니다. 이전과 동일합니다.
        """
        reply = QMessageBox.question(self, '종료 확인', '정말 애플리케이션을 종료하시겠습니까?',
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)

        if reply == QMessageBox.Yes:
            # 카메라 스레드 등 백그라운드 스레드를 여기서 안전하게 종료해야 합니다.
            if hasattr(self, 'monitoring_tab_content'):
                 self.monitoring_tab_content.clean_up() # MonitoringTab의 정리 함수 호출
            QApplication.instance().quit()

    def closeEvent(self, event):
        """
        윈도우의 'X' 버튼을 눌렀을 때 호출됩니다. 이전과 동일합니다.
        """
        self.show_exit_confirmation()
        event.ignore() # 기본 종료 이벤트를 무시하고, 우리 방식대로 종료 처리