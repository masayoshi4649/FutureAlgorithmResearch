"""保存済み小診断から損失の種類と再参加余力を整理し、新金融は実行しない。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]


def read(path: str) -> tuple:
    """
    機能: 保存済み小JSONを読み、その同bytesの指紋を記録する。
    引数: path(str)はroot相対位置。
    返り値: tuple[dict,str]は既存情報とSHA256。原板・NPZ・金融再生を呼ばない。
    """
    saved = (ROOT/path).read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def parent_scene(value: dict) -> dict:
    """
    機能: 既存実親の公開・新規・返済・事後診断点だけを小資料へ写す。
    引数: value(dict)は以前に保存した実親診断。
    返り値: dictは保存点。事後ピークを新しい判断条件へ使用しない。
    """
    return dict(parent=value['親'], 方向=value['方向'], 収支=value['収支'],
                公開=value['公開'], 新規=value['新規'], 実新規価格=value['実新規価格'],
                公開bid=value['公開bid'], 公開ask=value['公開ask'],
                返済=value['返済注文'], 当時方向票=value['代理票'],
                事後の経路参考=value.get('事後親清算経路'),
                最初の戻り失敗時刻='この小診断では未測定')


def fee(quantity: int, symbol: str) -> int:
    """
    機能: ユーザー指定片道料を注文ごとに切り捨てる純算術を行う。
    引数: quantity(int)、symbol(str)は整数枚数と商品。
    返り値: intは一注文の料。仮想売買・数量選択は実行しない。
    """
    assert quantity >= 0 and symbol in ('TOPIX', 'NK225')
    return int(quantity*({'TOPIX': 41.8, 'NK225': 11.}[symbol]))


def run() -> None:
    """
    機能: 既存の代表赤字・早期退出反証・KNOWN変更と費用余力の算術を保存する。
    引数: なし。
    返り値: None。原板・NPZ・準備cache・新金融は読まない。
    """
    paths = [
        'work/wave_v106/e01_trade_gate/diagnosis/全24の5寄与と赤字上位場及びW60成行P1L8の具体原因.json',
        'work/wave_v106/e01_trade_exit/diagnosis/全6二対照の具体損失軽減と勝ち喪失の診断.json',
        'work/wave_v106/e01_known_veto/finance/結果.json',
        'work/wave_v106/e01_absorption_gate/diagnosis/全299公開の表示維持観測と条件交差.json']
    data = [read(path) for path in paths]
    detail, early, known, witness = [x[0] for x in data]
    primary = detail['重点条件の全赤字場と黒字反証']['TOPIX']['赤字全場']
    top = []
    for day, scene in primary.items():
        parent = scene['初負け親']
        top.append(dict(session=day, 場収支=scene['収支'], 初負け=parent_scene(parent)))
    nk = []
    for day, scene in detail['results']['E01_TRADE_W60_CONFIRM_D0_P1L8']['NK225']['最悪3場'].items():
        if scene['変更']['収支'] < 0:
            nk.append(dict(session=day, 場収支=scene['変更']['収支'],
                           負け親=[parent_scene(p) for p in scene['最大損失2親']]))
    # ----------------------------------------
    # 早期返済で元の勝ちを失った事例と、入口見送り後に参加した別の負けを分ける。
    false_exits = []
    for v in early['具体例']:
        if v['種類'] != '旧勝ち親を赤字化した最大例' or v['id'] not in (
                'E01_EXIT_VETO_W10_P1_H8_V4', 'E01_EXIT_CONFIRM_W10_P1_H8_V4'):
            continue
        false_exits.append(dict(symbol=v['symbol'], session=v['session'], id=v['id'],
            早期判断=v['判断時基準の実残玉情報'], 元収支=v['基準P1L8親']['親']['収支'],
            新収支=v['新政策親']['親']['収支'],
            元最終返済=v['基準P1L8親']['実注文'][-1]))
    kid = 'E01_TRADE_W60_KNOWN_VETO_D0_P1L8'
    changes = [v for v in known['各場寄与'][kid] if v['収支変化'] != 0 or v['新たな入口の収支'] != 0]
    new_failure = [v for v in witness['witness'] if v['session'] == '2026-09-21_Night'
                   and v['symbol'] == 'TOPIX' and v['normal_row'] == 62243]
    assert len(new_failure) == 1
    # ----------------------------------------
    # 次の約定価格を使わず、公開時の費用だけで残余力の算術を点検する。
    room = 8000-7220
    quantities = []
    for q in range(1, 11):
        quoted_friction = q*10*10+2*fee(q, 'NK225')
        reserve_one_tick = q*10*10
        quantities.append(dict(枚数=q, 公開一呼値気配差と往復料=quoted_friction,
            一呼値悪化の追加予約=reserve_one_tick, 費用のみ残780以内=quoted_friction <= room,
            費用と一呼値予約が残780以内=quoted_friction+reserve_one_tick <= room))
    assert max(q['枚数'] for q in quantities if q['費用のみ残780以内']) == 6
    assert max(q['枚数'] for q in quantities if q['費用と一呼値予約が残780以内']) == 3
    # ----------------------------------------
    # 新しい金融結果と区別し、保存された診断点及び未測定の制御だけを記録する。
    target = HERE/'代表赤字と早期退出反証及び残余力の保存根拠.json'
    assert not target.exists()
    output = dict(全合格=True, source={path: sha for path, (_, sha) in zip(paths, data)},
        TOPIX逆票見送りの全赤字=list(sorted(top, key=lambda v: (v['場収支'], v['session']))),
        NK肯定票要求の全赤字=nk, 逆票早期退出の勝ち反証=false_exits,
        KNOWN_VETOの変化=changes, KNOWNで追加した負けの公開=new_failure,
        残余力の純算術=dict(比較事例='NK9/29Night先の親-7220、損失枠8000、残780',
            残余力=room, 公開気配='CONFIRM 23:25:13 bid66160/ask66170、KNOWN 19:32:34 bid65750/ask65760',
            費用額の分母='日経micro1枚、値幅10円×倍率10=100円＋往復22円=122円。注文別切捨て。',
            枚数別=quantities,
            保証='公開時の費用と任意の一呼値予約の算術だけ。次行約定/跳び/以後損益を保証しない。'),
        新金融=0, 新数量政策=0, 原板=0, NPZ=0, 準備cache=0, API=0,
        未測定=['各親の最初の戻り失敗時刻', '数量縮小後の約定・部分返済・再参加と新損益',
                '最小数量と絶対利益目標による活動喪失', '数量と費用を予約した口座の正しさ'])
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                      encoding='utf-8', newline='\n')
    print('代表赤字と元勝ち反証、残780のq6/q3算術を保存。新金融0。', flush=True)


if __name__ == '__main__':
    run()
