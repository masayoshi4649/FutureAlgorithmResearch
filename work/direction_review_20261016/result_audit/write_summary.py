"""独立小射影だけから、固定主評価と打切理由の短い説明を作る。"""

from pathlib import Path
import hashlib
import json
import math


HERE=Path(__file__).resolve().parent
SOURCE=HERE/'方向採点の主評価と各幅及び前後昼夜方向の独立小射影.json'
TARGET=HERE/'方向予測の独立集計と未解決理由.md'


def sha(raw: bytes) -> str:
    """
    機能: 小資料の同読取bytesを指紋にする。
    引数: raw(bytes)。
    返り値: str はSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


def pct(value: float | None) -> str:
    """
    機能: 分母なしを未定義として率を表示する。
    引数: value(float|None)。
    返り値: str は百分率又は未定義。
    """
    return '未定義' if value is None else f'{value*100:.2f}%'


def select(period: dict, rule: str='C', width: float=.001,
           origin: str='公開mid', direction: str='全体', group: str='非重複') -> dict:
    """
    機能: 独立再加算済みセルを一意に対応付ける。
    引数: period(dict)、rule/origin/direction/group(str)、width(float)。
    返り値: dict は対象セル。結果から最良幅を選ぶ関数ではない。
    """
    rows=[row for row in period['cells'] if all(row[name]==value for name,value in
        dict(rule=rule,width_fraction=width,origin=origin,direction=direction,group=group).items())]
    assert len(rows)==1
    return rows[0]


def pair(row: dict) -> str:
    """
    機能: 順先の分子と解決分母を表示する。
    引数: row(dict) は率を再加算したセル。
    返り値: str。全候補の分母と混同しない。
    """
    assert row['resolved']==row['favorable_first']+row['adverse_first']
    expected=row['favorable_first']/row['resolved'] if row['resolved'] else None
    assert expected==row['favorable_rate_resolved']
    return f"{row['favorable_first']}/{row['resolved']} ({pct(expected)})"


def main() -> None:
    """
    機能: 根へ渡す短いMDと小射影への接続証跡を新規保存する。
    引数: なし。
    返り値: None。元結果・観測NPZ・入力・金融にはアクセスしない。
    """
    assert not TARGET.exists()
    raw=SOURCE.read_bytes();value=json.loads(raw.decode('utf-8'))
    assert value['全合格'] is True
    lines=['# 方向予測の独立集計と未解決理由','',
        '固定主評価は **C・±0.10%・共通非重複・公開mid**。解決した事象で順先はTOPIX55.81%、日経57.61%だが、解決率は14.21%、43.24%に限られる。実売買の勝率でも、無条件の全候補的中率でもない。',
        '',
        '| 商品 | 起点 | 全候補 | 順先/解決 | 解決率 | 価格資格打切 | EOF | 仮新規気配なし |',
        '|---|---|---:|---:|---:|---:|---:|---:|']
    for symbol in ('TOPIX','NK225'):
        period=value['symbols'][symbol]['periods']['全33']
        for origin in ('公開mid','次行新規・費用後気配'):
            row=select(period,origin=origin)
            lines.append(f"| {symbol} | {origin} | {row['n']} | {pair(row)} | {pct(row['resolution_rate'])} | {row['price_cut']} | {row['eof']} | {row['entry_unavailable']} |")
    lines+=['',
        '公開midの同じ候補を常時売り方向として採点すると、TOPIX274/482＝56.85%、日経475/854＝55.62%。Cの差はそれぞれ−1.04、＋1.99ポイントで、両銘柄に強く共通する予測優位性は今回確立していない。派生対照なので独立標本は増えない。',
        '',
        '次行の仮新規価格から返済側気配・往復料を差し引く起点では、順先率は31.47%、33.41%まで低下する。これは実約定による決済勝率ではなく、気配と料を含む対称幅の先着評価。公開時のみ時間資格を判定し、直後注文の静観・強制返済取消は再現していない。',
        '', '## 打切の原因','',
        '主評価の価格打切は、TOPIX2910件、日経1121件とも**理由mask4だけ**。次行気配起点の2864件、1046件も同じ。mask4は「bid/askの非有限・非正・同値・逆転」の合流分類であり、どれだったかは今回の保存maskでは区別できない。連番欠落、価格時計、reset8、窓末の理由はこの主評価では0件。EOFは公開midのTOPIX1件だけ。',
        '',
        'したがって「時計不連続のせい」「同値板だけが原因」とは断定できない。途中で資格を失うことが無作為である保証もないため、解決内率を未解決部分へ外挿しない。欠測を勝ち・負けに補完せず、全候補の順先割合と解決率を併記する。理由ビットは重複し得るため、その和を件数にしない。今回は主評価の排他的patternが4だけだった。',
        '', '## A/B/C・各幅の共通非重複群','',
        'A＝最初の方向分類活動、B＝初期反対数量を一度も割らず公表活動Q0到達、C＝Bに方向側表示数量≧反対側を追加。公表活動をその価格の真の消費量・補充・心理と断定しない。',
        '',
        '| 商品 | 条件 | 幅 | 公開midの順先/解決 | 全候補 | 解決率 | 次行気配の順先/解決 |',
        '|---|---|---:|---:|---:|---:|---:|']
    for symbol in ('TOPIX','NK225'):
        period=value['symbols'][symbol]['periods']['全33']
        for rule in ('A','B','C'):
            for width in (.0005,.001,.002):
                mid=select(period,rule,width);quote=select(period,rule,width,'次行新規・費用後気配')
                assert mid['n']==quote['n']
                lines.append(f"| {symbol} | {rule} | {width*100:.2f}% | {pair(mid)} | {mid['n']} | {pct(mid['resolution_rate'])} | {pair(quote)} |")
    lines+=['', '同じruleでは最大幅0.20%の両起点終端まで重複候補を採らない共通maskを全3幅に使った。幅・条件を結果から選び直して成功とはしない。',
        '', '## 固定C・0.10%の前後・昼夜','',
        '| 商品 | 期間 | 公開midの順先/解決 | 全候補 | 解決率 | 次行気配の順先/解決 |',
        '|---|---|---:|---:|---:|---:|']
    for symbol in ('TOPIX','NK225'):
        for label in ('前16','後17','デイ','ナイト'):
            p=value['symbols'][symbol]['periods'][label]
            mid=select(p);quote=select(p,origin='次行新規・費用後気配')
            lines.append(f"| {symbol} | {label} | {pair(mid)} | {mid['n']} | {pct(mid['resolution_rate'])} | {pair(quote)} |")
    lines+=['', '## 固定C・0.10%の買い／売り','',
        '| 商品 | 判断方向 | 公開midの順先/解決 | 全候補 | 解決率 | 次行気配の順先/解決 |',
        '|---|---|---:|---:|---:|---:|']
    for symbol in ('TOPIX','NK225'):
        p=value['symbols'][symbol]['periods']['全33']
        for direction in ('買い','売り'):
            mid=select(p,direction=direction);quote=select(p,origin='次行新規・費用後気配',direction=direction)
            lines.append(f"| {symbol} | {direction} | {pair(mid)} | {mid['n']} | {pct(mid['resolution_rate'])} | {pair(quote)} |")
    lines+=['', '## 検査範囲','',
        '保存結果JSON1件と、その新出力observations66件を各1回読み、全108セル×66口座・固定方向対照・10商品期間をCounter/Fractionによる別実装で照合した。数値比較438,263項目合格。原市場NPZ・旧event入力・実台帳・API・金融・再measureは0。ラベルの原価格経路からの初到達そのものを再検証した監査ではない。',
        '',
        '旧既知33場の同じ経路を使う非金融測定。未知期間の予測精度・採算性・最適保有時間・売買実行可能性・未解決区間の方向は未確立。MFE/MAEは先着後を含む事後記述であり、先着率や実現利益へ混ぜていない。',
        '',
        '[独立数値小射影](方向採点の主評価と各幅及び前後昼夜方向の独立小射影.json) · [独立検査証跡](保存66観測と全セル対照及び期間の独立集計確認.json)', '']
    TARGET.write_text('\n'.join(lines),encoding='utf-8')
    proof=dict(全合格=True,元小射影SHA256=sha(raw),本文SHA256=sha(TARGET.read_bytes()),
        source_SHA256=sha(Path(__file__).read_bytes()),原結果追加読取=0,観測追加読取=0,
        原NPZ=0,event入力=0,金融=0,API=0,
        範囲='独立小射影から記述。同一rule共通非重複、固定主評価、未解決/派生対照/次行気配の非金融性を明記。')
    destination=HERE/'短い集計説明と分母及び理由範囲の確認.json'
    assert not destination.exists()
    destination.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False))


if __name__=='__main__':
    main()
