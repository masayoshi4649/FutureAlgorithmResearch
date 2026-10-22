"""固定仮想通知による数量比較を、市場データなしの人工原行で独立確認する。"""

import hashlib
import json
import os
from pathlib import Path
import sys
import numpy as np

HERE = Path(__file__).resolve().parent
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'audit_overlay_jit')
sys.path.insert(0, str(HERE))
import overlay137
import run137


def source_hash(path):
    """
    機能: 検査した実装の内容指紋を作る。
    引数: path(Path)はファイル位置。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(side=1, total=80):
    """
    機能: 既存通知と公開済み支持を持つ人工価格列を作る。
    引数: side(int)は方向、total(int)は原行数。
    返り値: dictは原行と設定の人工入力。
    """
    times = np.arange(total, dtype=float)
    bid = np.full(total, 99.)
    ask = np.full(total, 100.)
    market = np.zeros((total, 12))
    market[:, 4:8] = side * .3
    market[:, 8] = times - 1.
    market[:, 11] = 1.
    phase = np.ones(total, dtype=np.int64)
    original = np.array([[2., 1., 0., side, 10., 100. if side > 0 else 99., 10., 1.],
                         [70., 69., 0., -side, 10., 99. if side > 0 else 100., 11., 0.]])
    return dict(times=times, bid=bid, ask=ask, qok=np.ones(total, dtype=np.bool_),
                atr=np.full(total, 20.), market=market, phase=phase, original=original)


def run_case(data, initial=2, mode=2, width=.25, hold=15., adaptive=False, python=False):
    """
    機能: 人工親のみを数量層へ渡す。
    引数: data(dict)、数量・比較条件の数値、python(bool)は非JIT指定。
    返り値: ndarrayは十列の人工注文。
    """
    fn = overlay137.campaign.py_func if python else overlay137.campaign
    args = [data[k] for k in ('times', 'bid', 'ask', 'qok', 'atr', 'market', 'phase', 'original')]
    return fn(*args, initial, mode, width, hold, adaptive)


def independent_cash(orders):
    """
    機能: 建値集計を使わず、各売買の現金差額から費用後会計を求める。
    引数: orders(ndarray)は完結人工注文。
    返り値: tuple[float,int,float]は粗利益・手数料・純収支。
    """
    gross = float(np.sum(-orders[:, 3] * orders[:, 4] * orders[:, 5] * 100.))
    fees = sum(int(int(q) * 385 // 10) for q in orders[:, 4])
    return gross, fees, gross - fees


def check(condition, name, checks):
    """
    機能: 人工検査の合否を記録し、不一致を停止する。
    引数: condition(bool)、name(str)、checks(list)は判定と記録先。
    返り値: None。
    """
    assert condition, name
    checks.append(name)


def main():
    """
    機能: 枚数・約定・独立停止・未来非参照の人工検査だけを実行する。
    引数: なし。
    返り値: None。市場原本読取と金融再生は行わない。
    """
    before = {p.name: source_hash(p) for p in (HERE/'overlay137.py', HERE/'run137.py')}
    checks = []
    d = fixture()
    d['original'] = np.array([[2, 1, 0, 1, 10, 100, 10, 1],
                              [40, 39, 0, -1, 5, 110, 11, 0],
                              [70, 69, 0, -1, 5, 120, 12, 0]], dtype=float)
    d['bid'][40] = 110.; d['ask'][40] = 111.
    d['bid'][70] = 120.; d['ask'][70] = 121.
    o = run_case(d, 5, 0)
    check(o[:, 4].tolist() == [5, 2, 3], '5枚基準の端数返済は2枚と3枚', checks)
    check(o[:, 9].tolist() == [192, 77, 115], 'mini片道38.5円を注文ごと切捨て', checks)
    a = run137.account(o, d['times'], d['bid'], d['ask'], '人工', '2000-01-01_Day')
    check((a['gross'], a['fees'], a['net']) == (8000., 384, 7616.), '5枚基準の独立手計算', checks)
    o = run_case(d, 2, 0)
    check(o[:, 4].tolist() == [2, 1, 1], '2枚固定の端数返済', checks)
    check(independent_cash(o) == (3000., 153, 2847.), '2枚固定の独立手計算', checks)
    o = run_case(d, 1, 0)
    check(o[:, 4].tolist() == [1, 1] and int(o[-1, 0]) == 70, '1枚は端数部分返済で消えず最終全返済', checks)

    # ----------------------------------------
    # 追撃判断は初回以後の新観測を要求し、判断後の正常原行へ執行する。
    d = fixture(); d['bid'][3:] = 106.; d['ask'][3:] = 107.
    d['original'][-1, 5] = 106.
    o = run_case(d)
    additions = o[o[:, 6] == 901]
    check(len(additions) == 1 and additions[0, 0] == 48 and additions[0, 1] == 47,
          '初回後30秒と支持15秒を経た次原行で一度だけ3枚追撃', checks)
    check(additions[0, 4] == 3 and additions[0, 5] == 107., '追撃価格は初回価格へ遡らない', checks)
    d['qok'][48:51] = False
    o = run_case(d)
    add = o[o[:, 6] == 901][0]
    check(add[0] == 51 and add[1] == 47, '不正常原行を飛ばして次正常原行へ追撃', checks)
    d['qok'][:] = True; d['market'][38, 4] = 0.
    o = run_case(d)
    check(o[o[:, 6] == 901][0, 0] == 55, '支持中断で継続時計をリセット', checks)
    d['market'][:, 4] = .3; d['market'][:, 8] = d['times'][2]
    check(not np.any(run_case(d)[:, 6] == 901), '初回以前の相手観測だけでは追撃不可', checks)

    # ----------------------------------------
    # 独立停止は追加玉だけを閉じ、元玉の出口通知を動かさない。
    d = fixture(); d['bid'][3:50] = 106.; d['ask'][3:50] = 107.
    d['bid'][50:] = 94.; d['ask'][50:] = 95.; d['original'][-1, 5] = 94.
    o = run_case(d)
    stops = o[o[:, 6] == 902]
    check(len(stops) == 1 and stops[0, 0] == 51 and stops[0, 1] == 50 and stops[0, 4] == 3,
          '追加の0.5R逆行停止は次正常原行で3枚だけ返済', checks)
    check(o[-1, 0] == 70 and o[-1, 4] == 2 and o[-1, 8] == 0,
          '追加損切り後も初期2枚の元出口と再参加時計を維持', checks)
    check(np.count_nonzero(o[:, 6] == 901) == 1, '追加損切り後の再追加は禁止', checks)
    a = run137.account(o, d['times'], d['bid'], d['ask'], '人工', '2000-01-01_Night')
    check((a['gross'], a['fees'], a['net']) == independent_cash(o), '追加と初期脚の現金会計が親会計と一致', checks)

    d = fixture(); d['bid'][3:] = 106.; d['ask'][3:] = 107.
    d['original'] = np.array([[2,1,0,1,10,100,10,1],[48,47,0,-1,5,106,11,0],[70,69,0,-1,5,106,12,0]],dtype=float)
    o = run_case(d)
    check(not np.any(o[:,6] == 901), '追加予約の執行行で元部分返済が来れば取消', checks)

    # ----------------------------------------
    # 将来価格・将来通知・将来支持を置換しても接頭注文を変えない。
    d = fixture(); d['bid'][3:] = 106.; d['ask'][3:] = 107.; d['original'][-1, 5] = 106.
    original = run_case(d)
    for cut in (5, 31, 46, 48, 55):
        e = {k:v.copy() for k,v in d.items()}
        e['bid'][cut+1:] = 200.; e['ask'][cut+1:] = 201.
        e['market'][cut+1:, 4:8] = -.5; e['phase'][cut+1:] = 9
        e['original'][-1, 5] = 200.
        changed = run_case(e)
        check(np.array_equal(original[original[:,0] <= cut], changed[changed[:,0] <= cut]),
              f'未来置換後も原行{cut}までの注文不変', checks)
    py = run_case(d, python=True)
    check(np.array_equal(py, original), 'JITと非JITの全人工注文一致', checks)

    # ----------------------------------------
    # 売りの鏡像、主と補完の合算上限、時間帯少量化を検査する。
    e = {k:v.copy() for k,v in d.items()}
    e['bid'] = 300.-d['ask']; e['ask'] = 300.-d['bid']
    e['market'][:,4:8] *= -1.; e['original'][:,3] *= -1.; e['original'][:,5] = 300.-d['original'][:,5]
    sold = run_case(e)
    check(np.array_equal(original[:,[0,1,2,4,6,7,8,9]],sold[:,[0,1,2,4,6,7,8,9]]) and
          np.array_equal(original[:,3],-sold[:,3]) and np.array_equal(original[:,5],300.-sold[:,5]),
          '買い売りの鏡像対称', checks)
    q = dict(bid=d['bid'],ask=d['ask'],quote_valid=d['qok'])
    cfg = dict(initial=5,mode=0,width=0.,hold=0.,adaptive=False)
    extra = d['original'].copy(); extra[:,2] = 1
    allorders = overlay137.replay(d['times'],q,d['atr'],d['market'],d['phase'],d['original'],extra,cfg)
    a = run137.account(allorders,d['times'],d['bid'],d['ask'],'人工','2000-01-01_Day')
    check(a['max_per_side'] == 10 and len(a['parents']) == 2, '主5枚と補完5枚が同時でも上限10枚',checks)
    check((a['gross'],a['fees'],a['net']) == independent_cash(allorders), '主と補完の合算現金会計',checks)
    ct = run_case(d, adaptive=True)
    check(ct[0,4] == 5 and not np.any(ct[:,6] == 901), '強支持時の時間帯方式は最初から5枚',checks)
    d['phase'][:] = 9
    ct = run_case(d, adaptive=True)
    check(ct[0,4] == 1 and not np.any(ct[:,6] == 901), '警戒時間帯は初回1枚で追加しない',checks)

    after = {p.name: source_hash(p) for p in (HERE/'overlay137.py',HERE/'run137.py')}
    result = dict(passed=True,checks=len(checks),items=checks,sources=before,
                  unchanged_during_test=before==after,market_files_read=0,financial_replays=0,api=0,
                  limitations=['固定仮想通知の数量層でありGoのmini実状態の同値検査ではない。',
                               '追加停止幅はmax(20円,初回発注判断行の公開ATR)の0.5倍。',
                               '価格時計の接頭不変であり、未記録の壁時計受信順を証明しない。'])
    (HERE/'audit_overlay137.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,checks=len(checks),unchanged_during_test=before==after),ensure_ascii=False))


if __name__ == '__main__':
    main()
