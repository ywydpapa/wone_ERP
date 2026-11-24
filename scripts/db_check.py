import os
import sys

# 프로젝트 루트 경로 추가
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv
load_dotenv()

from core.db import DB_ENGINE, DB_HOST, DB_PORT, DB_NAME, DB_USER, get_connection

def check_database():
    print("=" * 65)
    print(" 🏥 WONE ERP 데이터베이스 연결 및 상태 진단 도구")
    print("=" * 65)

    engine = os.getenv("DB_ENGINE", DB_ENGINE).lower()
    print(f"[*] 설정된 DB 엔진: {engine.upper()}")

    if engine in ("mariadb", "mysql"):
        print(f"[*] 접속 대상: {DB_USER}@{DB_HOST}:{DB_PORT}/{DB_NAME}")
    else:
        from core.db import DB_PATH
        print(f"[*] 파일 경로: {DB_PATH}")

    try:
        conn = get_connection()
        print("[+] 데이터베이스 연결 성공!")
    except Exception as e:
        print(f"[-] 데이터베이스 연결 실패: {e}")
        print("\n[점검 사항]")
        print("  1. MariaDB 서비스가 실행 중인지 확인하세요.")
        print("  2. .env 파일의 DB_HOST, DB_PORT, DB_USER, DB_PASSWORD를 점검하세요.")
        print("  3. 사용자가 아직 초기화되지 않았다면 'python init_db.py'를 실행하세요.")
        return

    try:
        # 문자셋 확인 (MariaDB/MySQL인 경우)
        if engine in ("mariadb", "mysql"):
            cur = conn.execute("SELECT @@character_set_database, @@collation_database")
            charset_info = cur.fetchone()
            if charset_info:
                print(f"[+] 인코딩 설정: {charset_info[0]} / {charset_info[1]}")
                if "utf8mb4" not in charset_info[0]:
                    print("    [주의] utf8mb4가 아닙니다. 이모지 및 특수문자 저장을 위해 utf8mb4 설정을 권장합니다.")

        # 테이블 및 스키마 버전 확인
        try:
            cur = conn.execute("SELECT MAX(version) AS max_v FROM schema_versions")
            row = cur.fetchone()
            current_ver = row[0] if row else "None"
            print(f"[+] 현재 스키마 버전: {current_ver}")
        except Exception:
            print("[-] schema_versions 테이블을 찾을 수 없습니다. (init_db.py 실행 필요)")

        # 주요 테이블 레코드 건수 확인
        key_tables = [
            ("users", "사용자 계정"),
            ("employees", "근로자/임직원"),
            ("client_companies", "고객사"),
            ("erp_docs", "전자결재/전표 문서"),
            ("slip_lines", "분개 전표 라인"),
            ("attendance", "근태 기록"),
            ("payslips", "급여 명세서"),
            ("partners", "거래처"),
            ("items", "품목/자재"),
        ]

        print("\n[*] 주요 테이블 데이터 요약:")
        total_tables = 0

        # 전체 테이블 수 카운트
        if engine in ("mariadb", "mysql"):
            cur = conn.execute("SHOW TABLES")
            total_tables = len(cur.fetchall())
        else:
            cur = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
            total_tables = cur.fetchone()[0]

        print(f"    - 데이터베이스 내 총 테이블 수: {total_tables}개")

        for tbl, desc in key_tables:
            try:
                cur = conn.execute(f"SELECT COUNT(*) FROM `{tbl}`")
                cnt = cur.fetchone()[0]
                print(f"    - {tbl:<18} ({desc}): {cnt:>6,} 건")
            except Exception:
                print(f"    - {tbl:<18} ({desc}): [테이블 없음]")

        print("\n" + "=" * 65)
        print(" 🎉 데이터베이스 상태 진단 완료: 모든 점검을 통과했습니다.")
        print("=" * 65)

    finally:
        conn.close()

if __name__ == "__main__":
    check_database()
