"""現行の固定採用条件について、保存済み43場と追加2場の円会計を表示する。"""

import hashlib
import html
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STUDY = "00132_現行アルゴリズムの追加セッション検証"
DEST = ROOT / "アルゴリズム調査" / STUDY
REPORT = "現行アルゴリズムの全セッション損益.html"
OLD = ROOT / "work/regime131_20261020/公開候補の43場統合.json"
NEW = HERE / "results/追加セッションの会計.json"
ADDED = ("2026-10-20_Night", "2026-10-21_Day")
SYMBOLS = ("TOPIX", "NK225")
NAMES = {"TOPIX": "TOPIXミニ", "NK225": "日経マイクロ"}


def read(path):
    """
    機能: 保存済みのUTF-8会計を読む。
    引数: path(Path)は入力先。
    返り値: dictは会計と出典。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def ref(path):
    """
    機能: 参照資料の内容指紋を作る。
    引数: path(Path)は既存資料。
    返り値: dictは相対パスとSHA256。
    """
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def money(value):
    """
    機能: 円額を符号付きで短く表示する。
    引数: value(float)は手数料込み損益。
    返り値: strは表示用の円額。
    """
    assert math.isclose(value, round(value), abs_tol=1e-6)
    return f"+{round(value):,}" if value > 0 else (f"−{abs(round(value)):,}" if value < 0 else "0")


def cells(row):
    """
    機能: 利益・損失・収支のセルを作る。
    引数: row(dict)は親取引単位に集約した会計。
    返り値: strはHTMLの3セル。
    """
    values = (row["profit"], -row["loss"], row["net"])
    return "".join(f'<td class="{"positive" if x > 0 else "negative" if x < 0 else "zero"}">{money(x)}</td>' for x in values)


def totals(rows):
    """
    機能: 商品別の利益・損失・収支と補足評価を合計する。
    引数: rows(list[dict])は同一商品の場別会計。
    返り値: dictは累計と黒字・赤字の場数。
    """
    result = {key: sum(r[key] for r in rows) for key in ("profit", "loss", "net", "gross", "fees", "entries")}
    result.update(sessions=len(rows), black=sum(r["net"] > 0 for r in rows), red=sum(r["net"] < 0 for r in rows),
                  empty=sum(r["entries"] == 0 for r in rows),
                  without_top3=result["net"] - sum(sorted([r["net"] for r in rows if r["net"] > 0], reverse=True)[:3]))
    return result


def main():
    """
    機能: 既存会計の再利用と追加会計の検査後、簡潔な暗色HTMLと出典を作成する。
    引数: なし。固定した旧会計と追加再生の結果を読む。
    返り値: None。金融再生やパラメータ選択は行わない。
    """
    old_ref, new_ref = ref(OLD), ref(NEW)
    plan = read(HERE / "試行計画_v2.json")
    assert old_ref["sha256"] == plan["sources"][old_ref["path"]]
    old, new = read(OLD), read(NEW)
    assert old_ref == ref(OLD) and new_ref == ref(NEW)
    assert new["prior_result"] == old_ref
    assert new["selection"] == old["selection"] == plan["selection"]
    assert new["configs"] == plan["configs"] and new["input_manifest"] == plan["input_manifest"]
    assert old["passed"] and new["passed"]
    assert len(old["rows"]) == 86 and len(new["rows"]) == 4
    assert {r["session"] for r in new["rows"]} == set(ADDED)
    rows = sorted(old["rows"] + new["rows"], key=lambda r: (r["session"], SYMBOLS.index(r["symbol"])))
    by_key = {(r["session"], r["symbol"]): r for r in rows}
    sessions = sorted({r["session"] for r in rows})
    assert len(by_key) == len(rows) == 90 and len(sessions) == 45
    for session in sessions:
        for symbol in SYMBOLS:
            row = by_key[session, symbol]
            assert row["kind"] == session.rsplit("_", 1)[1]
            expected_core = ("DV07" if symbol == "TOPIX" else "DV05") if row["kind"] == "Day" else ("NV01" if symbol == "TOPIX" else "NV25")
            assert row["core_method"] == expected_core
            expected = "T06" if row["kind"] == "Day" else "T04" if symbol == "TOPIX" else "U06"
            assert row["method"] == expected
            assert row["profit"] >= 0 and row["loss"] >= 0 and row["fees"] >= 0
            assert math.isclose(row["profit"] - row["loss"], row["net"], abs_tol=1e-6)
            assert math.isclose(row["gross"] - row["fees"], row["net"], abs_tol=1e-6)
            assert row["max_long"] <= (10 if symbol == "TOPIX" else 20)
            assert row["max_short"] <= (10 if symbol == "TOPIX" else 20)
    summary = {symbol: totals([r for r in rows if r["symbol"] == symbol]) for symbol in SYMBOLS}
    added = {symbol: totals([r for r in new["rows"] if r["symbol"] == symbol]) for symbol in SYMBOLS}
    payload = dict(passed=True, selection=old["selection"], rows=rows, summary=summary, added_summary=added,
                   reused_sessions=43, new_sessions=list(ADDED), sources=[old_ref, new_ref],
                   note="00131固定条件の研究会計。既存43場は保存結果を再利用。追加2場で係数・手法を選び直していない。")
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / "セッション損益.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")

    # ----------------------------------------
    # 表示は利益・損失・収支と累計だけを中心にし、実行根拠は別ファイルへ分けます。
    total_rows = "".join(f'<tr><th scope="row">{NAMES[symbol]}</th>{cells(summary[symbol])}</tr>' for symbol in SYMBOLS)
    session_rows = []
    for session in sessions:
        new_row = session in ADDED
        label = session.replace("_Day", " デイ").replace("_Night", " ナイト")
        row_class = ' class="added"' if new_row else ""
        anchor = ' id="added-sessions"' if session == ADDED[0] else ""
        badge = ' <span class="badge">追加</span>' if new_row else ""
        session_rows.append(f'<tr{row_class}{anchor}><th scope="row">{html.escape(label)}{badge}</th>' +
                            "".join(cells(by_key[session, symbol]) for symbol in SYMBOLS) + '</tr>')
    page = f'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>現行アルゴリズム｜全45セッションの損益</title>
<style>
:root{{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0b1220;color:#e7eef9}}
body{{margin:0}}main{{max-width:1200px;margin:auto;padding:30px 20px 48px}}h1{{font-size:26px;margin:0 0 12px}}h2{{font-size:20px;margin:28px 0 12px}}
p{{line-height:1.7;color:#b6c4d8}}a{{color:#91caff}}a:focus-visible{{outline:3px solid #ffca7a}}
.scroll{{overflow:auto;border:1px solid #34445b;border-radius:10px}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:11px 13px;border-bottom:1px solid #28384e;white-space:nowrap;text-align:right}}th:first-child{{text-align:left}}
thead th{{background:#18263c;color:#d9e7f9}}tbody th{{font-weight:500}}tbody tr:nth-child(even){{background:#101b2c}}
.positive{{color:#83e1b0}}.negative{{color:#ffaaa6}}.zero{{color:#aebdd1}}.added{{background:#1a2d45!important}}.badge{{font-size:11px;background:#345680;border-radius:4px;padding:3px 6px;margin-left:5px;color:#eef6ff}}
.summary{{max-width:760px}}.note{{font-size:13px}}.unit{{text-align:right;font-size:13px;margin:0 0 8px}}footer{{margin-top:24px;color:#b6c4d8;font-size:13px}}tr{{scroll-margin-top:20px}}
</style></head><body><main>
<!--
[コンポーネント概要]
.summary は両商品の45セッション累計です。利益・損失は手数料後の親取引ごとに集計します。
#sessions は全45場の損益です。.added は今回追加した2場を示します。
#added-sessions は追加行へ直接移動するためのアンカーです。
.positive・.negative・.zero は損益の符号を色で補助し、表示符号も併記します。
-->
<h1>現行アルゴリズムの全45セッション損益</h1>
<p>2026年9月21日デイ〜10月21日デイ。<strong>10月20日ナイト・21日デイを追加。</strong> <a href="#added-sessions">追加分へ</a><br>
TOPIXミニ：片方向上限10枚／日経マイクロ：同20枚。日中・夜間の採用条件は前回から変更していません。</p>
<h2>累計</h2><div class="scroll summary"><table><thead><tr><th>商品</th><th>利益（円）</th><th>損失（円）</th><th>収支（円）</th></tr></thead><tbody>{total_rows}</tbody></table></div>
<h2>全セッション</h2><p class="unit">単位：円・手数料込み</p>
<div class="scroll"><table id="sessions"><thead><tr><th rowspan="2">セッション</th><th colspan="3">TOPIXミニ</th><th colspan="3">日経マイクロ</th></tr><tr><th>利益</th><th>損失</th><th>収支</th><th>利益</th><th>損失</th><th>収支</th></tr></thead><tbody>{''.join(session_rows)}</tbody></table></div>
<p class="note">利益・損失は、新規から部分返済を含む全返済までの取引群ごとに手数料を引き、正負を分けて合計。収支＝利益＋表中の損失（負数）。<br>
手数料は片道1枚あたりTOPIXミニ41.8円・日経マイクロ11円、注文ごとに円未満切捨て。ラージの次の正常な板気配を約定代理としたバックテストで、アプリの実約定記録ではありません。</p>
<footer><a href="README.md">固定した手法・検証条件</a> ／ <a href="セッション損益.json">集計データ</a> ／ <a href="../index.html">調査一覧</a></footer>
</main></body></html>'''
    (DEST / REPORT).write_text(page, encoding="utf-8")
    new_table = "\n".join("| " + session.replace("_Day", " デイ").replace("_Night", " ナイト") + " | " +
                            " | ".join(money(by_key[session, symbol]["net"]) + "円" for symbol in SYMBOLS) + " |" for session in ADDED)
    readme = f'''# 現行アルゴリズムの追加セッション検証

最初に **[全45セッションの利益・損失・収支]({REPORT})** を開いてください。設定や会計の確認が必要な場合だけ、このREADMEと[集計データ](セッション損益.json)を参照してください。

現在採用している00131の条件を固定し、追加2場を検証しました。新しい成績を見て手法・係数・配分を選び直していません。

| 追加セッション | TOPIXミニ収支 | 日経マイクロ収支 |
|---|---:|---:|
{new_table}

| 全45場累計 | 利益 | 損失 | 収支 |
|---|---:|---:|---:|
''' + "\n".join(f'| {NAMES[symbol]} | {money(summary[symbol]["profit"])}円 | {money(-summary[symbol]["loss"])}円 | {money(summary[symbol]["net"])}円 |' for symbol in SYMBOLS) + '''

## 固定した構成

| 区分 | TOPIX | 日経 |
|---|---|---|
| 日中主担当 | DV07 | DV05 |
| 日中の未参加時追加 | T06 | T06 |
| 夜間主担当 | NV01 | NV25 |
| 夜間の未参加時追加 | T04 | U06 |

主担当はTOPIXミニ5枚・日経マイクロ10枚、追加も最大5枚・10枚。片方向の同時上限は10枚・20枚。日経夜間のU06は、判断時の初期停止幅に応じて追加数量を減らします。判断に使うのは両銘柄のラージ板です。

## 会計と範囲

- 手数料込み。片道1枚TOPIXミニ41.8円、日経マイクロ11円、注文ごとに円未満切捨て。
- 利益・損失は新規から全返済までの親取引の純損益で集計。セッション損益を先に相殺してから正負へ分類していません。
- 旧43場は[00131の保存結果](../00131_時間帯と値動き状態を切り替える全場参加/README.md)をそのまま再利用。既存直近3場の18素材は指紋一致を確認しました。それ以前の40場の原本は今回再ハッシュしていません。
- 別途、旧10月19日ナイト・20日デイの4商品場を注文・損益の同値確認のためだけに再生しました。これは新しい成績や有効性の証拠に数えていません。
- 追加2場は双方の生板・1分足・5分足が揃い、場内返済時刻まで収録されています。入力は当該場の当時までの資料だけです。
- 研究時と同じ次正常原行のラージ気配で約定を代理します。実ミニ・マイクロの気配、通信遅延、途中起動、部分約定はこの表に含みません。Goアプリの実トレードログを再掲した成績ではありません。
- Go版の終場返済は到達時点で発注する実装で、旧日中研究の一部と一原行の差があります。本表は前回との比較を優先し、研究の同一会計を維持しています。
- 元データ・旧結果・稼働アプリは変更していません。現在セッションのAPI取得・実注文は行っていません。

## 再現資料

- [原データの棚卸し](../../work/selected131_input_audit_20261021/最新素材の棚卸し.json)
- [追加2場の円会計](../../work/update132_20261021/results/追加セッションの会計.json)
- [注文からの独立会計検査](../../work/update132_20261021/audit/独立注文会計と45場合計.json)
- [事前登録した固定計画](../../work/update132_20261021/試行計画_v2.json)
- [レポート生成](../../work/update132_20261021/report132.py)
'''
    (DEST / "README.md").write_text(readme, encoding="utf-8")
    # ----------------------------------------
    # 一覧はこの作業のブロックだけを更新し、過去の報告は保持します。
    top = ROOT / "README.md"
    old_text = top.read_text(encoding="utf-8-sig")
    note = f'最新：[00132：現行アルゴリズムの全45場損益](アルゴリズム調査/{STUDY}/{REPORT})。10月20日ナイト・21日デイを追加。手数料後の累計はTOPIXミニ{money(summary["TOPIX"]["net"])}円・日経マイクロ{money(summary["NK225"]["net"])}円。採用条件は00131から固定。'
    begin, end = "<!--00132案内-->", "<!--00132案内終了-->"
    block = begin + "\n" + note + "\n" + end
    if begin in old_text:
        old_text = old_text[:old_text.index(begin)] + block + old_text[old_text.index(end) + len(end):]
    else:
        pos = old_text.index("\n") + 1
        old_text = old_text[:pos] + "\n" + block + "\n" + old_text[pos:]
    top.write_text(old_text, encoding="utf-8")
    index = ROOT / "アルゴリズム調査/index.html"
    text = index.read_text(encoding="utf-8-sig")
    begin, end = "<!--00132開始-->", "<!--00132終了-->"
    block = f'{begin}<article class="task latest"><div class="number">作業00132・追加2セッション</div><h2>現行アルゴリズムの全45場損益</h2><p>10月20日ナイト・21日デイを追加。採用条件を固定し、各場の利益・損失・収支と累計を掲載。</p><a class="button" href="{STUDY}/{REPORT}">全45セッションの損益</a> <a href="{STUDY}/README.md">検証条件</a></article>{end}'
    if begin in text:
        text = text[:text.index(begin)] + block + text[text.index(end) + len(end):]
    else:
        marker = '<main id="work-list">'
        assert marker in text
        text = text.replace(marker, marker + "\n" + block, 1)
    index.write_text(text, encoding="utf-8")
    print(json.dumps(dict(report=str(DEST / REPORT), summary=summary, added=added), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
