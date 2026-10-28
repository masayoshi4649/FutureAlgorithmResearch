"""登録済みの不変手法と、別管理する運用時間割を公開する。"""
from __future__ import annotations

import json
from pathlib import Path
import shutil

from control164 import ROOT, HERE, CONFIGS, MANIFEST, verify_receipt, configs

OUT = ROOT/"アルゴリズム調査/00164_J02の日中改修と夜間の独立入口"


def main() -> None:
    """登録源を検査し、条件を変えず定義と時間割の資料を新規作成する。

    引数: なし。返り値: None。売買・金融再生は実行しない。
    """
    verify_receipt()
    items = configs()
    OUT.mkdir(parents=True,exist_ok=True)
    dest = OUT/"手法定義164.json"
    if dest.exists():
        assert dest.read_bytes() == CONFIGS.read_bytes()
    else:
        shutil.copyfile(CONFIGS,dest)
    rows = []
    for c in items:
        scope = {"Day":"日中","PreUS":"米国前","PostUS":"米国後"}[c["scope"]]
        if c["scope"] == "Day":
            description = c["description"]
        elif c.get("native"):
            description = c["native"]+"の元条件を、この時間帯だけへ固定した比較基準"
        else:
            entry = "逆進行後の反発・反落" if c["scope"] == "PreUS" else "順行後の押し戻しと再加速"
            protection = "利益Rから建値床とR追尾" if c["protection"] == "R利益開始" else "正利益から建値床、R追尾"
            description = entry+"／"+protection+("／利益後の新波へ再参加" if c["reentry"] else "")
        rows.append(f"|`{c['id']}`|{scope}|{description}|")
    document = """# 手法IDと時間割

**一つのIDに一つの売買条件を固定する。条件・配分・パラメータを変更するときは新IDにする。** 時間による切替は以下の時間割で管理し、昼夜を合成した手法IDは付けない。

今回の各IDの条件データは[手法定義164.json](手法定義164.json)。規則の指紋に加え、再生前に実装・原資料の指紋を登録している。

|ID|対象|変更内容|
|---|---|---|
"""+"\n".join(rows)+"""

## 時間割

|対象時間（日本時間）|使える手法ID|終了処理|
|---|---|---|
|デイ08:45～15:35|D164系列のうち一つ|15:35以降の正常板で全返済|
|ナイト17:00～米国開始15分前|P164系列のうち一つ|米国開始15分前以降の正常板で全返済|
|米国開始前後15分|なし|新規なし|
|米国開始15分後～翌05:50|U164系列のうち一つ|05:50以降の正常板で全返済|

今回の保存対象期間の米国開始基準は日本時間22:30。時刻は各場の入力目録に固定した。各手法は時間枠ごとに新しい状態から始める。夜間合計はPとUの非重複の会計を連結するだけであり、別の手法ではない。

## 枚数と計算価格

最大は買い100マイクロ・売り100マイクロ。それぞれ日経mini10枚相当。数量は1マイクロ刻みなので、mini10枚を常時持つ成績ではない。手数料0、判断も約定計算もラージの板を使用し、新規・返済とも判断後の次の正常板で買いAsk／売りBid。利益保護線の飛び越し損失も含む。

日中00は**00157第二巡J02**の比較再現であり、00154の同名J02とは異なる。初回は支持から10～100マイクロ、追加は元J02の配分を基準にする。支持スコアは勝率ではない。改修案の独自利益保護は実際の各玉の建値で判断する。

夜の新案は、直近の幅からRを決め、進行強度・効率と停止線までの危険額で枚数を決める。RはATRではない。初回・追加ごとにRを固定し、各実玉の建値を使う。危険予算5万円は約定後の損失上限保証ではない。

詳しい事前仕様：[計画164](../../work/research164/計画164.md)、[日中](../../work/research164/day_design/J02正本と部品設計164.md)、[夜間](../../work/research164/night_design/夜間の設計164.md)。旧IDの既存結果は改変していない。
"""
    path=OUT/"手法IDと時間割.md"
    if path.exists():
        assert path.read_text(encoding="utf-8") == document
    else:
        path.write_text(document,encoding="utf-8")
    print("不変20手法と独立時間割の資料を保存しました。")


if __name__ == "__main__":
    main()
