# 한국어로 오케이

Claude Code의 응답이 영어로 바뀌었을 때 한국어로 다시 쓰게 하는 Stop 훅입니다.

Claude Code를 쓰다 보면 한국어로 지시했는데도, 긴 작업을 마친 뒤나 영어 도구 출력을 읽은 직후에 보고가 영어로 돌아오는 일이 있습니다. CLAUDE.md에 "한국어로 응답하라"고 적어도 막히지 않아서, 턴이 끝날 때 본문을 기계로 검사하는 훅을 만들었습니다.

이 저장소는 [claude-code-japanese-guard](https://github.com/minorun365/claude-code-japanese-guard)의 구조를 그대로 옮긴 한국어판입니다. 원본 저작권 고지는 [NOTICE](NOTICE)에 있습니다.

## 동작 방식

턴이 끝날 때, 그 턴에 Claude가 쓴 본문의 영문자 수와 한글 문자 수를 셉니다. 영문자가 한글 문자 수의 3배를 넘으면 종료를 막고 한국어로 다시 쓰라고 되돌립니다. 되돌리기는 한 턴에 한 번까지라, 다시 쓴 답변이 또 영어여도 거기서 끝납니다.

검사 대상은 세 가지입니다.

- 마지막 도구 호출 뒤에 쓴 최종 답변
- 도구 호출 사이의 중간 보고 중 여러 줄인 것과 긴 문단
- 데스크톱 앱의 '다음 단계' 상자(`wrap_up` 도구)의 요약, 질문, 버튼 문구

코드 블록, 인라인 코드, URL, Markdown 링크, 이메일 주소는 세지 않으므로, 영어 명령이나 영문 초안을 보여 주는 응답은 되돌려지지 않습니다. 영문자 25자 미만의 짧은 답변과 JSON만 있는 답변도 대상이 아닙니다.

## 설치

Claude Code에 이 저장소의 URL을 주고 맡기면 설치됩니다.

> https://github.com/asdfqwerzxcc/claude-code-korean-guard 이거 설정해 줘

아래는 그때 Claude Code가 따르는 절차입니다. 직접 설치할 때도 같습니다.

1. 훅을 내려받고 실행 권한을 줍니다.

   ```bash
   mkdir -p ~/.claude/hooks
   curl -fsSL https://raw.githubusercontent.com/asdfqwerzxcc/claude-code-korean-guard/main/hooks/korean-guard.py -o ~/.claude/hooks/korean-guard.py
   chmod +x ~/.claude/hooks/korean-guard.py
   ```

2. `~/.claude/settings.json`의 `hooks.Stop`과 `hooks.PreToolUse` 배열에 다음을 한 건씩 추가합니다. 기존 설정은 남기고, 같은 `command`가 이미 등록돼 있으면 그 배열에는 추가하지 않습니다.

   `hooks.Stop`:

   ```json
   { "hooks": [ { "type": "command", "command": "~/.claude/hooks/korean-guard.py" } ] }
   ```

   `hooks.PreToolUse` ('다음 단계' 상자를 화면에 나오기 전에 막습니다):

   ```json
   { "matcher": "mcp__.*__wrap_up", "hooks": [ { "type": "command", "command": "~/.claude/hooks/korean-guard.py" } ] }
   ```

   matcher를 `wrap_up`만으로 쓰면 완전 일치로 처리되어 실제 도구 이름에 걸리지 않으므로 이 형태를 그대로 쓰세요. 권한 문제로 수정이 막히면 추가할 내용을 사용자에게 보여 주고 직접 추가하게 하세요.

3. 설정 파일이 JSON으로 읽히는지, 훅이 오류 없이 도는지 확인하고, 새로 연 세션부터 적용된다고 알립니다.

   ```bash
   python3 -c "import json,os;json.load(open(os.path.expanduser('~/.claude/settings.json')));print('OK')"
   ```

   ```bash
   echo '{}' | ~/.claude/hooks/korean-guard.py && echo OK
   ```

Python 3만 있으면 되고 추가 패키지는 필요 없습니다.

## 환경 변수

| 변수 | 기본값 | 의미 |
|---|---|---|
| `KOREAN_GUARD_MIN_LATIN` | `25` | 판정할 최소 영문자 수 |
| `KOREAN_GUARD_MIN_LATIN_MID` | `60` | 여러 줄 중간 보고를 판정할 최소 영문자 수 |
| `KOREAN_GUARD_MIN_LATIN_MID_LONG` | `250` | 한 줄 중간 보고를 판정할 최소 영문자 수 |
| `KOREAN_GUARD_RATIO` | `3` | 영어 위주로 볼 한글 문자 수 대비 영문자 배율 |
| `KOREAN_GUARD_WAIT` | `3` | 최종 답변이 대화 기록에 기록되기를 기다리는 초 |
| `KOREAN_GUARD_DISABLE` | 없음 | `1`이면 비활성화(`claude -p`를 쓰는 스크립트용) |

## 지난 세션에서 시험하기

대화 기록을 넘기면 마지막 턴에서 영어 위주였던 본문을 보여 줍니다.

```bash
python3 ~/.claude/hooks/korean-guard.py --check ~/.claude/projects/<프로젝트>/<세션 ID>.jsonl
```

## 테스트

```bash
python3 -m pip install pytest
python3 -m pytest -q
```

## 라이선스

Apache License 2.0. 원본 `claude-code-japanese-guard`(Copyright 2026 Minoru Onda)의 구조를 한국어 규칙으로 옮긴 파생작이며, 원본 고지는 [NOTICE](NOTICE)에 있습니다.
