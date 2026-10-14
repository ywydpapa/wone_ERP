LEAD_STATUS = {"new": "신규", "contact": "접촉중", "qualified": "검토", "converted": "거래처전환", "lost": "종료"}
LEAD_CLASS = {"new": "status-wait", "contact": "status-progress", "qualified": "status-review",
              "converted": "status-done", "lost": "status-closed"}

# 단계별 기본 성공확률(%). 가중 파이프라인 금액 산정 기준
STAGES = {"found": "발굴", "proposal": "제안", "nego": "협상", "won": "수주", "lost": "실패"}
STAGE_PROB = {"found": 10, "proposal": 40, "nego": 70, "won": 100, "lost": 0}
STAGE_CLASS = {"found": "status-wait", "proposal": "status-progress", "nego": "status-review",
               "won": "status-done", "lost": "status-reject"}

ACT_KINDS = {"call": "통화", "visit": "방문", "meeting": "미팅", "email": "메일", "etc": "기타"}
