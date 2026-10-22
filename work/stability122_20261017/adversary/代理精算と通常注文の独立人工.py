"""市場を読まず、途中利確停止と代理終値会計を独立に検査する。"""

from decimal import Decimal, ROUND_FLOOR
import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
ENGINE = BASE/'engine122.py'
CHECKS = []


def sha(path: Path) -> str:
    """
    機能: SOURCEだけからSHA256を求める。
    引数: path(Path)は小SOURCE。
    返り値: strは指紋。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(ok, name: str) -> None:
    """
    機能: 人工の独立期待を記録して不一致を停止する。
    引数: ok(bool)、name(str)は命題。
    返り値: None。
    """
    assert bool(ok), name
    CHECKS.append(name)


def fixture(last, times=None, bid=None, ask=None, target=900., cap=10) -> tuple:
    """
    機能: 実価格と無関係な人工気配・固定設定を組み立てる。
    引数: last/times/bid/ask(配列またはNone)、target(float)、cap(int)。
    返り値: tuple[dict,dict]は五気配列と設定。
    """
    x = np.asarray(last, dtype=float)
    t = np.arange(len(x), dtype=float) if times is None else np.asarray(times, dtype=float)
    b = x.copy() if bid is None else np.asarray(bid, dtype=float)
    a = b+.5 if ask is None else np.asarray(ask, dtype=float)
    quotes = dict(row=np.arange(len(x), dtype=np.int64), time=t, last=x, bid=b, ask=a)
    setting = dict(cap=cap, multiplier=1000., fee=41.8, observed_tick=.5,
                   session_start=0., entry_end=400., close_time=500., session_end=target)
    return quotes, setting


def account(output: tuple, quotes: dict, setting: dict, label: str) -> None:
    """
    機能: 実新規注文と代理精算だけから全UID損益をDecimal費用で独立計算する。
    引数: output(tuple)、quotes/setting(dict)、label(str)。
    返り値: None。約定を偽造せず代理前の在庫と代理後会計を分けて検査する。
    """
    orders, lots, curve, summary, proxy, context = output
    fee = int(Decimal(str(setting['fee'])).to_integral_value(rounding=ROUND_FLOOR))
    check(context['measured'], label+':代理観測資格あり')
    check(len(orders) == len(proxy) and not len(lots), label+':全実新規一枚と代理完結一対一')
    check(np.all(orders[:, 1] == 1), label+':代理返済を通常注文に混ぜない')
    check(len(set(proxy[:, 0])) == len(proxy), label+':代理UID重複なし')
    gross = profit = loss = 0.
    i = int(np.flatnonzero(quotes['row'] == context['reference_row'])[0])
    for entry, close in zip(orders, proxy):
        side = int(entry[2])
        xp = quotes['bid'][i] if side == 1 else quotes['ask'][i]
        g = side*(xp-entry[7])*setting['multiplier']
        net = g-2*fee
        check(close[0] == entry[0] and close[1] == side and close[6] == entry[7],
              label+':元UID方向建値保持')
        check(close[9] == xp and close[10] == g and close[11] == 2*fee and close[12] == net,
              label+':返済側BBOと往復手数料floor')
        check(close[7] == context['reference_row'] and close[8] == context['reference_time']
              and close[13] == setting['session_end'], label+':原観測と予定引けを分離')
        gross += g
        profit += max(net, 0.)
        loss += max(-net, 0.)
    expected = gross-2*fee*len(proxy)
    check(summary['net'] == summary['cash'] == profit-loss == expected,
          label+':代理現金と全玉純損益の独立合計')
    check(summary['fees'] == 2*fee*len(proxy) and summary['profit'] == profit
          and summary['loss'] == loss, label+':総費用と総利益総損失')
    check(summary['unclosed'] == 0 and context['base_unclosed'] == len(proxy),
          label+':代理前残玉と代理後の清算を区別')
    check(curve[-1, 5]+curve[-1, 6] == len(proxy), label+':観測curve在庫を過去に書換えない')
    check(curve[-1, 2] == summary['net'] and context['terminal_event']['equity'] == expected,
          label+':元清算時価と代理終了の一致')


def main() -> dict:
    """
    機能: 金融前の少数人工で入口・費用・観測終端・ロックを反証する。
    引数: なし。
    返り値: dictは人工だけの独立証跡。
    """
    beginning = sha(ENGINE)
    spec = importlib.util.spec_from_file_location('adversary_terminal122', ENGINE)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    source = {str(p.relative_to(ROOT)).replace('\\', '/'): sha(p)
              for p in (ENGINE, Path(engine.BASE.__file__))}
    cases = 0

    # ----------------------------------------
    # 単一実玉のBBO清算と、途中利益返済が一度もないこと。
    q, s = fixture([4000,4003,4003,4015,4015,4005,4005,4005],
                   times=[0,1,2,3,4,5,600,601])
    s['entry_end'] = 3.
    proxy = engine.evaluate(q,s,'CLOSE_PROXY')
    account(proxy,q,s,'途中利益を保持')
    check(len(proxy[0]) == 1 and proxy[4][0,12] == 1418., '高値から十pt戻っても途中利確しない')
    early = engine.evaluate(q,s,'EARLY')
    check(np.array_equal(proxy[0],early[0][early[0][:,1]==1]), '引け代理と早期通常返済の入口exact一致')
    check(len(early[1]) == 1 and early[1][0,14] == 9
          and early[0][-1,3] == 6 and early[0][-1,4] == 7, 'EARLYは元時刻判断後の次正常原行返済')
    check(not len(early[4]) and 'terminal_event' not in early[5], '通常返済に代理玉を足さない')
    cases += 2

    # ----------------------------------------
    # 同じ入口を使い、終端の上昇と下落が逆向きの純損益へ効く。
    directional = []
    for terminal in (4010.,3990.):
        q,s = fixture([4000,4003,4003,terminal], times=[0,1,2,600])
        s['entry_end'] = 3.
        out = engine.evaluate(q,s,'CLOSE_PROXY')
        account(out,q,s,'終端の方向反応')
        directional.append(out)
        cases += 1
    check(np.array_equal(directional[0][0],directional[1][0]), '終端将来値で入口が変わらない')
    check(directional[0][3]['net'] > 0 > directional[1][3]['net'], '終端の価格方向と純損益符号')

    # ----------------------------------------
    # 直前六分境界は包含、361秒前は測定不可で利益を捏造しない。
    q,s = fixture([4000,4003,4003,4005], times=[0,1,2,540])
    s['entry_end'] = 3.
    edge = engine.evaluate(q,s,'CLOSE_PROXY')
    account(edge,q,s,'六分境界')
    check(edge[5]['age_seconds'] == 360 and edge[5]['approximation'], '360秒前を明示代理として許容')
    q['time'][-1] = 539.
    stale = engine.evaluate(q,s,'CLOSE_PROXY')
    check(stale[5]['measured'] is False and stale[3]['net'] is None
          and stale[3]['profit'] is None and len(stale[4]) == 0
          and stale[3]['unclosed'] == 1, '361秒前は未測定・実残玉を保持し勝ちにしない')
    cases += 2

    # ----------------------------------------
    # 未来の行や不正行を終端へ救済しない。LastをBBOに置換しない。
    q,s = fixture([4000,4003,4003,4056,9999,9999],
                   times=[0,1,2,600,601,901],
                   bid=[4000,4003,4003,4058.5,np.nan,9999])
    s['entry_end'] = 3.
    out = engine.evaluate(q,s,'CLOSE_PROXY')
    account(out,q,s,'実観測終端選択')
    check(out[5]['reference_row'] == 3 and out[5]['reference_time'] == 600,
          '最後の不正行や予定時刻後の未来行へ差替えない')
    check(out[5]['reference_last'] == 4056 and out[4][0,9] == 4058.5
          and out[3]['net'] == 54918., '9/24末尾と同じLast4056とbid4058.5を混同しない')
    check(out[5]['last_price_reference_net'] == 52418., 'Last清算参考は別値として残す')
    cases += 1

    # ----------------------------------------
    # 両側10枚のロックは、価格上昇・下落から利益を生まない。
    staircase = [4000.]
    for value in range(4003,4031,3):
        staircase.extend([float(value),float(value)])
    staircase.extend([4000.,4000.])
    locked = []
    for terminal in (3980.,4060.):
        path = staircase+[terminal]
        q,s = fixture(path, times=list(range(len(path)-1))+[600.])
        out = engine.evaluate(q,s,'CLOSE_PROXY')
        account(out,q,s,'両方向十枚ロック')
        check(out[3]['max_long'] == out[3]['max_short'] == 10
              and len(out[4]) == 20, '片側十枚で両方向純枚数ゼロ')
        check(out[3]['fees'] == 1640., '二十枚の新規返済四十注文の費用')
        locked.append(out)
        cases += 1
    check(np.array_equal(locked[0][0],locked[1][0]), '両側cap後の終端値で実入口が変わらない')
    check(locked[0][3]['net'] == locked[1][3]['net'], '純枚数ゼロは平行価格変化に中立')

    # ----------------------------------------
    # 無取引は代理終了が可能でも利益にも取引勝ちにも加えない。
    q,s = fixture([4000.,4000.],times=[0,600])
    empty = engine.evaluate(q,s,'CLOSE_PROXY')
    account(empty,q,s,'無取引')
    check(empty[3]['net'] == 0 and empty[3]['wins'] == 0
          and empty[3]['closed_lots'] == 0, '無取引ゼロを勝ちにしない')
    cases += 1
    check(sha(ENGINE) == beginning, '経済SOURCE開始終端不変')
    return dict(passed=True,engine_sha256=beginning,source_SHA256=source,
                inspections=len(CHECKS),checks=CHECKS,synthetic_accounts=cases,
                scope='完全人工のTOPIX一枚料・固定3/6/9pt新規・途中返済なし・代理終了の比較。',
                oracle='手書きの閾値・原行期待と、実注文だけからDecimal料金floor/UID/返済側BBO純損益を独立に計算。',
                元市場追加読取=0, 保存実NPZ追加読取=0, 金融再生=0, API=0, 台帳変更=0)


if __name__ == '__main__':
    target = HERE/'途中利確なしと六分代理精算の独立人工.json'
    assert not target.exists()
    try:
        result = main()
    except Exception as exc:
        (HERE/'独立人工False.json').write_text(json.dumps(
            dict(passed=False,error=repr(exc),checks=CHECKS,engine_sha256=sha(ENGINE)),
            ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,engine_sha256=result['engine_sha256'],
                          inspections=result['inspections'],synthetic_accounts=result['synthetic_accounts'],
                          proof_sha256=sha(target)),ensure_ascii=False))
