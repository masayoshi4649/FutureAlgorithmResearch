"""五巡の成果・反例・優先順位を既存の研究案内と分類別知見へ追記する。"""

import html
import json
import os
import re
from pathlib import Path
from common128 import HERE, ROOT, PUBLIC, read, reference, save


def write_with_backup(path, content):
    """
    機能: 今回の対象文書の元内容を保存してから更新する。
    引数: path(Path)、content(str)は文書位置と新本文。
    返り値: None。同名の更新前記録を上書きしない。
    """
    backup=HERE/"文書更新前"/path.relative_to(ROOT)
    backup.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and not backup.exists():
        backup.write_bytes(path.read_bytes())
    path.write_text(content,encoding="utf-8")


def relative_links(text, source, target):
    """
    機能: 診断案のファイル相対リンクを共通知見の位置へ移し替える。
    引数: text(str)、source/target(Path)は本文と移動元・移動先文書。
    返り値: strは存在を確認した相対リンクの本文。
    """
    def replace(match):
        """
        機能: 一つのローカル参照を移動先基準へ変換する。
        引数: match(re.Match)はMarkdown参照。
        返り値: strは変換後の参照。
        """
        label,href=match.groups()
        if href.startswith(("http","#")):
            return match.group(0)
        dest=(source.parent/href).resolve()
        assert dest.exists(),dest
        return f"[{label}]({Path(os.path.relpath(dest,target.parent)).as_posix()})"
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)",replace,text)


def main():
    """
    機能: 全場の数値と法則単位の知見を案内へつなぎ、実行状態を正確に残す。
    引数: なし。
    返り値: None。金融再生・現在API接続・アプリ設定変更なし。
    """
    final=read(HERE/"採用候補と公開記録.json")
    comp=read(HERE/"round5/前後半と方向別の比較.json")
    all_summary={(s["method"],s["symbol"]):s for s in comp["summary"]}
    name=PUBLIC.name
    title="日中改修と夜間新造の損益.html"
    summary=("五巡56条件。日中D17はTOPIX+485,133円・日経+248,300円、赤字は各6/22場。"
        "夜間N36はTOPIX17黒字・3赤字・1無取引だが、日経12赤字。夜間の両銘柄共通運用は未完成。")
    lines=[
        "# 日中改修と夜間新造の反復検証","",
        f"最初に見るファイルは [{title[:-5]}]({title})。全条件を切り替えて各セッションの利益・損失・収支・累計を確認できます。",
        "",
        "読む順序：HTML → [手法と検証仕様](手法と検証仕様.md) → [全条件・前後半・方向別会計](../../work/daynight128_20261020/round5/前後半と方向別の比較.json)。",
        "",
        summary,"",
        "日中はE01の二市場入口を継承し、発注時の明確な逆行だけを拒否。相手の横ばいは許します。値幅が縮めば損切り予算も縮め、再拡大しません。",
        "夜間は20分の固定帯を抜けた後の進行確認を新造。米国開始後の再形成を待ち、支持が失われた場合の撤退とトレーリングを組み合わせました。",
        "",
        "| 区分・候補 | 商品 | 利益 | 損失 | 収支 | 黒字／赤字／ゼロ場 |",
        "| --- | --- | ---: | ---: | ---: | --- |",
    ]
    for label,method in (("日中第一候補","D17"),("夜間共通比較・採用保留","N27"),("夜間TOPIX優先の参考","N36")):
        for symbol in ("TOPIX","NK225"):
            s=all_summary[method,symbol]
            lines.append(f"| {label} {method} | {symbol} | {s['profit']:,.0f}円 | {s['loss']:,.0f}円 | {s['net']:+,.0f}円 | {s['black']}／{s['red']}／{s['flat']} |")
    lines += ["",
        "実際の初回はTOPIXミニ5枚・日経マイクロ10枚。D18〜D20だけ弱支持時の数量を2/4枚又は3/6枚に減らします。設定上限10/20枚、追加なし。提示された立会手数料を新規・返済の両側に課金。利益・損失は部分返済を全てまとめた完結親の手数料後正負です。",
        "",
        "## 完成と呼ばない理由","",
        "日中D17は全22場を見た開発内の第一候補。前半だけで選ぶとD18であり、D17の選択自体は未知データで検証していません。日中全体の上位3黒字を除いても両商品は黒字ですが、上昇場だけから上位3黒字を除くとTOPIX−186,936円・日経−11,880円。TOPIXの上昇場中央値は83円で、方向ごとの全面的な安定を示しません。",
        "",
        "夜間N27は日経の全21場で+7,240円に留まり、前半−24,500円、上位3黒字除外−78,780円。TOPIX優先N36も日経では赤字12場で、共通の安定した完成形は未達です。条件を増やして既知の負けだけを消したことを将来の優位性とは呼びません。",
        "",
        "## 再現と検証","",
        "- [統合入口のPython](../../work/daynight128_20261020/selected_algorithm.py)：Day/Nightだけで固定候補を切り替える研究用関数。夜間は採用を保留した比較上位の再現用です。",
        "- [日中核](../../work/daynight128_20261020/day_core2.py)・[夜間核](../../work/daynight128_20261020/night5.py)・[採用候補と状態](../../work/daynight128_20261020/採用候補と公開記録.json)。既存のライブアプリは変更していません。",
        "- 入力の因果的特徴と日中E01通常影通知は[入力準備](../../work/daynight128_20261020/入力準備.json)と[特徴作成](../../work/daynight128_20261020/features128.py)を参照。新しい資料では別番号の固定計画を作り、完成済み試行を上書きしません。",
        "- 全43場は以前の研究にも使った既知データ。日中前半11/後半11、夜間前半10/後半11は時系列の点検であり、未知の外部テストではありません。",
        "- 完成済みの同一通知・核設定は保存引用。条件数、保存会計数、実際の新しい金融再生数を別に記録しています。再集計と人工検証を市場標本数へ数えません。",
        "- 次正常原板行のラージBBOを代理約定価格として使用。実ミニ・マイクロ板、実受信順、注文待ち順位を再現した結果ではありません。",
        "",
        "## 各巡と具体的な損失","",
    ]
    for n in range(1,6):
        lines.append(f"- 第{n}巡：[固定計画](../../work/daynight128_20261020/round{n}/固定計画.json) ／ [会計](../../work/daynight128_20261020/round{n}/全条件の会計.json) ／ [全注文の独立照合](../../work/daynight128_20261020/audit/round{n}_全注文と全行会計の独立照合.json)。")
    lines += [
        "- [日中の失う利益と残る負け](../../work/daynight128_20261020/diagnosis_day/第二巡の診断と第三巡への修正.md)・[D17の保存注文照合](../../work/daynight128_20261020/diagnosis_day/第三巡D17の保存注文と拒否親差の独立確認.json)。",
        "- [夜間の入口・出口矛盾](../../work/daynight128_20261020/diagnosis_night/第一巡の入口出口矛盾五十八組と第二巡仮説.json)・[再参加による建値悪化](../../work/daynight128_20261020/diagnosis_night/第二巡再参加で失った勝ちと保護前の接触事実.json)・[中期支持の失効と消す勝ち](../../work/daynight128_20261020/diagnosis_night/第三巡の準備根拠失効と除去勝ちの診断.json)。",
        "- [共通知見](../共通/知見台帳/README.md)は入口・継続・出口・売買の工夫へ分けて追記。",
    ]
    write_with_backup(PUBLIC/"README.md","\n".join(lines)+"\n")
    # ----------------------------------------
    # 正式な調査番号で分類別Markdownへ法則を追記する。
    ledger=ROOT/"アルゴリズム調査/共通/知見台帳"
    additions={n:[] for n in ("入口","継続","出口","売買の工夫")}
    for mode in ("day","night"):
        source=HERE/f"diagnosis_{mode}/知見追記案.md"
        text=source.read_text(encoding="utf-8")
        starts=list(re.finditer(r"^## (入口|継続|出口|売買の工夫)\.md[^\n]*$",text,re.M))
        for i,m in enumerate(starts):
            kind=m.group(1)
            content=text[m.end():starts[i+1].start() if i+1<len(starts) else len(text)].strip()
            content=content.split("## 統合時の確認事項")[0].strip()
            content=re.sub(r"^### ","## ",content,flags=re.M)
            if mode=="day":
                content=relative_links(content,source,ledger/(kind+".md"))
                source_line=f"**出典：** [{name}](../../{name}/README.md)。\n\n"
                title_end=content.index("\n",content.index("## "))
                content=content[:title_end+1]+"\n"+source_line+content[title_end+1:]
            additions[kind].append(content)
    for kind,blocks in additions.items():
        path=ledger/(kind+".md")
        text=path.read_text(encoding="utf-8")
        assert '<a id="00128_' not in text,path
        write_with_backup(path,text+"\n\n"+"\n\n".join(blocks)+"\n")
    # ----------------------------------------
    # ナビゲーションと今後も維持する評価方針を記録する。
    for filename,link in (("README.md",f"アルゴリズム調査/{name}/{title}"),
        ("アルゴリズム調査/README.md",f"{name}/{title}"),
        ("アルゴリズム調査/共通/知見台帳/README.md",f"../../{name}/{title}")):
        path=ROOT/filename
        text=path.read_text(encoding="utf-8")
        assert "<!--00128案内-->" not in text
        head,rest=text.split("\n",1)
        write_with_backup(path,head+f"\n\n<!--00128案内-->\n最新：[00128：日中改修と夜間新造]({link})。{summary}\n<!--00128案内終了-->\n"+rest)
    path=ROOT/"アルゴリズム調査/index.html"
    text=path.read_text(encoding="utf-8")
    marker='<main id="work-list">'
    assert text.count(marker)==1
    card=f'\n<!--00128開始--><article class="task latest"><div class="number">作業00128・昼夜独立の五巡検証</div><h2>日中は改善、夜間の日経は未完成</h2><p>{html.escape(summary)}</p><a class="button" href="{name}/{title}">全セッションの損益</a> <a href="{name}/README.md">出典と仕様</a></article><!--00128終了-->'
    write_with_backup(path,text.replace(marker,marker+card))
    path=ROOT/"アルゴリズム調査/調査方針.md"
    text=path.read_text(encoding="utf-8")
    text+=f"\n\n<!--00128昼夜独立-->\n## 2026年10月20日：昼夜を分けた改修と新造\n\n{name}で日中E01改修と夜間新造を別の状態機械として五巡56条件を検証。00127に続き提示立会手数料を含める。以前の固定数値目標ではなく、各場の小〜中利益、赤字の頻度と深さ、上昇下落の偏り、大勝ち依存を評価する。損失時刻から仮説を立て、消す勝ちも調べ、条件を固定し、人工確認・重複登録後に全場を再検証する。\n\n日中D17は第一候補、夜間はTOPIX向けN36が参考候補。両銘柄共通の夜間N27は安定性不足で採用保留。全既知資料で上位を選んだ結果と、前半で固定したD18/N20の後半結果を分ける。改良を継続しても、既知の損失を消すための閾値追加だけを優位性の発見としない。現在API取得・実注文・ライブ設定変更は今回行わない。\n<!--00128昼夜独立終了-->\n"
    write_with_backup(path,text)
    path=ROOT/"AGENTS.md"
    text=path.read_text(encoding="utf-8")
    text+="\n\n## 2026年10月20日の昼夜独立研究\n\n- その後のユーザーの手数料込み比較依頼を受け、00127・00128は上記の立会手数料込みで評価する。00125・00126の手数料0の既存会計は変更しない。\n- 日中はE01改修、夜間は独立した新造を比較する。00128で日中D17を第一候補としたが、夜間の両銘柄共通運用は安定性未達。比較上位N27を実運用の採用確定と読まない。\n- 最新の評価指定と未解決点は調査方針・00128のREADME・分類別知見へ記録済み。過去の固定数値目標を再度必須にしない。\n"
    write_with_backup(path,text)
    save(HERE/"文書公開と知見追記.json",dict(passed=True,report=reference(PUBLIC/title),
        readme=reference(PUBLIC/"README.md"),knowledge=[reference(ledger/(k+".md")) for k in additions],
        law_count=sum(block.count('<a id="00128_') for blocks in additions.values() for block in blocks),
        financial_replays=0,conditions=56,unfinished="夜間の両銘柄共通安定性、未知データでの固定候補検証"))
    print("全場レポート案内、分類別知見、調査方針を保存")


if __name__=="__main__":
    main()
