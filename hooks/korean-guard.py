#!/usr/bin/env python3
"""Claude Code의 Stop 훅. 한 턴의 본문이 영어 위주이면 턴을 끝내지 않고 한국어로 다시 쓰게 한다.

검사 대상은 세 가지다.
1. 그 턴의 최종 답변. 마지막 도구 호출 뒤에 Claude가 쓴 본문이다.
   도구를 한 번도 호출하지 않은 턴은 본문 전체가 최종 답변이 된다.
2. 데스크톱 앱의 '다음 단계' 상자(wrap_up 도구)에 표시되는 recap, ask, 버튼 문구.
   상자가 최종 답변을 대신하는 턴에는 본문이 거의 남지 않아 1번 검사만으로는 빠져나간다.
3. 도구 호출 사이의 중간 보고 중 읽을 분량이 있는 것. 여러 줄이면 영문 MIN_LATIN_MID자 이상,
   한 줄이면 영문 MIN_LATIN_MID_LONG자 이상을 본다. 도구 호출 전의 한 줄 머리말은 화면에 작게만
   나오므로 대상에서 뺀다. 되돌리면 한국어 최종 답변 뒤에 머리말만 다시 쓰는 응답이 한 번 더 나와
   오히려 읽기 불편해진다. 몇 줄짜리 중간 보고는 본문과 같은 크기로 표시되므로 검사한다.
   중간 보고는 text가 아니라 thinking 블록(thinkingDisplay가 updates)으로 기록되기도 한다.

wrap_up은 PreToolUse 훅에서도 같은 판정으로 막는다. 상자가 영어인 채로 화면에 나오기 전에 되돌리기 위해서다.
최종 답변은 훅 입력의 last_assistant_message로도 본다. transcript 기록이 늦어도 놓치지 않기 위해서다.
그 값에는 마지막 응답 한 건만 들어오므로, transcript 판정도 남겨 두고 양쪽을 함께 본다.

코드 블록, 인라인 코드, URL, 이메일 주소, Markdown 링크는 세지 않는다.
영어 명령이나 영문 초안을 코드 블록으로 보여 주는 것은 정당하기 때문이다.
최종 답변이 JSON 값 그 자체(앞뒤 코드 펜스 허용)라면 판정하지 않는다.
스크립트가 읽는 출력이라, 되돌리면 설명이 섞여 JSON으로 읽히지 않게 되기 때문이다.
환경 변수 KOREAN_GUARD_DISABLE=1이면 아무것도 하지 않는다. claude -p로 사람이 읽지 않을 출력을 만들 때 쓴다.

되돌리기는 한 턴에 한 번만 한다(stop_hook_active가 켜져 있으면 통과).
다시 쓴 답변이 또 영어여도 거기서 멈춰 무한히 이어지지 않게 한다.

단독 실행: python3 korean-guard.py --check <transcript.jsonl>
"""

import json
import os
import re
import sys
import time

# I/O는 항상 UTF-8로 맞춘다. Windows에서 stdout이 cp949로 열리면 한국어 출력이 깨질 수 있다.
for _stream in (sys.stdin, sys.stdout):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

# 영문자가 이보다 적은 본문은 판정하지 않는다("OK", "Done" 정도의 짧은 대답은 놓친다)
MIN_LATIN = int(os.environ.get("KOREAN_GUARD_MIN_LATIN", "25"))
# 도구 호출 사이의 중간 보고(여러 줄)는 영문자가 이 이상일 때만 판정한다
MIN_LATIN_MID = int(os.environ.get("KOREAN_GUARD_MIN_LATIN_MID", "60"))
# 한 줄 중간 보고는 영문자가 이 이상인 긴 문단일 때만 판정한다
MIN_LATIN_MID_LONG = int(os.environ.get("KOREAN_GUARD_MIN_LATIN_MID_LONG", "250"))
# 영문자 수가 한글 문자 수의 이 배를 넘으면 영어 위주로 본다
RATIO = float(os.environ.get("KOREAN_GUARD_RATIO", "3"))
# 최종 답변이 transcript에 기록되기를 기다리는 상한(초)
WAIT_SECONDS = float(os.environ.get("KOREAN_GUARD_WAIT", "3"))
# 1이면 아무것도 하지 않는다(claude -p 등으로 사람이 읽지 않을 출력을 만들 때)
DISABLED = os.environ.get("KOREAN_GUARD_DISABLE") == "1"

# 한글 음절(U+AC00-D7A3)과 자모(U+1100-11FF, U+3131-318E)을 센다
HANGUL = re.compile(r"[\uAC00-\uD7A3\u1100-\u11FF\u3131-\u318E]")
LATIN = re.compile(r"[A-Za-z]")
IGNORE = [
    re.compile(r"```.*?```", re.S),
    re.compile(r"`[^`\n]*`"),
    re.compile(r"\[[^\]]*\]\([^)]*\)"),
    re.compile(r"https?://\S+"),
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
]

REASON = (
    "이번 턴의 본문에 영어로 쓴 부분이 있습니다.\n"
    "{quoted}\n"
    "사용자는 한국어 응답을 요청했습니다. 위에 나온 영어 부분만 한국어로 다시 써서 보내세요. "
    "이미 한국어로 쓰인 부분은 사용자에게 전달되었으니 다시 보내지 마세요. "
    "변명이나 원인 설명은 쓰지 말고, 앞으로의 응답도 모두 한국어로 작성하세요."
)

WRAP_UP_REASON = (
    "'다음 단계' 상자의 문구(recap, ask, 버튼)가 영어입니다. 사용자는 한국어 응답을 요청했습니다. "
    "모두 한국어로 다시 쓴 뒤 다시 호출하세요."
)


def is_english(text, min_latin=MIN_LATIN):
    """영어 위주 본문인가. 코드, 링크, URL, 이메일은 세지 않는다."""
    for pattern in IGNORE:
        text = pattern.sub("", text)
    latin = len(LATIN.findall(text))
    hangul = len(HANGUL.findall(text))
    return latin >= min_latin and latin > hangul * RATIO


def looks_like_json(text):
    """최종 답변이 JSON 값 그 자체(앞뒤 코드 펜스 허용)면 True"""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    if not t or t[0] not in "[{":
        return False
    try:
        json.loads(t)
        return True
    except ValueError:
        return False


def is_mid_report_english(text):
    """중간 보고 판정. 한 줄 머리말은 놓치고, 여러 줄이나 긴 문단만 본다."""
    lines = [line for line in text.strip().splitlines() if line.strip()]
    if len(lines) >= 2:
        return is_english(text, MIN_LATIN_MID)
    return is_english(text, MIN_LATIN_MID_LONG)


def is_wrap_up(name):
    """데스크톱 앱의 '다음 단계' 상자를 띄우는 도구인가(MCP 도구라 이름 앞에 접두사가 붙는다)"""
    return (name or "").endswith("wrap_up")


def wrap_up_text(tool_input):
    """'다음 단계' 상자에 표시되는 문자열(recap, ask, 버튼 문구)을 하나로 합친다"""
    tool_input = tool_input or {}
    parts = [tool_input.get("recap") or "", tool_input.get("ask") or ""]
    actions = tool_input.get("actions")
    if isinstance(actions, str):
        try:
            actions = json.loads(actions)
        except ValueError:
            actions = []
    for action in actions or []:
        if isinstance(action, dict):
            parts += [action.get("label") or "", action.get("message") or ""]
    return "\n".join(p for p in parts if p)


def head(text, label=""):
    return label + text.strip().splitlines()[0][:80]


def is_user_turn(entry):
    """사용자가 입력한 발언인가(도구 결과나 메타 정보의 user 엔트리는 제외)"""
    if entry.get("type") != "user" or entry.get("isMeta"):
        return False
    content = entry.get("message", {}).get("content")
    if isinstance(content, str):
        return True
    if isinstance(content, list):
        return not any(isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
    return False


def read_entries(transcript_path):
    entries = []
    with open(transcript_path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def turn_ended_in_text(entries):
    """이 턴의 최신 assistant 엔트리가 본문으로 끝났는가"""
    for entry in reversed(entries):
        if is_user_turn(entry):
            return False
        if entry.get("type") == "assistant":
            content = entry.get("message", {}).get("content") or []
            last = next((c for c in reversed(content) if isinstance(c, dict)), None)
            return bool(last) and last.get("type") == "text"
        if entry.get("type") == "user":  # 도구 결과가 마지막 = 최종 답변이 아직 기록되지 않음
            return False
    return False


def wait_for_final(transcript_path, timeout=WAIT_SECONDS):
    """Stop 훅은 최종 답변이 transcript에 기록되기 전에 호출될 수 있다.
    그대로 읽으면 최종 답변이 보이지 않아 영어여도 빠져나간다. 최종 답변이 나타날 때까지 기다린다.
    도구를 호출하지 않고 끝난 턴은 처음부터 본문으로 끝나 있으므로 기다리지 않는다."""
    deadline = time.time() + timeout
    entries = read_entries(transcript_path)
    while not turn_ended_in_text(entries) and time.time() < deadline:
        time.sleep(0.1)
        entries = read_entries(transcript_path)
    return entries


def english_passages(transcript_path, entries=None):
    if entries is None:
        entries = read_entries(transcript_path)
    start = 0
    for i, entry in enumerate(entries):
        if is_user_turn(entry):
            start = i + 1
    # 최종 답변 = 마지막 도구 호출 뒤의 본문. 도구 호출이 나올 때마다 다시 모은다
    final = []
    hits = []
    for entry in entries[start:]:
        if entry.get("type") != "assistant":
            continue
        for block in entry.get("message", {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                # 최종 답변이 되지 못한 본문은 중간 보고. 긴 것만 본다
                hits += [head(t, "(중간 보고)") for t in final if is_mid_report_english(t)]
                final = []
                if is_wrap_up(block.get("name")):
                    text = wrap_up_text(block.get("input"))
                    if is_english(text):
                        hits.append(head(text, "(다음 단계 상자)"))
            elif block.get("type") == "text":
                final.append(block.get("text", ""))
            elif block.get("type") == "thinking" and entry.get("thinkingDisplay") == "updates":
                # thinkingDisplay가 updates일 때 내용 있는 thinking은 중간 보고로 화면에 나온다
                text = block.get("thinking") or ""
                if text.strip() and is_mid_report_english(text):
                    hits.append(head(text, "(중간 보고)"))
    hits += [head(text) for text in final if is_english(text)]
    return hits


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        hits = english_passages(sys.argv[2])
        print("\n".join(hits) if hits else "영어 위주의 본문이 없습니다")
        return
    if DISABLED:
        return
    data = json.load(sys.stdin)
    if data.get("hook_event_name") == "PreToolUse":
        if is_wrap_up(data.get("tool_name")) and is_english(wrap_up_text(data.get("tool_input"))):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": WRAP_UP_REASON,
            }}, ensure_ascii=False))
        return
    if data.get("stop_hook_active"):
        return
    # 최종 답변이 JSON뿐이면 스크립트가 읽는 출력으로 본다. 되돌리면 "영어를 한국어로 고치라"는
    # 설명이 붙어 JSON으로 읽을 수 없게 된다
    if looks_like_json(data.get("last_assistant_message") or ""):
        return
    # 최종 답변 본문은 훅 입력의 last_assistant_message에도 들어 있다. transcript 기록을 기다리지 않고
    # 판정할 수 있고, 기록이 늦어도 놓치지 않는다. 이 값에는 마지막 응답 한 건만 들어오므로
    # 응답이 나뉘었을 때의 앞부분은 transcript에서 본다
    message = data.get("last_assistant_message") or ""
    message_en = bool(message) and is_english(message)
    path = data.get("transcript_path")
    hits = []
    if path:
        try:
            hits = english_passages(path, read_entries(path) if message_en else wait_for_final(path))
        except OSError:
            pass
    if message_en:
        first = head(message)
        if first not in hits:
            hits.append(first)
    if hits:
        quoted = "\n".join("- " + h for h in hits[:5])
        print(json.dumps({"decision": "block", "reason": REASON.format(quoted=quoted)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
