"""固定T06の追加一場を、独立検算した数値だけで簡潔に公開する。"""

from datetime import datetime, timezone, timedelta
import hashlib
from html import escape
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
RESEARCH = ROOT / "アルゴリズム調査"
NAME = "00134_十月二十二日デイのTOPIX損益"
OUT = RESEARCH / NAME
TITLE = "10月22日デイのTOPIX損益"
MANAGER = RESEARCH / "00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
TRIAL = "134_T06固定_20261022Day_TOPIX"


def read(path: Path) -> dict:
    """
    機能: 保存済みの実測・独立検算JSONを読む。
    引数: path(Path)はファイル位置。
    返り値: dictは内容。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def reference(path: Path) -> dict:
    """
    機能: 公開根拠と台帳の内容指紋を計算する。
    引数: path(Path)は保存済みファイル。
    返り値: dictは相対位置とSHA256。
    """
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return dict(path=path.relative_to(ROOT).as_posix(), sha256=digest)


def money(value: float) -> str:
    """
    機能: 円単位の会計を符号付きで表示する。
    引数: value(float)は円金額。
    返り値: strは表示文字列。
    """
    return f"{value:+,.0f}円" if value else "0円"


def write(path: Path, text: str) -> None:
    """
    機能: 新しい作業成果をUTF-8で保存する。
    引数: path(Path)は位置、text(str)は本文。
    返り値: None。旧成果は上書きしない。
    """
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def main() -> None:
    """
    機能: 一場の会計・約定一覧・根拠を公開し、既存知見に追記して試行を完了にする。
    引数: なし。監査合格を前提とする。
    返り値: None。金融再生・条件変更・実注文はしない。
    """
    result_path = HERE / "results/追加セッションの会計.json"
    audit_path = HERE / "audit/独立注文会計と約定明細.json"
    result, audit = read(result_path), read(audit_path)
    assert result["passed"] and audit["passed"] and len(result["rows"]) == 1
    row, account = result["rows"][0], audit["account"]
    assert row["session"] == "2026-10-22_Day" and row["symbol"] == "TOPIX"
    for key in ("profit", "loss", "net", "gross", "fees", "entries", "quantity", "max_long", "max_short"):
        assert row[key] == account[key], key
    assert row["profit"] - row["loss"] == row["net"] == row["gross"] - row["fees"]
    OUT.mkdir(exist_ok=False)
    write(OUT / "損益.json", json.dumps(dict(account=account, orders=audit["orders"],
        result=reference(result_path), audit=reference(audit_path)), ensure_ascii=False, indent=2) + "\n")
    profits = money(row["profit"])
    losses = money(-row["loss"])
    net = money(row["net"])
    overview = f"| 2026-10-22 デイ | {profits} | {losses} | **{net}** |"
    assumption = ("T06（主担当DV07＋未参加時の一回補完）。TOPIXミニ片方向上限10枚、主担当5枚・補完最大5枚。"
                  "判定にはTOPIX・日経のラージ板を使用。各時点までの情報で再生し、追加データで条件を変更していません。")
    fee_note = f"手数料前収支は{money(row['gross'])}、手数料は{row['fees']:,.0f}円。片道41.8円×枚数を注文ごとに円未満切捨て。"
    limit = "従来研究と同じラージの次正常原行気配による代理約定です。実アプリのミニ板での約定損益や通信遅延を再現した結果ではありません。"
    count_note = (f"新規{row['entries']}回、累計新規{row['quantity']}枚。実際の最大同時保有は買い{row['max_long']}枚・売り{row['max_short']}枚。"
                  f"主担当{money(row['components']['旧核']['net'])}、補完{money(row['components']['追加']['net'])}。全玉場内返済済み。")
    md = f"""# {TITLE}

最初に[{TITLE}.html]({TITLE}.html)を開いてください。約定明細と条件を掲載しています。検算には[損益.json](損益.json)を参照してください。

{assumption}

| セッション | 利益（手数料後） | 損失（手数料後） | 収支 |
| --- | ---: | ---: | ---: |
{overview}

{fee_note}

{count_note}

利益・損失は、新規から全返済までの親取引の純損益を正負別に合計した値です。

{limit}

## 再現資料

- [元資料の監査](../../work/update134_20261022/素材監査.json)：当場の二市場6素材。15:35の場内返済まで収録。
- [固定した計画](../../work/update134_20261022/試行計画.json)：入口・継続・出口・配分・費用・約定・入力と実装を事前登録。
- [実行手順](../../work/update134_20261022/run134.py)：prepare、register、runの順。既存出力は上書きしない。
- [独立会計検算](../../work/update134_20261022/audit/独立注文会計と約定明細.json)：全注文の数量・価格・料金・次正常原行・最終保有0を照合。

前回資料は[00132](../00132_現行アルゴリズムの追加セッション検証/README.md)。今回は当場TOPIXだけを新規検証し、旧場の再生や条件探索、API取得・実注文・アプリ設定変更は行っていません。
"""
    write(OUT / "README.md", md)
    execution_rows = []
    for order in audit["orders"]:
        action = ("新規" if order["opening"] else "返済") + ("買い" if order["side"] > 0 else "売り")
        execution_rows.append(f"<tr><td>{escape(order['time'][11:19])}</td><td>{action}</td><td>{order['quantity']}</td><td>{order['price']:,.2f}</td><td>{'—' if order['opening'] else money(order['gross_pnl'])}</td><td>{order['fee']:,.0f}円</td></tr>")
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{TITLE}</title>
<style>:root{{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#0c121d;color:#e5edf7}}body{{max-width:1000px;margin:auto;padding:28px 20px;line-height:1.8}}h1{{font-size:1.8rem}}table{{width:100%;border-collapse:collapse;margin:20px 0}}th,td{{padding:10px;border-bottom:1px solid #34445d;text-align:right;white-space:nowrap}}th:first-child,td:first-child{{text-align:left}}th{{background:#182438}}strong{{color:#8ed7ef}}a{{color:#96cfff}}.scroll{{overflow-x:auto}}.note{{color:#bdc9da;font-size:.92rem}}</style></head><body>
<!--
[コンポーネント概要]
#summaryは独立会計検算後の一セッションの利益・損失・収支を示します。
#executionsは全約定の日本時刻・方向・枚数・価格・返済粗損益・手数料を表示します。
.scrollは狭い画面で表を横スクロールして読む領域です。
-->
<h1>{TITLE}</h1><p>T06 ／ TOPIXミニ片方向上限10枚</p>
<div class="scroll"><table id="summary"><thead><tr><th>セッション</th><th>利益・手数料後</th><th>損失・手数料後</th><th>収支</th></tr></thead><tbody><tr><td>2026-10-22 デイ</td><td>{profits}</td><td>{losses}</td><td><strong>{net}</strong></td></tr></tbody></table></div>
<p>{fee_note}</p><p>{count_note}</p>
<p class="note">{assumption} 利益・損失は親取引単位で集計しています。</p>
<h2>売買の明細</h2><div class="scroll"><table id="executions"><thead><tr><th>日本時刻</th><th>売買</th><th>枚数</th><th>約定価格</th><th>返済損益・手数料前</th><th>注文手数料</th></tr></thead><tbody>{''.join(execution_rows)}</tbody></table></div>
<p class="note">{limit}</p><p><a href="README.md">条件と再現資料</a> ／ <a href="損益.json">集計データ</a></p></body></html>
"""
    write(OUT / (TITLE + ".html"), page)
    assert len(execution_rows) == len(audit["orders"])
    for value in (profits, losses, net, fee_note):
        assert value in page and value in md
    # ----------------------------------------
    # 共通の一覧と、参加補完の役割を記した既知項目へ当場の観測だけを追記する。
    index = RESEARCH / "index.html"
    text = index.read_text(encoding="utf-8")
    marker = '<main id="work-list">'
    assert text.count(marker) == 1
    card = f'<article class="task latest"><div class="number">作業00134・追加一場</div><h2>{TITLE}</h2><p>現行T06、上限10枚。手数料後{net}。</p><a class="button" href="{NAME}/{TITLE}.html">損益と売買明細</a></article>'
    index.write_text(text.replace(marker, marker + "\n<!--00134開始-->" + card + "<!--00134終了-->", 1), encoding="utf-8", newline="\n")
    listing = RESEARCH / "README.md"
    text = listing.read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    listing.write_text(first + f"\n\n最新：[00134：{TITLE}]({NAME}/{TITLE}.html)。現行T06・上限10枚、手数料後{net}。\n" + rest, encoding="utf-8", newline="\n")
    knowledge = RESEARCH / "共通/知見台帳/売買の工夫.md"
    text = knowledge.read_text(encoding="utf-8")
    position = text.index('### 固定した一回の参加補完が利益でも、主担当の赤字を埋めるとは限らない')
    following = text.find("\n<a id=", position)
    assert following > position
    note = (f"\n**追加観測（条件固定）：** [00134_十月二十二日デイのTOPIX損益](../../{NAME}/README.md)。2026-10-22デイのTOPIX一場を追加。"
            f"主担当{row['components']['旧核']['entries']}親・{money(row['components']['旧核']['net'])}、"
            f"参加補完{row['components']['追加']['entries']}親・{money(row['components']['追加']['net'])}、合算{net}（手数料後）。"
            "観測終点は当場全返済。今回の分母はTOPIX一場だけで、補完の予測率や将来の安定性を新たに確定する結果ではない。\n\n")
    knowledge.write_text(text[:following] + note + text[following:], encoding="utf-8", newline="\n")
    # ----------------------------------------
    # 台帳は当試行だけ完了へ変更し、再生せずに閲覧用データの整合を確認する。
    ledger = MANAGER.parent / "data/trials.json"
    before = reference(ledger)
    backup = ledger.parent / "history" / ("trials_" + before["sha256"] + ".json")
    if not backup.exists():
        shutil.copyfile(ledger, backup)
    document = read(ledger)
    chosen = [item for item in document["trials"] if item["id"] == TRIAL]
    assert len(chosen) == 1 and chosen[0]["status"] == "未実行"
    chosen[0].update(status="固定条件の追加一場検証完了", result=f"2026-10-22デイTOPIX・T06・上限10枚。手数料後{net}。条件再探索なし、注文会計の独立検算合格。ラージ代理約定。")
    chosen[0]["evidence"] += [reference(result_path), reference(audit_path), reference(OUT / "損益.json")]
    document["updated_at"] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    temp = ledger.with_suffix(".134tmp")
    write(temp, json.dumps(document, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temp.replace(ledger)
    write(HERE / "表示と完了の検算.json", json.dumps(dict(passed=True, financial_replays=0,
        account=row, executions=len(execution_rows), before=before, after=reference(ledger),
        report=reference(OUT / (TITLE + ".html"))), ensure_ascii=False, indent=2) + "\n")
    for action in ("build", "verify"):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(MANAGER), action], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        write(HERE / ("台帳_" + action + ".json"), json.dumps(dict(returncode=process.returncode, stdout=process.stdout, stderr=process.stderr), ensure_ascii=False, indent=2) + "\n")
        assert process.returncode == 0, process.stderr[-3000:]
    print(net, str(OUT / (TITLE + ".html")), flush=True)


if __name__ == "__main__":
    main()
