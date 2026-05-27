import argparse
import calendar
import datetime
import json
from pathlib import Path
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pandas as pd

try:
    import jpholiday
except ImportError:
    jpholiday = None


@dataclass(frozen=True)
class StoreInfo:
    store_abbrev: str
    store_full_name: str
    store_cd_abbrev: int
    store_cd_full: int
    aliases: List[str]


class ShiftNotationInterpreter:
    def __init__(self, rules_path: str, store_master_path: str) -> None:
        self.rules = self._load_json(rules_path)
        self.store_master = self._load_json(store_master_path)

        self._separator_from = self.rules["definitions"]["canonicalization"]["normalize_separators"][
            "from"
        ]
        self._separator_to = self.rules["definitions"]["canonicalization"]["normalize_separators"]["to"]

        self.leave_tokens = self.rules["definitions"]["tokens"]["leave"]
        self.shift_symbol_map = self._build_shift_symbol_map(
            self.rules["definitions"]["tokens"]["shift_symbol_map"]
        )
        # Fallback mapping for common symbols (in case rules file is corrupted)
        fallback_symbol_map = {
            "〇": "early",
            "○": "early",
            "◯": "early",
            "O": "early",
            "o": "early",
            "△": "middle",
            "▲": "middle",
            "×": "late",
            "✕": "late",
            "✗": "late",
            "✖️": "late",
            "X": "late",
            "x": "late",
        }
        for sym, stype in fallback_symbol_map.items():
            self.shift_symbol_map[sym] = stype
        # Prefer longer aliases first (e.g., multi-char symbols like "✖️")
        self._symbol_aliases_desc = sorted(self.shift_symbol_map.keys(), key=len, reverse=True)

        self.rule_regex = self._build_rule_regex(self.rules["rules"])
        self.store_time_regex = re.compile(
            self._adapt_regex(
                r"^(?<store>(?=[A-Za-zぁ-んァ-ヶ一-龠々・]*[A-Za-zぁ-んァ-ヶ一-龠々・])"
                r"[\p{L}\p{N}ぁ-んァ-ヶ一-龠々・]{1,12})\s*"
                r"(?<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*-\s*"
                r"(?<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)$"
            )
        )
        self.store_symbol_end_regex = re.compile(
            self._adapt_regex(
                r"^(?<store>(?=[A-Za-zぁ-んァ-ヶ一-龠々・]*[A-Za-zぁ-んァ-ヶ一-龠々・])"
                r"[\p{L}\p{N}ぁ-んァ-ヶ一-龠々・]{1,12})\s*"
                r"(?<symbol>〇|○|◯|O|o|△|▲|✕|×|✗|✖️|X|x)\s*"
                r"[-~〜～]\s*(?<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)$"
            )
        )
        self.store_symbol_end_compact_regex = re.compile(
            self._adapt_regex(
                r"^(?<store>(?=[A-Za-zぁ-んァ-ヶ一-龠々・]*[A-Za-zぁ-んァ-ヶ一-龠々・])"
                r"[\p{L}\p{N}ぁ-んァ-ヶ一-龠々・]{1,12})\s*"
                r"(?<symbol>〇|○|◯|O|o|△|▲|✕|×|✗|✖️|X|x)\s*"
                r"(?<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)$"
            )
        )
        self.symbol_end_regex = re.compile(
            self._adapt_regex(
                r"^(?<symbol>〇|○|◯|O|o|△|▲|✕|×|✗|✖️|X|x)\s*"
                r"[-~〜～]\s*(?<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)$"
            )
        )
        self.symbol_time_range_regex = re.compile(
            self._adapt_regex(
                r"^(?<symbol>〇|○|◯|O|o|△|▲|✕|×|✗|✖️|X|x)\s*"
                r"(?<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\\s*-\\s*"
                r"(?<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\\d)?)$"
            )
        )
        self.simple_symbol_time_range_regex = re.compile(
            r"^(?P<symbol>\u3007|\u25CB|\u25EF|O|o|\u25B3|\u25B2|\u00D7|\u2715|\u2717|\u2716|X|x)\s*(?P<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*-\s*(?P<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)$"
        )

        self.time_range_symbol_suffix_regex = re.compile(
            self._adapt_regex(
                r"^(?<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*[-~〜～]\s*"
                r"(?<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*"
                r"(?<symbol>〇|○|◯|O|o|△|▲|✕|×|✗|✖️|X|x)$"
            )
        )
        self.time_start_symbol_suffix_regex = re.compile(
            self._adapt_regex(
                r"^(?<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*[-~\u301c\uFF5E\u2010\u2011\u2012\u2013\u2014\u2212]\s*"
                r"(?<symbol>\u3007|\u25CB|\u25EF|O|o|\u25B3|\u25B2|\u2715|\u00D7|\u2717|\u2716\uFE0F|X|x)$"
            )
        )
        self.through_shift_regex = re.compile(
            self._adapt_regex(
                r"^(?<sym1>\u3007|\u25CB|\u25EF|O|o)\s*"
                r"(?:[-~\u301c\uFF5E\u2010\u2011\u2012\u2013\u2014\u2212\u30fc]?\s*)"
                r"(?<sym2>\u2715|\u00D7|\u2717|\u2716\uFE0F|X|x)$"
            )
        )
        self.simple_time_range_regex = re.compile(
            r"^(?P<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*-\s*(?P<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)$"
        )
        self.time_range_search_regex = re.compile(
            self._adapt_regex(
                r"(?<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*[-~〜～]\s*(?<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)"
            )
        )
        self.store_time_search_regex = None

        self.store_index = self._build_store_index(self.store_master["stores"])
        self.store_list = [s["store_abbrev"] for s in self.store_master["stores"]]
        self.store_info_by_abbrev = {
            s["store_abbrev"]: StoreInfo(
                store_abbrev=s["store_abbrev"],
                store_full_name=s["store_full_name"],
                store_cd_abbrev=s["store_cd_abbrev"],
                store_cd_full=s["store_cd_full"],
                aliases=s["aliases"],
            )
            for s in self.store_master["stores"]
        }
        # Virtual stores for office/home-work patterns
        self._add_virtual_store(
            store_abbrev="本社",
            store_full_name="本社",
            aliases=["事務所", "事務", "事”", "本社"],
        )
        self._add_virtual_store(
            store_abbrev="在宅",
            store_full_name="在宅",
            aliases=["在宅"],
        )
        self._add_virtual_store(
            store_abbrev="インスタライブ",
            store_full_name="インスタライブ",
            aliases=["インスタライブ", "インスタ", "instaライブ", "インスタLive"],
        )
        self.store_find_regex, self.store_time_search_regex = self._build_store_time_search_regex()

    @staticmethod
    def _load_json(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _build_shift_symbol_map(entries: List[dict]) -> Dict[str, str]:
        mapping: Dict[str, str] = {}
        for entry in entries:
            shift_type = entry.get("shift_type")
            for alias in entry.get("aliases", []):
                mapping[alias] = shift_type
        return mapping

    @staticmethod
    def _adapt_regex(pattern: str) -> str:
        # Convert PCRE-style named groups and \p classes to Python re compatible form.
        pattern = pattern.replace("(?<", "(?P<")
        pattern = pattern.replace(r"\p{L}\p{N}", "A-Za-z0-9")
        return pattern

    def _build_rule_regex(self, rules: List[dict]) -> Dict[str, re.Pattern]:
        rule_regex: Dict[str, re.Pattern] = {}
        for rule in rules:
            rule_id = rule.get("id")
            when = rule.get("when", {})
            if "regex" in when:
                pattern = self._adapt_regex(when["regex"])
                rule_regex[rule_id] = re.compile(pattern)
        return rule_regex

    @staticmethod
    def _normalize_key(text: str) -> str:
        s = unicodedata.normalize("NFKC", text)
        s = s.strip()
        s = re.sub(r"\s+", " ", s)
        s = s.replace("\u5e97", "")
        s = re.sub(r"H\d+$", "", s, flags=re.IGNORECASE)
        if s.endswith("T"):
            s = s[:-1]
        if s.endswith("\uff34"):
            s = s[:-1]
        return s

    def _build_store_index(self, stores: List[dict]) -> Dict[str, StoreInfo]:
        index: Dict[str, StoreInfo] = {}
        for store in stores:
            info = StoreInfo(
                store_abbrev=store["store_abbrev"],
                store_full_name=store["store_full_name"],
                store_cd_abbrev=store["store_cd_abbrev"],
                store_cd_full=store["store_cd_full"],
                aliases=store["aliases"],
            )
            keys = [store["store_abbrev"], store["store_full_name"]] + store["aliases"]
            for key in keys:
                if not key:
                    continue
                index[self._normalize_key(key)] = info
        return index

    def _build_store_time_search_regex(self) -> tuple[re.Pattern, re.Pattern]:
        store_keys = set()
        for info in self.store_info_by_abbrev.values():
            for key in [info.store_abbrev, info.store_full_name] + info.aliases:
                if not key:
                    continue
                store_keys.add(self.canonicalize(key))
        # prefer longer names first to avoid partial matches
        store_list = sorted(store_keys, key=len, reverse=True)
        escaped = [re.escape(s) for s in store_list if s]
        store_alt = "|".join(escaped) if escaped else r"(?!x)x"
        pattern = (
            r"(?P<store>"
            + store_alt
            + r")\s*(?P<start>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)\s*[-~〜～]\s*(?P<end>(?:2[0-3]|[01]?\d)(?::?[0-5]\d)?)"
        )
        store_regex = re.compile(store_alt)
        return store_regex, re.compile(pattern)

    def _add_virtual_store(
        self, store_abbrev: str, store_full_name: str, aliases: List[str]
    ) -> None:
        if store_abbrev in self.store_info_by_abbrev:
            return
        info = StoreInfo(
            store_abbrev=store_abbrev,
            store_full_name=store_full_name,
            store_cd_abbrev=0,
            store_cd_full=0,
            aliases=aliases,
        )
        self.store_info_by_abbrev[store_abbrev] = info
        if store_abbrev not in self.store_list:
            self.store_list.append(store_abbrev)
        for key in [store_abbrev, store_full_name] + aliases:
            if not key:
                continue
            self.store_index[self._normalize_key(str(key))] = info

    def resolve_store(self, text: Optional[str]) -> Optional[StoreInfo]:
        if text is None:
            return None
        key = self._normalize_key(str(text))
        info = self.store_index.get(key)
        if info:
            return info

        if key.endswith("T") or key.endswith("Ｔ"):
            trimmed = key[:-1]
            info = self.store_index.get(trimmed)
            if info:
                return info

        # Fallback: partial match by longest normalized key
        best_len = 0
        best_info = None
        for store_info in self.store_info_by_abbrev.values():
            candidates = [store_info.store_abbrev, store_info.store_full_name] + store_info.aliases
            for cand in candidates:
                if not cand:
                    continue
                norm = self._normalize_key(str(cand))
                if norm and norm in key and len(norm) > best_len:
                    best_len = len(norm)
                    best_info = store_info
        return best_info

    def canonicalize(self, text: Optional[str]) -> str:
        if text is None:
            return ""
        s = unicodedata.normalize("NFKC", str(text))
        # Replace stray '?' used in some exports for shift symbols
        s = re.sub(r"\?(?=\d)", "〇", s)
        # Drop trailing annotations like MW2h / 休憩2h / みなし1.5H
        s = re.sub(r"\bMW\s*\d+(?:\.\d+)?\s*h\b", "", s, flags=re.IGNORECASE)
        s = re.sub(r"\b(休憩|休み|break)\s*\d+(?:\.\d+)?\s*h\b", "", s, flags=re.IGNORECASE)
        s = re.sub(r"みなし\s*\d+(?:\.\d+)?\s*h", "", s, flags=re.IGNORECASE)
        s = re.sub(r"片道みなし\s*\d+(?:\.\d+)?\s*h", "", s, flags=re.IGNORECASE)
        s = re.sub(r"(稼働調整|早退|遅刻)", "", s)
        # Treat "公休/公 → 出勤変更" prefixes as non-leave markers
        s = re.sub(r"^(公休|公)\s*(→|⇒|➡|→|=>|->|ｰ>|→)?\s*", "", s)
        s = re.sub(r"(公休|公)\s*(→|⇒|➡|→|=>|->|ｰ>)", "", s)
        # Normalize separators
        s = s.replace(";", ":")
        for ch in ["～", "〜", "－", "ー", "―", "‐", "‑", "–", "—", "−", "ｰ", "~"]:
            s = s.replace(ch, "-")
        s = re.sub(r"\s+", " ", s).strip()
        # Ensure time range separators are normalized even if rules file is corrupted
        s = re.sub(r"(?<=\d)\?(?=\d)", "-", s)
        s = re.sub(r"(?<=\d)〇(?=\d)", "-", s)
        return s

    @staticmethod
    def _normalize_time(text: str) -> str:
        t = text.strip()
        if ":" in t:
            hour, minute = t.split(":", 1)
        else:
            if len(t) <= 2:
                hour, minute = t, "00"
            elif len(t) == 3:
                hour, minute = t[:-2], t[-2:]
            else:
                hour, minute = t[:2], t[2:]
        return f"{int(hour):02d}:{int(minute):02d}"

    def parse(self, raw_text: Optional[str], context_home_store: Optional[str]) -> dict:
        # Handle multi-line shifts (e.g., time range + store-only line + time range)
        if raw_text is not None and ("\n" in str(raw_text) or "\r" in str(raw_text)):
            lines = [l for l in re.split(r"[\r\n]+", str(raw_text)) if l.strip()]
            result = {
                "normalized_text": "",
                "labels": [],
                "entities": {
                    "home_store": None,
                    "help_store": None,
                    "shift_type": None,
                    "start_time": None,
                    "end_time": None,
                    "is_until_last": False,
                    "leave_type": None,
                    "segments": [],
                },
                "errors": [],
            }
            pending_store = None
            for idx_line, line in enumerate(lines):
                line_norm = self.canonicalize(line)
                if not line_norm:
                    continue
                # store+P without time -> fixed 11:00-18:00
                m = re.match(r"^(?P<store>[^\d\s]+)\s*P$", line_norm, flags=re.IGNORECASE)
                if m:
                    store_info = self.resolve_store(m.group("store"))
                    if store_info:
                        result["labels"].extend(["help", "time_range"])
                        result["entities"]["segments"].append(
                            {
                                "segment_type": "help_store_work",
                                "store": store_info.store_abbrev,
                                "start_time": "11:00",
                                "end_time": "18:00",
                            }
                        )
                        pending_store = None
                        continue
                # store-only line (no digits)
                if not re.search(r"\d", line_norm):
                    store_info = self.resolve_store(line_norm)
                    if store_info:
                        # If next line has a time range, treat as pending store
                        next_line = lines[idx_line + 1] if idx_line + 1 < len(lines) else ""
                        next_norm = self.canonicalize(next_line) if next_line else ""
                        if next_norm and re.search(r"\d", next_norm):
                            pending_store = store_info.store_abbrev
                        else:
                            result["labels"].extend(["help", "time_range"])
                            result["entities"]["segments"].append(
                                {
                                    "segment_type": "help_store_work",
                                    "store": store_info.store_abbrev,
                                    "start_time": "11:00",
                                    "end_time": "20:30",
                                }
                            )
                            pending_store = None
                        continue
                # store + time range
                m = self.store_time_regex.match(line_norm)
                store_info = None
                store_raw = None
                start_raw = None
                if m:
                    store_raw = m.group("store")
                    start_raw = m.group("start")
                    if store_raw and start_raw and store_raw[-1].isdigit() and re.match(r"^\d:\d{2}$", start_raw):
                        start_raw = f"{store_raw[-1]}{start_raw}"
                        store_raw = store_raw[:-1]
                    store_info = self.resolve_store(store_raw)
                if not m:
                    m = re.search(
                        r"^(?P<store>[^\d\s]+)\s*(?P<start>(?:2[0-3]|[01]\d|\d)(?::[0-5]\d)?)\s*-\s*(?P<end>(?:2[0-3]|[01]\d|\d)(?::[0-5]\d)?)",
                        line_norm,
                    )
                    if m:
                        store_raw = re.sub(r"H\\d+$", "", m.group("store"), flags=re.IGNORECASE).strip()
                        store_info = self.resolve_store(store_raw)
                if m and store_info:
                    start_val = m.group("start")
                    if store_raw and start_raw:
                        start_val = start_raw
                    result["labels"].extend(["help", "time_range"])
                    result["entities"]["segments"].append(
                        {
                            "segment_type": "help_store_work",
                            "store": store_info.store_abbrev,
                            "start_time": self._normalize_time(start_val),
                            "end_time": self._normalize_time(m.group("end")),
                        }
                    )
                    pending_store = None
                    continue
                # time range only
                m = self.simple_time_range_regex.match(line_norm)
                if not m:
                    rule = self.rule_regex.get("R-400")
                    m = rule.match(line_norm) if rule else None
                if m:
                    store = pending_store or context_home_store
                    if store:
                        result["labels"].append("time_range")
                        result["entities"]["segments"].append(
                            {
                                "segment_type": "home_store_work",
                                "store": store,
                                "start_time": self._normalize_time(m.group("start")),
                                "end_time": self._normalize_time(m.group("end")),
                            }
                        )
                        pending_store = None
                        continue
            if result["entities"]["segments"]:
                result["entities"]["start_time"] = result["entities"]["segments"][0]["start_time"]
                result["entities"]["end_time"] = result["entities"]["segments"][-1]["end_time"]
                return result

        text = self.canonicalize(raw_text)

        result = {
            "normalized_text": text,
            "labels": [],
            "entities": {
                "home_store": None,
                "help_store": None,
                "shift_type": None,
                "start_time": None,
                "end_time": None,
                "is_until_last": False,
                "leave_type": None,
                "segments": [],
            },
            "errors": [],
        }

        # store+P without time -> fixed 11:00-18:00
        m = re.match(r"^(?P<store>[^\d\s]+)\s*P$", text, flags=re.IGNORECASE)
        if m:
            store_info = self.resolve_store(m.group("store"))
            if store_info:
                result["labels"].extend(["help", "time_range"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["start_time"] = "11:00"
                result["entities"]["end_time"] = "18:00"
                result["entities"]["is_until_last"] = False
                return result

        # store-only line (no digits) -> fixed 11:00-20:30
        if text and not re.search(r"\d", text):
            store_info = self.resolve_store(text)
            if store_info:
                result["labels"].extend(["help", "time_range"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["start_time"] = "11:00"
                result["entities"]["end_time"] = "20:30"
                result["entities"]["is_until_last"] = False
                return result

        if text == "":
            result["labels"].append("leave")
            result["entities"]["leave_type"] = "off_day"
            return result

        # Leave tokens
        if any(token in text for token in self.leave_tokens["off_day"]):
            result["labels"].append("leave")
            result["entities"]["leave_type"] = "off_day"
            return result
        if any(token in text for token in self.leave_tokens["paid_leave"]):
            result["labels"].append("leave")
            result["entities"]["leave_type"] = "paid_leave"
            return result
        if text in self.leave_tokens["requested_off"]:
            result["labels"].append("leave")
            result["entities"]["leave_type"] = "requested_off"
            return result

        # Composite move (store staff): 11-富士見15:00-20:00
        rule = self.rule_regex.get("R-200")
        m = rule.match(text) if rule else None
        if m:
            store_raw = m.group("store")
            store_info = self.resolve_store(store_raw)
            home_info = self.resolve_store(context_home_store) if context_home_store else None
            result["labels"].extend(["composite_move", "help"])
            result["entities"]["help_store"] = store_info.store_abbrev if store_info else store_raw
            result["entities"]["start_time"] = self._normalize_time(m.group("start1"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end2"))
            if home_info:
                result["entities"]["segments"].append(
                    {
                        "segment_type": "home_store_work",
                        "store": home_info.store_abbrev,
                        "start_time": self._normalize_time(m.group("start1")),
                        "end_time": self._normalize_time(m.group("start2")),
                    }
                )
            if store_info:
                result["entities"]["segments"].append(
                    {
                        "segment_type": "help_store_work",
                        "store": store_info.store_abbrev,
                        "start_time": self._normalize_time(m.group("start2")),
                        "end_time": self._normalize_time(m.group("end2")),
                    }
                )
            return result

        # Composite move (HQ staff): 柏11-富士見15:00-20:00
        rule = self.rule_regex.get("R-210")
        m = rule.match(text) if rule else None
        if m:
            store1_info = self.resolve_store(m.group("store1"))
            store2_info = self.resolve_store(m.group("store2"))
            result["labels"].extend(["composite_move", "help"])
            if store1_info:
                result["entities"]["segments"].append(
                    {
                        "segment_type": "store1_work",
                        "store": store1_info.store_abbrev,
                        "start_time": self._normalize_time(m.group("start1")),
                        "end_time": self._normalize_time(m.group("start2")),
                    }
                )
            if store2_info:
                result["entities"]["segments"].append(
                    {
                        "segment_type": "store2_work",
                        "store": store2_info.store_abbrev,
                        "start_time": self._normalize_time(m.group("start2")),
                        "end_time": self._normalize_time(m.group("end2")),
                    }
                )
            return result

        # Help store with explicit time range: 四條畷 11:00-20:30
                # Help store with explicit time range: ??? 11:00-20:30
        # Robust fallback: store + time range + optional annotation
        m = re.search(
            r"^(?P<store>[^\d\s]+\w*)\s*(?P<start>(?:2[0-3]|[01]\d|\d)(?::[0-5]\d)?)\s*-\s*(?P<end>(?:2[0-3]|[01]\d|\d)(?::[0-5]\d)?)",
            text,
        )
        if m:
            store_raw = re.sub(r"H\d+$", "", m.group("store"), flags=re.IGNORECASE).strip()
            start_raw = m.group("start")
            if store_raw and start_raw and store_raw[-1].isdigit() and re.match(r"^\d:\d{2}$", start_raw):
                start_raw = f"{store_raw[-1]}{start_raw}"
                store_raw = store_raw[:-1]
            store_info = self.resolve_store(store_raw)
            if store_info:
                result["labels"].extend(["help", "time_range"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["start_time"] = self._normalize_time(start_raw)
                result["entities"]["end_time"] = self._normalize_time(m.group("end"))
                result["entities"]["is_until_last"] = False
                return result

        # Help store + start time + shift symbol suffix: 堺8:30-○
        m = re.search(
            r"^(?P<store>[^\d\s\u3007\u25CB\u25EF\u004F\u006F\u25B3\u25B2\u00D7\u2715\u2717\u0058\u0078]+)\s*(?P<start>(?:2[0-3]|[01]\d|\d)(?::?[0-5]\d)?)\s*[-~\u301c\uFF5E\u2010\u2011\u2012\u2013\u2014\u2212\u30fc]\s*(?P<symbol>\u3007|\u25CB|\u25EF|O|o|\u25B3|\u25B2|\u00D7|\u2715|\u2717|X|x)$",
            text,
        )
        if m:
            store_raw = re.sub(r"H\d+$", "", m.group("store"), flags=re.IGNORECASE).strip()
            start_raw = m.group("start")
            if store_raw and start_raw and store_raw[-1].isdigit() and re.match(r"^\d:\d{2}$", start_raw):
                start_raw = f"{store_raw[-1]}{start_raw}"
                store_raw = store_raw[:-1]
            store_info = self.resolve_store(store_raw)
            if store_info:
                symbol = m.group("symbol")
                result["labels"].extend(["help", "partial_time"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
                result["entities"]["start_time"] = self._normalize_time(start_raw)
                result["entities"]["is_until_last"] = False
                return result

                        # Simple store + symbol + end time: ???-17:00
        m = re.search(
            r"^(?P<store>[^\d\s\u3007\u25CB\u25EF\u004F\u006F\u25B3\u25B2\u00D7\u2715\u2717\u0058\u0078]+)\s*(?P<symbol>\u3007|\u25CB|\u25EF|O|o|\u25B3|\u25B2|\u00D7|\u2715|\u2717|X|x)\s*[-~\u301c\uFF5E\u2010\u2011\u2012\u2013\u2014\u2212\u30fc]\s*(?P<end>(?:2[0-3]|[01]\d|\d)(?::?[0-5]\d)?)$",
            text,
        )
        if m:
            store_info = self.resolve_store(m.group("store"))
            if store_info:
                symbol = m.group("symbol")
                result["labels"].extend(["help", "partial_time"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
                result["entities"]["end_time"] = self._normalize_time(m.group("end"))
                result["entities"]["is_until_last"] = False
                return result

# Help store + end time only: ???-17 / ????17
        m = re.search(
            r"^(?P<store>[^\d\s???Oo???????Xx]+)\s*[-~\u301c\uff5e\u2010\u2011\u2012\u2013\u2014\u2212\u30fc]\s*(?P<end>(?:2[0-3]|[01]\d|\d)(?::?[0-5]\d)?)$",
            text,
        )
        if m:
            store_raw = re.sub(r"H\d+$", "", m.group("store"), flags=re.IGNORECASE).strip()
            store_info = self.resolve_store(store_raw)
            if store_info:
                result["labels"].extend(["help", "partial_time"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["end_time"] = self._normalize_time(m.group("end"))
                result["entities"]["is_until_last"] = False
                return result

        m = self.store_time_regex.match(text)
        if m:
            store_raw = m.group("store")
            start_raw = m.group("start")
            if store_raw and start_raw and store_raw[-1].isdigit() and re.match(r"^\d:\d{2}$", start_raw):
                start_raw = f"{store_raw[-1]}{start_raw}"
                store_raw = store_raw[:-1]
            store_info = self.resolve_store(store_raw)
            if store_info:
                result["labels"].extend(["help", "time_range"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["start_time"] = self._normalize_time(start_raw)
                result["entities"]["end_time"] = self._normalize_time(m.group("end"))
                result["entities"]["is_until_last"] = False
                return result

        # Help notation: 富士見〇 / 富士見△ / 富士見✕
        rule = self.rule_regex.get("R-300")
        m = rule.match(text) if rule else None
        if m:
            store_info = self.resolve_store(m.group("store"))
            symbol = m.group("symbol")
            result["labels"].append("help")
            result["entities"]["help_store"] = store_info.store_abbrev if store_info else m.group(
                "store"
            )
            result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
            return result

        # Help store + symbol + end time: 川崎 〇～17:00
        # Help store + symbol only: ???? / ??? / ??? ?
        store_match = None
        if self.store_find_regex:
            store_candidates = list(self.store_find_regex.finditer(text))
            if store_candidates:
                store_match = store_candidates[-1].group(0)
        if store_match and not re.search(r"\d", text):
            for symbol in self._symbol_aliases_desc:
                if symbol in text:
                    store_info = self.resolve_store(store_match)
                    if store_info:
                        result["labels"].append("help")
                        result["entities"]["help_store"] = store_info.store_abbrev
                        result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
                        return result

                        # Simple store + symbol + end time: ???-17:00
        m = re.search(
            r"^(?P<store>[^\d\s\u3007\u25CB\u25EF\u004F\u006F\u25B3\u25B2\u00D7\u2715\u2717\u0058\u0078]+)\s*(?P<symbol>\u3007|\u25CB|\u25EF|O|o|\u25B3|\u25B2|\u00D7|\u2715|\u2717|X|x)\s*[-~\u301c\uFF5E\u2010\u2011\u2012\u2013\u2014\u2212\u30fc]\s*(?P<end>(?:2[0-3]|[01]\d|\d)(?::?[0-5]\d)?)$",
            text,
        )
        if m:
            store_info = self.resolve_store(m.group("store"))
            if store_info:
                symbol = m.group("symbol")
                result["labels"].extend(["help", "partial_time"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
                result["entities"]["end_time"] = self._normalize_time(m.group("end"))
                result["entities"]["is_until_last"] = False
                return result

        m = self.store_symbol_end_regex.match(text)
        if m:
            store_info = self.resolve_store(m.group("store"))
            if store_info:
                symbol = m.group("symbol")
                shift_type = self.shift_symbol_map.get(symbol)
                result["labels"].extend(["help", "time_range"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["shift_type"] = shift_type
                result["entities"]["start_time"] = None
                result["entities"]["end_time"] = self._normalize_time(m.group("end"))
                result["entities"]["is_until_last"] = False
                return result

        # Help store + symbol + end time (compact): 川崎〇17:00 / 川崎✖️1700
        m = self.store_symbol_end_compact_regex.match(text)
        if m:
            store_info = self.resolve_store(m.group("store"))
            if store_info:
                symbol = m.group("symbol")
                shift_type = self.shift_symbol_map.get(symbol)
                result["labels"].extend(["help", "time_range"])
                result["entities"]["help_store"] = store_info.store_abbrev
                result["entities"]["shift_type"] = shift_type
                result["entities"]["start_time"] = None
                result["entities"]["end_time"] = self._normalize_time(m.group("end"))
                result["entities"]["is_until_last"] = False
                return result

        # Through shift (home store): ??? / ?-?
        m = self.through_shift_regex.match(text)
        if m:
            result["labels"].extend(["through_shift", "shift_symbol"])
            result["entities"]["shift_type"] = "through"
            result["entities"]["is_until_last"] = False
            return result

        # Symbol + end time (home store): 〇～18:00 / ✖️-1700
        m = self.symbol_end_regex.match(text)
        if m:
            symbol = m.group("symbol")
            result["labels"].extend(["shift_symbol", "partial_time"])
            result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            result["entities"]["is_until_last"] = False
            return result

        m = self.simple_symbol_time_range_regex.match(text)
        if m:
            symbol = m.group("symbol")
            result["labels"].extend(["time_range", "shift_tagged_time_range"])
            result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            result["entities"]["is_until_last"] = False
            return result

        # Symbol + time range (home store): ◯930-1700
        m = self.symbol_time_range_regex.match(text)
        if m:
            symbol = m.group("symbol")
            result["labels"].extend(["time_range", "shift_tagged_time_range"])
            result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            result["entities"]["is_until_last"] = False
            return result

        # Time range + symbol suffix (home store): 11-20:30× / 10:30-20△
        m = self.time_range_symbol_suffix_regex.match(text)
        if m:
            symbol = m.group("symbol")
            result["labels"].extend(["time_range", "shift_tagged_time_range"])
            result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            result["entities"]["is_until_last"] = False
            return result

        # Start time + symbol suffix (home store): 8:30-? / 930-?
        m = self.time_start_symbol_suffix_regex.match(text)
        if m:
            symbol = m.group("symbol")
            result["labels"].extend(["shift_symbol", "partial_time"])
            result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["is_until_last"] = False
            return result

        # Multi store+time segments within one cell: 事務所10-15レイク16-19
        segments = []
        for m in self.store_time_search_regex.finditer(text):
            store_info = self.resolve_store(m.group("store"))
            if not store_info:
                continue
            segments.append(
                {
                    "segment_type": "help_store_work",
                    "store": store_info.store_abbrev,
                    "start_time": self._normalize_time(m.group("start")),
                    "end_time": self._normalize_time(m.group("end")),
                }
            )
        if segments:
            if len(segments) >= 2:
                result["labels"].extend(["composite_move", "help"])
                result["entities"]["segments"] = segments
                result["entities"]["start_time"] = segments[0]["start_time"]
                result["entities"]["end_time"] = segments[-1]["end_time"]
                result["entities"]["is_until_last"] = False
                return result
            seg = segments[0]
            result["labels"].extend(["help", "time_range"])
            result["entities"]["help_store"] = seg["store"]
            result["entities"]["start_time"] = seg["start_time"]
            result["entities"]["end_time"] = seg["end_time"]
            result["entities"]["is_until_last"] = False
            return result

        # Multi time ranges with store names (fallback): 事務所10-15レイク16-19
        time_matches = list(self.time_range_search_regex.finditer(text))
        if len(time_matches) >= 2 and self.store_find_regex:
            segments = []
            last_store = None
            for tm in time_matches:
                prefix = text[: tm.start()]
                store_matches = list(self.store_find_regex.finditer(prefix))
                if store_matches:
                    last_store = store_matches[-1].group(0)
                store_info = self.resolve_store(last_store) if last_store else None
                if not store_info:
                    continue
                segments.append(
                    {
                        "segment_type": "help_store_work",
                        "store": store_info.store_abbrev,
                        "start_time": self._normalize_time(tm.group("start")),
                        "end_time": self._normalize_time(tm.group("end")),
                    }
                )
            if len(segments) >= 2:
                result["labels"].extend(["composite_move", "help"])
                result["entities"]["segments"] = segments
                result["entities"]["start_time"] = segments[0]["start_time"]
                result["entities"]["end_time"] = segments[-1]["end_time"]
                result["entities"]["is_until_last"] = False
                return result

        # Fallback extraction from text containing extra annotations (e.g. "千葉 10:30-20:00 MW2h")
        m = self.time_range_search_regex.search(text)
        if m and not self.simple_time_range_regex.match(text):
            store_candidate = None
            for token in re.split(r"\s+", text):
                info = self.resolve_store(token)
                if info:
                    store_candidate = info.store_abbrev
                    break
            if store_candidate:
                result["labels"].extend(["help", "time_range"])
                result["entities"]["help_store"] = store_candidate
            else:
                result["labels"].append("time_range")
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            result["entities"]["is_until_last"] = False
            return result

        m = self.simple_time_range_regex.match(text)
        if m:
            result["labels"].append("time_range")
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            return result

        # Time range: 11:00-18:00
        m = self.simple_time_range_regex.match(text)
        if m:
            result["labels"].append("time_range")
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            return result

        rule = self.rule_regex.get("R-400")
        m = rule.match(text) if rule else None
        if m:
            result["labels"].append("time_range")
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["end_time"] = self._normalize_time(m.group("end"))
            return result

        # Until last: 11-
        rule = self.rule_regex.get("R-410")
        m = rule.match(text) if rule else None
        if m:
            result["labels"].append("until_last")
            result["entities"]["start_time"] = self._normalize_time(m.group("start"))
            result["entities"]["is_until_last"] = True
            return result

        # Shift symbol only: 〇 / △ / ✕
        rule = self.rule_regex.get("R-500")
        m = rule.match(text) if rule else None
        if m:
            symbol = m.group("symbol")
            result["labels"].append("shift_symbol")
            result["entities"]["shift_type"] = self.shift_symbol_map.get(symbol)
            return result

        # Fallback
        result["labels"].append("fallback")
        result["entities"]["leave_type"] = "off_day"
        result["errors"].append("UNPARSEABLE")
        return result


def load_shift_type_map(path: Optional[str]) -> Dict[str, Tuple[int, int]]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    result: Dict[str, Tuple[int, int]] = {}
    for key, value in raw.items():
        if not isinstance(value, str) or "-" not in value:
            continue
        start_str, end_str = value.split("-", 1)
        start_min = time_to_minutes(start_str)
        end_min = time_to_minutes(end_str)
        result[key] = (start_min, end_min)
    return result


def time_to_minutes(time_text: str) -> int:
    t = str(time_text).strip()
    if ":" in t:
        hour, minute = t.split(":", 1)
    else:
        if len(t) <= 2:
            hour, minute = t, "00"
        elif len(t) == 3:
            hour, minute = t[:-2], t[-2:]
        else:
            hour, minute = t[:2], t[2:]
    return int(hour) * 60 + int(minute)


def minutes_to_label(start_min: int, end_min: int) -> str:
    return f"{start_min//60:02d}:{start_min%60:02d}-{end_min//60:02d}:{end_min%60:02d}"


def build_time_slots(start_hour: int, end_hour: int, slot_minutes: int) -> List[Tuple[int, int, str]]:
    slots: List[Tuple[int, int, str]] = []
    start_min = start_hour * 60
    end_min = end_hour * 60
    for s in range(start_min, end_min, slot_minutes):
        e = s + slot_minutes
        slots.append((s, e, minutes_to_label(s, e)))
    return slots


def build_time_slots_by_minutes(
    start_min: int, end_min: int, slot_minutes: int
) -> List[Tuple[int, int, str]]:
    slots: List[Tuple[int, int, str]] = []
    for s in range(start_min, end_min, slot_minutes):
        e = s + slot_minutes
        slots.append((s, e, minutes_to_label(s, e)))
    return slots


def clip_range(
    start_min: int, end_min: int, open_min: int, close_min: int
) -> Optional[Tuple[int, int]]:
    if end_min <= open_min or start_min >= close_min:
        return None
    return max(start_min, open_min), min(end_min, close_min)


def load_business_hours(path: Optional[str]) -> Dict[int, dict]:
    if not path:
        return {}
    with open(path, "r", encoding="utf-8") as f:
        obj = json.load(f)
    stores = obj.get("entities", {}).get("stores", [])
    result: Dict[int, dict] = {}
    for store in stores:
        store_cd = store.get("store_cd_full")
        if store_cd is None:
            continue
        result[int(store_cd)] = store
    return result


def get_day_type(date_obj: datetime.date) -> str:
    if jpholiday and jpholiday.is_holiday(date_obj):
        return "sun_holiday"
    if date_obj.weekday() == 6:
        return "sun_holiday"
    if date_obj.weekday() == 5:
        return "sat"
    return "weekday"


def get_store_hours(
    business_hours_map: Dict[int, dict],
    store_cd_full: int,
    day_type: str,
) -> Optional[Tuple[int, int]]:
    store = business_hours_map.get(store_cd_full)
    if not store:
        return None
    hours = store.get("business_hours", {}).get(day_type)
    if not hours:
        return None
    open_time = hours.get("open")
    close_time = hours.get("close")
    if not open_time or not close_time:
        return None
    return time_to_minutes(open_time), time_to_minutes(close_time)


def get_store_shift_range(
    business_hours_map: Dict[int, dict],
    store_cd_full: int,
    shift_type: str,
) -> Optional[Tuple[int, int]]:
    store = business_hours_map.get(store_cd_full)
    if not store:
        return None
    shift_times = store.get("shift_times", {})
    shift = shift_times.get(shift_type)
    if not shift:
        return None
    start = shift.get("start")
    end = shift.get("end")
    if not start or not end:
        return None
    return time_to_minutes(start), time_to_minutes(end)


def summarize_attendance_by_time(
    df: pd.DataFrame,
    year: int,
    month: int,
    rules_path: str,
    store_master_path: str,
    business_hours_path: Optional[str],
    slot_start_hour: int,
    slot_end_hour: int,
    slot_minutes: int,
    shift_type_map: Dict[str, Tuple[int, int]],
) -> Tuple[pd.DataFrame, List[str]]:
    interpreter = ShiftNotationInterpreter(rules_path, store_master_path)
    business_hours_map = load_business_hours(business_hours_path)
    days_in_month = calendar.monthrange(year, month)[1]
    default_open_min = slot_start_hour * 60
    default_close_min = slot_end_hour * 60
    primary_store_cols = {"店舗Key", "店舗名", "所属店舗", "所属店", "所属KEY"}
    ignore_cols = {"氏名", "社員CD", "販売力", "所属"}
    candidate_store_cols: List[str] = []
    for col in df.columns:
        if not isinstance(col, str):
            continue
        if col.startswith("D"):
            continue
        col_norm = unicodedata.normalize("NFKC", col)
        if col_norm in primary_store_cols or ("店舗" in col_norm) or ("所属" in col_norm):
            candidate_store_cols.append(col)

    # store member -> (start_min, sales_power, productivity_index, work_minutes) for ordering and aggregation
    slot_attendance: Dict[
        Tuple[int, str, str], Dict[str, Tuple[int, Optional[float], Optional[float], Optional[int]]]
    ] = {}
    special_attendance: Dict[
        Tuple[int, str, str], Dict[str, Tuple[int, Optional[float], Optional[float], Optional[int]]]
    ] = {}
    break_candidates: Dict[Tuple[int, str], Dict[str, Tuple[int, int]]] = {}
    break_overrides: Dict[Tuple[int, str, str], Dict[str, int]] = {}
    warnings: List[str] = []
    slots_by_day_store: Dict[Tuple[int, str], List[Tuple[int, int, str]]] = {}
    hours_by_day_store: Dict[Tuple[int, str], Tuple[int, int]] = {}
    output_store_list = list(interpreter.store_list)

    for day in range(1, days_in_month + 1):
        date_obj = datetime.date(year, month, day)
        day_type = get_day_type(date_obj)
        for store_abbrev in interpreter.store_list:
            info = interpreter.store_info_by_abbrev[store_abbrev]
            open_close = get_store_hours(business_hours_map, info.store_cd_full, day_type)
            if not open_close:
                warnings.append(
                    f"business hours missing: store={store_abbrev} day_type={day_type}"
                )
                open_close = (default_open_min, default_close_min)
            if open_close[1] <= open_close[0]:
                warnings.append(
                    f"invalid business hours: store={store_abbrev} day_type={day_type}"
                )
                continue
            hours_by_day_store[(day, store_abbrev)] = open_close
            slots = build_time_slots_by_minutes(
                open_close[0], open_close[1], slot_minutes
            )
            slots_by_day_store[(day, store_abbrev)] = slots
            for _, _, label in slots:
                slot_attendance[(day, store_abbrev, label)] = {}


    def enrich_label_with_hours(label: str, work_minutes: Optional[int]) -> str:
        if work_minutes is None:
            return label
        hours = round(work_minutes / 60.0, 1)
        return label.replace(':0.0:', f':{hours:.1f}:')

    def place_break_interval(
        start_min: int, end_min: int, duration: int, preferred_start: int
    ) -> Optional[Tuple[int, int]]:
        if end_min - start_min <= duration:
            return None
        if start_min <= preferred_start <= end_min - duration:
            return (preferred_start, preferred_start + duration)
        mid_start = start_min + max(0, ((end_min - start_min) - duration) // 2)
        return (mid_start, mid_start + duration)

    def compute_break_intervals(
        start_min: int, end_min: int, early_end_min: Optional[int]
    ) -> List[Tuple[int, int]]:
        work_minutes = max(0, end_min - start_min)
        if work_minutes <= 360:
            return []
        if work_minutes < 480:
            total_break = 45
            window_end = min(end_min, early_end_min) if early_end_min else end_min
            if window_end <= start_min:
                return []
            window_start = max(start_min, 12 * 60)
            if window_end - window_start < total_break:
                window_start = max(start_min, window_end - total_break)
            interval = (window_start, min(window_start + total_break, window_end))
            return [interval] if interval[1] > interval[0] else []
        # 8時間以上: 60分 + 30分
        total_break = 90
        window_end = min(end_min, early_end_min) if early_end_min else end_min
        if window_end <= start_min:
            return []
        window_start = max(start_min, 12 * 60)
        if window_end - window_start < total_break:
            window_start = max(start_min, window_end - total_break)
        # 12:00開始で60分+30分（必要なら前倒しして早番終了までに回し切る）
        main_start = window_start
        main_end = min(main_start + 60, window_end)
        sub_start = min(main_end, window_end)
        sub_end = min(sub_start + 30, window_end)
        breaks: List[Tuple[int, int]] = []
        if main_end > main_start:
            breaks.append((main_start, main_end))
        if sub_end > sub_start:
            breaks.append((sub_start, sub_end))
        return breaks

    def resolve_store_info(store_name: Optional[str]) -> Tuple[Optional[str], Optional[int]]:
        if not store_name:
            return None, None
        store_info = interpreter.resolve_store(str(store_name))
        if store_info:
            return store_info.store_abbrev, store_info.store_cd_full
        return str(store_name), None

    def ensure_store_day_with_hours(
        day_num: int, store_abbrev: str, open_close: Tuple[int, int]
    ) -> Tuple[Tuple[int, int], List[Tuple[int, int, str]]]:
        key = (day_num, store_abbrev)
        hours_by_day_store[key] = open_close
        slots = build_time_slots_by_minutes(open_close[0], open_close[1], slot_minutes)
        slots_by_day_store[key] = slots
        for _, _, label in slots:
            slot_attendance.setdefault((day_num, store_abbrev, label), {})
        if store_abbrev not in output_store_list:
            output_store_list.append(store_abbrev)
        return open_close, slots

    def ensure_store_day(
        day_num: int, store_abbrev: str, store_cd_full: Optional[int]
    ) -> Tuple[Tuple[int, int], List[Tuple[int, int, str]]]:
        key = (day_num, store_abbrev)
        if key in hours_by_day_store and key in slots_by_day_store:
            return hours_by_day_store[key], slots_by_day_store[key]
        date_obj = datetime.date(year, month, day_num)
        day_type = get_day_type(date_obj)
        open_close = None
        if store_cd_full is not None:
            open_close = get_store_hours(business_hours_map, store_cd_full, day_type)
        if not open_close:
            warnings.append(
                f"business hours missing: store={store_abbrev} day_type={day_type}"
            )
            open_close = (default_open_min, default_close_min)
        if open_close[1] <= open_close[0]:
            open_close = (default_open_min, default_close_min)
        return ensure_store_day_with_hours(day_num, store_abbrev, open_close)

    def find_home_store(row: pd.Series) -> Optional[str]:
        preferred_cols = ["店舗Key", "店舗名", "所属店舗", "所属店", "所属KEY"]
        for col in preferred_cols:
            if col not in row.index:
                continue
            val = row.get(col)
            if pd.notna(val):
                store_info = interpreter.resolve_store(str(val))
                if store_info:
                    return store_info.store_abbrev
        for col in candidate_store_cols:
            val = row.get(col)
            if pd.notna(val):
                store_info = interpreter.resolve_store(str(val))
                if store_info:
                    return store_info.store_abbrev
        for col in df.columns:
            if not isinstance(col, str):
                continue
            if col in ignore_cols or col.startswith("D"):
                continue
            val = row.get(col)
            if pd.notna(val):
                store_info = interpreter.resolve_store(str(val))
                if store_info:
                    return store_info.store_abbrev
        return None

    unassigned_records = []

    for _, row in df.iterrows():
        name = row.get("氏名")
        emp_cd = row.get("社員CD")
        default_sales_value = 2.0
        sales_value = None
        if "販売力" in df.columns:
            sales_value = row.get("販売力")
        elif len(df.columns) > 3:
            sales_value = row.iloc[3]
        if pd.notna(sales_value):
            try:
                sales_value = round(float(sales_value), 1)
                # 0評価は2.0として扱う
                if abs(sales_value) < 1e-9:
                    sales_value = default_sales_value
            except (TypeError, ValueError):
                # 非数値はブランク同等として2.0
                sales_value = default_sales_value
        else:
            # ブランクは2.0
            sales_value = default_sales_value

        def productivity_index(value: Optional[float]) -> Optional[float]:
            if value is None:
                return None
            if value >= 5.0:
                return 1.5
            if value >= 4.5:
                return 1.3
            if value >= 4.0:
                return 1.0
            if value >= 3.5:
                return 0.7
            if value >= 3.0:
                return 0.5
            if value >= 2.5:
                return 0.3
            return 0.0
        if pd.isna(name):
            name = ""
        if pd.notna(emp_cd):
            try:
                emp_cd_value = int(emp_cd)
            except (TypeError, ValueError):
                emp_cd_value = str(emp_cd)
        else:
            emp_cd_value = None

        home_store = find_home_store(row)

        for day in range(1, days_in_month + 1):
            col = f"D{day}"
            if col not in df.columns:
                continue
            raw = row.get(col)
            if pd.isna(raw):
                raw = None
            raw_text = "" if raw is None else re.sub(r"\s+", " ", str(raw)).strip()
            has_ignored_annotation = False
            if raw_text:
                norm_for_check = unicodedata.normalize("NFKC", raw_text)
                if re.search(r"\bMW\s*\d+(?:\.\d+)?\s*h\b", norm_for_check, flags=re.IGNORECASE):
                    has_ignored_annotation = True
                elif re.search(
                    r"\b(休憩|休み|break)\s*\d+(?:\.\d+)?\s*h\b",
                    norm_for_check,
                    flags=re.IGNORECASE,
                ):
                    has_ignored_annotation = True
            sales_str = "" if sales_value is None else f"{sales_value:.1f}"
            index_value = productivity_index(sales_value)
            work_minutes = None
            if emp_cd_value is not None:
                label = f"{name}(店頭:{emp_cd_value}:{sales_str}:{raw_text})"
            else:
                label = f"{name}(店頭::{sales_str}:{raw_text})" if raw_text else f"{name}(店頭::{sales_str}:)"

            parsed = interpreter.parse(raw, home_store)
            if parsed["entities"]["leave_type"]:
                # If parser failed and marked as leave, treat as error instead of silent skip
                if "fallback" in parsed.get("labels", []) or parsed.get("errors"):
                    home_store_label = home_store or ""
                    if home_store_label:
                        home_store_label = str(home_store_label)
                    unassigned_records.append(
                        {
                            "date": day,
                            "home_store": home_store_label,
                            "label": label,
                            "raw": raw_text,
                            "errors": parsed.get("errors") or ["PARSE_ERROR"],
                        }
                    )
                continue

            assignments: List[Tuple[str, Optional[Tuple[int, int]]]] = []
            if parsed["entities"]["segments"]:
                for seg in parsed["entities"]["segments"]:
                    store = seg.get("store")
                    start = seg.get("start_time")
                    end = seg.get("end_time")
                    if store and start and end:
                        assignments.append((store, (time_to_minutes(start), time_to_minutes(end))))
            elif parsed["entities"]["help_store"]:
                store = parsed["entities"]["help_store"]
                if parsed["entities"]["start_time"] and parsed["entities"]["end_time"]:
                    assignments.append(
                        (
                            store,
                            (
                                time_to_minutes(parsed["entities"]["start_time"]),
                                time_to_minutes(parsed["entities"]["end_time"]),
                            ),
                        )
                    )
                else:
                    shift_type = parsed["entities"]["shift_type"]
                    store_abbrev, store_cd_full = resolve_store_info(store)
                    shift_range = None
                    if shift_type and store_cd_full is not None:
                        shift_range = get_store_shift_range(
                            business_hours_map, store_cd_full, shift_type
                        )
                    if parsed["entities"]["end_time"] and shift_range:
                        end_min = time_to_minutes(parsed["entities"]["end_time"])
                        shift_range = (shift_range[0], end_min)
                    if parsed["entities"]["start_time"] and shift_range:
                        start_min = time_to_minutes(parsed["entities"]["start_time"])
                        shift_range = (start_min, shift_range[1])
                    if not shift_range and shift_type in shift_type_map:
                        shift_range = shift_type_map[shift_type]
                        if parsed["entities"]["start_time"]:
                            start_min = time_to_minutes(parsed["entities"]["start_time"])
                            shift_range = (start_min, shift_range[1])
                    assignments.append((store_abbrev or store, shift_range))
            else:
                if parsed["entities"]["start_time"]:
                    end_time = parsed["entities"]["end_time"]
                    if not end_time and parsed["entities"]["shift_type"]:
                        store_abbrev, store_cd_full = resolve_store_info(home_store)
                        if store_cd_full is not None:
                            shift_range = get_store_shift_range(
                                business_hours_map, store_cd_full, parsed["entities"]["shift_type"]
                            )
                            if shift_range:
                                end_time = f"{shift_range[1]//60:02d}:{shift_range[1]%60:02d}"
                    if not end_time and parsed["entities"]["is_until_last"]:
                        store_abbrev, store_cd_full = resolve_store_info(home_store)
                        open_close, _ = ensure_store_day(
                            day, store_abbrev or home_store, store_cd_full
                        )
                        end_time = f"{open_close[1]//60:02d}:{open_close[1]%60:02d}"
                    if end_time:
                        assignments.append(
                            (
                                home_store,
                                (time_to_minutes(parsed["entities"]["start_time"]), time_to_minutes(end_time)),
                            )
                        )
                else:
                    shift_type = parsed["entities"]["shift_type"]
                    store_abbrev, store_cd_full = resolve_store_info(home_store)
                    shift_range = None
                    if shift_type == "through":
                        if store_cd_full is not None:
                            early = get_store_shift_range(business_hours_map, store_cd_full, "early")
                            late = get_store_shift_range(business_hours_map, store_cd_full, "late")
                            if early and late:
                                shift_range = (early[0], late[1])
                        if not shift_range:
                            open_close, _ = ensure_store_day(day, store_abbrev or home_store, store_cd_full)
                            shift_range = open_close
                    elif shift_type and store_cd_full is not None:
                        shift_range = get_store_shift_range(
                            business_hours_map, store_cd_full, shift_type
                        )
                    if parsed["entities"]["end_time"] and shift_range:
                        end_min = time_to_minutes(parsed["entities"]["end_time"])
                        shift_range = (shift_range[0], end_min)
                    if not shift_range and shift_type in shift_type_map:
                        shift_range = shift_type_map[shift_type]
                    assignments.append((store_abbrev or home_store, shift_range))

            if not assignments:
                home_store_label = home_store or ""
                if home_store_label:
                    home_store_label = str(home_store_label)
                unassigned_records.append(
                    {
                        "date": day,
                        "home_store": home_store_label,
                        "label": label,
                        "raw": raw_text,
                        "errors": parsed["errors"],
                    }
                )
                continue

            added_any = False
            miss_reasons = []
            for store, time_range in assignments:
                if not store:
                    warnings.append(f"store unresolved: name={name} day={day} raw={raw}")
                    miss_reasons.append("STORE_UNRESOLVED")
                    continue
                if not label:
                    miss_reasons.append("LABEL_MISSING")
                    continue
                store_abbrev, store_cd_full = resolve_store_info(store)
                if not store_abbrev:
                    warnings.append(f"store unresolved: name={name} day={day} raw={raw}")
                    miss_reasons.append("STORE_UNRESOLVED")
                    continue
                open_close, slots = ensure_store_day(day, store_abbrev, store_cd_full)
                if time_range is None:
                    bucket = f"SHIFT_TYPE:{parsed['entities']['shift_type'] or 'UNKNOWN'}"
                    key = (day, store_abbrev, bucket)
                    if key not in special_attendance:
                        special_attendance[key] = {}
                    # no time info; use large start_min to keep after timed staff
                    label_with_hours = enrich_label_with_hours(label, work_minutes)
                    if label_with_hours not in special_attendance[key]:
                        special_attendance[key][label_with_hours] = (9999, sales_value, index_value, work_minutes)
                    added_any = True
                    continue

                start_min, end_min = time_range
                work_minutes = max(0, end_min - start_min)
                early_end_min = None
                if store_cd_full is not None:
                    early_range = get_store_shift_range(
                        business_hours_map, store_cd_full, "early"
                    )
                    if early_range:
                        early_end_min = early_range[1]
                break_intervals = compute_break_intervals(start_min, end_min, early_end_min)
                clipped = clip_range(start_min, end_min, open_close[0], open_close[1])
                if not clipped:
                    # Prioritize shift time even if outside business hours
                    expanded_open = min(start_min, open_close[0])
                    expanded_close = max(end_min, open_close[1])
                    open_close, slots = ensure_store_day_with_hours(
                        day, store_abbrev, (expanded_open, expanded_close)
                    )
                    start_min, end_min = start_min, end_min
                else:
                    start_min, end_min = clipped
                label_with_hours = enrich_label_with_hours(label, work_minutes)
                key = (day, store_abbrev)
                candidate_map = break_candidates.setdefault(key, {})
                if label_with_hours in candidate_map:
                    prev_start, prev_end = candidate_map[label_with_hours]
                    candidate_map[label_with_hours] = (
                        min(prev_start, start_min),
                        max(prev_end, end_min),
                    )
                else:
                    candidate_map[label_with_hours] = (start_min, end_min)
                matched = False
                for slot_start, slot_end, slot_label in slots:
                    if start_min < slot_end and end_min > slot_start:
                        slot_key = (day, store_abbrev, slot_label)
                        current = slot_attendance[slot_key].get(label_with_hours)
                        if current is None or start_min < current[0]:
                            slot_attendance[slot_key][label_with_hours] = (
                                start_min,
                                sales_value,
                                index_value,
                                work_minutes,
                            )
                        matched = True
                if matched:
                    added_any = True
                else:
                    miss_reasons.append("NO_SLOT_MATCH")

            if not added_any:
                if has_ignored_annotation and not miss_reasons:
                    miss_reasons = ["IGNORED_ANNOTATION_NO_MATCH"]
                home_store_label = home_store or ""
                if home_store_label:
                    home_store_label = str(home_store_label)
                unassigned_records.append(
                    {
                        "date": day,
                        "home_store": home_store_label,
                        "label": label,
                        "raw": raw_text,
                        "errors": miss_reasons or parsed["errors"],
                    }
                )

    # build break schedule per day/store
    for (day, store_abbrev), candidate_map in break_candidates.items():
        if (day, store_abbrev) not in slots_by_day_store:
            continue
        info = interpreter.store_info_by_abbrev.get(store_abbrev)
        store_cd_full = info.store_cd_full if info else None
        early_end_min = None
        if store_cd_full is not None:
            early_range = get_store_shift_range(business_hours_map, store_cd_full, "early")
            if early_range:
                early_end_min = early_range[1]
        slots = slots_by_day_store[(day, store_abbrev)]
        # find cutoff when base staffing drops to 1 or less
        cutoff_start = None
        for slot_start, slot_end, slot_label in slots:
            if slot_start < 12 * 60:
                continue
            base_count = len(slot_attendance.get((day, store_abbrev, slot_label), {}))
            if base_count <= 1:
                cutoff_start = slot_start
                break
        sorted_candidates = sorted(
            [(label, s, e) for label, (s, e) in candidate_map.items()],
            key=lambda x: x[1],
        )
        # first round: 60 (>=8h) or 45 (6-8h)
        pointer = 12 * 60
        for label, start_min, end_min in sorted_candidates:
            work_minutes = max(0, end_min - start_min)
            if work_minutes <= 360:
                continue
            if work_minutes >= 480:
                first_break_duration = 60
                first_break_display = 60
            else:
                first_break_duration = 60
                first_break_display = 45
            window_end = min(end_min, early_end_min) if early_end_min else end_min
            if window_end - start_min < first_break_duration:
                continue
            start_at = max(pointer, start_min, 12 * 60)
            if start_at + first_break_duration > window_end:
                start_at = max(start_min, window_end - first_break_duration)
            if start_at + first_break_duration > end_min:
                continue
            pointer = max(pointer, start_at + first_break_duration)
            for slot_start, slot_end, slot_label in slots:
                if slot_start <= start_at < slot_end:
                    key = (day, store_abbrev, slot_label)
                    break_overrides.setdefault(key, {})[label] = first_break_display
                    break
        # second round: 30 for >=8h in the same order
        total_staff = len(sorted_candidates)
        if total_staff <= 2:
            min_second_break_start = 18 * 60
        elif total_staff == 3:
            min_second_break_start = 17 * 60 + 30
        else:
            min_second_break_start = 17 * 60
        for label, start_min, end_min in sorted_candidates:
            work_minutes = max(0, end_min - start_min)
            if work_minutes < 480:
                continue
            second_break = 30
            window_end = min(end_min, early_end_min) if early_end_min else end_min
            if cutoff_start is not None:
                window_end = min(window_end, cutoff_start)
            if window_end - start_min < second_break:
                continue
            start_at = max(pointer, start_min, 12 * 60)
            # delay 30-min breaks based on staffing level
            start_at = max(start_at, min_second_break_start)
            # if staffing drops to 1 or less, force completion before cutoff
            if cutoff_start is not None:
                latest_start = cutoff_start - second_break
                if latest_start < start_at:
                    start_at = latest_start
            if start_at + second_break > window_end:
                start_at = max(start_min, window_end - second_break)
                start_at = max(start_at, min_second_break_start)
            if start_at + second_break > end_min:
                continue
            pointer = max(pointer, start_at + second_break)
            for slot_start, slot_end, slot_label in slots:
                if slot_start <= start_at < slot_end:
                    key = (day, store_abbrev, slot_label)
                    break_overrides.setdefault(key, {})[label] = second_break
                    break

    rows = []
    for day in range(1, days_in_month + 1):
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        for store_abbrev in output_store_list:
            if (day, store_abbrev) not in slots_by_day_store:
                continue
            info = interpreter.store_info_by_abbrev.get(store_abbrev)
            store_full_name = info.store_full_name if info else store_abbrev
            store_cd_full = info.store_cd_full if info else None
            for _, _, slot_label in slots_by_day_store[(day, store_abbrev)]:
                member_map = slot_attendance[(day, store_abbrev, slot_label)]
                break_key = (day, store_abbrev, slot_label)
                break_labels = break_overrides.get(break_key, {})
                members = [
                    m for m, _ in sorted(member_map.items(), key=lambda x: (x[1][0], x[0]))
                ]
                staff_count = len(member_map)
                if break_labels:
                    updated = []
                    for m in members:
                        br = break_labels.get(m)
                        if br:
                            if "(店頭:" in m:
                                updated.append(m.replace("(店頭:", f"(休憩({br}分):", 1))
                            else:
                                updated.append(f"{m}(休憩({br}分))")
                        else:
                            updated.append(m)
                    members = updated
                # apply break weights: 30min -> 0.5, otherwise 0.0
                total_weight = 0.0
                weighted_sales_sum = 0.0
                weighted_index_sum = 0.0
                for m, v in member_map.items():
                    br = break_labels.get(m)
                    if br == 30:
                        weight = 0.5
                    elif br:
                        weight = 0.0
                    else:
                        weight = 1.0
                    total_weight += weight
                    if v[1] is not None:
                        weighted_sales_sum += v[1] * weight
                    if v[2] is not None:
                        weighted_index_sum += v[2] * weight
                if total_weight < 1.0:
                    staff_count = 0.0
                    avg_sales = None
                    index_sum = None
                else:
                    staff_count = round(total_weight, 1)
                    avg_sales = round(weighted_sales_sum / total_weight, 1) if total_weight else None
                    index_sum = round(weighted_index_sum, 1) if total_weight else None
                rows.append(
                    {
                        "date": date_str,
                        "store_abbrev": store_abbrev,
                        "store_full_name": store_full_name,
                        "store_cd_full": store_cd_full,
                        "time_slot": slot_label,
                        "staff_count": staff_count,
                        "avg_sales": avg_sales,
                        "index_sum": index_sum,
                        "members_list": members,
                        "error_type": "",
                        "error_detail": "",
                    }
                )
            for key in list(special_attendance.keys()):
                if key[0] != day or key[1] != store_abbrev:
                    continue
                bucket = key[2]
                member_map = special_attendance[key]
                members = [
                    m for m, _ in sorted(member_map.items(), key=lambda x: (x[1][0], x[0]))
                ]
                sales_vals = [v[1] for v in member_map.values() if v[1] is not None]
                avg_sales = round(sum(sales_vals) / len(sales_vals), 1) if sales_vals else None
                index_vals = [v[2] for v in member_map.values() if v[2] is not None]
                index_sum = round(sum(index_vals), 1) if index_vals else None
                rows.append(
                    {
                        "date": date_str,
                        "store_abbrev": store_abbrev,
                        "store_full_name": store_full_name,
                        "store_cd_full": store_cd_full,
                        "time_slot": bucket,
                        "staff_count": len(members),
                        "avg_sales": avg_sales,
                        "index_sum": index_sum,
                        "members_list": members,
                        "error_type": "",
                        "error_detail": "",
                    }
                )

    if unassigned_records:
        for rec in unassigned_records:
            date_str = f"{year:04d}-{month:02d}-{rec['date']:02d}"
            member_label = rec.get("label") or rec.get("raw") or ""
            error_codes = rec.get("errors") or []
            error_type = "PARSE_ERROR" if error_codes else "UNASSIGNED"
            error_detail = ";".join(error_codes) if error_codes else "UNASSIGNED"
            rows.append(
                {
                    "date": date_str,
                    "store_abbrev": rec["home_store"],
                    "store_full_name": rec["home_store"],
                    "store_cd_full": None,
                    "time_slot": "ERROR",
                    "staff_count": 0,
                    "avg_sales": None,
                    "index_sum": None,
                    "members_list": [member_label],
                    "error_type": error_type,
                    "error_detail": error_detail,
                }
            )

    return pd.DataFrame(rows), warnings


def load_monthly_shift_df(year: int, month: int) -> pd.DataFrame:
    from shift_totall import SHIFT_CREATE, USER

    honbu_df, tenpo_df, *_ = SHIFT_CREATE(USER, year, month)
    return pd.concat([honbu_df, tenpo_df], ignore_index=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily per-store attendance summary (time slots)")
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument("--month", type=int, required=True)
    parser.add_argument(
        "--rules",
        default="shift_rules_new.json",
        help="Path to shift rules JSON (default: shift_rules_new.json)",
    )
    parser.add_argument(
        "--store-master",
        default="store_master.json",
        help="Path to store_master.json",
    )
    parser.add_argument(
        "--business-hours",
        default="business_hours_and_shift_times.json",
        help="Path to business_hours_and_shift_times.json",
    )
    parser.add_argument(
        "--output",
        default="attendance_summary.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--slot-start-hour",
        type=int,
        default=8,
        help="Start hour for time slots (inclusive)",
    )
    parser.add_argument(
        "--slot-end-hour",
        type=int,
        default=22,
        help="End hour for time slots (exclusive)",
    )
    parser.add_argument(
        "--slot-minutes",
        type=int,
        default=60,
        help="Minutes per time slot",
    )
    parser.add_argument(
        "--shift-type-map",
        default=None,
        help="Optional JSON mapping for shift_type time ranges",
    )
    parser.add_argument(
        "--input-csv",
        default=None,
        help="Optional: CSV exported from SHIFT_CREATE output",
    )
    parser.add_argument(
        "--export-df-xlsx",
        default="monthly_shift_df.xlsx",
        help="Export monthly shift DataFrame to Excel (xlsx)",
    )
    args = parser.parse_args()

    rules_path = args.rules
    if not Path(rules_path).exists() and rules_path == "shift_rules_new.json":
        legacy_rules = Path("shift_rules.json")
        if legacy_rules.exists():
            print("warning: shift_rules_new.json が見つからないため shift_rules.json を使用します")
            rules_path = str(legacy_rules)

    if args.input_csv:
        df = pd.read_csv(args.input_csv)
    else:
        df = load_monthly_shift_df(args.year, args.month)

    if args.export_df_xlsx:
        try:
            df.to_excel(args.export_df_xlsx, index=False)
        except PermissionError:
            print(f"warning: cannot write {args.export_df_xlsx} (file may be open)")

    shift_type_map = load_shift_type_map(args.shift_type_map)
    summary_df, warnings = summarize_attendance_by_time(
        df,
        args.year,
        args.month,
        rules_path,
        args.store_master,
        args.business_hours,
        args.slot_start_hour,
        args.slot_end_hour,
        args.slot_minutes,
        shift_type_map,
    )
    # Expand members into member_1..member_N columns (left-justified)
    if "members_list" in summary_df.columns:
        members_lists = summary_df["members_list"].apply(
            lambda lst: lst if isinstance(lst, list) else []
        )
        max_members = members_lists.map(len).max() if len(members_lists) else 0
        if max_members > 0:
            member_cols = {
                f"member_{i+1}": members_lists.map(
                    lambda lst, idx=i: lst[idx] if idx < len(lst) else ""
                )
                for i in range(max_members)
            }
            summary_df = summary_df.drop(columns=["members_list"]).assign(**member_cols)
    summary_df.to_csv(args.output, index=False, encoding="utf-8-sig")

    if warnings:
        print(f"warnings: {len(warnings)}")
        for w in warnings[:20]:
            print(w)


if __name__ == "__main__":
    main()
