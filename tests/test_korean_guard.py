import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "korean-guard.py"

EN = "The build finished successfully and all tests passed, so I will publish the page now."
KO = "빌드가 통과했고 테스트도 모두 성공했으니 이제 페이지를 공개하겠습니다."
EN_MID = ("I have finished reading the configuration files.\n"
          "Next I will update the build script, run the tests again, and report the results once everything passes.")
EN_ONE_LINE = "Register the page in the index after the existing entry, then publish it and check the build log."
KO_MID = "설정 파일을 다 읽었습니다. 이제 빌드 스크립트를 고치고 테스트를 다시 돌리겠습니다."
KO_TOOL_PREFIX = "빌드를 먼저 확인하겠습니다. 그다음 전체 테스트를 돌립니다."
EN_TOOL_PREFIX = "Checking the build first. Then I will run the whole test suite."


def user(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def tool_result():
    return {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}}


def assistant(text):
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def tool_use():
    return {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}}


def thinking(text, display="updates"):
    return {"type": "assistant", "thinkingDisplay": display,
            "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": text}]}}


def wrap_up(recap, ask=None, actions=None):
    inp = {"recap": recap}
    if ask:
        inp["ask"] = ask
    if actions is not None:
        inp["actions"] = actions
    return {"type": "assistant", "message": {"role": "assistant", "content": [
        {"type": "tool_use", "name": "mcp__ccd_turn__wrap_up", "input": inp}]}}


def write_transcript(path, entries):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries), encoding="utf-8")


def run_payload(payload, env=None):
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
        env={**os.environ, **(env or {})},
    )
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def run_hook(tmp_path, entries, stop_hook_active=False, last_message=None, env=None, name="transcript.jsonl"):
    path = tmp_path / name
    write_transcript(path, entries)
    payload = {"transcript_path": str(path), "stop_hook_active": stop_hook_active}
    if last_message is not None:
        payload["last_assistant_message"] = last_message
    return run_payload(payload, env)


def pre_tool_use(tool_name, tool_input):
    return run_payload({"hook_event_name": "PreToolUse", "tool_name": tool_name, "tool_input": tool_input})


def blocked(result):
    return bool(result and result.get("decision") == "block")


CASES = [
    ("english_body_blocks", [user("공개해 줘"), assistant(EN)], False, True),
    ("korean_body_passes", [user("공개해 줘"), assistant(KO)], False, False),
    ("short_english_tool_prefix_passes",
     [user("공개해 줘"), assistant(EN_TOOL_PREFIX), tool_use(), tool_result(), assistant(KO)], False, False),
    ("long_one_line_tool_prefix_passes",
     [user("공개해 줘"), assistant(EN_ONE_LINE), tool_use(), tool_result(), assistant(KO)], False, False),
    ("english_final_after_tool_blocks",
     [user("공개해 줘"), assistant(KO), tool_use(), tool_result(), assistant(EN)], False, True),
    ("mixed_korean_then_english_blocks", [user("공개해 줘"), assistant(KO), assistant(EN)], False, True),
    ("code_block_english_ignored", [user("설치 방법은?"), assistant(
        "다음 명령을 실행하세요.\n```bash\nnpm install && npm run build && npm test -- --coverage --watchAll=false\n```")],
     False, False),
    ("inline_code_english_ignored",
     [user("설치 방법은?"), assistant("`npm run build` 명령을 실행하세요. 끝나면 알려 드리겠습니다.")], False, False),
    ("markdown_link_english_ignored", [user("자료는?"), assistant(
        "참고: [Apple Developer Documentation](https://developer.apple.com/documentation/)")], False, False),
    ("bare_url_english_ignored", [user("자료는?"), assistant(
        "자세한 내용은 https://example.com/some/very/long/english/path/that/should/not/count 를 보세요.")], False, False),
    ("email_english_ignored", [user("연락처는?"), assistant(
        "문의는 someone@example.com 으로 주세요. 답변이 늦을 수 있습니다.")], False, False),
    ("previous_turn_english_ignored", [user("a"), assistant(EN), user("b"), assistant(KO)], False, False),
    ("stop_hook_active_passes", [user("공개해 줘"), assistant(EN)], True, False),
    ("short_english_passes", [user("됐어?"), assistant("OK, done.")], False, False),
    ("long_english_mid_report_blocks",
     [user("공개해 줘"), assistant(EN_MID), tool_use(), tool_result(), assistant(KO)], False, True),
    ("english_updates_thinking_blocks",
     [user("공개해 줘"), thinking(EN_MID), tool_use(), tool_result(), assistant(KO)], False, True),
    ("korean_updates_thinking_passes",
     [user("공개해 줘"), thinking(KO_MID), tool_use(), tool_result(), assistant(KO)], False, False),
    ("non_updates_thinking_ignored",
     [user("공개해 줘"), thinking(EN_MID, display="summarized"), tool_use(), tool_result(), assistant(KO)], False, False),
    ("english_wrap_up_blocks",
     [user("공개해 줘"), wrap_up(EN, "Should I publish it now?"), tool_result(), assistant("응답 없음")], False, True),
    ("korean_wrap_up_passes", [user("공개해 줘"), wrap_up(KO, "공개할까요?", [{"label": "공개하기"}]),
                               tool_result(), assistant("응답 없음")], False, False),
]


@pytest.mark.parametrize("entries,stop_active,expect_block", [case[1:] for case in CASES],
                         ids=[case[0] for case in CASES])
def test_stop_hook(tmp_path, entries, stop_active, expect_block):
    result = run_hook(tmp_path, entries, stop_hook_active=stop_active)
    assert blocked(result) is expect_block


JSON_OUT = json.dumps({"status": "ok", "items": [{"title": "Weekly build report", "summary": EN}]})


@pytest.mark.parametrize("last_message,expect_block", [
    (JSON_OUT, False),
    ("```json\n" + JSON_OUT + "\n```", False),
    (EN + "\n" + JSON_OUT, True),
    ("{" + EN, True),
], ids=["json_only_passes", "fenced_json_passes", "english_prose_before_json_blocks", "invalid_json_blocks"])
def test_json_output(tmp_path, last_message, expect_block):
    result = run_hook(tmp_path, [user("JSON으로 줘"), tool_use(), tool_result()], last_message=last_message)
    assert blocked(result) is expect_block


def test_delayed_final_answer_blocks(tmp_path):
    path = tmp_path / "late.jsonl"
    write_transcript(path, [user("공개해 줘"), tool_use(), tool_result()])

    def append_final():
        time.sleep(0.5)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(assistant(EN), ensure_ascii=False) + "\n")

    timer = threading.Timer(0.5, append_final)
    timer.start()
    try:
        result = run_payload({"transcript_path": str(path)}, env={"KOREAN_GUARD_WAIT": "3"})
    finally:
        timer.join(timeout=5)
    assert not timer.is_alive()
    assert blocked(result)


def test_last_message_english_blocks_without_waiting(tmp_path):
    result = run_payload(
        {"transcript_path": str(tmp_path / "missing.jsonl"), "last_assistant_message": EN},
        env={"KOREAN_GUARD_WAIT": "10"},
    )
    assert blocked(result)


def test_last_message_korean_passes(tmp_path):
    result = run_hook(tmp_path, [user("공개해 줘"), assistant(KO)], last_message=KO)
    assert result is None


def test_split_response_earlier_english_blocks(tmp_path):
    result = run_hook(tmp_path, [user("공개해 줘"), assistant(EN), assistant(KO)], last_message=KO)
    assert blocked(result)


def test_disable_env_passes(tmp_path):
    result = run_hook(tmp_path, [user("공개해 줘"), assistant(EN)], last_message=EN,
                      env={"KOREAN_GUARD_DISABLE": "1"})
    assert result is None


@pytest.mark.parametrize("tool_name,tool_input,expect_deny", [
    ("mcp__ccd_turn__wrap_up",
     {"recap": EN, "ask": "Publish now?", "actions": [{"label": "Publish", "message": "Yes, go ahead."}]}, True),
    ("mcp__ccd_turn__wrap_up",
     {"recap": "공개 준비가 끝났습니다.", "actions": json.dumps([{"label": "Go", "message": EN}])}, True),
    ("mcp__ccd_turn__wrap_up", {"recap": KO, "ask": "공개할까요?", "actions": [{"label": "공개하기"}]}, False),
    ("Bash", {"command": EN}, False),
], ids=["english_wrap_up_denied", "json_string_actions_denied", "korean_wrap_up_allowed", "other_tool_ignored"])
def test_pre_tool_use(tool_name, tool_input, expect_deny):
    result = pre_tool_use(tool_name, tool_input)
    denied = bool(result and result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny")
    assert denied is expect_deny


@pytest.mark.parametrize("korean_text", [
    "ㅎㅏㄴㄱㅜㄱㅇㅓ " * 10,
    "\u1112\u1161\u11ab" * 10,
], ids=["compatibility_jamo_counts", "combining_jamo_counts"])
def test_hangul_jamo_counts_as_korean(tmp_path, korean_text):
    result = run_hook(tmp_path, [user("공개해 줘"), assistant(korean_text + EN)])
    assert result is None


def test_check_mode_reports_english(tmp_path):
    path = tmp_path / "check.jsonl"
    write_transcript(path, [user("공개해 줘"), assistant(EN)])
    proc = subprocess.run(
        [sys.executable, str(HOOK), "--check", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    assert "The build finished" in proc.stdout
