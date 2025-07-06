# 사용할 기본 이미지 (Python 3.12)
FROM python:3.12-slim-bullseye

# 컨테이너 내부에서 작업할 디렉토리 설정
WORKDIR /app

# 시스템 의존성 설치
# 각 줄 끝의 '\' 뒤에 공백이 없어야 하며, 다음 줄 시작 시 불필요한 공백이 없도록 주의
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xrm0 \
    libxcb-xtest0 \
    libxcb-composite0 \
    libxcb-cursor0 \
    libxcb-damage0 \
    libxcb-dpms0 \
    libxcb-dri2-0 \
    libxcb-dri3-0 \
    libxcb-glx0 \
    libxcb-present0 \
    libxcb-record0 \
    libxcb-res0 \
    libxcb-screensaver0 \
    libxcb-shm0 \
    libxcb-util1 \
    libxcb-xf86dri0 \
    libxcb-xv0 \
    libxcb-xvmc0 \
    libxcb-sync-dev \
    libxcb-icccm4-dev \
    libxcb-render-util0-dev \
    libxcb-xkb-dev \
    libxext-dev \
    libxrender-dev \
    libfontconfig1 \
    libfreetype6 \
    xserver-xorg-video-dummy \
    xvfb \
    ffmpeg && \
    rm -rf /var/lib/apt/lists/*
# 파이썬 의존성 설치
# requirements.txt를 먼저 복사하여 캐싱 활용 (파일 변경 시에만 이 단계 재실행)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 프로젝트 소스 코드 복사
COPY . .

# 환경 변수 설정
# GUI 실행을 위한 DISPLAY 설정 (Xvfb 사용)
ENV DISPLAY=:99
# PyQt5가 XCB 플러그인을 찾을 수 있도록 설정
ENV QT_QPA_PLATFORM=offscreen

# PORT 설정 (시스템 아키텍처에 명시된 포트들)
EXPOSE 9001/udp  
EXPOSE 9002/udp 
EXPOSE 9003/TCP
EXPOSE 9004/TCP
EXPOSE 9005/TCP
EXPOSE 9006/TCP
EXPOSE 9008/TCP

# 애플리케이션 시작 명령어
CMD ["/bin/bash", "-c", "Xvfb :99 -screen 0 1280x720x24 & \
    python3 main_server/system_manager.py"]