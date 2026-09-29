#!/bin/bash
# /api/stt, 음성 설정 저장 체크. 8001 서버 기동 상태에서 실행
set -u
BASE=http://localhost:8001
CK=/tmp/voice_ck.txt
TMP=$(mktemp -d)
PASS=0
FAIL=0

check() {
  if [ "$3" = "$2" ]; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1))
    echo "FAIL: $1 (기대 $2, 실제 $3)"
  fi
}

tok=$(curl -s -c $CK $BASE/login | grep -o '[a-f0-9]\{64\}' | head -1)
curl -s -b $CK -c $CK -o /dev/null -d "username=user1&password=1234&csrf_token=$tok" $BASE/login_check
tok=$(curl -s -b $CK $BASE/ | grep -o 'csrf-token" content="[a-f0-9]*' | sed 's/.*content="//')

orig=$(sqlite3 erp.db "SELECT accessibility_settings FROM users WHERE username='user1'")
[ -z "$orig" ] && orig='{}'

say -v Yuna "하이 이알피 출근부 열어줘" -o $TMP/v.aiff
afconvert -f WAVE -d LEI16@16000 -c 1 $TMP/v.aiff $TMP/v.wav
head -c 3000000 /dev/zero > $TMP/big.wav

check "비로그인" 303 "$(curl -s -o /dev/null -w '%{http_code}' -F audio=@$TMP/v.wav $BASE/api/stt)"
check "2MB 초과" 413 "$(curl -s -b $CK -o /dev/null -w '%{http_code}' -F csrf_token=$tok -F audio=@$TMP/big.wav $BASE/api/stt)"
check "깨진 파일" 400 "$(printf 'xx' > $TMP/bad.wav; curl -s -b $CK -o /dev/null -w '%{http_code}' -F csrf_token=$tok -F audio=@$TMP/bad.wav $BASE/api/stt)"

res=$(curl -s -b $CK -F csrf_token=$tok -F audio=@$TMP/v.wav $BASE/api/stt)
echo "인식: $res"
check "정상 인식" 1 "$(echo "$res" | grep -c '출근')"

curl -s -b $CK -o /dev/null -H 'Content-Type: application/json' \
  -d '{"voice_amount": true, "dwell_read": true}' $BASE/api/accessibility
saved=$(sqlite3 erp.db "SELECT accessibility_settings FROM users WHERE username='user1'")
check "voice_amount 저장" 1 "$(echo "$saved" | grep -c '"voice_amount": true')"
check "dwell_read 저장" 1 "$(echo "$saved" | grep -c '"dwell_read": true')"
curl -s -b $CK -o /dev/null -H 'Content-Type: application/json' -d "$orig" $BASE/api/accessibility

check "tts 비로그인" 303 "$(curl -s -o /dev/null -w '%{http_code}' -F text=안녕 -F voice=F1 -F speed=normal $BASE/api/tts)"
check "tts 빈 텍스트" 400 "$(curl -s -b $CK -o /dev/null -w '%{http_code}' -F text= -F voice=F1 -F speed=normal $BASE/api/tts)"
long301=$(python3 -c "print('가'*301)")
check "tts 301자" 400 "$(curl -s -b $CK -o /dev/null -w '%{http_code}' -F text="$long301" -F voice=F1 -F speed=normal $BASE/api/tts)"
check "tts 잘못된 voice" 400 "$(curl -s -b $CK -o /dev/null -w '%{http_code}' -F text=안녕 -F voice=X1 -F speed=normal $BASE/api/tts)"
check "tts 잘못된 speed" 400 "$(curl -s -b $CK -o /dev/null -w '%{http_code}' -F text=안녕 -F voice=F1 -F speed=turbo $BASE/api/tts)"

curl -s -b $CK -o $TMP/out.wav -w '%{http_code}' -F text=안녕하세요 -F voice=F1 -F speed=normal $BASE/api/tts > $TMP/code.txt
check "tts 정상" 200 "$(cat $TMP/code.txt)"
check "tts wav 헤더" 1 "$(head -c 4 $TMP/out.wav | grep -c RIFF)"

curl -s -b $CK -o /dev/null -H 'Content-Type: application/json' -d '{"tts_voice": "M1", "tts_speed": "slow"}' $BASE/api/accessibility
saved=$(sqlite3 erp.db "SELECT accessibility_settings FROM users WHERE username='user1'")
check "tts_voice 저장" 1 "$(echo "$saved" | grep -c '\"tts_voice\": \"M1\"')"
check "tts_speed 저장" 1 "$(echo "$saved" | grep -c '\"tts_speed\": \"slow\"')"
curl -s -b $CK -o /dev/null -H 'Content-Type: application/json' -d "$orig" $BASE/api/accessibility

echo "TTS_DIR 없는 경로 503은 'TTS_DIR=/tmp/none .venv/bin/uvicorn main:app --port 8002' 로 띄운 뒤 수동 확인"

rm -rf $TMP
echo "통과 $PASS / 실패 $FAIL"
[ $FAIL -eq 0 ]
