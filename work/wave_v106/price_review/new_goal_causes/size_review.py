"""保存小資料だけを突合し、旧赤字と回復勝ちの公開時予定数量を整理する。"""

import hashlib
import importlib.util
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SOURCE = 'work/wave_v106/size_availability/公開299のATR両気配と予定数量可用性.json'
SOURCE_SHA = '67014ed5401371e86bcbf32f2e5bc94a5cb07e9c27954c8a133040574c3e74fa'


def read(path: str) -> tuple:
    """
    機能: 保存済み小JSONだけを読み、同bytesの指紋を返す。
    引数: path(str)はroot相対位置。
    返り値: tuple[dict,str]は小資料とSHA256。原入力・NPZ・金融は読まない。
    """
    saved = (ROOT/path).read_bytes()
    return json.loads(saved.decode('utf-8-sig')), hashlib.sha256(saved).hexdigest()


def digest(path: Path) -> str:
    """
    機能: 小資料及び固定sourceの指紋を確認する。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。大型入力には使用しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def match(index: dict, symbol: str, session: str, point: dict, parent: int, side: int) -> dict:
    """
    機能: 元公開と299射影の同normal・原seq・時計・親・方向を一致させる。
    引数: index(dict)、symbol/session(str)、point(dict)、parent/side(int)は保存公開の同定情報。
    返り値: dictは一致した一公開。約定行又は途中判断行へ置換しない。
    """
    value = index[symbol, session, point['normal_row']]
    assert value['paper_parent'] == parent and value['side'] == side
    assert value['raw_seq'] == point['raw_seq']
    assert value['price_time_s'] == point['price_time_s'] and value['JST'] == point['JST']
    assert value['W60']['candidate_raw_row'] == value['raw_row']
    assert value['W60']['candidate_raw_seq'] == value['raw_seq']
    assert value['W60']['candidate_price_time_s'] == value['price_time_s']
    return value


def reservation(value: dict, category: str, context: dict, reference: dict, risk: object) -> dict:
    """
    機能: 固定1ATR予定式を小射影から再計算し、元数量・一枚・選択qの予約額を分解する。
    引数: value/category/context/reference/riskは公開dict、種類str、旧結果dict、由来dict、固定純算術module。
    返り値: dictは初回全予算での静的予約と三元門の採否。新損益は算出しない。
    """
    assert value['quote_valid']
    computed = risk.measure(value['ATR'], value['bid'], value['ask'], value['symbol'])
    assert computed == value['sizing'] and computed['known']
    for mode in ('VETO', 'CONFIRM', 'KNOWN_VETO'):
        assert tuple(value['old_gate'][mode].values()) == risk.gate(value['W60'], mode)
    q = computed['proposed_quantity']
    amount = computed['risk_by_quantity'][q-1]['planned_risk_yen'] if q else 0.
    atr_reserve = q*value['ATR']*risk.VALUE[value['symbol']]
    spread_reserve = q*(value['ask']-value['bid'])*risk.VALUE[value['symbol']]
    fees = 2*risk.fee(q, value['symbol'])
    assert abs(amount-(atr_reserve+spread_reserve+fees)) <= 1e-8
    result = dict(種類=category, 保存由来=reference,
        session=value['session'], symbol=value['symbol'], paper_parent=value['paper_parent'], side=value['side'],
        JST=value['JST'], 公開normal_row=value['publish_normal_row'], raw_row=value['raw_row'], raw_seq=value['raw_seq'],
        price_time_s=value['price_time_s'], 公開ATR=value['ATR'], 公開bid=value['bid'], 公開ask=value['ask'],
        公開気配差=value['ask']-value['bid'], 初回全予算=computed['budget_yen'],
        元初回枚数=value['original_qty'], 元枚数予定額=computed['original_quantity_risk'],
        最小一枚予定額=computed['risk_by_quantity'][0]['planned_risk_yen'], 初回予定q=q,
        予定q予約額=amount, 内訳=dict(ATR予約=atr_reserve, 気配差予約=spread_reserve, 往復料予約=fees),
        予約後予定余白=computed['budget_yen']-amount, 各整数量=computed['risk_by_quantity'],
        元W60=value['W60'], 三元公開採否=value['old_gate'],
        三元門と予定正量の両方を満たす={m: v['allowed'] and q > 0 for m, v in value['old_gate'].items()},
        保存旧結果の参考=context,
        限界='初回fullbudgetだけの当時予約。同じ原行の数量可用性であり、後半remainingbudget・実busy・次行約定・新損益は未測定。')
    if q < computed['maximum_quantity']:
        assert computed['risk_by_quantity'][q]['planned_risk_yen'] > computed['budget_yen']
    return result


def run() -> None:
    """
    機能: 代表六赤字場の七負け親、回復勝ち二親、KNOWNで追加された入口の予定qを保存する。
    引数: なし。
    返り値: None。小JSONだけを読み、自所有域へ新証跡を保存する。
    """
    paths = [SOURCE,
        'work/wave_v106/price_review/new_goal_causes/代表赤字と早期退出反証及び残余力の保存根拠.json',
        'work/wave_v106/e01_trade_exit/diagnosis/全6二対照の具体損失軽減と勝ち喪失の診断.json']
    data = [read(path) for path in paths]
    size, evidence, exits = [v[0] for v in data]
    assert data[0][1] == SOURCE_SHA and size['全合格'] and evidence['全合格']
    fixed_source = size['source_SHA256']
    assert len(fixed_source) == 4
    assert all(digest(ROOT/path) == sha for path, sha in fixed_source.items())
    spec = importlib.util.spec_from_file_location('固定予定算術', ROOT/'work/wave_v106/size_availability/risk.py')
    risk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(risk)
    index = {(v['symbol'], v['session'], v['publish_normal_row']): v for v in size['witness']}
    assert len(index) == len(size['witness']) == 299
    results = []
    # ----------------------------------------
    # 旧代表の六赤字場を構成した七負け親を、将来の損失額で数量選択せず対応させる。
    for key, symbol in (('TOPIX逆票見送りの全赤字', 'TOPIX'), ('NK肯定票要求の全赤字', 'NK225')):
        mode = 'VETO' if symbol == 'TOPIX' else 'CONFIRM'
        for scene in evidence[key]:
            parents = [scene['初負け']] if symbol == 'TOPIX' else scene['負け親']
            for parent in parents:
                side = 1 if parent['方向'] == '買い' else -1
                value = match(index, symbol, scene['session'], parent['公開'], parent['parent'], side)
                assert value['bid'] == parent['公開bid'] and value['ask'] == parent['公開ask']
                assert value['W60'] == parent['当時方向票'] and value['old_gate'][mode]['allowed']
                results.append(reservation(value, '旧代表赤字の負け親',
                    dict(旧母条件=mode, 旧場収支=scene['場収支'], 旧親収支=parent['収支']),
                    dict(path=paths[1], 場キー=key, session=scene['session'], 親=parent['parent']), risk))
    assert len(results) == 7
    # ----------------------------------------
    # 早期返済では切り過ぎた元勝ちの入口を、同じ公開時の1ATR式で確認する。
    wins = [v for v in exits['具体例'] if v['種類'] == '旧勝ち親を赤字化した最大例'
            and v['id'] == 'E01_EXIT_CONFIRM_W10_P1_H8_V4']
    assert len(wins) == 2
    for scene in wins:
        original = scene['基準P1L8親']
        order = original['実注文'][0]
        assert order['新規'] and order['reason'] == 90
        value = match(index, scene['symbol'], scene['session'], order['判断'], original['親']['親'], order['side'])
        assert value['bid'] == order['判断']['bid'] and value['ask'] == order['判断']['ask']
        assert order['quantity'] == value['original_qty']
        results.append(reservation(value, '旧回復勝ちの反証',
            dict(旧親収支=original['親']['収支'], 旧早期退出後親収支=scene['新政策親']['親']['収支'],
                 旧逆票早期判断=scene['判断時基準の実残玉情報']),
            dict(path=paths[2], 具体例ID=scene['id'], session=scene['session'], symbol=scene['symbol'],
                 固定対象親=scene['固定対象親']), risk))
    # ----------------------------------------
    # 情報不足の入口を拒否した後の追加参加例も、残余予算とは区別して照合する。
    extra = evidence['KNOWNで追加した負けの公開']
    assert len(extra) == 1
    for scene in extra:
        point = dict(normal_row=scene['normal_row'], raw_seq=scene['candidate_raw_seq'],
                     price_time_s=scene['candidate_price_time_s'], JST=scene['JST'])
        value = match(index, scene['symbol'], scene['session'], point, scene['paper_parent'], scene['side'])
        assert value['raw_row'] == scene['candidate_raw_row']
        assert value['old_gate']['KNOWN_VETO']['allowed'] == scene['base_known_veto_allowed']
        results.append(reservation(value, 'KNOWN変更後の追加入口',
            dict(追加親の新損益未算出=True, 元保存KNOWN親の収支はこの小射影に未収録=True),
            dict(path=paths[1], 場キー='KNOWNで追加した負けの公開', session=scene['session'],
                 親=scene['paper_parent']), risk))
    assert len(results) == 10
    assert all(v['初回予定q'] == 0 for v in results if v['symbol'] == 'TOPIX' and v['種類'] == '旧代表赤字の負け親')
    assert all(v['初回予定q'] == 0 for v in results if v['種類'] == '旧回復勝ちの反証')
    assert all(digest(ROOT/path) == sha for path, sha in fixed_source.items())
    # ----------------------------------------
    # 新金融と比例推定を行わず、対応資料と計算の証跡だけを新規保存する。
    target = HERE/'代表六赤字場と回復勝ちの初回予定数量.json'
    assert not target.exists()
    output = dict(全合格=True, source={p: sha for p, (_, sha) in zip(paths, data)},
        診断source_SHA256=digest(Path(__file__)), 固定数量source_SHA256=fixed_source,
        計算=size['計算'], 初回全予算=size['予算'], 元初回上限=size['元初回上限'],
        紙上停止係数=size['紙上停止係数'], 対応候補数=len(results), 診断=results,
        結論=['旧TOP四赤字入口は全て初回q0。ただし実損失を避けた新金融結果ではない。',
              '旧回復勝ちTOP9/22NightとNK9/28Dayもq0。悪い入口だけを除外する式ではない。',
              '旧NK赤字入口は2枚・2枚・1枚となる。新収支の比例推定は実施していない。'],
        未測定=['損切り後のremainingbudgetを反映した数量', '新数量による約定・部分返済・再参加と新金融結果',
                '新数量で絶対利益停止枠を達成するまでの追加取引', '実口座busy/quiet/goalstopの候補採否'],
        約束='1ATRは公開時予約。元paper0.75ATR影出口と異なり、実損失の保証ではない。',
        新金融=0, 比例損益推定=0, 原入力再読=0, NPZ=0, 原板=0, API=0, 固定4py編集=0)
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
                      encoding='utf-8', newline='\n')
    print('代表六赤字場七親・回復勝ち二親・追加一入口の初回予定qを保存。新金融0。', flush=True)


if __name__ == '__main__':
    run()
