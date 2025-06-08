# main_server/system_launcher.py
from .system_manager import SystemManager

if __name__ == '__main__':
    server = SystemManager()
    server.start()

# python -m main_server.system_launcher