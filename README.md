# 🛡️ NEIGHBOT - AI 기반 자율 순찰 로봇 시스템
<p align="center">
  <img src="https://github.com/user-attachments/assets/3d17872c-ab10-4d6a-b9f8-281d113cd8c1" width="300"/>
</p>

> “Neighborhood + Robot”  
> 생활 속 위험 요소를 감지하고 대응하는 AI 순찰 시스템

# 📚 목차

- [1. 프로젝트 소개](#1-프로젝트-소개)
- [2. 시스템 구조](#2-시스템-구조)
- [3. 주요 기능](#3-주요-기능)
- [4. 핵심 기술](#4-핵심-기술)
- [5. 트러블 슈팅 사례](#5-트러블-슈팅-사례)
- [6. 회고 및 향후 계획](#6-회고-및-향후-계획)
- [7. 기술 스택](#7-기술-스택)
- [8. 팀원 소개](#8-팀원-소개)


---

# 1. 프로젝트 소개
> ⏰ 프로젝트 기간: 2025.05.22 ~ 2025.07.02
<p align="center">
  <img src="image.png" width="500"/>
</p>


**Neighbot**은 도심 내 사각지대에서 발생할 수 있는 **위험 상황(무기, 쓰러짐, 흡연 등)** 을 실시간으로 감지하고,  
그에 맞는 **알림 및 대응 기능**을 제공하는 **AI 기반 순찰 로봇 시스템**입니다.  
※ 실제 물리적 로봇이 아닌, **로봇을 위한 통합 시스템** 구축이 본 프로젝트의 핵심입니다.

- 최근 중국의 자율 경찰 로봇 도입 사례 참고
- 문제 조기 감지 및 초기 대응 시간 단축
- 글로벌 AI 감시 기술 트렌드 반영

---

# 2. 시스템 구조

## 시스템 아키텍쳐
<p align="center">
  <img src="image-1.png" width="500"/>
</p>

## ER 다이어그램
<p align="center">
  <img src="image-2.png" width="500"/>
</p>

## State 다이어그램
<p align="center">
  <img src="image-3.png" width="300"/>
</p>

[로봇] → 영상 송출
↓
[AI 서버] → YOLO 분석
↓
[메인 서버] → 데이터 통합, 명령 판단
↓
[GUI/DB] → 실시간 모니터링, 영상/사건 저장


- `ai_server/` - YOLO 분석 및 감지 처리
- `main_server/` - 분석 결과 통합, 판단, DB 관리
- `robot/` - 영상 전송 및 명령 수신
- `gui/` - PyQt 기반 사용자 인터페이스
- `shared/` - 메시지 프로토콜 및 유틸리티 모듈

> 📁 디렉토리 구조: [`프로젝트 Neighbot 디렉토리 구조.md`](./프로젝트%20Neighbot%20디렉토리%20구조.md) 참고


---

# 3. 주요 기능

- **YOLO 기반 객체 인식 (총, 칼, 담배)**
- **YOLO Pose 기반 쓰러짐 감지**
- **GUI 실시간 영상 모니터링 및 경보 대응**
- **사건 로그 자동 저장 및 조회 기능**
- **원격 로봇 제어 (이동, 순찰, 복귀 명령)**


---

# 4. 핵심 기술
## 감지 모델 & 사건 종류

| 항목     | 모델             | 조건                            | 사건 유형          |
|----------|------------------|----------------------------------|---------------------|
| 총       | YOLO Segmentation | 2초 이내 40% 프레임 이상 감지   | 불법 무기 소지     |
| 칼       | YOLO Segmentation | 2초 이내 40% 프레임 이상 감지   | 흉기 난동           |
| 담배     | YOLO Detection    | 2초 이내 40% 프레임 이상 감지   | 불법 흡연           |
| 쓰러짐   | YOLO Pose         | 2초 이내 40% 프레임 이상 감지   | 응급 상황 (실신 등) |

---

## 판단 알고리즘

단순 "객체 검출"이 아닌, **일정 시간 동안의 프레임 비율과 confidence 값을 종합 판단**하여 상황을 판단하는 알고리즘 적용  
→ False Positive(오탐) 감소, 신뢰도 향상

---

# 5. 트러블 슈팅 사례

- **쓰러짐 감지 성능 저하**
  - 누드 모델 학습 → 옷 입은 사람에 대한 인식률 저하
  - 해결: Skeleton 기반 MLP 모델 결합하여 개선

- **스트리밍 지연 현상**
  - 데이터 병합 스레드의 병목 → 과거 프레임 급재생
  - 해결: Timeout 설정 + 데이터 큐 최적화

- **YOLO 오탐지 문제**
  - 유사 객체 탐지 / Angle variation 취약
  - 해결: Negative set 강화 + Seg 모델 전환

---

# 6. 회고 및 향후 계획

- 기술조사 단계가 미흡해 초기 설계 시간이 부족했음
- 딥러닝 모델의 내부 알고리즘 설계 필요성 확인
- Skeleton 기반 판별 모델 및 학습 최적화 지속 예정


---

# 7. 기술 스택

| 분류 | 구성 | |
|------|------|--|
| **운영 체제** | Ubuntu 24.04 | ![Ubuntu](https://img.shields.io/badge/Ubuntu-E95420?style=for-the-badge&logo=Ubuntu&logoColor=white) |
| **개발 언어** | Python 3.10 | ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white) |
| **프레임워크** | YOLOv8, OpenCV | ![YOLO](https://img.shields.io/badge/YOLOv8-FF7F50?style=for-the-badge&logo=openai&logoColor=white) ![OpenCV](https://img.shields.io/badge/OpenCV-5C3EE8?style=for-the-badge&logo=opencv&logoColor=white) |
| **UI 프레임워크** | PyQt5 | ![PyQt](https://img.shields.io/badge/PyQt5-41CD52?style=for-the-badge&logo=qt&logoColor=white) |
| **DB** | MySQL (GCP 기반) | ![MySQL](https://img.shields.io/badge/MySQL-4479A1?style=for-the-badge&logo=mysql&logoColor=white) |
| **버전 관리** | Git / GitHub | ![Git](https://img.shields.io/badge/git-F05032?style=for-the-badge&logo=git&logoColor=white) ![GitHub](https://img.shields.io/badge/github-181717?style=for-the-badge&logo=github&logoColor=white) |
| **협업 도구** | Jira, Confluence, Slack | ![Jira](https://img.shields.io/badge/Jira-0052CC?style=for-the-badge&logo=Jira&logoColor=white) ![Confluence](https://img.shields.io/badge/Confluence-172B4D?style=for-the-badge&logo=confluence&logoColor=white) ![Slack](https://img.shields.io/badge/slack-4A154B?style=for-the-badge&logo=slack&logoColor=white) |


---


# 8. 팀원 소개

| 이름     | 역할 | 담당 업무 |
|----------|------|-----------|
| **이건우** (팀장) | 시스템 설계 총괄 | - Neighbot 로봇 시스템 개발<br>- 문제 상황 판단 알고리즘 개발<br>- YOLO Segmentation 모델 구현 |
| **박태환** (팀원) | AI 백엔드 개발 | - AI 서버 백엔드 시스템 개발<br>- YOLO Pose 모델 구현<br>- YOLO Object Detection 모델 구현 |
| **김민수** (팀원) | GUI & 아키텍처 | - GUI 디자인 및 시스템 개발<br>- DB 설계 및 구성<br>- Interface Spec & 통신 규약 설계<br>- 시스템 아키텍처 도안 |
| **이승훈** (팀원) | 메인 서버 개발 | - Main 서버 백엔드 시스템 개발<br>- Jira 스케줄 관리 보조<br>- PyQt GUI 초기 설계 |
| **김대인** (팀원) | 문서 & 테스트 관리 | - Jira 스케줄 & 업무 & 미팅 관리<br>- 시스템 시나리오 제작<br>- Confluence 문서 관리<br>- 연동 테스트 기획 및 진행<br>- YOLO Pose 모델 학습 보조 |
