"""번역 창 시작 파일 — '번역창 실행.bat'이 이 파일을 실행한다."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from wowchat.app import main  # noqa: E402

if __name__ == "__main__":
    main()
