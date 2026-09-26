"""WoWChatLog.txt 찾기 · 감시(tail) · 줄 파싱.

게임과의 연결은 이 파일을 '읽기'만 한다. 게임 메모리 읽기, 입력 자동화는 하지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import os
import re
import string
from dataclasses import dataclass, field
from typing import List, Optional

LOG_NAME = "WoWChatLog.txt"

# ---------------------------------------------------------------------------
# 1. 로그 파일 위치 찾기
# ---------------------------------------------------------------------------

_WOW_DIR_NAMES = ("World of Warcraft", "WoW", "World of Warcraft Forever")
_PARENTS = (
    "",
    "Program Files (x86)",
    "Program Files",
    "Games",
    "Game",
    "Blizzard",
    "Battle.net",
    r"Program Files (x86)\Blizzard",
    r"Program Files\Blizzard",
)


def _drives() -> List[str]:
    if os.name != "nt":
        return ["/"]
    return [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]


def _battlenet_install_paths() -> List[str]:
    """Battle.net이 기록해 둔 게임 설치 경로 (product.db 안의 문자열)."""
    out = []
    pd = os.environ.get("ProgramData", r"C:\ProgramData")
    db = os.path.join(pd, "Battle.net", "Agent", "product.db")
    try:
        with open(db, "rb") as f:
            data = f.read()
    except OSError:
        return out
    for m in re.finditer(rb"[A-Za-z]:[/\\][^\x00-\x1f\"<>|?*]{2,200}", data):
        p = m.group(0).decode("utf-8", errors="ignore").rstrip("\\/ ")
        if "warcraft" in p.lower() or "wow" in p.lower():
            if os.path.isdir(p) and p not in out:
                out.append(p)
    return out


def candidate_wow_roots() -> List[str]:
    roots = []

    def add(p):
        p = os.path.normpath(p)
        if os.path.isdir(p) and p not in roots:
            roots.append(p)

    for p in _battlenet_install_paths():
        add(p)
        add(os.path.dirname(p))  # product.db가 _xxx_ 폴더 자체를 가리킬 때
    for drive in _drives():
        for parent in _PARENTS:
            for name in _WOW_DIR_NAMES:
                add(os.path.join(drive, parent, name))
        # 드라이브 바로 아래 / 한 단계 아래의 '*warcraft*' 폴더
        try:
            top = [os.path.join(drive, e) for e in os.listdir(drive)]
        except OSError:
            continue
        for d in top:
            low = os.path.basename(d).lower()
            if "warcraft" in low or low in ("wow", "games", "game", "blizzard"):
                add(d)
                try:
                    for e in os.listdir(d):
                        if "warcraft" in e.lower() or e.lower().startswith("wow"):
                            add(os.path.join(d, e))
                except OSError:
                    pass
    return roots


def candidate_log_paths(extra_roots: Optional[List[str]] = None) -> List[str]:
    """와우 설치 폴더 아래 `_xxx_\\Logs\\WoWChatLog.txt` 후보들.

    파일이 아직 없어도 Logs 폴더(또는 게임 버전 폴더)가 있으면 후보로 넣는다.
    """
    found = []
    for root in (extra_roots or []) + candidate_wow_roots():
        try:
            entries = os.listdir(root)
        except OSError:
            continue
        legacy = os.path.join(root, "Logs", LOG_NAME)  # _xxx_ 폴더 없는 옛 구조
        if os.path.isdir(os.path.dirname(legacy)) and legacy not in found:
            found.append(legacy)
        for e in entries:
            flavor_dir = os.path.join(root, e)
            if not (e.startswith("_") and e.endswith("_") and os.path.isdir(flavor_dir)):
                continue
            path = os.path.join(flavor_dir, "Logs", LOG_NAME)
            if path not in found:
                found.append(path)
    return found


def pick_best_log(paths: List[str]) -> Optional[str]:
    """가장 최근에 기록된 로그 → 없으면 forever 폴더 → 첫 후보."""
    existing = [p for p in paths if os.path.isfile(p)]
    if existing:
        return max(existing, key=lambda p: os.path.getmtime(p))
    for p in paths:
        if "forever" in p.lower():
            return p
    return paths[0] if paths else None


# ---------------------------------------------------------------------------
# 2. tail 방식 감시
# ---------------------------------------------------------------------------


class LogTailer:
    """파일 끝을 따라가며 새 줄만 돌려준다.

    - 시작 시점의 기존 내용은 건너뛴다.
    - 파일이 없어졌다가 다시 생기거나, 크기가 줄면(초기화) 처음부터 다시 읽는다.
    - 매번 열고 닫아서 게임이 파일을 쓰는 데 방해하지 않는다.
    """

    def __init__(self, path: str, skip_existing: bool = True):
        self.path = path
        self._pos: Optional[int] = None
        self._ident = None
        self._partial = b""
        self.size = 0
        if skip_existing and os.path.isfile(path):
            st = os.stat(path)
            self._pos = self._real_size() or 0
            self.size = self._pos
            self._ident = self._identity(st)
        else:
            self._pos = 0 if os.path.isfile(path) else None

    @staticmethod
    def _identity(st):
        # Windows에서 st_ctime은 '생성 시각' → 파일이 새로 만들어지면 바뀐다.
        return (getattr(st, "st_ino", 0), st.st_ctime if os.name == "nt" else 0)

    @property
    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def _real_size(self) -> Optional[int]:
        # 게임이 파일을 열어 둔 채 쓰는 동안 Windows의 os.stat 크기/수정시각은
        # 갱신이 늦을 수 있다 → 파일을 직접 열어 끝 위치로 크기를 잰다.
        try:
            with open(self.path, "rb") as f:
                f.seek(0, os.SEEK_END)
                return f.tell()
        except OSError:
            return None

    def poll(self) -> List[str]:
        try:
            st = os.stat(self.path)
        except OSError:
            # 파일이 사라짐 → 다시 생기면 처음부터
            self._pos = None
            self._partial = b""
            return []
        size = self._real_size()
        if size is None:
            return []

        ident = self._identity(st)
        if self._pos is None or ident != self._ident or size < self._pos:
            self._pos = 0
            self._partial = b""
        self._ident = ident
        if size == self._pos:
            return []

        try:
            with open(self.path, "rb") as f:
                f.seek(self._pos)
                data = f.read(size - self._pos)
        except OSError:
            return []
        self._pos += len(data)
        self.size = self._pos

        data = self._partial + data
        parts = data.split(b"\n")
        self._partial = parts.pop()  # 아직 줄바꿈이 오지 않은 마지막 조각
        lines = []
        for raw in parts:
            text = raw.rstrip(b"\r").decode("utf-8", errors="replace")
            if text.strip():
                lines.append(text)
        return lines


# ---------------------------------------------------------------------------
# 3. 줄 파싱
# ---------------------------------------------------------------------------

# 채널 필터 키
PARTY, WHISPER, GUILD, SAY, PUBLIC, TRADE = "party", "whisper", "guild", "say", "public", "trade"
CHANNEL_LABELS = {
    PARTY: "파티",
    WHISPER: "귓속말",
    GUILD: "길드",
    SAY: "일반 대화",
    PUBLIC: "공개",
    TRADE: "거래",
}


@dataclass
class ChatLine:
    channel: str  # 위 필터 키 중 하나
    label: str  # 화면에 보일 채널 이름 (예: 파티, 2. 거래)
    sender: str
    text: str
    time: _dt.datetime
    outgoing: bool = False  # 내가 보낸 귓속말
    raw: str = field(default="", repr=False)


_TS_RE = re.compile(
    r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\s+(\d{1,2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(?:-\d+)?\s+(.*)$"
)

# 게임 텍스트 이스케이프 코드 정리
_ESCAPES = [
    (re.compile(r"\|c[0-9a-fA-F]{8}"), ""),
    (re.compile(r"\|r"), ""),
    (re.compile(r"\|H[^|]*\|h"), ""),
    (re.compile(r"\|h"), ""),
    (re.compile(r"\|T[^|]*\|t"), ""),
    (re.compile(r"\|A[^|]*\|a"), ""),
    (re.compile(r"\|K[^|]*\|k"), "?"),
]

_NAME = r"\[?(?P<name>[^\s:\[\]]+?)\]?"

# 1) [채널] 이름: 내용
_BRACKET_RE = re.compile(r"^\[(?P<chan>[^\]]+)\]\s*" + _NAME + r"\s*:\s?(?P<msg>.*)$")
# 2) 귓속말/외침/말하기 (영문·한글 클라이언트)
_SIMPLE_RES = [
    (re.compile(r"^" + _NAME + r" whispers\s*:\s?(?P<msg>.*)$"), WHISPER, "귓속말", False),
    (re.compile(r"^To " + _NAME + r"\s*:\s?(?P<msg>.*)$"), WHISPER, "귓속말", True),
    (re.compile(r"^" + _NAME + r"\s*님(?:의|이) 귓속말\s*:\s?(?P<msg>.*)$"), WHISPER, "귓속말", False),
    (re.compile(r"^" + _NAME + r"\s*님(?:에게|께) 귓속말\s*:\s?(?P<msg>.*)$"), WHISPER, "귓속말", True),
    (re.compile(r"^" + _NAME + r" says\s*:\s?(?P<msg>.*)$"), SAY, "일반", False),
    (re.compile(r"^" + _NAME + r" yells\s*:\s?(?P<msg>.*)$"), SAY, "외침", False),
    (re.compile(r"^" + _NAME + r"\s*님의 말\s*:\s?(?P<msg>.*)$"), SAY, "일반", False),
    (re.compile(r"^" + _NAME + r"\s*님의 외침\s*:\s?(?P<msg>.*)$"), SAY, "외침", False),
    # 한글 클라이언트 일반 대화: "이름: 내용" (이름에 공백 없음)
    (re.compile(r"^" + _NAME + r": (?P<msg>.+)$"), SAY, "일반", False),
]

_PARTY_WORDS = ("party", "raid", "instance", "battleground", "파티", "공격대", "인스턴스", "전장", "공대")
_GUILD_WORDS = ("guild", "officer", "길드", "관리자", "오피서")
_TRADE_WORDS = ("trade", "거래", "交易")

# 일반 대화 패턴에 걸리면 안 되는 시스템성 이름
_NOT_A_NAME = {"loot", "전리품", "경험치", "system", "시스템", "http", "https"}


def _clean(text: str) -> str:
    for pat, rep in _ESCAPES:
        text = pat.sub(rep, text)
    return text.strip()


def _strip_realm(name: str) -> str:
    return name.split("-", 1)[0] if "-" in name else name


def _parse_time(m) -> _dt.datetime:
    now = _dt.datetime.now()
    mon, day, year, hh, mm, ss, ms = m.group(1, 2, 3, 4, 5, 6, 7)
    y = int(year) if year else now.year
    if y < 100:
        y += 2000
    try:
        t = _dt.datetime(y, int(mon), int(day), int(hh), int(mm), int(ss), int((ms or "0").ljust(3, "0")) * 1000)
    except ValueError:
        return now
    # 연도 없는 형식에서 새해 직후 12/31 로그가 미래로 잡히는 것 방지
    if not year and t - now > _dt.timedelta(days=1):
        t = t.replace(year=y - 1)
    return t


def classify_bracket(chan: str) -> Optional[str]:
    low = chan.lower()
    numbered = bool(re.match(r"^\d+\.", chan.strip()))
    if numbered:
        return TRADE if any(w in low for w in _TRADE_WORDS) else PUBLIC
    if any(w in low for w in _PARTY_WORDS):
        return PARTY
    if any(w in low for w in _GUILD_WORDS):
        return GUILD
    if any(w in low for w in _TRADE_WORDS):
        return TRADE
    return None


def line_timestamp(line: str) -> Optional[_dt.datetime]:
    """줄 앞의 게임 기록 시각 (파일 기록 지연 측정용)."""
    m = _TS_RE.match(line)
    return _parse_time(m) if m else None


def parse_line(line: str) -> Optional[ChatLine]:
    """채팅 한 줄 → ChatLine. 시스템 메시지 등 채팅이 아니면 None."""
    raw = line
    m = _TS_RE.match(line)
    if m:
        when = _parse_time(m)
        body = m.group(8)
    else:
        when = _dt.datetime.now()
        body = line
    body = _clean(body)
    if not body:
        return None

    bm = _BRACKET_RE.match(body)
    kind = classify_bracket(bm.group("chan").strip()) if bm else None
    if bm and kind is not None:
        chan = bm.group("chan").strip()
        label = chan  # 파티장/공격대/2. 거래 등 게임 표기 그대로
        msg = bm.group("msg").strip()
        if not msg:
            return None
        return ChatLine(kind, label, _strip_realm(bm.group("name")), msg, when, False, raw)

    for pat, kind, label, outgoing in _SIMPLE_RES:
        sm = pat.match(body)
        if not sm:
            continue
        name = sm.group("name")
        if name.lower() in _NOT_A_NAME or name.isdigit():
            return None
        msg = sm.group("msg").strip()
        if not msg:
            return None
        return ChatLine(kind, label, _strip_realm(name), msg, when, outgoing, raw)
    return None  # 시스템 메시지, 감정표현, [알 수 없는 채널] 등
