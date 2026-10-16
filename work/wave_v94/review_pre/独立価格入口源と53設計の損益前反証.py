"""人工価格と原板だけで、現在入口、源分離、中心利確の反例を独立検査する。"""

from copy import deepcopy
import ast
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import sys
from types import SimpleNamespace

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
os.environ['NUMBA_CACHE_DIR'] = str(HERE / 'jit')
PARTS = ROOT / 'work/wave_v93/input_theory/準備と初回入口及び価格板源の独立人工反証.py'


def module(name: str, path: Path) -> object:
    """
    機能: 純部品を固有名で読み、保存場の実行器mainは呼ばない。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 前検証に使った実装及び資料の指紋を求める。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fixture(symbol: str, side: int, gap: bool) -> tuple[dict, dict]:
    """
    機能: 初回回復と正当な新準備、又は新規後中心越えgapを持つ別人工原板を作る。
    引数: symbol(str)、side(int、1又は-1)、gap(bool)。
    返り値: tuple[dict,dict]は原板と厳密過去の公開資格。実場データは使わない。
    """
    size = 45
    times = 300. + np.arange(size,dtype=float)
    anchor,tick,width,peer_anchor,peer_tick,peer_width = ((4000.,.5,5.,68000.,10.,70.) if symbol == 'TOPIX'
                                                       else (68000.,10.,70.,4000.,.5,5.))
    progress = np.zeros(size)
    progress[4:7] = -1.25
    progress[7:10] = -1.5
    progress[10:20] = -.75
    progress[24:27] = -1.25
    progress[27:30] = -1.5
    progress[30:34] = -.75
    progress[34:] = .5
    if gap:
        progress[11:] = (1. if symbol == 'TOPIX' else 20.) / width
    last = anchor + progress*width
    bid,ask = last.copy(),last+tick
    peer_mid = peer_anchor+progress*peer_width
    if side == -1:
        last = 2.*anchor-last
        bid,ask = 2.*anchor-ask,2.*anchor-bid
        peer_mid = 2.*peer_anchor-peer_mid
    valid = np.ones(size,bool)
    seq = np.arange(size,dtype=np.int64)
    record = dict(symbol=symbol,time_s=times,seq=seq,price=last,bid=bid,ask=ask,
                  price_valid=valid.copy(),quote_valid=valid.copy(),tick=tick,start=0.,limit=600.)
    signal = dict(grid=times,mapped=seq.astype(np.int32),mode=np.full(size,2,np.int8),
                  quality=valid.copy(),reset=np.zeros(size,bool),event=np.zeros(size,np.int8),
                  trend_width=10.*width,range_width=width,current_valid=valid.copy(),
                  arm_common=np.zeros(size,np.int8),reverse_long=np.zeros(size,bool),reverse_short=np.zeros(size,bool),
                  peer_mid=peer_mid,peer_source=seq.copy(),peer_valid=valid.copy(),peer_width=peer_width,peer_tick=peer_tick,
                  own_source=seq.copy(),own_source_time=times-1.,peer_source_time=times-2.,
                  raw_range_valid=valid.copy(),raw_range_eligible=valid.copy(),raw_oldest_time=times-301.,
                  price_observable=valid.copy(),price_mode=np.full(size,2,np.int8),
                  price_own_index=seq+1000,price_peer_index=seq+2000,
                  price_own_raw_seq=seq+3000,price_peer_raw_seq=seq+4000,
                  price_own_time=times-3.,price_peer_time=times-4.,
                  price_own_valid=valid.copy(),price_peer_valid=valid.copy())
    return record,signal


def gate_cases(engine: object, configs: dict[str,dict]) -> list[dict]:
    """
    機能: 初回不合格の後に現在窓が回復しても同episodeを使い回さないと確認する。
    引数: engine(object)、configs(dict[str,dict])。
    返り値: list[dict]は両資産買売G1/G2の人工イベント。採択用損益は計算しない。
    """
    rows = []
    for symbol in ('TOPIX','NK225'):
        for side in (-1,1):
            for gate in (1,2):
                config = configs[f'I3_G{gate}_S0_T0']
                record,signal = fixture(symbol,side,False)
                if gate == 1:
                    signal['price_observable'][10] = False
                else:
                    signal['price_mode'][10] = 0
                signal['arm_common'][20] = -side
                before = pickle.dumps((record,signal),protocol=5)
                value = engine.execute(record,signal,config,finish=False)
                events = value['events']
                gates = events[events[:,3] == 27]
                np.testing.assert_array_equal(gates[:2,0],[10,30])
                np.testing.assert_array_equal(gates[:2,11],[0,1])
                entries = value['orders'][value['orders'][:,7] == 1]
                assert len(entries) == 1 and entries[0,1] == 30 and entries[0,0] == 31
                assert not np.any((events[:,3] == 1) & (events[:,0] < 30))
                assert (value['risk_state_trace'][10:20,0] == 1).all()
                source = value['price_source_trace']
                assert source[10,4] != source[10,6] and source[10,5] != source[10,7]
                assert source[10,17] == 10 and source[10,18] == 0
                assert source[30,17] == 30 and source[30,18] == 1
                assert source[10,8] < source[10,10] and source[10,9] < source[10,11]
                assert before == pickle.dumps((record,signal),protocol=5)
                rows.append({'商品':symbol,'方向':side,'入口G':gate,'最初拒否行':10,
                             '窓回復後でも同エピソード不参加':True,'共同破綻解除行':20,
                             '新準備後の次回受理行':30,'次正常気配の新規行':31,
                             '価格源及び執行源を別保存':True,'入力不変':True})
    return rows


def center_cases(engine: object, configs: dict[str,dict]) -> list[dict]:
    """
    機能: 利益側でない固定中心でもT1だけ入口を変更せず、返済netを負として扱うと確認する。
    引数: engine(object)、configs(dict[str,dict])。
    返り値: list[dict]は同新規のT0/T1人工反例。正式候補の保存場損益ではない。
    """
    cases = []
    for symbol in ('TOPIX','NK225'):
        for side in (-1,1):
            record,signal = fixture(symbol,side,True)
            target = engine.execute(record,signal,configs['I3_G1_S0_T1'],finish=False)
            widths = engine.execute(record,signal,configs['I3_G1_S0_T0'],finish=False)
            entry = target['orders'][target['orders'][:,7] == 1]
            other = widths['orders'][widths['orders'][:,7] == 1]
            np.testing.assert_array_equal(entry,other)
            assert len(entry) == 1 and entry[0,1] == 10 and entry[0,0] == 11
            trade = target['trades'][0]
            parent = target['range_parent_diagnostics'][0]
            quantity = 10 if symbol == 'TOPIX' else 20
            multiplier,fee_unit = (1000.,41.8) if symbol == 'TOPIX' else (10.,11.)
            fee = math.floor(quantity*fee_unit+1e-8)
            expected = side*(trade[7]-trade[6])*quantity*multiplier-2*fee
            assert trade[5] == quantity and trade[13] == 15 and trade[11] == expected < 0
            assert side*(parent[7]-trade[6]) < 0
            assert parent[22] == parent[7] and parent[27] == 1 and parent[28] == expected
            assert len(widths['trades']) == 0
            cases.append({'商品':symbol,'方向':side,'判断行':10,'新規行':11,'T0及びT1新規全列一致':True,
                          '新規価格':float(trade[6]),'判断時固定中心':float(parent[7]),
                          '実新規から中心が利益側':False,'中心返済判断行':int(parent[24]),
                          '次気配返済行':int(trade[3]),'返済価格':float(trade[7]),
                          '枚数':quantity,'片道料金':fee,'返済理由':15,'純損益':float(expected),
                          '計算の意味':'別人工の一親反例。保存31場又は新正式候補の成績ではない。'})
    return cases


def design_checks(catalog: object) -> dict:
    """
    機能: 全53対照が一軸差を保ち、rho及びN4が基本48へ紛れ込まないと検査する。
    引数: catalog(object)。
    返り値: dictは条件表と識別上の反証。
    """
    conditions = catalog.catalog()
    byid = {value['id']:value for value in conditions}
    assert len(conditions) == len(byid) == 53 and catalog.PRIMARY == 'I3_G1_S0_T1'
    direct = []
    for condition in conditions[:48]:
        assert condition['range_entry_max_risk_widths'] == 0 and condition['range_entry_min_center_ratio'] == 0
        assert condition['range_failure_reentry_kind'] == 'legacy'
        profile,gate,stop,target = condition['id'].split('_')
        for axis,replacement,field in ((0,'I0' if profile in ('I1','I2') else 'I2','price_lane'),
                                       (1,'G0','range_entry_context'),(2,'S0','range_stop_kind'),
                                       (3,'T0','range_target_kind')):
            if axis == 0 and profile == 'I0' or axis == 1 and gate == 'G0' or axis == 2 and stop == 'S0' or axis == 3 and target == 'T0':
                continue
            parts = [profile,gate,stop,target]
            parts[axis] = replacement
            reference = byid['_'.join(parts)]
            differences = [key for key in condition if key != 'id' and condition[key] != reference[key]]
            assert differences == [field],(condition['id'],reference['id'],differences)
            direct.append({'対象':condition['id'],'対照':reference['id'],'単独差':field})
    source = ast.parse((WORK/'engine.py').read_text(encoding='utf-8'))
    simulate = next(node for node in source.body if isinstance(node,ast.FunctionDef) and node.name=='simulate')
    accepted = next(node for node in ast.walk(simulate) if isinstance(node,ast.If) and ast.unparse(node.test)=='accepted')
    assert not any(isinstance(node,ast.If) and 'target_kind' in ast.unparse(node.test) for node in accepted.body)
    return {'条件数':53,'基本数':48,'主':catalog.PRIMARY,'単独差比較':direct,
            '基本48のrho及びN4無効':True,'T1専用の利益側中心入口フィルタなし':True}


def stability_checks() -> dict:
    """
    機能: 保存場を読まず、事前安定指標の無取引・尺度・大損・含み損の人工境界を確かめる。
    引数: なし。
    返り値: dictは人工集計の資格と論理限界。正式候補の損益ではない。
    """
    tree = ast.parse((WORK/'research.py').read_text(encoding='utf-8'))
    functions = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('stability','score')]
    assert len(functions) == 2
    namespace = {'np':np,'catalog':SimpleNamespace(SYMBOLS=('TOPIX','NK225'))}
    exec(compile(ast.Module(body=functions,type_ignores=[]),'人工用の事前評価部品','exec'),namespace)
    calculate = namespace['stability']
    cases = []
    for name,units,quantity,drawdown in (
            ('無取引を活動黒字率へ数えない',[-1.,.2,-.5,.2,None,None,None,None],10,0.),
            ('数量だけ五分の一',[-1.,.2,-.5,.2,None,None,None,None],2,0.),
            ('稀な大損',[.5,.5,.5,.5,.5,.5,.5,-5.],10,0.),
            ('小さい確定黒字だけ',[.001]*8,10,0.),
            ('確定黒字でも大きな含み損',[.001]*8,10,10.),
            ('全て無取引',[None]*8,10,0.)):
        rows,prepared = [],{}
        sessions = [f'人工場{index}' for index in range(8)]
        for symbol in ('TOPIX','NK225'):
            scale,value,first = (1,1000.,4000.) if symbol == 'TOPIX' else (2,10.,68000.)
            compare = quantity*scale*value*first*.001
            for session,unit in zip(sessions,units):
                rows.append(dict(symbol=symbol,session=session,campaigns=0 if unit is None else 1,
                                 net=0. if unit is None else unit*compare,equity_drawdown=drawdown*compare))
                prepared[session,symbol] = dict(record=dict(price=np.array([first])))
        value = calculate(rows,dict(trend_budget=0,range_budget=quantity),prepared,sessions)
        for symbol,result in value.items():
            if name == '全て無取引':
                assert result['active_sessions'] == 0 and result['no_trade_sessions'] == 8
                assert result['downside_rms_units'] == 0.
                assert result['active_downside_rms_units'] is result['positive_session_rate'] is None
            elif name in ('無取引を活動黒字率へ数えない','数量だけ五分の一'):
                assert result['active_sessions'] == result['no_trade_sessions'] == 4
                factor = quantity/10.
                assert abs(result['downside_rms_units']-factor*math.sqrt(1.25/8)) < 1e-9
                assert abs(result['active_downside_rms_units']-factor*math.sqrt(1.25/4)) < 1e-9
                assert result['positive_session_rate'] == .5
            elif name == '稀な大損':
                assert abs(result['downside_rms_units']-5./math.sqrt(8)) < 1e-9
                assert result['worst_session_loss_units'] == 5.
            else:
                assert result['downside_rms_units'] == 0 and result['positive_session_rate'] == 1.
                assert result['worst_intraday_drawdown_units'] == drawdown
        cases.append({'条件':name,'設定TOPIX数量':quantity,
                      'TOPIX指標':{field:value['TOPIX'][field] for field in (
                          'active_sessions','no_trade_sessions','downside_rms_units','active_downside_rms_units','positive_session_rate',
                          'worst_session_loss_units','worst_intraday_drawdown_units')},'両商品独立式一致':True})
    scale_cases = []
    for symbol,base,extra,cap,multiplier,opening,fee_unit in (
            ('TOPIX',8,2,10,1000.,4000.,41.8),('NK225',16,4,20,10.,68000.,11.)):
        sessions = [f'分母人工場{index}' for index in range(16)]
        unit = base*multiplier*opening*.001
        fee = 2*math.floor(extra*fee_unit+1e-8)
        original_nets = [unit*.25]*7+[-unit]+[None]*8
        scenarios = [('J8',8,original_nets,[base]*16),
                     ('未稼働range枠追加',10,original_nets,[base]*16),
                     ('短い追加玉又は両建て',10,original_nets[:7]+[-unit-fee]+original_nets[8:],[base]*7+[cap]+[base]*8),
                     ('追加活動で料金損失',10,original_nets[:8]+[-float(fee)]+[None]*7,[base]*8+[extra]+[base]*7)]
        measured = {}
        for name,budget,nets,peaks in scenarios:
            rows,prepared = [],{}
            for active_symbol in ('TOPIX','NK225'):
                for session,net,peak in zip(sessions,nets,peaks):
                    rows.append(dict(symbol=active_symbol,session=session,campaigns=0 if net is None else 1,
                                     net=0. if net is None else net,equity_drawdown=0.,stats={'max_total_held':peak}))
                    prepared[session,active_symbol] = dict(record=dict(price=np.array([opening])))
            measured[name] = calculate(rows,dict(trend_budget=budget,range_budget=0),prepared,sessions)[symbol]
        base_value = measured['J8']
        idle_value = measured['未稼働range枠追加']
        assert base_value['downside_rms_units'] == idle_value['downside_rms_units']
        assert base_value['worst_session_loss_units'] == idle_value['worst_session_loss_units']
        assert measured['短い追加玉又は両建て']['downside_rms_units'] > base_value['downside_rms_units']
        assert measured['追加活動で料金損失']['downside_rms_units'] > base_value['downside_rms_units']
        assert measured['追加活動で料金損失']['active_downside_rms_units'] < base_value['active_downside_rms_units']
        for result in measured.values():
            assert result['comparison_cap'] == cap
            assert result['session_count'] == 16
        scale_cases.append({'商品':symbol,'未使用設定枠だけで主指標改善不可':True,
                            '一瞬の増玉又は両建てで追加料金を失うと主指標悪化':True,
                            '別場の料金損失と活動追加では主指標悪化':True,
                            '活動RMSだけは見かけ改善するため補助扱い':True,
                            '主比較単位上限':cap,'主平均母数':16,
                            '各条件主RMS':{name:result['downside_rms_units'] for name,result in measured.items()}})
    return {'人工数':len(cases),'検査':cases,'分母の両商品追加反証':scale_cases,
            '損益前修正':'全条件共通上限10/20と共通全評価場数。設定数量は表示のみ、活動RMSは補助。',
            '限界':[
        '下方偏差は観測した確定収支だけの要約。未出現の稀な大損や翌日の成功確率を保証しない。',
        '20親・8活動場は最小条件であり精度保証ではない。少活動と無取引を安定の達成へ代用しない。',
        '実額を減らす数量縮小は運用リスク削減として反映される。入口出口又は予測自体の改善と区別し、実円額・実保有量・同数量源対照を併記する。',
        '確定黒字の下方偏差は0でも、場中に大きな含み損を抱えた可能性は残る。全玉清算時価の最大下落を必ず別に判断する。',
        '下方偏差の最小化だけなら僅かな黒字が有利になり得る。両費用後黒字、損小利大、金額80%及び最大日除外の目標を保持する。',
        '共通上限数量×始値0.1%は比較単位であり、実停止幅、最大損失保証、必要証拠金又は約定全量を表さない。',
        '全場数の主RMSでは無取引は実損失0。活動黒字率では勝ちにしない。全無取引は活動要件を満たさず成功認定しない。',
        '前16の参考順位を結果前に固定しても全31は既知。後15を未見の性能証明と呼ばず、事後全31上位と主を区別する。']}


def save(name: str, value: dict, fingerprints: dict[str,str]) -> None:
    """
    機能: 指紋を結んだ前検証資料を担当review_preへ保存する。
    引数: name(str)、value(dict)、fingerprints(dict[str,str])。
    返り値: None。旧成果又は正式会計を書き替えない。
    """
    value.update(SHA256=fingerprints,全31既知=True,採択用新損益閲覧=0,新保存場損益計算=0,
                 正式新条件実行=0,現在API取得=0,実注文=0,旧変更=0)
    path = HERE/name
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps({'資料':str(path.relative_to(ROOT)),'SHA256':digest(path),'全合格':value['全合格']},ensure_ascii=False),flush=True)


def main() -> None:
    """
    機能: 前検証目録の独立源分類及び敵対的53設計の二資料を再現する。
    引数: なし。
    返り値: None。純状態及び人工実行だけを行い、保存場の正式結果を読まない。
    """
    paths = [Path(__file__),PARTS,WORK/'strategy.py',WORK/'engine.py',WORK/'catalog.py',
             WORK/'結果前の設計案_r1.json',WORK/'inputs_r1/core.py',
             WORK/'research.py',WORK/'セッション安定性の事前評価.json',
             HERE/'実保有ピークと活動母数の安定指標を反証.py',
             HERE/'実保有ピークと活動母数の安定指標への敵対的反証.json',
             ROOT/'work/wave_v93/strategy.py',ROOT/'work/wave_v93/engine.py',
             ROOT/'work/wave_v92/strategy.py',ROOT/'work/wave_v91/strategy.py',ROOT/'work/wave_v90/strategy.py']
    before = {str(path.relative_to(ROOT)):digest(path) for path in paths}
    strategy = module('独立分類と入口執行94損益前',WORK/'strategy.py')
    catalog = module('独立53条件94損益前',WORK/'catalog.py')
    helper = module('独立源検査の純状態部品',PARTS)
    configs = {value['id']:value for value in catalog.catalog()}
    config = configs[catalog.PRIMARY]
    states = helper.state_checks(strategy,config)
    connections = helper.source_checks(strategy,config)
    gates = gate_cases(strategy.ENGINE,configs)
    centers = center_cases(strategy.ENGINE,configs)
    design = design_checks(catalog)
    stability = stability_checks()
    for path in paths:
        assert digest(path) == before[str(path.relative_to(ROOT))],str(path)
    save('独立価格分類と入口及び源分離.json',
         {'全合格':True,'純状態人工数':len(states),'源接続数':len(connections),'初回ゲート実人工数':len(gates),
          '純状態':states,'源接続':connections,'初回拒否後の再参加':gates,
          '価格窓と板の執行を分離':True,'G0準備とG1G2現在入口を分離':True,
          '制限':['純源接続は旧prepare返り値を固定した検査。旧内部の実原本は別独立監査。',
                  '人工執行は回復信号を与えた有限経路。全実接頭部及び真の受信時刻の証明とは異なる。']},before)
    save('53設計の敵対的反証.json',
         {'全合格':True,'対照設計':design,'中心負net人工数':len(centers),'固定中心の負net反例':centers,
          '結果前セッション安定性の反証':stability,
          '主の結果前反証':[
              'I3は約定価格履歴を観測できるようにする入力修正。観測増加は利益を生む法則ではない。',
              'G1は現在の判断材料が有限である条件であり、均衡中心へ戻る予測の正しさは保証しない。',
              'S0は狭い極値停止で帰還前の勝ちを失う経路を減らし得るが、中心へ戻らない漂流の損失を拡大し得る。',
              'T1は早い中心帰還を利益として確定し得る一方、3幅の大勝ちを捨て、次気配で中心越え新規したときは負netにもなる。',
              'したがって主I3_G1_S0_T1の両商品80%又は全日安定は理論から結論できない。結果前主は変えず反証する。',
              '4入力は価格種類と採用範囲を分け、3入口及び2停止及び2目標は別軸にする。旧C11との差は複合変更で部品単独の因果効果ではない。',
              'M82の価値はJ8へ2枚を追加した差、J10から2枚を置換した差、R2同数量単独一致を別々に見る。低相関だけで成功にしない。',
              '固定枠が完全独立なら親別金額利益割合は源別G+Lを重みとする加重平均であり、有効な源を超える上限にはならない。',
              '全31場は既知。前16と後15の再探索は未知データの成績ではない。無取引又は少数活動も80%の達成にしない。'],
          '結果後必須比較':['53×62=3286口座を独立に親及び注文費用で再計算する。',
                         '各一軸比較を同一判断・同一新規の管理差、除外親G/L、新固有親G/Lに分ける。',
                         '最大利益日及び最大利益親除外、買売別、前後、全原板の清算時価下落、活動不足を反証する。',
                         'M82の源別注文及び全時価がJ8/R2同数量単独へ完全一致するか検査する。'],
          '人工返済の位置づけ':'4例の一親負netは仕様反例であり、正式候補又は保存31場の成績ではない。'},before)


if __name__ == '__main__':
    main()
