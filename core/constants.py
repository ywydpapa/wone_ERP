POST_CATEGORIES = [
    ("general", "자유게시판"),
    ("notice", "공지사항"),
    ("qna", "질문/답변"),
    ("tips", "업무 팁"),
    ("daily", "일상"),
]

SIMPLE_SLIP_PURPOSES = [
    ("사무용품", "813", "소모품비", True),
    ("교통비", "825", "여비교통비", True),
    ("식대/회식", "812", "복리후생비", True),
    ("통신비", "826", "통신비", True),
    ("임대료", "820", "임차료", True),
    ("수리/유지보수", "822", "수선비", True),
    ("광고/홍보", "830", "광고선전비", True),
    ("배송비", "827", "운반비", True),
    ("인쇄/복사", "831", "사무비", True),
    ("기타 지출", "835", "잡비", True),
    ("매출", "401", "상품매출", False),
    ("용역수입", "402", "용역매출", False),
    ("기타 수입", "901", "잡수입", False),
]

ERP_REDIRECTS = {
    "draft":         "/erp_groupware",
    "hr_task":       "/erp_hr",
    "stock_move":    "/erp_inventory",
    "work_order":    "/erp_product",
    "po":            "/erp_purch",
    "activity":      "/erp_scrm",
    "expense":       "/erp_fa",
    "leave":         "/erp_hr",
    "business_trip": "/erp_hr",
    "trip_report":   "/erp_hr",
    "weekly_report": "/erp_groupware",
    "congrats":      "/erp_hr",
    "salary":        "/erp_hr",
    "overtime":      "/erp_hr",
}

ERP_DOC_TYPES = {
    "new_hr_task":         ("hr_task",        "HR 업무"),
    "new_activity":        ("activity",       "활동 등록"),
    "new_leave":           ("leave",          "휴가신청서"),
    "new_business_trip":   ("business_trip",  "출장신청서"),
    "new_trip_report":     ("trip_report",    "출장보고서"),
    "new_weekly_report":   ("weekly_report",  "주간업무보고서"),
    "new_congrats":        ("congrats",       "경조금신청서"),
    "new_salary":          ("salary",         "급여명세서"),
    "new_overtime":        ("overtime",       "초과근무신청서"),
}

# 전용 폼으로 대체된 구 라우트 리다이렉트
ERP_LEGACY_REDIRECTS = {
    "new_po":              "/purchase-orders/new",
    "new_work_order":      "/work-orders/new",
    "new_stock_move":      "/stock",
}

COMPANY_INFO = {
    "name": "(주)원플러스", "biz_no": "123-86-00001", "representative": "대표이사",
    "address": "서울특별시 강남구 테헤란로 123", "biz_type": "서비스업", "biz_item": "소프트웨어 개발",
}

ACCOMMODATION_CATEGORY_LABELS = {
    "assistive_tech": "보조기기 지원",
    "work_assistant": "근로지원인",
    "workspace_adjust": "작업환경 개선",
}

ACCOMMODATION_STATUS_LABELS = {
    "pending": "접수", "reviewing": "검토중", "approved": "승인",
    "rejected": "반려", "completed": "완료",
}

ERP_DOC_TYPE_LABELS = {
    "draft":          "결재 기안",
    "hr_task":        "HR 업무",
    "stock_move":     "입출고",
    "work_order":     "작업 지시",
    "po":             "구매 발주",
    "activity":       "영업 활동",
    "expense":        "자금관리",
    "leave":          "휴가신청",
    "business_trip":  "출장신청",
    "trip_report":    "출장보고",
    "weekly_report":  "주간업무보고",
    "congrats":       "경조금신청",
    "salary":         "급여명세",
    "overtime":       "초과근무",
}

# KEAD 15개 장애유형
DISABILITY_TYPES = [
    "지체장애", "뇌병변장애", "시각장애", "청각장애", "언어장애",
    "안면장애", "신장장애", "심장장애", "간장애", "호흡기장애",
    "장루요루장애", "뇌전증장애", "지적장애", "자폐성장애", "정신장애",
]

DISABILITY_DEGREE_LABELS = {
    "심한장애": "심한 장애(중증)",
    "심하지않은장애": "심하지 않은 장애(경증)",
}

APPEAL_TYPE_LABELS = {
    "transit": "대중교통 지연",
    "medical": "병원 진료",
    "accident": "교통사고/차량 고장",
    "disability": "장애 관련",
    "family": "가족 긴급",
    "etc": "기타",
}
