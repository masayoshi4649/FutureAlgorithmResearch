"""予定記事と公式市場時計を、売買方向を含まない観測資料に整理する。"""

from collections import Counter
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
JST = ZoneInfo("Asia/Tokyo")
NOW = datetime.now(timezone.utc).isoformat()
HOLIDAYS = {"2026-09-21", "2026-09-22", "2026-09-23", "2026-10-12"}


def load(path: Path):
    """
    機能: UTF-8の保存資料を読み込む。
    引数: path (Path) はJSONファイル。
    返り値: dictまたはlist は保存内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(name: str, value):
    """
    機能: 非金融の調査資料を保存する。
    引数: name (str) はファイル名、value (dictまたはlist) は内容。
    返り値: None。
    """
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def instant(value: str) -> datetime:
    """
    機能: 記事のRFC3339時刻を日本時間に変換する。
    引数: value (str) は時差を含む時刻。
    返り値: datetime は日本時間の時刻。
    """
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(JST)


def market_clock(day: str, zone: str, hour: int, minute: int) -> str:
    """
    機能: 現地営業日の市場時刻を夏時間込みで日本時間へ変換する。
    引数: day (str) は現地日付、zone (str) はIANA名、hour/minute (int) は時分。
    返り値: str は日本時間のISO形式。
    """
    date = datetime.fromisoformat(day).date()
    return datetime.combine(date, time(hour, minute), ZoneInfo(zone)).astimezone(JST).isoformat()


def parent_session(event: datetime, sessions: set[str]) -> str | None:
    """
    機能: 予定時刻が保存対象のどのセッションに属すかを判定する。
    引数: event (datetime) は日本時間、sessions (set[str]) は保存済み場ID。
    返り値: strまたはNone は該当ID。場外はNone。
    """
    day = event.date()
    if time(8, 45) <= event.time() <= time(15, 39):
        candidate = f"{day}_Day"
    elif event.time() >= time(17):
        candidate = f"{day}_Night"
    elif event.time() <= time(5, 54):
        candidate = f"{day - timedelta(days=1)}_Night"
    else:
        return None
    return candidate if candidate in sessions else None


def build():
    """
    機能: 予定記事索引、事前時刻の一覧、市場時計、時計の人工照合を保存する。
    引数: なし。入力は既存の予定記事と43場の準備表のみ。
    返り値: dict は非金融資料の件数と検証結果。
    """
    raw_path = HERE / "予定記事26本_取得原文.json"
    raw = load(raw_path)["記事"]
    prepared_path = ROOT / "work/daynight128_20261020/入力準備.json"
    sessions = {item["session"] for item in load(prepared_path)["packets"]}
    days = sorted(s[:10] for s in sessions if s.endswith("_Day"))
    articles, events = [], []
    for article in raw:
        published = instant(article["published_at"])
        fetched = instant(article["fetched_at"])
        latest = max(published, fetched)
        if article.get("updated_at"):
            latest = max(latest, instant(article["updated_at"]))
        daily = article["headline"].startswith("今日の注目スケジュール")
        rec = {
            "記事ID": article["id"], "見出し": article["headline"],
            "URL": article["canonical_url"], "収集元": article["source_name"],
            "公表時刻": published.isoformat(), "取得元の収集時刻": fetched.isoformat(),
            "今回取得時刻の上限": raw_path.stat().st_mtime,
            "対象日": str(published.date()), "版ID": article["revision_id"],
            "分類": "当日朝の予定" if daily else "週末の翌週見通し",
            "利用可能時刻の代理下限": latest.isoformat(),
            "要約": "当日の公表予定を列挙。予想値と前回値は特徴に使わない。" if daily else
                    "翌週の経済指標・政策・決算の見通し。日中の発表時刻が確定しない記述は予定フラグに使わない。",
            "限界": "取得元の収集時刻は現在版の過去配信を厳密証明しない。原板と同時に実受信できたかは未検証。",
        }
        articles.append(rec)
        if not daily:
            continue
        region = "未分類"
        for line in article["body_text"].splitlines():
            if "＜国内＞" in line:
                region = "日本"
            elif "＜海外＞" in line:
                region = "海外"
            match = re.match(r"^(\d{1,2}):(\d{2})[ \u3000]+(.+)$", line.strip())
            if not match:
                continue
            hour, minute = int(match[1]), int(match[2])
            dt = datetime.combine(published.date(), time(), JST) + timedelta(hours=hour, minutes=minute)
            label = re.split(r"\u3000+| {2,}", match[3])[0].strip()
            events.append({
                "予定時刻": dt.isoformat(), "記事内時刻": f"{hour:02d}:{minute:02d}",
                "項目": label, "地域": region, "記事ID": article["id"],
                "URL": article["canonical_url"], "公表時刻": published.isoformat(),
                "取得元の収集時刻": fetched.isoformat(),
                "利用可能時刻の代理下限": latest.isoformat(),
                "公表と収集が予定前": latest < dt,
                "対応保存場": parent_session(dt, sessions),
                "方向・結果・予想値を利用": False,
            })
    assert len(days) == 22 and len(sessions) == 43
    assert len(raw) == 26 and sum(a["分類"] == "当日朝の予定" for a in articles) == 22
    assert {a["対象日"] for a in articles if a["分類"] == "当日朝の予定"} == set(days)
    assert all(e["公表と収集が予定前"] for e in events)
    calendars = []
    for day in days:
        calendars.append({
            "日付": day, "日本現物開場": day not in HOLIDAYS,
            "日本先物の保存場": sorted(s for s in sessions if s.startswith(day)),
            "日本現物時計": [] if day in HOLIDAYS else ["09:00", "11:30", "12:30", "15:25", "15:30"],
            "日本現物時計の意味": ["前場開始", "前場終了", "後場開始", "クロージングオークション注文受付開始", "引け"],
            "米国現物開始": market_clock(day, "America/New_York", 9, 30),
            "米国引け需給期間開始": market_clock(day, "America/New_York", 15, 50),
            "米国現物引け": market_clock(day, "America/New_York", 16, 0),
            "独主要現物開始": market_clock(day, "Europe/Berlin", 9, 0),
            "独主要現物終了": market_clock(day, "Europe/Berlin", 17, 30),
            "英主要現物開始": market_clock(day, "Europe/London", 8, 0),
            "英主要現物終了": market_clock(day, "Europe/London", 16, 30),
            "注意": "開始終了は主要現物セッション。時間外・先物市場全体の停止を意味しない。対象期間の英独米は平日休場なし。",
        })
    artificial = []
    for day, us_expected, eu_expected in [
        ("2026-10-23", "22:30", "16:00"),
        ("2026-10-26", "22:30", "17:00"),
        ("2026-11-02", "23:30", "17:00"),
    ]:
        us = market_clock(day, "America/New_York", 9, 30)[11:16]
        eu = market_clock(day, "Europe/Berlin", 9, 0)[11:16]
        uk = market_clock(day, "Europe/London", 8, 0)[11:16]
        assert (us, eu, uk) == (us_expected, eu_expected, eu_expected)
        artificial.append({"日付": day, "米開始JST": us, "独開始JST": eu, "英開始JST": uk})
    summary = {
        "作成UTC": NOW, "金融再生数": 0, "記事数": len(articles),
        "日別予定記事数": 22, "週見通し記事数": 4,
        "時刻付き予定数": len(events), "保存場内予定数": sum(e["対応保存場"] is not None for e in events),
        "保存場内の予定がある場数": len({e["対応保存場"] for e in events if e["対応保存場"]}),
        "全保存場数": len(sessions), "日中場数": len(days),
        "日本現物開場日数": len(days) - len(HOLIDAYS), "日本現物休場日数": len(HOLIDAYS),
        "休場日": sorted(HOLIDAYS), "日本時間の予定分布": dict(Counter(e["予定時刻"][11:16] for e in events)),
        "記事入力SHA256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "保存場一覧入力SHA256": hashlib.sha256(prepared_path.read_bytes()).hexdigest(),
        "夏時間人工確認": artificial, "passed": True,
        "欠落の扱い": "記事に記載がない予定を『予定なし』と断定しない。機械的市場時計とニュース予定の有無を別列にする。",
        "因果限界": "事前に分かる予定時刻でも、この時間帯が儲かること・方向を当てることは未測定。",
    }
    save("記事索引と利用可能性.json", sorted(articles, key=lambda x: x["公表時刻"]))
    save("事前予定_方向数値なし.json", sorted(events, key=lambda x: x["予定時刻"]))
    save("市場時計と現物休場日.json", calendars)
    save("予定資料整理の確認.json", summary)
    return summary


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
