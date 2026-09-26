"""와우 채팅 실시간 번역 창 (tkinter)."""
from __future__ import annotations

import collections
import datetime as _dt
import json
import os
import queue
import statistics
import sys
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor

import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import wowlog
from .textkind import lookup_abbreviation, needs_translation, normalize
from .translate import (
    REPLY_LANG_LABELS,
    ApiKeyError,
    DailyLimitReached,
    TranslateFailed,
    TranslationCache,
    Translator,
    UsageCounter,
    read_api_key,
    save_api_key,
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
USAGE_PATH = os.path.join(DATA_DIR, "usage.json")
CACHE_PATH = os.path.join(DATA_DIR, "cache.json")
UNKNOWN_PATH = os.path.join(DATA_DIR, "인식못한_줄.txt")
ERROR_PATH = os.path.join(DATA_DIR, "error.log")
HELP_PATH = os.path.join(BASE_DIR, "사용법.txt")

DEFAULT_CONFIG = {
    "model": "claude-haiku-4-5",
    "daily_limit": 1000,
    "log_path": "",
    "max_lines": 200,
    "poll_interval_ms": 250,
    "delay_warn_seconds": 3,
    "font_size": 11,
    "save_unknown_lines": True,
}

CHANNEL_ORDER = [wowlog.PARTY, wowlog.WHISPER, wowlog.GUILD, wowlog.SAY, wowlog.PUBLIC, wowlog.TRADE]
DEFAULT_FILTERS = {wowlog.PARTY: True, wowlog.WHISPER: True, wowlog.GUILD: True, wowlog.SAY: True,
                   wowlog.PUBLIC: False, wowlog.TRADE: False}
CHANNEL_COLORS = {
    wowlog.PARTY: "#9fb4ff", wowlog.WHISPER: "#ff9ff0", wowlog.GUILD: "#6fe38a",
    wowlog.SAY: "#f0f0f0", wowlog.PUBLIC: "#ffc9a8", wowlog.TRADE: "#ffc9a8",
}

BG, BG2, FG, FG_DIM, FG_ORIG, ACCENT, WARN = "#12161d", "#1c222c", "#f2f4f7", "#7f8b9b", "#98a2b0", "#e0b45c", "#ff7b6b"


def _load_json(path, default):
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else default
    except (OSError, ValueError):
        return default


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_config():
    cfg = dict(DEFAULT_CONFIG)
    user = _load_json(CONFIG_PATH, None)
    if user is None:
        _save_json(CONFIG_PATH, DEFAULT_CONFIG)
    else:
        cfg.update(user)
    return cfg


def _pick_font(root, names, size, weight="normal"):
    families = set(tkfont.families(root))
    for n in names:
        if n in families:
            return (n, size, weight)
    return ("TkDefaultFont", size, weight)


class TranslatorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        os.makedirs(DATA_DIR, exist_ok=True)
        self.cfg = load_config()
        self.state = _load_json(STATE_PATH, {})

        self.usage = UsageCounter(USAGE_PATH, int(self.cfg["daily_limit"]))
        self.cache = TranslationCache(CACHE_PATH)
        self.translator = None
        self.api_key_problem = False
        self.pool = ThreadPoolExecutor(max_workers=3)
        self.results: "queue.Queue" = queue.Queue()

        self.tailer = None
        self.log_path = None
        self.log_auto = not self.cfg.get("log_path")
        self.delays = collections.deque(maxlen=15)
        self.last_line_at = None

        self.entry_ids = collections.deque()
        self.next_id = 0
        self.my_replies = collections.deque(maxlen=30)
        self.last_reply = ""

        self._build_ui()
        self._restore_window()
        self._init_translator(ask_if_missing=True)
        self._select_log(initial=True)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(200, self._poll_log)
        self.root.after(100, self._drain_results)
        self.root.after(500, self._update_status)
        self.root.after(15000, self._rescan_log)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        r = self.root
        r.title("와우 채팅 번역")
        r.configure(bg=BG)
        r.minsize(320, 300)
        size = int(self.cfg.get("font_size", 11))
        self.f_orig = _pick_font(r, ["Microsoft JhengHei", "Microsoft JhengHei UI", "Microsoft YaHei",
                                     "Noto Sans CJK TC", "Noto Sans TC"], size - 2)
        self.f_ko = _pick_font(r, ["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR", "Noto Sans KR"], size + 1, "bold")
        self.f_ui = _pick_font(r, ["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR"], 9)
        self.f_head = _pick_font(r, ["Malgun Gothic", "맑은 고딕", "Noto Sans CJK KR"], size - 3)
        self.f_reply = _pick_font(r, ["Microsoft JhengHei", "Microsoft JhengHei UI", "Malgun Gothic",
                                      "Noto Sans CJK TC"], size)

        style = ttk.Style(r)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, font=self.f_ui)
        style.configure("TCheckbutton", background=BG, foreground=FG)
        style.map("TCheckbutton", background=[("active", BG2)])
        style.configure("TButton", background=BG2, foreground=FG, padding=(8, 2))
        style.map("TButton", background=[("active", "#2a3340")])
        style.configure("TCombobox", fieldbackground=BG2, background=BG2, foreground=FG, arrowcolor=FG)
        style.map("TCombobox", fieldbackground=[("readonly", BG2)], foreground=[("readonly", FG)])
        style.configure("Horizontal.TScale", background=BG)

        # --- 상단: 채널 필터
        top = tk.Frame(r, bg=BG)
        top.pack(fill="x", padx=6, pady=(6, 0))
        saved = self.state.get("filters", {})
        self.filter_vars = {}
        for i, ch in enumerate(CHANNEL_ORDER):
            v = tk.BooleanVar(value=bool(saved.get(ch, DEFAULT_FILTERS[ch])))
            v.trace_add("write", lambda *_: self._save_state())
            self.filter_vars[ch] = v
            ttk.Checkbutton(top, text=wowlog.CHANNEL_LABELS[ch], variable=v).grid(row=i // 3, column=i % 3, sticky="w", padx=(0, 8))

        # --- 두 번째 줄: 투명도 / 항상 위 / 메뉴
        bar = tk.Frame(r, bg=BG)
        bar.pack(fill="x", padx=6, pady=(2, 4))
        tk.Label(bar, text="투명도", bg=BG, fg=FG_DIM, font=self.f_ui).pack(side="left")
        self.alpha_var = tk.DoubleVar(value=float(self.state.get("alpha", 0.92)))
        ttk.Scale(bar, from_=0.3, to=1.0, variable=self.alpha_var, length=110,
                  command=lambda _v: self._apply_alpha()).pack(side="left", padx=(4, 10))
        self.topmost_var = tk.BooleanVar(value=bool(self.state.get("topmost", True)))
        ttk.Checkbutton(bar, text="항상 위", variable=self.topmost_var, command=self._apply_topmost).pack(side="left")

        menu_btn = tk.Menubutton(bar, text="⚙ 설정", bg=BG2, fg=FG, activebackground="#2a3340",
                                 activeforeground=FG, relief="flat", font=self.f_ui)
        m = tk.Menu(menu_btn, tearoff=False)
        m.add_command(label="로그 파일 위치 직접 지정…", command=self._choose_log)
        m.add_command(label="로그 위치 자동 찾기로 되돌리기", command=self._reset_log_auto)
        m.add_separator()
        m.add_command(label="API 키 변경…", command=lambda: self._ask_api_key(force=True))
        m.add_command(label="화면 지우기", command=self._clear)
        m.add_separator()
        m.add_command(label="설정 파일 열기 (config.json)", command=lambda: self._open_file(CONFIG_PATH))
        m.add_command(label="사용법 보기", command=lambda: self._open_file(HELP_PATH))
        menu_btn["menu"] = m
        menu_btn.pack(side="right")

        # --- 하단 상태줄 (먼저 pack 해서 항상 보이게)
        self.status = tk.Label(r, text="", anchor="w", bg=BG2, fg=FG_DIM, font=self.f_ui, padx=6)
        self.status.pack(side="bottom", fill="x")

        # --- 답장 영역
        reply = tk.Frame(r, bg=BG)
        reply.pack(side="bottom", fill="x", padx=6, pady=(4, 4))
        row1 = tk.Frame(reply, bg=BG)
        row1.pack(fill="x")
        self.reply_entry = tk.Entry(row1, bg=BG2, fg=FG, insertbackground=FG, relief="flat", font=self.f_ko[:2])
        self.reply_entry.pack(side="left", fill="x", expand=True, ipady=4)
        self.reply_entry.bind("<Return>", lambda _e: self.on_reply())
        labels = list(REPLY_LANG_LABELS.values())
        self.lang_var = tk.StringVar(value=REPLY_LANG_LABELS.get(self.state.get("reply_lang", "zh-TW"), labels[0]))
        cb = ttk.Combobox(row1, textvariable=self.lang_var, values=labels, state="readonly", width=11)
        cb.pack(side="left", padx=4)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._save_state())
        self.reply_btn = ttk.Button(row1, text="번역", command=self.on_reply)
        self.reply_btn.pack(side="left")

        row2 = tk.Frame(reply, bg=BG)
        row2.pack(fill="x", pady=(4, 0))
        self.reply_out = tk.Entry(row2, bg=BG, fg=ACCENT, relief="flat", font=self.f_reply,
                                  readonlybackground=BG, state="readonly")
        self.reply_out.pack(side="left", fill="x", expand=True)
        ttk.Button(row2, text="다시 복사", command=self._copy_last).pack(side="left", padx=(4, 0))
        self.reply_info = tk.Label(reply, text="한국어로 쓰고 Enter → 번역문이 클립보드에 복사됩니다 (게임에서 Ctrl+V)",
                                   anchor="w", bg=BG, fg=FG_DIM, font=self.f_head)
        self.reply_info.pack(fill="x")

        # --- 가운데: 번역 목록
        mid = tk.Frame(r, bg=BG)
        mid.pack(fill="both", expand=True, padx=6)
        self.text = tk.Text(mid, bg=BG, fg=FG, wrap="word", relief="flat", borderwidth=0,
                            highlightthickness=0, padx=4, pady=4, cursor="arrow", state="disabled")
        sb = ttk.Scrollbar(mid, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("head", font=self.f_head, foreground=FG_DIM, spacing1=6)
        self.text.tag_configure("orig", font=self.f_orig, foreground=FG_ORIG)
        self.text.tag_configure("trans", font=self.f_ko, foreground=FG, spacing3=4)
        self.text.tag_configure("local", font=self.f_ko, foreground="#9fe3b0", spacing3=4)
        self.text.tag_configure("pending", font=self.f_head, foreground=FG_DIM, spacing3=4)
        self.text.tag_configure("fail", font=self.f_head, foreground=WARN, spacing3=4)
        for ch, color in CHANNEL_COLORS.items():
            self.text.tag_configure("ch_" + ch, foreground=color, font=self.f_head)

    def _restore_window(self):
        geo = self.state.get("geometry")
        try:
            self.root.geometry(geo or "440x620")
        except tk.TclError:
            self.root.geometry("440x620")
        self._apply_alpha()
        self._apply_topmost()

    def _apply_alpha(self):
        try:
            self.root.attributes("-alpha", max(0.3, min(1.0, self.alpha_var.get())))
        except tk.TclError:
            pass

    def _apply_topmost(self):
        self.root.attributes("-topmost", bool(self.topmost_var.get()))
        self._save_state()

    def _save_state(self):
        inv = {v: k for k, v in REPLY_LANG_LABELS.items()}
        self.state.update({
            "filters": {ch: bool(v.get()) for ch, v in self.filter_vars.items()},
            "alpha": round(float(self.alpha_var.get()), 2),
            "topmost": bool(self.topmost_var.get()),
            "reply_lang": inv.get(self.lang_var.get(), "zh-TW") if hasattr(self, "lang_var") else "zh-TW",
        })
        if self.root.state() == "normal":
            self.state["geometry"] = self.root.geometry()
        _save_json(STATE_PATH, self.state)

    def on_close(self):
        try:
            self._save_state()
            self.cache.save()
        finally:
            self.pool.shutdown(wait=False, cancel_futures=True)
            self.root.destroy()

    def _open_file(self, path):
        try:
            os.startfile(path)  # type: ignore[attr-defined]  (Windows)
        except Exception:
            messagebox.showinfo("파일 위치", path, parent=self.root)

    # ------------------------------------------------------------ API 키
    def _init_translator(self, ask_if_missing=False):
        key = read_api_key(ENV_PATH)
        if not key and ask_if_missing:
            key = self._ask_api_key()
        if not key:
            self.translator = None
            return
        try:
            self.translator = Translator(key, self.cfg["model"], self.usage, self.cache)
            self.api_key_problem = False
        except ImportError:
            messagebox.showerror("설치 문제", "anthropic 패키지가 없습니다. '번역창 실행.bat'으로 실행해 주세요.", parent=self.root)
            self.translator = None

    def _ask_api_key(self, force=False):
        key = simpledialog.askstring(
            "Claude API 키 입력",
            "Claude API 키를 붙여 넣으세요 (sk-ant- 로 시작).\n"
            "console.anthropic.com → API Keys 에서 만들 수 있습니다.\n"
            "이 PC의 .env 파일에만 저장됩니다.",
            parent=self.root, show="*",
        )
        if not key or not key.strip():
            return None
        key = key.strip()
        if not key.startswith("sk-ant-"):
            messagebox.showwarning("API 키", "sk-ant- 로 시작하는 키가 아닙니다. 다시 확인해 주세요.", parent=self.root)
            return None
        save_api_key(ENV_PATH, key)
        os.environ.pop("ANTHROPIC_API_KEY", None)
        if force:
            self._init_translator()
        return key

    # ------------------------------------------------------------ 로그 선택
    def _select_log(self, initial=False):
        if not self.log_auto:
            path = self.cfg["log_path"]
        else:
            path = wowlog.pick_best_log(wowlog.candidate_log_paths())
        if path and path != self.log_path:
            self.log_path = path
            self.tailer = wowlog.LogTailer(path, skip_existing=True)
        elif not path and initial:
            self.root.after(800, self._no_wow_found)

    def _no_wow_found(self):
        if self.log_path:
            return
        if messagebox.askyesno(
            "와우 폴더를 못 찾음",
            "WoWChatLog.txt 위치를 자동으로 찾지 못했습니다.\n"
            "와우 설치 폴더 안의 Logs 폴더를 직접 지정할까요?\n\n"
            "(예: World of Warcraft\\_forever_\\Logs)",
            parent=self.root,
        ):
            self._choose_log()

    def _choose_log(self):
        d = filedialog.askdirectory(title="와우 Logs 폴더 선택 (WoWChatLog.txt가 생기는 곳)", parent=self.root)
        if not d:
            return
        path = os.path.join(d, wowlog.LOG_NAME)
        if os.path.basename(os.path.normpath(d)).lower() != "logs" and os.path.isdir(os.path.join(d, "Logs")):
            path = os.path.join(d, "Logs", wowlog.LOG_NAME)
        self.cfg["log_path"] = path
        self._write_config()
        self.log_auto = False
        self.log_path = None
        self._select_log()

    def _reset_log_auto(self):
        self.cfg["log_path"] = ""
        self._write_config()
        self.log_auto = True
        self.log_path = None
        self._select_log(initial=True)

    def _write_config(self):
        user = _load_json(CONFIG_PATH, dict(DEFAULT_CONFIG))
        user["log_path"] = self.cfg["log_path"]
        _save_json(CONFIG_PATH, user)

    def _rescan_log(self):
        # 자동 모드: 다른 버전 폴더의 로그가 더 최근이면 그쪽으로 따라간다
        if self.log_auto:
            best = wowlog.pick_best_log(wowlog.candidate_log_paths())
            cur_ok = self.log_path and os.path.isfile(self.log_path)
            if best and best != self.log_path and (not cur_ok or os.path.isfile(best)):
                if not cur_ok or os.path.getmtime(best) > os.path.getmtime(self.log_path) + 5:
                    self.log_path = best
                    self.tailer = wowlog.LogTailer(best, skip_existing=True)
        self.root.after(15000, self._rescan_log)

    # ------------------------------------------------------------ 로그 감시
    def _poll_log(self):
        try:
            if self.tailer:
                for line in self.tailer.poll():
                    self._handle_line(line)
        except Exception:
            _log_error()
        self.root.after(int(self.cfg.get("poll_interval_ms", 250)), self._poll_log)

    def _handle_line(self, line: str):
        now = _dt.datetime.now()
        self.last_line_at = now
        ts = wowlog.line_timestamp(line)
        if ts is not None:
            d = (now - ts).total_seconds()
            if -5 < d < 600:
                self.delays.append(max(0.0, d))

        chat = wowlog.parse_line(line)
        if chat is None:
            if self.cfg.get("save_unknown_lines"):
                self._note_unknown(line)
            return
        if not self.filter_vars[chat.channel].get():
            return

        if chat.outgoing or normalize(chat.text) in self.my_replies:
            if needs_translation(chat.text) or lookup_abbreviation(chat.text):
                self._add_entry(chat, "↳ 내가 보낸 메시지", "pending")
            return

        local = lookup_abbreviation(chat.text)
        if local:
            self._add_entry(chat, local, "local")
            return
        if not needs_translation(chat.text):
            return  # 한국어, 숫자·기호뿐인 메시지
        if self.translator is None:
            self._add_entry(chat, "(API 키가 없어 번역하지 않음 — ⚙ 설정 → API 키)", "fail")
            return
        cached = self.cache.get("ko", chat.text)
        if cached is not None:
            self._add_entry(chat, cached, "trans")
            return
        eid = self._add_entry(chat, "번역 중…", "pending")
        self.pool.submit(self._work_incoming, eid, chat.text)

    def _note_unknown(self, line):
        # 파서를 다듬을 때 쓰도록 인식 못한 줄을 조금만 남긴다 (최대 약 200KB)
        try:
            if os.path.isfile(UNKNOWN_PATH) and os.path.getsize(UNKNOWN_PATH) > 200_000:
                return
            with open(UNKNOWN_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass

    def _work_incoming(self, eid, text):
        try:
            out, _ = self.translator.translate("ko", text)
            self.results.put(("entry", eid, out, "trans"))
        except DailyLimitReached:
            self.results.put(("entry", eid, "(오늘 번역 한도 도달 — 원문만 표시)", "fail"))
        except ApiKeyError as e:
            self.results.put(("entry", eid, f"(번역 실패: {e})", "fail"))
            self.results.put(("apikey", str(e)))
        except TranslateFailed as e:
            self.results.put(("entry", eid, f"(번역 실패: {e} — 원문만 표시)", "fail"))
        except Exception as e:  # noqa: BLE001
            _log_error()
            self.results.put(("entry", eid, f"(번역 실패: {type(e).__name__})", "fail"))

    # ------------------------------------------------------------ 목록 표시
    def _add_entry(self, chat: wowlog.ChatLine, translation: str, style: str) -> int:
        eid = self.next_id
        self.next_id += 1
        t = self.text
        at_bottom = t.yview()[1] >= 0.999
        t.configure(state="normal")
        t.mark_set(f"e{eid}", "end-1c")
        t.mark_gravity(f"e{eid}", "left")
        arrow = "→ " if chat.outgoing else ""
        t.insert("end", f"{chat.time:%H:%M} · ", "head")
        t.insert("end", f"[{chat.label}] {arrow}{chat.sender}", ("head", "ch_" + chat.channel))
        t.insert("end", "\n")
        t.insert("end", chat.text + "\n", "orig")
        t.insert("end", translation, (style, f"t{eid}"))
        t.insert("end", "\n")
        self.entry_ids.append(eid)
        limit = int(self.cfg.get("max_lines", 200))
        while len(self.entry_ids) > limit:
            old = self.entry_ids.popleft()
            t.delete("1.0", f"e{self.entry_ids[0]}")
            t.mark_unset(f"e{old}")
            t.tag_delete(f"t{old}")
        t.configure(state="disabled")
        if at_bottom:
            t.see("end")
        return eid

    def _set_translation(self, eid, value, style):
        t = self.text
        ranges = t.tag_ranges(f"t{eid}")
        if not ranges:
            return  # 이미 200줄 밖으로 밀려남
        at_bottom = t.yview()[1] >= 0.999
        t.configure(state="normal")
        start = ranges[0]
        t.delete(start, ranges[1])
        t.insert(start, value, (style, f"t{eid}"))
        t.configure(state="disabled")
        if at_bottom:
            t.see("end")

    def _clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")
        for eid in self.entry_ids:
            self.text.tag_delete(f"t{eid}")
        self.entry_ids.clear()

    def _drain_results(self):
        try:
            while True:
                item = self.results.get_nowait()
                kind = item[0]
                if kind == "entry":
                    self._set_translation(*item[1:])
                elif kind == "reply":
                    self._show_reply(*item[1:])
                elif kind == "apikey" and not self.api_key_problem:
                    self.api_key_problem = True
                    self.root.after(10, lambda msg=item[1]: self._api_key_failed(msg))
        except queue.Empty:
            pass
        self.root.after(100, self._drain_results)

    def _api_key_failed(self, msg):
        messagebox.showwarning("API 키 문제", f"{msg}\n새 키를 입력해 주세요.", parent=self.root)
        self._ask_api_key(force=True)

    # ------------------------------------------------------------ 답장
    def on_reply(self):
        text = self.reply_entry.get().strip()
        if not text:
            return
        if self.translator is None:
            self._set_reply_info("API 키가 없습니다. ⚙ 설정 → API 키 변경", WARN)
            return
        inv = {v: k for k, v in REPLY_LANG_LABELS.items()}
        lang = inv.get(self.lang_var.get(), "zh-TW")
        self.reply_btn.state(["disabled"])
        self._set_reply_info("번역 중…", FG_DIM)
        self.pool.submit(self._work_reply, text, lang)

    def _work_reply(self, text, lang):
        try:
            out, _ = self.translator.translate(lang, text)
            self.results.put(("reply", out, None))
        except DailyLimitReached:
            self.results.put(("reply", None, "오늘 번역 한도에 도달했습니다 (config.json의 daily_limit)."))
        except ApiKeyError as e:
            self.results.put(("reply", None, f"번역 실패: {e}"))
            self.results.put(("apikey", str(e)))
        except TranslateFailed as e:
            self.results.put(("reply", None, f"번역 실패: {e}"))
        except Exception as e:  # noqa: BLE001
            _log_error()
            self.results.put(("reply", None, f"번역 실패: {type(e).__name__}"))

    def _show_reply(self, out, err):
        self.reply_btn.state(["!disabled"])
        if err:
            self._set_reply_info(err, WARN)
            return
        self.last_reply = out
        self.my_replies.append(normalize(out))
        self.reply_out.configure(state="normal")
        self.reply_out.delete(0, "end")
        self.reply_out.insert(0, out)
        self.reply_out.configure(state="readonly")
        self._copy_last()
        self.reply_entry.delete(0, "end")

    def _copy_last(self):
        if not self.last_reply:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_reply)
        self.root.update()
        n = len(self.last_reply.encode("utf-8"))
        if n > 255:
            self._set_reply_info(f"⚠ {n}/255 바이트 — 와우 채팅 한 줄 제한 초과! 문장을 나눠서 보내세요. (복사는 됨)", WARN)
        else:
            self._set_reply_info(f"✓ 클립보드에 복사됨 ({n}/255 바이트) — 게임 채팅창에서 Ctrl+V", "#9fe3b0")

    def _set_reply_info(self, text, color):
        self.reply_info.configure(text=text, fg=color)

    # ------------------------------------------------------------ 상태줄
    def _update_status(self):
        parts = [f"오늘 번역 {self.usage.today}/{self.usage.daily_limit}회"]
        warn = False
        if self.translator is None:
            parts.append("API 키 없음")
            warn = True
        if not self.log_path:
            parts.append("로그 위치 모름 (⚙ 설정)")
            warn = True
        elif not os.path.isfile(self.log_path):
            parts.append("채팅 기록 꺼짐 → 게임에서 /chatlog")
            warn = True
        else:
            flavor = os.path.basename(os.path.dirname(os.path.dirname(self.log_path)))
            parts.append(f"{flavor} 감시 중")
        if self.delays:
            d = statistics.median(self.delays)
            limit = float(self.cfg.get("delay_warn_seconds", 3))
            parts.append(f"기록 지연 약 {d:.1f}초" + (" ⚠" if d > limit else ""))
            warn = warn or d > limit
        self.status.configure(text=" · ".join(parts), fg=WARN if warn else FG_DIM)
        self.root.after(1000, self._update_status)


def _log_error():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ERROR_PATH, "a", encoding="utf-8") as f:
            f.write(f"--- {_dt.datetime.now():%Y-%m-%d %H:%M:%S}\n{traceback.format_exc()}\n")
    except OSError:
        pass


def main():
    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    root = tk.Tk()

    def report(exc, val, tb):
        _log_error_exc(exc, val, tb)
        messagebox.showerror("오류", f"{val}\n\n자세한 내용: data\\error.log", parent=root)

    root.report_callback_exception = report
    try:
        app = TranslatorApp(root)
    except Exception:
        _log_error()
        messagebox.showerror("시작 오류", traceback.format_exc()[-800:])
        raise
    root.mainloop()
    return app


def _log_error_exc(exc, val, tb):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(ERROR_PATH, "a", encoding="utf-8") as f:
            f.write(f"--- {_dt.datetime.now():%Y-%m-%d %H:%M:%S}\n{''.join(traceback.format_exception(exc, val, tb))}\n")
    except OSError:
        pass


if __name__ == "__main__":
    main()
