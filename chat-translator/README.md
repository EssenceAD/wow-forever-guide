# 와우 채팅 실시간 번역 창

World of Warcraft: Forever 채팅(중국어 번체/간체·영어)을 한국어로 실시간 번역하고,
한국어 답장을 대만어(번체)/영어로 번역해 클립보드에 복사하는 Windows용 작은 창.

- 사용자 안내: [`사용법.txt`](사용법.txt) · 실행: `번역창 실행.bat` 더블클릭
- Python 3.9+ · tkinter(표준) · `anthropic` SDK 하나만 설치 (전용 `.venv`)
- 게임 연동은 `WoWChatLog.txt` **읽기 전용**. 메모리 읽기·입력 자동화·자동 전송 없음.

## 구조
| 파일 | 역할 |
|---|---|
| `wowchat/wowlog.py` | 로그 위치 자동 탐색(`<드라이브>\…\World of Warcraft\_xxx_\Logs`), tail 감시(재생성·초기화 추적), 채널별 줄 파서(영문·한글 클라이언트) |
| `wowchat/textkind.py` | 번역 대상 판별(한자/영문 위주), 약어 로컬 사전(88, 3Q, ty, gg …) |
| `wowchat/translate.py` | Claude 호출(프롬프트·게임 용어집), 번역 캐시, 하루 사용량 제한, `.env` 키 저장 |
| `wowchat/app.py` | tkinter UI (필터·투명도·항상 위·답장·상태줄) |
| `config.json` | 모델명, 하루 한도, 로그 경로 등 |

## 실제 PC에서 확인이 필요한 것 (0단계)
개발 환경에 와우가 없어 실제 로그 샘플 없이 영문/한글 클라이언트 표준 문구로 파서를 만들었다.
- 인식 못한 줄은 `data/인식못한_줄.txt`에 쌓인다 → 여기에 채팅 줄이 보이면 그 형식을 파서에 추가.
- 파일 기록 지연은 로그 줄의 타임스탬프와 읽은 시각 차이로 상태줄에 실시간 표시(3초 초과 시 ⚠).

## 테스트
```
python -m unittest discover -s tests
```
