#!/bin/bash
# 크로스테넌트 접근 차단 회귀 체크. 8001 서버 기동 상태에서 실행
set -u
BASE=http://localhost:8001
DB=erp.db
A=hanyang_mgr
B=daehan_mgr
PASS=0
FAIL=0

login() {
  local tok
  tok=$(curl -s -c "$2" $BASE/login | grep -o '[a-f0-9]\{64\}' | head -1)
  curl -s -b "$2" -c "$2" -o /dev/null -d "username=$1&password=1234&csrf_token=$tok" $BASE/login_check
}

check() {
  if [ "$3" = "$2" ]; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
    echo "FAIL: $1 (기대 $2, 실제 $3)"
  fi
}

# B사 자원 id 수집
B_REQ=$(sqlite3 $DB "SELECT wr.id FROM work_requests wr JOIN client_users cu ON cu.company_id=wr.company_id JOIN users u ON u.id=cu.user_id WHERE u.username='$B' LIMIT 1")
B_TASK=$(sqlite3 $DB "SELECT t.id FROM tasks t JOIN work_requests wr ON t.work_request_id=wr.id JOIN client_users cu ON cu.company_id=wr.company_id JOIN users u ON u.id=cu.user_id WHERE u.username='$B' LIMIT 1")
B_EMP=$(sqlite3 $DB "SELECT e.id FROM employees e JOIN client_users cu ON cu.company_id=e.company_id JOIN users u ON u.id=cu.user_id WHERE u.username='$B' LIMIT 1")
B_LEAVE_FILE=$(sqlite3 $DB "SELECT lr.attachment FROM leave_requests lr JOIN employees e ON lr.employee_id=e.id JOIN client_users cu ON cu.company_id=e.company_id JOIN users u ON u.id=cu.user_id WHERE u.username='$B' AND lr.attachment != '' LIMIT 1" | sed 's/^.*|//')

login $A /tmp/tenant_a.txt

code() { curl -s -b /tmp/tenant_a.txt -o /dev/null -w "%{http_code}" "$1"; }

[ -n "$B_REQ" ]  && check "타사 요청 반출" 303 "$(code $BASE/client/requests/$B_REQ/export)"
[ -n "$B_REQ" ]  && check "타사 산출물 zip" 303 "$(code $BASE/client/requests/$B_REQ/deliverables.zip)"
[ -n "$B_REQ" ]  && check "타사 요청 상세" 303 "$(code $BASE/client/requests/$B_REQ)"
[ -n "$B_TASK" ] && check "타사 태스크 상세" 303 "$(code $BASE/client/tasks/$B_TASK)"
[ -n "$B_EMP" ]  && check "타사 직원 근태" 303 "$(code $BASE/client/attendance/$B_EMP)"
[ -n "$B_LEAVE_FILE" ] && check "타사 휴가 첨부" 404 "$(code $BASE/files/leave/$B_LEAVE_FILE)"
check "client 검색 전표 미노출" 0 "$(curl -s -b /tmp/tenant_a.txt "$BASE/api/search?q=EXP" | grep -c '"slip"')"

# 근로자: 미배정 태스크 차단
login kim_sujin /tmp/tenant_w.txt
W_OTHER_TASK=$(sqlite3 $DB "SELECT t.id FROM tasks t WHERE t.assigned_to IS NOT NULL AND t.assigned_to != (SELECT e.id FROM employees e JOIN users u ON e.user_id=u.id WHERE u.username='kim_sujin') LIMIT 1")
[ -n "$W_OTHER_TASK" ] && check "근로자 미배정 태스크" 303 "$(curl -s -b /tmp/tenant_w.txt -o /dev/null -w "%{http_code}" $BASE/task/$W_OTHER_TASK)"

# 근로자: 타사 task_id 걸린 PO 상세 차단
X_PO=$(sqlite3 $DB "SELECT po.id FROM purchase_orders po JOIN tasks t ON po.task_id=t.id JOIN work_requests wr ON t.work_request_id=wr.id WHERE wr.company_id != (SELECT e.company_id FROM employees e JOIN users u ON e.user_id=u.id WHERE u.username='kim_sujin') LIMIT 1")
[ -n "$X_PO" ] && check "근로자 타사 발주 상세" 303 "$(curl -s -b /tmp/tenant_w.txt -o /dev/null -w "%{http_code}" $BASE/purchase-orders/$X_PO)"

# staff 반출 차단 (require_client_with_company 가 staff를 로그인으로 돌려보냄)
STAFF_USER=$(sqlite3 $DB "SELECT username FROM users WHERE role='platform_staff' LIMIT 1")
if [ -n "$STAFF_USER" ] && [ -n "$B_REQ" ]; then
  login "$STAFF_USER" /tmp/tenant_s.txt
  check "staff 반출 차단" 303 "$(curl -s -b /tmp/tenant_s.txt -o /dev/null -w "%{http_code}" $BASE/client/requests/$B_REQ/export)"
fi

echo "통과 $PASS / 실패 $FAIL"
[ $FAIL -eq 0 ]
