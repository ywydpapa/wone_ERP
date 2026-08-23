from __future__ import annotations


def derive_tier2(profile: dict) -> dict:
    p = profile

    hand_l = p.get("hand_left", "unknown")
    hand_r = p.get("hand_right", "unknown")
    foot_l = p.get("foot_left", "unknown")
    foot_r = p.get("foot_right", "unknown")
    neck   = p.get("neck", "unknown")
    vision = p.get("vision", "unknown")
    speech = p.get("speech", "unknown")

    eye_movement   = p.get("eye_movement", -1)
    eyelid_control = p.get("eyelid_control", -1)
    breath_control = p.get("breath_control", -1)

    inputs = []

    # 시선 포인터
    gaze_ok = (eye_movement == 1) and (vision != "blind")
    inputs.append({
        "name": "시선 포인터",
        "method": "gaze_pointer",
        "feasible": gaze_ok,
        "reason": (
            "안구 움직임 가능 + 시력 있음" if gaze_ok
            else (
                "시력 없음 (전맹)" if vision == "blind"
                else "안구 움직임 제한"
            )
        ),
    })

    # 눈 깜빡임
    blink_ok = (eyelid_control == 1)
    inputs.append({
        "name": "눈 깜빡임 입력",
        "method": "blink_input",
        "feasible": blink_ok,
        "reason": "눈꺼풀 제어 가능" if blink_ok else "눈꺼풀 제어 불가",
    })

    # 머리 추적
    head_ok = neck in ("limited", "full")
    inputs.append({
        "name": "머리 추적",
        "method": "head_tracking",
        "feasible": head_ok,
        "reason": "목 움직임 가능" if head_ok else "목 움직임 불가",
    })

    # 음성 입력
    voice_ok = speech in ("unclear_correctable", "capable")
    inputs.append({
        "name": "음성 입력",
        "method": "voice_input",
        "feasible": voice_ok,
        "reason": (
            "명료한 발화 가능" if speech == "capable"
            else "발화 가능 (교정 필요)" if speech == "unclear_correctable"
            else "발화 불가"
        ),
    })

    # 손 제스처 / 키보드 / 마우스
    hand_any_usable = hand_l not in ("unable", "unknown") or hand_r not in ("unable", "unknown")
    hand_ok = hand_l != "unable" or hand_r != "unable"
    inputs.append({
        "name": "손 제스처",
        "method": "hand_gesture",
        "feasible": hand_ok and hand_any_usable,
        "reason": "한쪽 이상 손 사용 가능" if (hand_ok and hand_any_usable) else "양손 사용 불가",
    })

    keyboard_ok = (hand_l == "precise") or (hand_r == "precise")
    inputs.append({
        "name": "표준 키보드/마우스",
        "method": "keyboard_mouse",
        "feasible": keyboard_ok,
        "reason": "정밀 손 동작 가능" if keyboard_ok else "정밀 손 동작 불가",
    })

    # 발 마우스
    foot_ok = (foot_l not in ("unable", "unknown")) or (foot_r not in ("unable", "unknown"))
    foot_usable = foot_l != "unable" or foot_r != "unable"
    inputs.append({
        "name": "발 마우스",
        "method": "foot_mouse",
        "feasible": foot_usable and foot_ok,
        "reason": "한쪽 이상 발 사용 가능" if (foot_usable and foot_ok) else "발 사용 불가",
    })

    # 호흡 스위치
    sip_ok = (breath_control == 1)
    inputs.append({
        "name": "호흡 스위치 (Sip-and-puff)",
        "method": "sip_and_puff",
        "feasible": sip_ok,
        "reason": "호흡 제어 가능" if sip_ok else "호흡 제어 불가",
    })

    # 최고 대역폭 선택
    bw_wpm = 0

    if speech == "capable":
        bw_wpm = max(bw_wpm, 80)
    if speech == "unclear_correctable":
        bw_wpm = max(bw_wpm, 60)
    if keyboard_ok:
        bw_wpm = max(bw_wpm, 40)
    if (hand_l == "gross_only") or (hand_r == "gross_only"):
        bw_wpm = max(bw_wpm, 20)
    if eye_movement == 1:
        bw_wpm = max(bw_wpm, 15)
    if neck not in ("unable", "unknown"):
        bw_wpm = max(bw_wpm, 12)
    if breath_control == 1:
        bw_wpm = max(bw_wpm, 5)

    if bw_wpm >= 40:
        bandwidth = "high"
    elif bw_wpm >= 12:
        bandwidth = "medium"
    else:
        bandwidth = "low"

    return {
        "available_inputs": inputs,
        "bandwidth": bandwidth,
        "bandwidth_wpm": bw_wpm,
    }


def derive_tier3(tier2: dict, profile: dict | None = None) -> dict:
    if profile is None:
        profile = {}

    inputs_by_method = {
        item["method"]: item["feasible"]
        for item in tier2.get("available_inputs", [])
    }
    bandwidth = tier2.get("bandwidth", "low")
    bandwidth_wpm = tier2.get("bandwidth_wpm", 0)

    vision = profile.get("vision", "unknown")
    speech = profile.get("speech", "unknown")
    sustained_focus = profile.get("sustained_focus", -1)

    has_text_input = (
        inputs_by_method.get("keyboard_mouse", False)
        or inputs_by_method.get("voice_input", False)
        or inputs_by_method.get("gaze_pointer", False)
        or inputs_by_method.get("head_tracking", False)
        or inputs_by_method.get("blink_input", False)
        or inputs_by_method.get("sip_and_puff", False)
    )

    has_select_confirm = (
        has_text_input
        or inputs_by_method.get("hand_gesture", False)
        or inputs_by_method.get("foot_mouse", False)
    )

    capabilities = []

    # 결재
    approval_ok = has_select_confirm
    capabilities.append({
        "task": "결재 / 전자서명",
        "task_key": "approval",
        "feasible": approval_ok,
        "required_inputs": ["선택", "확인"],
        "reason": (
            "선택·확인 동작이 가능한 입력 수단이 있음" if approval_ok
            else "선택·확인이 가능한 입력 수단 없음"
        ),
    })

    # 채팅 상담
    chat_ok = has_text_input
    capabilities.append({
        "task": "채팅 상담",
        "task_key": "chat_support",
        "feasible": chat_ok,
        "required_inputs": ["텍스트 입력"],
        "reason": (
            "음성 또는 키보드 등 텍스트 입력 수단 있음" if chat_ok
            else "텍스트 입력 수단 없음"
        ),
    })

    # 전화 상담
    phone_ok = (speech == "capable")
    capabilities.append({
        "task": "전화 상담",
        "task_key": "phone_support",
        "feasible": phone_ok,
        "required_inputs": ["명료한 발화"],
        "reason": (
            "명료한 발화 가능" if phone_ok
            else (
                "발화 불명료 (보조 수단 필요)" if speech == "unclear_correctable"
                else "발화 불가"
            )
        ),
    })

    # 데이터 입력
    data_entry_ok = has_text_input and (bandwidth in ("high", "medium"))
    capabilities.append({
        "task": "데이터 입력",
        "task_key": "data_entry",
        "feasible": data_entry_ok,
        "required_inputs": ["텍스트 입력", "충분한 입력 속도"],
        "reason": (
            f"텍스트 입력 가능, 추정 속도 {bandwidth_wpm}wpm" if data_entry_ok
            else (
                f"입력 속도 부족 (추정 {bandwidth_wpm}wpm, 최소 medium 필요)"
                if has_text_input
                else "텍스트 입력 수단 없음"
            )
        ),
    })

    # 자료 검토
    review_ok = (vision != "blind") and (sustained_focus == 1)
    capabilities.append({
        "task": "자료 검토",
        "task_key": "document_review",
        "feasible": review_ok,
        "required_inputs": ["시력 (전맹 제외)", "지속 집중력"],
        "reason": (
            "시력 있음 + 지속 집중 가능" if review_ok
            else (
                "전맹으로 시각 자료 검토 불가" if vision == "blind"
                else "지속 집중력 미확인 또는 제한"
            )
        ),
    })

    # 기획/문서 작성
    planning_ok = has_text_input
    capabilities.append({
        "task": "기획 / 문서 작성",
        "task_key": "planning_drafting",
        "feasible": planning_ok,
        "required_inputs": ["텍스트 입력 (AI 보조 활용 가능)"],
        "reason": (
            f"텍스트 입력 수단 있음 (추정 속도 {bandwidth_wpm}wpm, AI 보조 병행 가능)"
            if planning_ok
            else "텍스트 입력 수단 없음"
        ),
    })

    return {"capabilities": capabilities}
