# MCP 연결

기존 상태 API를 조회하는 읽기 전용 MCP 서버입니다. MCP 호출로 모니터링 작업을 시작하거나 학교 서버를 추가 검사하지 않습니다.

연결된 클라이언트는 도구 이름·설명·입력 스키마를 받아 필요한 도구를 선택할 수 있습니다. 실제 호출 여부는 클라이언트의 기능과 사용자 승인 설정에 따릅니다.

## 준비

Python 3.10 이상으로 저장소 디렉터리에서 실행하세요.

```sh
python3 -m venv .venv-mcp
. .venv-mcp/bin/activate
python -m pip install -r requirements-mcp.txt
```

MCP가 읽을 API 주소를 지정합니다. 기본값은 로컬 상태 서버의 `http://127.0.0.1:9085/api/status`입니다. 이미 공개된 상태 페이지를 읽는다면 다음과 같이 지정할 수 있습니다.

```sh
export STATUS_API_URL=https://ping.butterflyjin.kr/api/status
python mcp_server.py
```

stdio 서버이므로 명령을 직접 실행하면 MCP 메시지 입력을 기다립니다. 일반 터미널에서 질문을 입력하는 프로그램은 아닙니다. stdout은 MCP 통신에 사용하고, 진단 메시지는 stderr에 기록합니다.

## 클라이언트 등록

다음은 stdio를 지원하는 클라이언트의 일반적인 JSON 설정 예시입니다. 실제 설정 파일 위치와 형식은 사용하는 클라이언트에 맞춰 적용하세요. 아래 절대 경로는 본인 환경으로 변경해야 합니다.

```json
{
  "mcpServers": {
    "service-status": {
      "command": "/absolute/path/to/project/.venv-mcp/bin/python",
      "args": ["/absolute/path/to/project/mcp_server.py"],
      "env": {
        "STATUS_API_URL": "https://ping.butterflyjin.kr/api/status"
      }
    }
  }
}
```

Windows에서는 가상환경 Python 경로가 `.venv-mcp\\Scripts\\python.exe`입니다.

등록 후 도구 목록에 아래 세 도구가 나타나는지 확인하세요. 이 저장소의 파일을 만드는 것만으로 클라이언트 설정이 자동 변경되지는 않습니다.

## 도구

### `get_status()`

서비스 ID·이름·상태·마지막 검사 시각·응답 시간을 반환합니다. 즉시 재검사하지 않으므로 마지막 검사 시각을 함께 확인해야 합니다.

### `get_history(hours=24, service="all")`

`hours`는 `1`, `24`, `168` 중 하나입니다. `service`는 `get_status`에서 확인한 ID 또는 `all`입니다. 기본 구성의 ID는 `ssh101`, `ssh102`, `eclass`입니다.

성공률, 구간별 검사 수·성공 수·기록 공백 여부, 연속 실패 관측 구간을 반환합니다. 시간은 Unix 초이며 표시 기준 시간대는 Asia/Seoul입니다. 배열의 필드 이름과 종료 상태 의미도 응답에 포함됩니다. 성공률은 검사 표본 기준이며 기록 공백은 정상으로 간주하지 않습니다.

### `get_incidents(service="all")`

연속 3회 실패로 확정된 장애와 복구 이력을 반환합니다. 짧은 실패는 확정 장애 이력에 없을 수 있으므로 `get_history`에서 확인하세요.

## 동작 범위

- MCP 서버는 로컬 stdio로 실행하며 HTTP 포트를 열지 않습니다.
- 운영자가 설정한 상태 API에만 GET 요청합니다. 도구 인자로 임의 URL이나 포트를 받지 않습니다.
- API 응답은 5초 동안 공유합니다. 조회 실패 시 이전 정상 결과로 대신 응답하지 않으며, 2초 동안 재시도를 억제합니다.
- API 조회 실패는 학교 서비스 장애라는 뜻이 아닙니다.
- 기존 API가 제공하는 최근 7일의 기록과 최대 30건의 장애 이력 범위를 사용합니다.
- MCP SDK는 선택 의존성입니다. 기본 웹 서비스는 계속 Python 표준 라이브러리만 사용합니다.
- 공개 원격 HTTP MCP 엔드포인트나 클라이언트 설정 변경은 포함하지 않습니다.

## 검증

SDK를 설치한 가상환경에서 실행합니다.

```sh
python -m unittest discover -s tests -v
```

모의 API와 실제 stdio MCP 연결을 사용해 도구 발견, 읽기 전용 속성, 세 도구 호출, 입력 오류를 검증합니다. 세 도구를 연속 호출할 때 API 조회는 한 번이고, 실제 학교 서버에는 접속하지 않습니다.

공식 SDK: [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk)
