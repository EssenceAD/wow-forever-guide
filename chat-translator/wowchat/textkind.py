"""번역 대상 판별 + 게임 채팅 약어 로컬 사전."""
from __future__ import annotations

import re
from typing import Optional

# 약어/짧은 인사 → 즉시 풀이 (API 호출 없음). 키는 소문자.
ABBREVIATIONS = {
    # 중국어권 숫자·영문 은어
    "88": "바이바이 (잘 가)",
    "886": "바이바이 (잘 가)",
    "8888": "바이바이~",
    "3q": "고마워 (Thank you)",
    "3q3q": "고마워 고마워",
    "3qq": "고마워",
    "555": "흑흑 (우는 소리)",
    "5555": "흑흑 (우는 소리)",
    "233": "ㅋㅋㅋ",
    "2333": "ㅋㅋㅋ",
    "23333": "ㅋㅋㅋㅋ",
    "666": "대박, 잘한다 (666)",
    "6666": "대박, 잘한다 (666)",
    "+1": "나도 (+1)",
    "orz": "좌절 (orz)",
    # 중국어 짧은 말
    "謝謝": "고마워",
    "谢谢": "고마워",
    "感謝": "감사해요",
    "感谢": "감사해요",
    "謝啦": "고마워~",
    "谢啦": "고마워~",
    "哈哈": "ㅋㅋ",
    "哈哈哈": "ㅋㅋㅋ",
    "哈哈哈哈": "ㅋㅋㅋㅋ",
    "呵呵": "ㅎㅎ",
    "嗯": "응",
    "嗯嗯": "응응",
    "好": "좋아",
    "好的": "알겠어",
    "好喔": "좋아~",
    "好哦": "좋아~",
    "拜拜": "바이바이",
    "掰掰": "바이바이",
    "辛苦了": "수고했어",
    "抱歉": "미안",
    "不好意思": "미안해요",
    "等等": "잠깐만",
    "等我": "기다려 줘",
    "沒問題": "문제없어",
    "没问题": "문제없어",
    "你好": "안녕",
    "大家好": "다들 안녕",
    # 영어 약어
    "ty": "고마워 (ty)",
    "tyty": "고마워 고마워",
    "tyvm": "정말 고마워",
    "thx": "고마워 (thx)",
    "thanks": "고마워",
    "tks": "고마워",
    "tx": "고마워",
    "np": "천만에 (np)",
    "yw": "천만에 (yw)",
    "gg": "수고했어 (gg)",
    "gj": "잘했어 (gj)",
    "wp": "잘했어 (wp)",
    "gl": "행운을 빌어 (gl)",
    "hf": "재밌게 해 (hf)",
    "glhf": "행운을 빌어, 재밌게 해",
    "lol": "ㅋㅋ",
    "lmao": "ㅋㅋㅋ",
    "rofl": "ㅋㅋㅋㅋ",
    "haha": "ㅋㅋ",
    "brb": "잠깐 자리 비움 (곧 올게)",
    "afk": "자리 비움",
    "bio": "화장실 다녀올게 (bio)",
    "omw": "가는 중",
    "otw": "가는 중",
    "inv": "초대해 줘 (inv)",
    "inv pls": "초대 부탁해",
    "inv plz": "초대 부탁해",
    "pst": "귓말 줘 (PST)",
    "sry": "미안",
    "sorry": "미안",
    "k": "응 (k)",
    "kk": "응응",
    "ok": "오케이",
    "okay": "오케이",
    "wb": "어서 와 (wb)",
    "nvm": "신경 쓰지 마",
    "idk": "몰라",
    "oom": "마나 없음 (oom)",
    "rdy": "준비 완료",
    "ready": "준비 완료",
    "r": "준비 완료 (r)",
    "w8": "잠깐 (기다려)",
    "wait": "잠깐 (기다려)",
    "sec": "잠깐만",
    "1 sec": "잠깐만",
    "hi": "안녕",
    "hello": "안녕",
    "hey": "안녕",
    "yo": "안녕",
    "bye": "바이",
    "cya": "또 봐",
    "gn": "잘 자",
    "gz": "축하해 (gz)",
    "grats": "축하해",
    "gratz": "축하해",
    "congrats": "축하해",
    "ding": "레벨업! (ding)",
    "y": "응 (y)",
    "yes": "응",
    "yep": "응",
    "n": "아니 (n)",
    "no": "아니",
    "nope": "아니",
    "lf": "구함 (LF)",
    "lfg": "파티 구함 (LFG)",
    "lfm": "파티원 구함 (LFM)",
}

_HAN_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿]")
_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_ITEM_LINK_RE = re.compile(r"\[[^\]]*\]")
_EDGE_PUNCT = " \t.!?~,;:。！？～、…'\"()（）"


def normalize(text: str) -> str:
    """캐시/약어 비교용: 소문자 + 공백 정리 + 앞뒤 문장부호 제거."""
    t = re.sub(r"\s+", " ", text).strip().lower()
    return t.strip(_EDGE_PUNCT)


def lookup_abbreviation(text: str) -> Optional[str]:
    """메시지 전체가 약어(들)로만 이루어져 있으면 풀이를 돌려준다."""
    key = normalize(text)
    if not key:
        return None
    if key in ABBREVIATIONS:
        return ABBREVIATIONS[key]
    # 반복 글자 줄이기: "tyyyy" "88888" "哈哈哈哈哈"
    for n in (3, 2):
        squeezed = re.sub(r"(.)\1{%d,}" % n, r"\1" * n, key)
        if squeezed in ABBREVIATIONS:
            return ABBREVIATIONS[squeezed]
    words = [w.strip(_EDGE_PUNCT) for w in key.split(" ")]
    words = [w for w in words if w]
    if 1 < len(words) <= 4 and all(w in ABBREVIATIONS for w in words):
        return " / ".join(ABBREVIATIONS[w] for w in words)
    return None


def needs_translation(text: str) -> bool:
    """한자(한글 제외) 또는 영문 위주 메시지만 True.

    한국어 메시지, 숫자·기호뿐인 메시지, 아이템 링크뿐인 메시지는 False.
    """
    body = _ITEM_LINK_RE.sub(" ", text)
    han = len(_HAN_RE.findall(body))
    hangul = len(_HANGUL_RE.findall(body))
    latin = len(_LATIN_RE.findall(body))
    if han == 0 and latin == 0:
        return False  # 숫자·기호·한글뿐
    if hangul == 0:
        return han > 0 or latin >= 2
    # 한글이 섞여 있으면 한글보다 외국어가 확실히 많을 때만
    return han > hangul * 2 or latin > hangul * 4
