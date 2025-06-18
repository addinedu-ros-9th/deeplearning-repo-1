# gui/tabs/monitoring_tab.py

from PyQt5.QtWidgets import QWidget
from PyQt5.uic import loadUi

# MonitoringTab: Main Monitoring 탭의 UI 로드만 담당
class MonitoringTab(QWidget):
    def __init__(self):
        super().__init__()
        loadUi('./gui/ui/monitoring_tab.ui', self)
