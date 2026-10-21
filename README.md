# wone_ERP

장애인 친화 고용 플랫폼의 전사 ERP 시스템 (채용 후 단계)

채용 확정 이후의 근태 관리, 업무 보고, 월간 리포트 자동화, 고용장려금/부담금 증빙, 결재를 담당한다. 
채용 전 단계 - wone_Recruit https://github.com/ywydpapa/wone_Recruit

설계 문서: [wone_Recruit/docs/plan.md](https://github.com/ywydpapa/wone_Recruit/blob/master/docs/plan.md): 프로젝트 전체 구조, 비즈니스 모델, DB 설계, 미결 사항

## 기술 스택

- Backend: FastAPI (Python)
- Frontend: Jinja2 + Bootstrap 5 + FontAwesome
- DB: SQLite (개발용) → PostgreSQL (이관 예정)
- Auth: Session 기반 (Starlette SessionMiddleware)

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
main.py          # 앱 엔트리포인트
init_db.py       # DB 초기화 스크립트
funchub.py       # 공용 함수
core/            # 공통 모듈 (DB, 인증 등)
routers/         # auth, dashboard 등 라우터
templates/       # Jinja2 템플릿
static/          # CSS, JS, 이미지
```

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
pip install -r requirements.txt
python scripts/backup_db.py   # DB 백업
python init_db.py             # 미적용 마이그레이션 반영
```

`init_db.py`는 미적용 마이그레이션만 실행하므로 재실행하여도 무방하다.
주민등록번호 암호화 마이그레이션이 포함되어 있으므로 최초 배포 시 아래 암호화 키를 먼저 등록하여야 한다.

## 음성 기능

- 음성 안내: 사용자 PC 내장 한국어 음성(윈도우 Heami, 맥 Yuna 등)을 우선 사용하며, 미설치 시 서버 Supertonic 음성으로 대체한다.
- 음성 인식: 서버 Whisper 모델을 사용한다.
- 모델 파일은 용량 문제로 저장소에서 제외하였다. 신규 서버는 인터넷 연결 상태에서 최초 1회 내려받는다.

```bash
python scripts/fetch_tts.py       # Supertonic 음성 모델 (models/supertonic)
python scripts/fetch_whisper.py   # Whisper 음성 인식 모델
```

- Supertonic과 Whisper는 onnxruntime을 공유한다. 패키지 설치 또는 버전 변경 후 음성 인식 오류 발생 시 서버 로그의 `음성 디코딩 실패`, `서버 VAD 실패` 항목을 확인한다.
- 계정 설정에서 스크린리더 모드를 켠 경우 음성 대신 화면 말풍선으로만 안내한다.

## 개인정보 암호화 배포 절차

주민등록번호는 개인정보 보호법 제24조의2에 따라 암호화하여 저장합니다.
배포 시 아래 순서를 지켜야 하며, 순서가 바뀌면 서버가 기동되지 않습니다.

1. 패키지 설치
   pip install -r requirements.txt

2. 암호화 키 생성 (최초 1회)
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   출력된 값을 서버 환경변수 ERP_RNO_KEY에 등록합니다.

3. 기존 데이터 변환
   python init_db.py
   평문으로 저장된 주민등록번호를 일괄 암호화합니다. 중간에 중단되어도 재실행하면 됩니다.

4. 서버 재시작

### 유의사항
- 암호화 키를 분실하면 저장된 주민등록번호를 복구할 수 없습니다. 키는 서버 외 별도 장소에 보관하여 주십시오.
- 키를 소스코드, DB, 저장소에 포함해서는 안 됩니다.
- ERP_RNO_KEY가 없으면 서버는 기동 시 오류를 출력하고 종료합니다.
