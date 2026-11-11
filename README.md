# wone_ERP

장애인 친화 고용 플랫폼의 전사 ERP 시스템입니다 (채용 후 단계).

채용 확정 이후의 근태 관리, 업무 보고, 월간 리포트, 고용장려금/부담금 증빙, 결재를 담당합니다.
채용 전 단계는 [wone_Recruit](https://github.com/ywydpapa/wone_Recruit)에서 담당합니다.

## 기술 스택

- Backend: FastAPI (Python)
- Frontend: Jinja2 + Bootstrap 5 + FontAwesome
- DB: SQLite (erp.db)
- Auth: 세션 기반 (Starlette SessionMiddleware)

## 실행 방법

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python init_db.py        # DB 초기화 (erp.db 생성)
uvicorn main:app --reload
```

## 구조

```
main.py            # 앱 엔트리포인트, 미들웨어, 정적 파일 MIME 지정
init_db.py         # 미적용 마이그레이션 실행
migrate.py         # 마이그레이션 실행기
migrations/        # 001~132 순번 마이그레이션
seed_sample.py     # 로컬 테스트용 샘플 데이터
core/              # 업무 로직 (급여, 근태, 결재, 전표, 재고 등)
  db.py            # DB 연결 (erp.db)
  deps.py          # 세션 확인, 템플릿 공통
  crypto.py        # 주민등록번호 암호화
  workflow.py      # 업무요청 상태 전이
routers/           # 화면, API 라우터
  erp_*.py         # 재무, 구매, 영업, 재고, 생산
  hr*.py           # 인사, 근태, 급여 장부
  client*.py       # 고객사 담당자 화면
  worker*.py       # 근로자 화면
  platform*.py     # wone 운영자 화면
  accessibility.py # 음성 인식(Whisper), 음성 안내(Supertonic)
templates/         # Jinja2 템플릿, base.html에 사이드바와 공통 스크립트
static/js/         # 화면 스크립트
help/              # 화면 도움말 데이터(JSON), 수정 시 서버 재시작 필요
scripts/           # DB 백업, 음성 모델 다운로드
tests/             # pytest, tests/js는 음성 명령 분류 테스트
var/               # 업로드 파일, DB 백업 (저장소 제외)
```

### 화면 스크립트

| 파일 | 역할 |
|---|---|
| voice-parse.js | 인식된 문장을 명령 종류로 분류 |
| voice.js | 명령 실행, 받아쓰기, 브라우저 VAD, 음성 안내 재생 |
| erp-voice.js | ERP 목록, 행 선택 등 업무 화면 명령 |
| worker-voice.js | 근로자 화면 명령, 본인 확인 |
| screen-read.js | 화면 읽기 대상 추출 |
| a11y-widget.js | 접근성 설정 위젯 (고대비, 글자 크기 등) |
| headmouse.js | 헤드마우스 |
| form-kit.js | 금액 입력 서식 등 폼 공통 |
| mdi.js | 탭 작업창 |
| aline.js | 결재선 편집 |

음성 명령은 voice-parse.js의 `classify`에 분류를 추가한 뒤 voice.js 실행부에 연결합니다. 사이드바 조작은 base.html의 `toggleSidebar`, `toggleSubmenu`를 사용합니다.

## 현재 구현 상태

- 인사: 직원 등록, 근로자 명부, 근로계약서, 인사발령, 증명서 발급, 교육 이력
- 근태/급여: 출퇴근, 연차, 근태 이의신청, 급여 확정 및 지급, 원천세, 퇴직소득세, 4대보험 신고
- 재무: 전표, 장부, 재무제표, 부가세, 세금계산서, 예산, 고정자산
- 구매/영업/재고/생산: 구매요청~입고검사, 견적~출고, 재고 수불 및 실사, 작업지시
- 결재: 결재선, 대결자 지정, 문서별 결재 통합
- 장애인 고용: 고용 현황 보고, 고용장려금 산정 자료
- 접근성: 음성 명령 및 안내, 헤드마우스, 고대비, 스크린리더 모드

## 배포 절차

```bash
git pull
pip install -r requirements.txt
python scripts/backup_db.py   # DB 백업
python init_db.py             # 미적용 마이그레이션 반영
```

이후 서버를 재시작합니다.

- `init_db.py`는 미적용 마이그레이션만 실행하므로 재실행해도 무방합니다.
- 최초 배포 시에는 아래 암호화 키를 먼저 등록해야 합니다.

## 개인정보 암호화

주민등록번호는 개인정보 보호법 제24조의2에 따라 암호화하여 저장합니다.

### 최초 1회 키 등록

1. 키 생성
   ```bash
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. 출력된 값을 `.env`에 `ERP_RNO_KEY=출력값` 형식으로 추가합니다.
3. 배포 절차대로 `init_db.py`를 실행합니다. 기존 평문 주민등록번호가 일괄 암호화되며, 중단 시 재실행하면 됩니다.

### 유의사항

- 키를 분실하면 저장된 주민등록번호를 복구할 수 없습니다. 서버 외 별도 장소에 보관해 주십시오.
- 키는 소스코드, DB, 저장소에 포함하지 않도록 주의해 주십시오.
- `ERP_RNO_KEY`가 없으면 서버가 기동 시 오류를 출력하고 종료합니다.

## 음성 기능

- 음성 안내: 사용자 PC 내장 한국어 음성(윈도우 Heami, 맥 Yuna 등)을 우선 사용하며, 미설치 시 서버 Supertonic 음성으로 대체합니다.
- 음성 인식: 서버 Whisper 모델을 사용합니다.
- 모델 파일은 용량 문제로 저장소에서 제외했습니다. 신규 서버는 인터넷 연결 상태에서 최초 1회 내려받습니다.

```bash
python scripts/fetch_tts.py       # Supertonic 음성 모델 (models/supertonic)
python scripts/fetch_whisper.py   # Whisper 음성 인식 모델
```

- Supertonic과 Whisper는 onnxruntime을 공유합니다. 패키지 설치 또는 버전 변경 후 음성 인식 오류가 발생하면 서버 로그의 `음성 디코딩 실패`, `서버 VAD 실패` 항목을 확인합니다.
- 계정 설정에서 스크린리더 모드를 켠 경우 음성 대신 화면 말풍선으로만 안내합니다.
