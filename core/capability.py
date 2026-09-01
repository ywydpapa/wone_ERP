def derive_tier1(profile):
    return profile


def derive_tier2(profile):
    p = profile

    hand_l = p.get("hand_left", "unknown")
    hand_r = p.get("hand_right", "unknown")
    foot_l = p.get("foot_left", "unknown")
    foot_r = p.get("foot_right", "unknown")
    neck = p.get("neck", "unknown")
    vision = p.get("vision", "unknown")
    speech = p.get("speech", "unknown")

    eye_movement = p.get("eye_movement", -1)
    eyelid_control = p.get("eyelid_control", -1)
    breath_control = p.get("breath_control", -1)

    inputs = []

    gaze_ok = (eye_movement == 1) and (vision != "blind")
    inputs.append({"name": "시선 포인터", "method": "gaze_pointer", "feasible": gaze_ok})

    blink_ok = (eyelid_control == 1)
    inputs.append({"name": "눈 깜빡임 입력", "method": "blink_input", "feasible": blink_ok})

    head_ok = neck in ("limited", "full")
    inputs.append({"name": "머리 추적", "method": "head_tracking", "feasible": head_ok})

    voice_ok = speech in ("unclear_correctable", "capable")
    inputs.append({"name": "음성 입력", "method": "voice_input", "feasible": voice_ok})

    hand_any_usable = hand_l not in ("unable", "unknown") or hand_r not in ("unable", "unknown")
    hand_ok = hand_l != "unable" or hand_r != "unable"
    inputs.append({"name": "손 제스처", "method": "hand_gesture", "feasible": hand_ok and hand_any_usable})

    keyboard_ok = (hand_l == "precise") or (hand_r == "precise")
    inputs.append({"name": "표준 키보드/마우스", "method": "keyboard_mouse", "feasible": keyboard_ok})

    foot_ok = (foot_l not in ("unable", "unknown")) or (foot_r not in ("unable", "unknown"))
    foot_usable = foot_l != "unable" or foot_r != "unable"
    inputs.append({"name": "발 마우스", "method": "foot_mouse", "feasible": foot_usable and foot_ok})

    sip_ok = (breath_control == 1)
    inputs.append({"name": "호흡 스위치 (Sip-and-puff)", "method": "sip_and_puff", "feasible": sip_ok})

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

    bw_thresholds = [(40, "high"), (12, "medium")]
    bandwidth = next((label for threshold, label in bw_thresholds if bw_wpm >= threshold), "low")

    return {
        "available_inputs": inputs,
        "bandwidth": bandwidth,
        "bandwidth_wpm": bw_wpm,
    }


def derive_tier3(tier2, profile=None):
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

    capabilities.append({
        "task": "결재 / 전자서명",
        "task_key": "approval",
        "feasible": has_select_confirm,
    })

    capabilities.append({
        "task": "채팅 상담",
        "task_key": "chat_support",
        "feasible": has_text_input,
    })

    capabilities.append({
        "task": "전화 상담",
        "task_key": "phone_support",
        "feasible": speech == "capable",
    })

    data_entry_ok = has_text_input and (bandwidth in ("high", "medium"))
    capabilities.append({
        "task": "데이터 입력",
        "task_key": "data_entry",
        "feasible": data_entry_ok,
        "bandwidth_wpm": bandwidth_wpm,
        "has_text_input": has_text_input,
    })

    capabilities.append({
        "task": "자료 검토",
        "task_key": "document_review",
        "feasible": (vision != "blind") and (sustained_focus == 1),
        "vision": vision,
    })

    capabilities.append({
        "task": "기획 / 문서 작성",
        "task_key": "planning_drafting",
        "feasible": has_text_input,
        "bandwidth_wpm": bandwidth_wpm,
    })

    return {"capabilities": capabilities}
