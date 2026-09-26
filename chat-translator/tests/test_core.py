import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wowchat import wowlog  # noqa: E402
from wowchat.textkind import lookup_abbreviation, needs_translation  # noqa: E402
from wowchat.translate import TranslationCache, UsageCounter  # noqa: E402


class ParseTest(unittest.TestCase):
    def check(self, line, channel, sender, text, outgoing=False):
        c = wowlog.parse_line(line)
        self.assertIsNotNone(c, line)
        self.assertEqual((c.channel, c.sender, c.text, c.outgoing), (channel, sender, text, outgoing))

    def test_english_client(self):
        ts = "9/26 21:15:32.123  "
        self.check(ts + "[Party] Xiaoming: 等我一下", wowlog.PARTY, "Xiaoming", "等我一下")
        self.check(ts + "[Party Leader] Bob-Realm: pull now", wowlog.PARTY, "Bob", "pull now")
        self.check(ts + "[Raid] 小明: 坦呢", wowlog.PARTY, "小明", "坦呢")
        self.check(ts + "[Guild] Amy: hi all", wowlog.GUILD, "Amy", "hi all")
        self.check(ts + "[Officer] Amy: x y", wowlog.GUILD, "Amy", "x y")
        self.check(ts + "[2. Trade - City] Seller: WTS [Linen Cloth] 5s ea", wowlog.TRADE, "Seller", "WTS [Linen Cloth] 5s ea")
        self.check(ts + "[1. General - Elwynn Forest] Joe: where is hogger", wowlog.PUBLIC, "Joe", "where is hogger")
        self.check(ts + "[4. LookingForGroup] Joe: LFM DM", wowlog.PUBLIC, "Joe", "LFM DM")
        self.check(ts + "Joe whispers: inv pls", wowlog.WHISPER, "Joe", "inv pls")
        self.check(ts + "To Joe: 好的", wowlog.WHISPER, "Joe", "好的", outgoing=True)
        self.check(ts + "Joe says: hello there", wowlog.SAY, "Joe", "hello there")
        self.check(ts + "Joe yells: help!", wowlog.SAY, "Joe", "help!")
        self.check(ts + "[Joe] says: bracketed", wowlog.SAY, "Joe", "bracketed")

    def test_korean_client(self):
        ts = "9/26 21:15:32.123  "
        self.check(ts + "[파티] 小明: 88", wowlog.PARTY, "小明", "88")
        self.check(ts + "[파티장] Bob: go", wowlog.PARTY, "Bob", "go")
        self.check(ts + "[공격대] Bob: go", wowlog.PARTY, "Bob", "go")
        self.check(ts + "[길드] 아무개: 안녕", wowlog.GUILD, "아무개", "안녕")
        self.check(ts + "[2. 거래 - 도시] 상인: WTS", wowlog.TRADE, "상인", "WTS")
        self.check(ts + "[1. 공개 - 엘윈 숲] 조: hi", wowlog.PUBLIC, "조", "hi")
        self.check(ts + "小明님의 귓속말: 謝謝", wowlog.WHISPER, "小明", "謝謝")
        self.check(ts + "小明님에게 귓속말: 不客氣", wowlog.WHISPER, "小明", "不客氣", outgoing=True)
        self.check(ts + "小明: 你好", wowlog.SAY, "小明", "你好")
        self.check(ts + "小明님의 외침: 救命", wowlog.SAY, "小明", "救命")

    def test_screenshot_lines(self):
        ts = "9/26/2026 02:04:12.345-4  "
        self.check(ts + "[1. 공개 - 스톰윈드] [咒魂终章]: [毛纺包]=10毛料，人在银行邮箱，直接组",
                   wowlog.PUBLIC, "咒魂终章", "[毛纺包]=10毛料，人在银行邮箱，直接组")
        self.check(ts + "[1. General - Stormwind City] [Hans-Everlook]: /w me für mehr Infos",
                   wowlog.PUBLIC, "Hans", "/w me für mehr Infos")

    def test_color_codes_and_links(self):
        c = wowlog.parse_line("9/26 21:15:32.123  [Party] Bob: need |cff0070dd|Hitem:1234::|h[Cool Sword]|h|r ?")
        self.assertEqual(c.text, "need [Cool Sword] ?")

    def test_system_lines_ignored(self):
        ts = "9/26 21:15:32.123  "
        for line in [
            ts + "You receive loot: [Linen Cloth].",
            ts + "You gain 120 experience.",
            ts + "Bob has come online.",
            ts + "[System] something",
            ts + "Joe waves at you.",
            ts + "전리품을 획득했습니다: [리넨 옷감]",
            ts + "경험치를 120 얻었습니다.",
            ts + "Loot: something",
        ]:
            self.assertIsNone(wowlog.parse_line(line), line)

    def test_timestamp(self):
        t = wowlog.line_timestamp("9/26 21:15:32.123  x")
        self.assertEqual((t.month, t.day, t.hour, t.minute, t.second), (9, 26, 21, 15, 32))
        self.assertIsNone(wowlog.line_timestamp("no time here"))


class TextKindTest(unittest.TestCase):
    def test_abbrev(self):
        self.assertIn("바이바이", lookup_abbreviation("88"))
        self.assertIn("고마워", lookup_abbreviation("3Q"))
        self.assertIn("고마워", lookup_abbreviation("3q!!"))
        self.assertIn("고마워", lookup_abbreviation("ty"))
        self.assertIn("수고", lookup_abbreviation("GG"))
        self.assertIsNotNone(lookup_abbreviation("ty gg"))
        self.assertIsNotNone(lookup_abbreviation("88888"))
        self.assertIsNone(lookup_abbreviation("LFM DM need heal"))
        self.assertIsNone(lookup_abbreviation("12345"))

    def test_needs_translation(self):
        self.assertTrue(needs_translation("缺一個補，來的密"))
        self.assertTrue(needs_translation("需要治疗吗"))
        self.assertTrue(needs_translation("LFM Deadmines need healer"))
        self.assertFalse(needs_translation("부활 없어서 뛰어오셔야 해요"))
        self.assertFalse(needs_translation("123 456 !!"))
        self.assertFalse(needs_translation("[Linen Cloth] 5"))
        self.assertFalse(needs_translation("ㅋㅋㅋ ok"))
        self.assertTrue(needs_translation("坦呢? 你好 ㅋ"))


class TailerTest(unittest.TestCase):
    def test_follow_truncate_recreate(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "WoWChatLog.txt")
        with open(p, "wb") as f:
            f.write(b"old line 1\r\nold line 2\r\n")
        t = wowlog.LogTailer(p)
        self.assertEqual(t.poll(), [])  # 기존 내용 무시
        with open(p, "ab") as f:
            f.write("새 줄\r\n반쪽".encode("utf-8"))
        self.assertEqual(t.poll(), ["새 줄"])
        with open(p, "ab") as f:
            f.write(b" done\r\n")
        self.assertEqual(t.poll(), ["반쪽 done"])
        # 초기화(크기 감소)
        with open(p, "wb") as f:
            f.write(b"a\r\n")
        self.assertEqual(t.poll(), ["a"])
        # 삭제 후 재생성 (재접속)
        os.remove(p)
        self.assertEqual(t.poll(), [])
        with open(p, "wb") as f:
            f.write(b"after relog\r\n")
        self.assertEqual(t.poll(), ["after relog"])

    def test_file_created_later(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "WoWChatLog.txt")
        t = wowlog.LogTailer(p)
        self.assertEqual(t.poll(), [])
        with open(p, "wb") as f:
            f.write(b"first\n")
        self.assertEqual(t.poll(), ["first"])


class StoreTest(unittest.TestCase):
    def test_usage_limit(self):
        d = tempfile.mkdtemp()
        u = UsageCounter(os.path.join(d, "u.json"), 2)
        self.assertTrue(u.try_take())
        self.assertTrue(u.try_take())
        self.assertFalse(u.try_take())
        self.assertEqual(UsageCounter(os.path.join(d, "u.json"), 2).today, 2)

    def test_cache(self):
        d = tempfile.mkdtemp()
        c = TranslationCache(os.path.join(d, "c.json"))
        c.put("ko", "WTS  Linen!", "리넨 팝니다")
        self.assertEqual(c.get("ko", "wts linen"), "리넨 팝니다")
        c.save()
        self.assertEqual(TranslationCache(os.path.join(d, "c.json")).get("ko", "WTS Linen"), "리넨 팝니다")


class TranslatorTest(unittest.TestCase):
    def test_translate_uses_cache_and_limit(self):
        try:
            from wowchat.translate import DailyLimitReached, Translator
        except ImportError:
            self.skipTest("anthropic not installed")
        d = tempfile.mkdtemp()
        calls = []

        def create(**kw):
            calls.append(kw)
            return SimpleNamespace(content=[SimpleNamespace(type="text", text="復活沒了，要跑屍過來")])

        tr = Translator("sk-ant-test", "claude-haiku-4-5",
                        UsageCounter(os.path.join(d, "u.json"), 1), TranslationCache(os.path.join(d, "c.json")))
        tr.client = SimpleNamespace(messages=SimpleNamespace(create=create))
        out, cached = tr.translate("zh-TW", "부활 없어서 뛰어오셔야 해요")
        self.assertEqual((out, cached), ("復活沒了，要跑屍過來", False))
        self.assertEqual(calls[0]["model"], "claude-haiku-4-5")
        self.assertIn("번체", calls[0]["system"])
        out, cached = tr.translate("zh-TW", "부활 없어서 뛰어오셔야 해요")
        self.assertTrue(cached)
        self.assertEqual(len(calls), 1)
        with self.assertRaises(DailyLimitReached):
            tr.translate("ko", "hello there friend")


if __name__ == "__main__":
    unittest.main()
