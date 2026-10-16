"""観測診断の件数と限界を共通知見及び最新の案内に接続する。"""

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
STUDY = ROOT / 'アルゴリズム調査'
CURRENT = '00112_元の公開時点と継続中の参加機会の診断'
REPORT = '初回見送り後に根拠が揃う場面の診断.md'


def write(path: Path, content: str) -> None:
    """
    機能: 日本語の完成文書をUTF-8で保存する。
    引数: path(Path)は対象、content(str)は文書。
    返り値: None。市場入力・金融結果を変更しない。
    """
    path.write_text(content.rstrip() + '\n', encoding='utf-8', newline='\n')


def append(name: str, anchor: str, title: str, body: str) -> None:
    """
    機能: 当時条件・分母・終点と未測を伴う法則を実在出典へ結び付ける。
    引数: name/anchor/title/body(str)は分類と法則。
    返り値: None。同じアンカーは重複させない。
    """
    path = STUDY / '共通/知見台帳' / (name + '.md')
    previous = path.read_text(encoding='utf-8-sig')
    if f'id="{anchor}"' in previous:
        return
    source = (f'**出典：** [{CURRENT}](../../{CURRENT}/README.md)。'
              f'根拠：[具体時刻と区間数](../../{CURRENT}/{REPORT})、'
              '[小集計](../../../work/e01_opportunity_trace_20261015/root_review/初回不成立後の現在資格と別母集団の小集計.json)、'
              '[独立再集計](../../../work/e01_opportunity_trace_20261015/technical_audit/初回不成立後の現在資格と別分母の独立小集計監査.json)。')
    write(path, previous.rstrip() + f'\n\n<a id="{anchor}"></a>\n\n## {title}\n\n{source}\n\n{body}')


def main() -> None:
    """
    機能: 元公開後の条件成立を記録し、新手法の利益とは区別する。
    引数: なし。完成小集計と独立監査を確認する。
    返り値: None。新金融は実行しない。
    """
    value = json.loads((HERE / '初回不成立後の現在資格と別母集団の小集計.json').read_text(encoding='utf-8-sig'))
    audit = json.loads((HERE.parent / 'technical_audit/初回不成立後の現在資格と別分母の独立小集計監査.json').read_text(encoding='utf-8-sig'))
    assert value['全合格'] and audit['全合格'] and value['対象場'] == 33
    append('入口', '00112_初回不成立後に現在の条件が成立する',
           '初回不成立後に現在の条件が成立する区間を捨てていた',
           '**当時条件：** 元E01公開後の同じ紙上方向区間。現在60秒の出来高方向代理known・2票以上・signed比TOP0.5／日経0.25。価格は両市場各2更新以上・signed比各0.25、相手は価格時刻代理でstrict過去。静観・新規期間・気配・公開費用等は別flag。\n\n'
           '**分母・終点：** 全33場のTOP147／日経152紙上方向区間。初回出来高不成立124／95のうち、区間の最終観測までに後の市場資格付き成立が102／83。価格もANDすると初回不成立138／130中86／97。初回値を持ち越さず当該行の票を使った。\n\n'
           '**限界・未測：** 条件成立への移行数であり、取引機会・先着率・勝率ではない。実busy・場stop・FAK失効との交差と後の収支は未測。SELECTED ANDのTOP閾値は0.5で、旧VOL25 ANDの0.25と別。初回失敗と保存修正の二読を新独立標本に数えない。')
    append('継続', '00112_公開時の根拠を後へ固定しない',
           '公開時の根拠を後へ固定せず現在の反応を取り直す',
           '**観測例：** 9/21デイTOP12:02:59・原seq30949は出来高代理買1売1、価格票自1相手1。12:03:22・seq30976は買3売1、価格票自3相手2とも上向きへ変化。日経11:55:04・seq34848は買0売1・価格比自−0.333相手0、12:03:36・seq35851は買3売0・価格票自3相手3とも上向き。\n\n'
           '**分母・範囲：** 各商品、時系列で最初の両条件後成立例1区間。更新票は正出来高差とLast対直前気配の代理。真の買売量・主体・補充・建玉原価ではない。\n\n'
           '**未測：** この変化に入った後の成功率、保持・撤退の損益効果、指標水準との因果は未測。終点後の上昇を当時条件へ使っていない。MA接触や押し安値は接触前水準と認定rowを固定して別検証する。')
    append('売買の工夫', '00112_正常観測数と参加機会を区別する',
           '全観測を調べても同じ波の反復を独立機会へ水増ししない',
           '**実測：** TOP全normal4,149,062行／価格時計値186,292、日経4,294,424／134,455。別母集団の両条件・共通市場資格の連続観測区間はTOP買1369売1294、日経買2804売2680。BUY/SELLに同じ全行分母を与え、分母を二倍にしない。\n\n'
           '**当時条件・範囲：** 紙上zeroや別方向中も含む全normal。正常・静観・新規期間だけを共通資格とし、紙上ATR・公開費用・実保有をこの群に追加していない。紙上方向区間の群と別。\n\n'
           '**限界：** 多数の行は同じ価格時計・同じ波・同じ窓を反復する。連続区間も取引機会・勝率ではない。新算法では水準接触と新しい反応のイベントへまとめ、全後続を一運転して手数料・損失を数える必要がある。')

    # ----------------------------------------
    # 最新の金融検証111と、非金融の診断112を区別して案内する。
    for path in (ROOT / 'README.md', STUDY / 'README.md'):
        text = path.read_text(encoding='utf-8-sig')
        text = text.replace('では、初回に見送った後の中央参加と、指標水準での参加者行動を診断する準備中。',
                            'では初回見送り後の現在資格を全33場で診断済み。TOPIX102／124・日経83／95区間で後から条件が成立。新手法の金融成績は未測。')
        lead = (f'[00112の具体時刻と診断]({'アルゴリズム調査/' if path == ROOT / 'README.md' else ''}{CURRENT}/{REPORT})。'
                '頭と尻尾を見送り、後の注文反応から中央へ入る仮説を整理した。\n\n')
        if f'{CURRENT}/{REPORT}' not in text:
            marker = '前段の [00105' if path == ROOT / 'README.md' else '前段 **[00105'
            text = text.replace(marker, lead + marker, 1)
        write(path, text)
    index = STUDY / 'index.html'
    text = index.read_text(encoding='utf-8-sig')
    text = text.replace(f'<a href="{CURRENT}/README.md">次の中央参加の診断（準備中）</a>',
                        f'<a href="{CURRENT}/{REPORT}">中央参加の観測診断（金融未測）</a>')
    text = text.replace('次の00112で中央への参加機会を診断する。',
                        '00112で初回見送り後の現在資格を診断済み。新手法の利益は未測。')
    text = text.replace('00112で途中参加と指標の行動仮説を診断する準備中です。',
                        '00112の観測診断は完了。途中参加と指標の行動仮説の金融効果は未測です。')
    write(index, text)
    print('00112の分類知見・具体診断の導線を保存。新金融0。')


if __name__ == '__main__':
    main()
