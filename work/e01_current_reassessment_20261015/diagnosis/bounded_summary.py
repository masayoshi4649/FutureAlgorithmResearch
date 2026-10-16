"""根へ渡す原因小結を50KiB未満へ限定し、全親の二重配置を避ける。"""

import json
from pathlib import Path

import run

HERE=Path(__file__).resolve().parent
INPUT=HERE/'方向とコスト及び保護未起動の限定小結.json'
SUPPORT=HERE/'初期支持線と更新支持線の判断時比較.json'
OUTPUT=HERE/'根へ渡す九条件と六例の限定小結.json'


def money(value: dict) -> dict:
    """
    機能: 全親又は負親の同じ分母と金額恒等式を必要列へ限定する。
    引数: value(dict) は既集計。
    返り値: dict は金額・分類・保護分母。未知を零にしない。
    """
    keys=('parent_count','mid_direction_yen','crossing_disadvantage_yen','actual_fee_yen','actual_net_yen',
          'wins','losses','mid_reverse_count','nonnegative_mid_but_net_loss','once_positive_liquidation_count',
          'never_positive_liquidation_count','support_updated_parents','peak_reached_wide_arm','exits')
    return {k:value[k] for k in keys if k in value}


def parent(value: dict, full: bool) -> dict:
    """
    機能: 代表負親又は勝ち反証を公開票・約定・極値だけに限定する。
    引数: value(dict)、full(bool) は既小例と負親詳細の必要性。
    返り値: dict は既保存の小例。全親は再配置しない。
    """
    keys=('session','symbol','parent','side','q','net','peak','wide_arm','cash_stop','support_updates',
          'adverse_ticks','exit_reason','publication','entry','exit_fill')
    if full:
        keys += ('session_net','best','worst_point','exit_source','amounts')
    return {k:value[k] for k in keys if k in value}


def main() -> None:
    """
    機能: 保存小集計だけから限定JSONを作り、最大サイズと出典を検査する。
    引数: なし。
    返り値: None。元結果・実台帳・cache・API・金融は読まない。
    """
    assert not OUTPUT.exists()
    before=run.sources()
    a=json.loads(INPUT.read_text(encoding='utf-8'))
    b=json.loads(SUPPORT.read_text(encoding='utf-8'))
    assert a['出典結果SHA256']==b['出典結果SHA256']==run.EXPECTED_SHA
    output=dict(全合格=True,出典結果SHA256=run.EXPECTED_SHA,
        出典小結SHA256=run.sha(INPUT),支持線比較SHA256=run.sha(SUPPORT),診断sourceSHA256=run.sha(Path(__file__)),
        九条件={cid:{s:{k:money(t) for k,t in z.items()} for s,z in syms.items()} for cid,syms in a['全九条件の全親と負親'].items()},
        主反応WIDE={s:{k:money(z) for k,z in a['主③WIDEの詳細'][s].items() if k in ('全親','負親','負親かつ一度も黒字なし','負親かつ途中黒字あり')} for s in run.CAP},
        支持更新返済の初期線比較={s:{k:money(z) for k,z in syms.items()} for s,syms in b['results'][run.MAIN].items()},
        赤字上位三場六親={s:[parent(v,True) for v in vv] for s,vv in a['赤字六例'].items()},
        勝ち反証最大二親={s:[parent(v,False) for v in vv] for s,vv in a['同条件の勝ち反証最大2例'].items()},
        留保=['中値は同入口/返済時点の恒等式。逆売買又は中値約定利益ではない。',
              '未来の極値は診断限定。支持線OFFの利益/後参加は未測。',
              'peer両BBOと一部支持更新時計は未保存。'],
        元結果一目的読取=1,元金融追加読取=0,台帳=0,cache=0,原板=0,API=0,新金融=0)
    raw=json.dumps(output,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    assert len(raw.encode('utf-8'))<50*1024
    OUTPUT.write_text(raw,encoding='utf-8')
    assert before==run.sources()
    print(json.dumps(dict(全合格=True,bytes=len(raw.encode('utf-8')),SHA256=run.sha(OUTPUT)),ensure_ascii=False))


if __name__=='__main__':
    main()
