"""実市場を再生せず、単一位置のR注文順序と料金台帳を小人工で独立検算する。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import numpy as np

from range_math import order_fee


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/range_price'


def digest(path: Path) -> str:
    """
    機能: sourceと所有複製の同内容を検証する。
    引数: path(Path)は小source。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str, path: Path):
    """
    機能: 金融fixtureだけに使うsourceを隔離名でimportする。
    引数: name(str)、path(Path)は私有複製又は純接口。
    返り値: moduleは検査対象。実入力を読み込まない。
    """
    spec = importlib.util.spec_from_file_location(name,path); value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value; spec.loader.exec_module(value); return value


def fixture(symbol: str, side: int, mode: int, label: str) -> tuple[dict,dict,dict]:
    """
    機能: 待機・同row競合・約定gap・予約保持を原行順に定義した小人工を作る。
    引数: symbol(str)、side(int)、mode(int)はmarket1/limit2、label(str)は経路。
    返り値: tuple[dict,dict,dict]はprepared、normal_case、config。
    """
    tick = .5 if symbol == 'TOPIX' else 10.; n = 13; base = 1000*tick
    times = np.arange(n,dtype=float); bid = np.full(n,base); ask = bid+tick
    target,stop,line = base+5*tick,base-2*tick,base
    pending_trend = np.zeros(n,bool); quiet = np.zeros(n,bool); quiet_start = np.full(n,np.nan)
    valid = np.ones(n,bool)
    if mode == 1:
        bid[3:] = base+5*tick; bid[4:] = base+4*tick
    else:
        bid[2] = base+tick; bid[3] = base-tick; bid[4:] = base+5*tick; bid[5:] = base+4*tick
    ask = bid+tick
    if label == '同行TREND到達': pending_trend[3] = True
    if label == '未到達TREND取消': pending_trend[2] = True
    if label == '未到達stop取消': bid[2],ask[2] = stop,base+2*tick
    if label in ('marketstopgap','limitstopgap'): bid[2],ask[2] = base-4*tick,base-3*tick
    if label == 'markettargetgap': bid[2],ask[2] = base+6*tick,base+7*tick
    if label == 'market次正常': valid[2] = False
    if label == '返済次正常': valid[4:6] = False
    if label == '保有TRENDだけ':
        target = base+100*tick; pending_trend[3:10] = True
        bid[:] = base; ask[:] = base+tick
    if label == 'J同行取消':
        bid[2],ask[2] = base-tick,base; quiet[2] = True; quiet_start[2] = 2.
    if label == 'cut同行取消':
        bid[:] = base+tick; ask[:] = base+2*tick
        bid[1],ask[1] = base,base+tick; bid[10],ask[10] = base-tick,base
    if side < 0:
        bid,ask = 2*base-ask,2*base-bid
        target,stop,line = 2*base-target,2*base-stop,2*base-line
    record = dict(人工素材=True,symbol=symbol,tick=tick,start=0.,end=13.,limit=12.,time_s=times,
        seq=np.arange(100,113,dtype=np.int64),bid=bid,ask=ask,price=(bid+ask)/2,
        quote_valid=valid,price_valid=np.ones(n,bool))
    event = np.zeros(n,np.int8); event[1] = side
    family = np.zeros(n,np.int8); family[1] = 2
    supports = np.full(n,np.nan); supports[1] = stop
    stops = supports.copy(); targets = np.full(n,np.nan); targets[1] = target
    limits = np.full(n,np.nan); limits[1] = line; modes = np.zeros(n,np.int8); modes[1] = mode
    metadata = dict(row=1,normal_row=1,raw_row=1,raw_seq=101,side=side,support_price=stop,
        selected_support_roots=[],episode=('R_PRICE',side,101),reference_kind='純価格範囲外停止')
    normal = dict(entry_id='私有R人工',event=event,support_price=supports,entry_quality=np.ones(n,bool),
        entry_reset=np.zeros(n,bool),execution_to_raw_index=np.arange(n,dtype=np.int64),decisions=[metadata],
        entry_families=family,target_prices=targets,entry_stop_prices=stops,entry_limit_prices=limits,
        entry_modes=modes,range_pending_trend=pending_trend,quiet=quiet,quiet_start_s=quiet_start)
    config = dict(id='私有R人工',support_ticks=4,initial_stop_fraction=.001,profit_trail=False,
        r_profit=False,reentry_band=False,session_brake=False,session_budget_multiple=1.,
        cooldown_seconds=30.,start_offset=0.,cut_offset=2.,force_offset=1.)
    prepared = dict(record=record,reference_open=base,signal=dict(trend_width=5*tick))
    return prepared,normal,config


def economy(record: dict, output: dict) -> int:
    """
    機能: engine会計に依存せず注文ごとのcash、料金、保有、清算時価を独立再構成する。
    引数: record/output(dict)は人工気配と実注文件数。
    返り値: intは検査行数。予約を保有や利益へ数えない。
    """
    symbol = record['symbol']; multiplier = 1000 if symbol == 'TOPIX' else 10
    fee_text = '41.8' if symbol == 'TOPIX' else '11'; cash = 0.; held = 0; reserve = 0; cursor = 0
    lastbid = lastask = None; orders = output['orders']; n = len(record['seq']); checks = 0
    for row in range(n):
        qok = bool(record['quote_valid'][row] and np.isfinite(record['time_s'][row]) and
            np.isfinite(record['bid'][row]) and np.isfinite(record['ask'][row]) and 0 < record['bid'][row] < record['ask'][row])
        if qok: lastbid,lastask = record['bid'][row],record['ask'][row]
        while cursor < len(orders) and orders[cursor,0] == row:
            o = orders[cursor]; action,qty = int(o[4]),int(o[5]); price = o[6]; new = bool(o[7]); fee = order_fee(qty,fee_text)
            assert qok and row > int(o[1]); assert price == record['ask' if action > 0 else 'bid'][row]
            assert o[9] == fee and price/record['tick'] == round(price/record['tick'])
            if new: assert held == 0; reserve = order_fee(qty,fee_text)
            else: assert held == -action*qty; reserve = 0
            cash -= action*qty*price*multiplier+fee; held += action*qty; cursor += 1; checks += 4
        expected = cash+held*(lastbid if held > 0 else lastask)*multiplier-reserve if held else cash
        assert abs(expected-output['curve'][row]) <= 1e-7
        assert output['target_trace'][row,0] == max(held,0) and output['target_trace'][row,1] == max(-held,0)
        assert abs(output['source_curve'][row].sum()-expected) <= 1e-7
        assert output['target_trace'][row,2:4].max() <= (10 if symbol == 'TOPIX' else 20)
        checks += 4
    for trade in output['trades']:
        gross = trade[4]*trade[5]*(trade[7]-trade[6])*multiplier
        assert abs(trade[10]-gross) <= 1e-7 and abs(trade[11]-(gross-trade[8]-trade[9])) <= 1e-7
        checks += 2
    assert cursor == len(orders); return checks


def cut(prepared: dict, normal: dict, size: int) -> tuple[dict,dict]:
    """
    機能: 当時の原行接頭だけを渡し、将来の場末・目標・気配を含めない。
    引数: prepared/normal(dict)、size(int)は受領行数。
    返り値: tuple[dict,dict]は人工接頭入力。既知予定limitは保持する。
    """
    p = deepcopy(prepared); n = deepcopy(normal)
    for key,value in p['record'].items():
        if isinstance(value,np.ndarray): p['record'][key] = value[:size].copy()
    for key,value in n.items():
        if isinstance(value,np.ndarray): n[key] = value[:size].copy()
    n['decisions'] = [d for d in n['decisions'] if d['row'] < size]
    return p,n


def main() -> None:
    """
    機能: 最終sourceの同内容コピーを私有域で人工再生し、順序と料金を確かめる。
    引数: なし。正式input・正式financeを読まない。
    返り値: Noneは独立小人工proof。既存sourceへ書き込まない。
    """
    paths = [SOURCE/'engine/core.py',SOURCE/'interface.py']; before = {str(p.relative_to(ROOT)):digest(p) for p in paths}
    snapshot = HERE/'range_engine_snapshot.py'; snapshot.write_bytes(paths[0].read_bytes()); assert digest(snapshot) == before[str(paths[0].relative_to(ROOT))]
    engine = load('独立R執行複製',snapshot); interface = load('独立R接口',paths[1])
    interface.module = lambda name,path: engine
    checks = {}; runs = 0
    def counted(name: str, count: int = 1) -> None:
        """
        機能: 検査件数を用途で分ける。
        引数: name(str)、count(int)は検査種と件数。
        返り値: Noneは私有集計を更新する。
        """
        checks[name] = checks.get(name,0)+count
    cases = [(1,'基準'),(2,'基準'),(2,'同行TREND到達'),(2,'未到達TREND取消'),(2,'未到達stop取消'),
        (1,'marketstopgap'),(2,'limitstopgap'),(1,'markettargetgap'),(1,'market次正常'),(1,'返済次正常'),
        (1,'保有TRENDだけ'),(2,'J同行取消'),(2,'cut同行取消')]
    for symbol in ('TOPIX','NK225'):
        qty = 5 if symbol == 'TOPIX' else 10
        for side in (-1,1):
            for mode,label in cases:
                p,n,c = fixture(symbol,side,mode,label); result = interface.play(p,n,c,quantity=qty,python=True); runs += 1
                counted('注文cash料金玉全行curveと保有',economy(p['record'],result))
                assert not result['target_trace'][-1].any(); counted('終端flatと予約解消')
                entries = result['orders'][result['orders'][:,7] == 1]
                if label in ('未到達TREND取消','未到達stop取消','J同行取消','cut同行取消'):
                    assert not len(entries) and not len(result['trades']) and not result['orders'].any(); counted('未約定取消と未来非復活')
                else:
                    assert len(entries) == 1 and len(result['trades']) == 1
                    entryrow = int(entries[0,0]); exitrow = int(result['trades'][0,3]); assert entryrow > 1 and exitrow > entryrow
                    assert np.all(result['source_curve'][:,0] == 0); counted('R源と当行新規返済禁止')
                    if label == '同行TREND到達': assert entryrow == 3 and exitrow == 5; counted('live到達先でTREND架空取消なし')
                    if label in ('marketstopgap','limitstopgap'):
                        assert entryrow == 2 and exitrow == 3 and result['trades'][0,13] == 11; counted('実gap入口保持とstop次quote返済')
                    if label == 'markettargetgap':
                        assert entryrow == 2 and exitrow == 3 and result['trades'][0,11] < 0; counted('予定RRの実fill不保証を損失も保存')
                    if label == 'market次正常': assert entryrow == 3; counted('正常気配まで予約保持')
                    if label == '返済次正常': assert exitrow == 6; counted('返済予約を正常気配まで保持')
                    if label == '保有TRENDだけ': assert exitrow == 11 and result['trades'][0,13] == 6; counted('保有mode非退出と既知場末timer')
                    size = entryrow+1; prefixp,prefixn = cut(p,n,size)
                    prefix = interface.play(prefixp,prefixn,c,quantity=qty,finish=False,python=True)
                    assert not len(prefix['trades']) and prefix['target_trace'][-1,:2].sum() == qty
                    np.testing.assert_array_equal(prefix['orders'],result['orders'][result['orders'][:,0] < size])
                    np.testing.assert_array_equal(prefix['curve'],result['curve'][:size]); counted('保有接頭に未来清算なし')
                try:
                    interface.play(p,n,c,quantity=(11 if symbol == 'TOPIX' else 21),python=True)
                except AssertionError: counted('片方向cap超過拒否')
                else: raise AssertionError('上限超過を拒否しなかった')
    assert before == {str(p.relative_to(ROOT)):digest(p) for p in paths}
    output = dict(全合格=True,scope='最終R_PRICE注文sourceの小人工のみ',検査件数=checks,人工口座=runs,
        source_SHA256=before,私有複製SHA256=digest(snapshot),開始終端source一致=True,
        正式金融結果読取=0,正式金融再生=0,原本NPZAPI=0,
        私有実行='source完全同内容複製を私有JIT域で使用。接口module解決だけ検査process内で当該複製へ結ぶ。既存source変更なし。',
        留保='各quoteの全枚約定は代理。実指値queueや小口商品の別板は再現していない。',
        レビューsource_SHA256=digest(Path(__file__)))
    (HERE/'range_注文順序と実gap及び料金の独立人工.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('R注文独立人工',runs,'口座',sum(checks.values()),'検査合格',flush=True)


if __name__ == '__main__':
    main()
