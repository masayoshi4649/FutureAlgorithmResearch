"""本物の新候補生成から四引数会計と根の保存・比較部まで、小人工だけで接続する。"""

from copy import deepcopy
import inspect
import json
from pathlib import Path
import sys

import numpy as np

from range_input_check import fixture, digest
from range_engine_check import load, economy


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/range_price'


def packet(symbol: str, side: int, scene: str) -> dict:
    """
    機能: 正しい六点RANGE・範囲内反発・予定RRを持つ、全候補source用の人工場を作る。
    引数: symbol(str)、side(int)、scene(str)は約定gap又は指値の競合。
    返り値: dictはprepared/cases/measured/quiet。旧金融結果を読まない。
    """
    import features
    raws,records,cases = fixture(symbol,side)
    other = next(s for s in records if s != symbol)
    for s in records:
        tick = records[s]['tick']; raw = raws[s]; record = records[s]
        # ----------------------------------------
        # 差し替えるのは当該人工の将来行だけ。初回判断row7の六点価格とRRを保持する。
        positive = np.array([101.,111.,101.,111.,105.,102.,100.,101.,102.,106.,105.,105.,105.])
        times = np.array([0.,60.,120.,180.,240.,300.,300.,300.,300.,310.,320.,1140.,1200.])
        if s == other: times[5:9] = 299.
        if scene in ('LIMIT','LIMIT_TREND_RACE','LIMIT_TREND_CANCEL'):
            positive[9] = 100.; positive[10] = 106.
        if scene == 'MARKET_TARGET_GAP': positive[8] = 107.; positive[9] = 105.
        if scene == 'MARKET_STOP_GAP': positive[8] = 98.; positive[9] = 98.
        if scene in ('LIMIT_TREND_RACE','LIMIT_TREND_CANCEL'):
            times[9] = 360. if s == symbol else 359.; times[10] = 361. if s == symbol else 360.
            positive[10] = 104.
        if scene == 'LIMIT_TREND_CANCEL': positive[9] = 102.; positive[10] = 100.
        midpoint = (1000.+positive+.5)*tick
        if side < 0: midpoint = 2400*tick-midpoint
        bid,ask = midpoint-tick/2,midpoint+tick/2; seq = np.arange(200,213,dtype=np.int64); mapping = np.arange(13,dtype=np.int64)
        raw.update(raw_seq=seq,price_time_s=times.copy(),bid=bid.copy(),ask=ask.copy(),execution_to_raw_index=mapping)
        record.update(seq=seq,time_s=times.copy(),bid=bid,ask=ask,price=midpoint,
            quote_valid=np.ones(13,bool),price_valid=np.ones(13,bool),limit=1200.,end=1201.)
        cases[s] = dict(event=np.zeros(13,np.int8),support_price=np.full(13,np.nan),entry_quality=np.zeros(13,bool),
            entry_reset=np.ones(13,bool),execution_to_raw_index=mapping,decisions=[])
    measured = {s:features.build(raws,records,s) for s in records}
    prepared = {s:dict(record=records[s],reference_open=float(records[s]['price'][0]),signal=dict(trend_width=5*records[s]['tick'])) for s in records}
    return dict(session='2000-01-03_Day',prepared=prepared,cases={s:dict(C_OWN=cases[s]) for s in records},measured=measured,
        quiet={s:dict(active=np.zeros(13,bool),start_s=np.full(13,np.nan),windows=[]) for s in records})


def expand(item: dict, n: int) -> np.ndarray:
    """
    機能: 根の変化行保存を独立した逐次保持で全行へ展開する。
    引数: item(dict)はrows/values、n(int)は元の正常行数。
    返り値: ndarrayは圧縮前と照合する再構成値。
    """
    assert len(item['rows']) and item['rows'][0] == 0
    answer = []; cursor = 0
    for row in range(n):
        while cursor+1 < len(item['rows']) and item['rows'][cursor+1] <= row: cursor += 1
        answer.append(item['values'][cursor].copy())
    return np.array(answer)


def main() -> None:
    """
    機能: 登録済みsourceを変更せず、実候補・注文・会計・根保存の契約を結合検査する。
    引数: なし。正式run/bindは呼ばず、実金融値を使わない。
    返り値: Noneは最終source束縛の合同人工証跡。JITは私有複製域だけ。
    """
    sys.path.insert(0,str(SOURCE))
    import selection
    import catalog
    import interface
    import runner
    paths = [SOURCE/name for name in ('common.py','catalog.py','features.py','selection.py','prepare.py','data.py','interface.py','runner.py')]
    paths += [SOURCE/'engine/core.py',SOURCE/'engine/accounting.py',ROOT/'work/wave_v106/regime_price/features.py',
        ROOT/'work/wave_v102/accounting.py',ROOT/'work/wave_v106/accounting.py']
    before = {str(path.relative_to(ROOT)):digest(path) for path in paths}
    assert len(inspect.signature(load('独立最終四引数会計',SOURCE/'engine/accounting.py').inspect).parameters) == 4
    accounting = sys.modules['独立最終四引数会計']
    snapshot = HERE/'range_joint_engine_snapshot.py'; snapshot.write_bytes((SOURCE/'engine/core.py').read_bytes())
    assert digest(snapshot) == digest(SOURCE/'engine/core.py'); engine = load('独立合同R執行複製',snapshot)
    interface.module = lambda name,path: engine
    counts = {}; joint = 0
    def count(label: str, amount: int = 1) -> None:
        """
        機能: 合同検査の件数を用途ごとに記録する。
        引数: label(str)、amount(int)は名称と件数。
        返り値: Noneは私有検査計数を更新する。
        """
        counts[label] = counts.get(label,0)+amount
    for symbol in ('TOPIX','NK225'):
        qty = 5 if symbol == 'TOPIX' else 10
        for side in (-1,1):
            for scene in ('MARKET','MARKET_TARGET_GAP','MARKET_STOP_GAP','LIMIT','LIMIT_TREND_RACE','LIMIT_TREND_CANCEL'):
                p = packet(symbol,side,scene); mode = 'LIMIT' if scene.startswith('LIMIT') else 'MARKET'
                config = next(c for c in catalog.catalog() if c['mode']=='R_ONLY' and c['range_er']==.2 and c['margin_ticks']==(2 if mode=='LIMIT' else 1) and c['range_entry']==mode)
                normal = selection.build(p,symbol,config); assert normal['event'][7] == side and normal['entry_families'][7] == 2
                original = deepcopy(normal['decisions'][0]); assert original['fee_included_ratio'] >= 1.25 and original['stop_clearance_ticks'] >= 2
                prepared = p['prepared'][symbol]; prepared['record']['人工素材'] = True
                output = interface.play(prepared,normal,config,quantity=qty,python=True)
                result = accounting.inspect((p['session'],symbol),prepared['record'],output,normal)
                count('本物の候補から四引数会計への接口'); joint += 1
                count('独立cash料金全行と原quote',economy(prepared['record'],output))
                assert len(output['orders']) == 0 if scene == 'LIMIT_TREND_CANCEL' else len(output['trades']) == 1
                if scene == 'MARKET_TARGET_GAP': assert result['net'] < 0; count('予定RR成立後の実損失保持')
                if scene == 'LIMIT_TREND_RACE':
                    entry = output['orders'][output['orders'][:,7] == 1][0]
                    assert normal['range_pending_trend'][int(entry[0])] and int(entry[0]) == 9
                    assert output['trades'][0,3] == 11; count('到達同行TREND先fillと保有非退出')
                if scene == 'LIMIT_TREND_CANCEL': assert result['campaigns'] == 0 and result['net'] == 0; count('取消非活動を勝ちにしない')
                saved = runner.stored(output,normal,prepared['record'])
                for key in ('curve','source_curve','target_trace'):
                    np.testing.assert_array_equal(expand(saved[key],saved['row_count']),output[key]); count('根の疎会計から全行exact復元')
                assert saved['selection_diagnostics'] == normal['decisions'] and normal['decisions'][0] == original
                mapping = runner.DIFFERENCE.trade_map(output,prepared['record'])
                delta = runner.DIFFERENCE.contribution({},mapping)
                assert abs(delta['収支変化']-result['net']) <= 1e-7 and delta['失った基準利益'] == 0
                count('取引対応と寄与式の接続')
            # ----------------------------------------
            # 保存旧金融の代わりに、同じC物理注文を人工全量と半量へ実行し派生則だけ確かめる。
            p = packet(symbol,side,'MARKET'); config = next(c for c in catalog.catalog() if c['mode']=='AUTO' and c['range_er']==.2 and c['margin_ticks']==1 and c['range_entry']=='MARKET')
            normal = selection.build(p,symbol,config); row = 7; support = float(p['prepared'][symbol]['record']['bid' if side > 0 else 'ask'][row])
            normal['entry_families'][row] = 1; normal['support_price'][row] = support
            normal['decisions'] = [dict(row=row,normal_row=row,raw_row=row,raw_seq=207,side=side,support_price=support,
                selected_support_roots=[dict(anchor_raw_seq=203,support_price=support)],episode=('C人工',side,207))]
            p['prepared'][symbol]['record']['人工素材'] = True
            full = interface.play(p['prepared'][symbol],normal,config,quantity=2*qty,python=True)
            half = interface.play(p['prepared'][symbol],normal,config,quantity=qty,python=True)
            expected = runner.DIFFERENCE.trade_map(half,p['prepared'][symbol]['record'])
            actual = runner.scaled_map(full,p['prepared'][symbol]['record']); assert actual == expected
            count('根C対照の整数half量とfee2倍及びmap一致')
            tampered = deepcopy(full); tampered['orders'][0,9] += 1
            try: runner.scaled_map(tampered,p['prepared'][symbol]['record'])
            except AssertionError: count('半量へ写せない料金を拒否')
            else: raise AssertionError('料金倍率不一致を拒否しない')
    assert before == {str(path.relative_to(ROOT)):digest(path) for path in paths}
    output = dict(全合格=True,scope='最終四引数会計とroot runnerの純人工結合・登録済み実市場金融未実行',
        検査件数=counts,検査合計=sum(counts.values()),合同人工口座=joint,source_SHA256=before,
        開始終端source一致=True,private_JIT='work/wave_v106/price_review/jit',
        正式金融結果読取=0,正式金融再生=0,正式input旧cache読取=0,原本NPZAPI=0,
        限界='この人工は候補・約定・会計の接続検査。市場での予測改善や収益の証拠ではない。C半量の検査値も人工であり保存対照の収益を使っていない。',
        レビューsource_SHA256=digest(Path(__file__)),私有完全複製SHA256=digest(snapshot))
    (HERE/'range_最終四引数会計と根実行部の合同人工.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print('最終合同',joint,'口座',sum(counts.values()),'検査合格',flush=True)


if __name__ == '__main__':
    main()
