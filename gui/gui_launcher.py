# gui/gui_launcher.py
import sys
from PyQt5.QtWidgets import QApplication
from .main_gui import MainApplication

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_app = MainApplication(app)
    sys.exit(app.exec_())