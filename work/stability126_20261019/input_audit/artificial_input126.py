"""市場本文を使わず、原版E01の入力時刻と共同参照を独立人工で確認する。"""

import ast
import csv
from datetime import datetime
import hashlib
from io import StringIO
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MIRROR = ROOT / 'work/stability126_20261019/engine/legacy_root'
SOURCES = {}
CHECKS = []


def functions(relative: str, names: tuple[str, ...], namespace: dict, *, owned: bool = True) -> dict:
    """
    機能: 保存源の指定関数をAST本体無変更で人工用環境へ取り出す。
    引数: relative(str)、names(tuple[str,...])、namespace(dict)、owned(bool)は源と環境。
    返り値: dictは関数を含む環境。上位moduleの市場I/O・旧キャッシュを実行しない。
    """
    path = (MIRROR if owned else ROOT) / relative
    payload = path.read_bytes()
    SOURCES[path.relative_to(ROOT).as_posix()] = hashlib.sha256(payload).hexdigest()
    tree = ast.parse(payload.decode('utf-8-sig'))
    nodes = [v for v in tree.body if isinstance(v, ast.FunctionDef) and v.name in names]
    assert {v.name for v in nodes} == set(names)
    for node in nodes:
        assert not node.decorator_list
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), 'exec'), namespace)
    return namespace


def check(name: str, passed: bool) -> None:
    """
    機能: 独立期待値との比較を保存し、不合格なら即停止する。
    引数: name(str)は検査内容、passed(bool)は独立比較の結果。
    返り値: None。
    """
    assert passed, name
    CHECKS.append(dict(name=name, passed=True))


def same(name: str, left: object, right: object) -> None:
    """
    機能: 浮動小数NaNを含む配列の同値を独立確認する。
    引数: name(str)、left/right(object)は比較対象。
    返り値: None。
    """
    np.testing.assert_array_equal(left, right, err_msg=name)
    check(name, True)


class PandasView:
    """合成CSVだけをread_csvへ返す人工用Pandas代理。"""

    def __init__(self, frame: pd.DataFrame) -> None:
        """
        機能: 当該検査で使用する合成足を保持する。
        引数: frame(pd.DataFrame)は合成された足。
        返り値: None。
        """
        self.frame = frame

    def __getattr__(self, name: str) -> object:
        """
        機能: I/O以外のPandas機能をそのまま渡す。
        引数: name(str)は属性名。
        返り値: objectはPandas属性。
        """
        return getattr(pd, name)

    def read_csv(self, *args: object, **kwargs: object) -> pd.DataFrame:
        """
        機能: ファイルを開かず合成足のコピーだけを返す。
        引数: args(tuple)、kwargs(dict)は未使用の通常CSV引数。
        返り値: pd.DataFrameは合成足。
        """
        return self.frame.copy(deep=True)


def bars_checks() -> None:
    """
    機能: 1分足公開120秒・未確定除外・未来切断を独立確認する。
    引数: なし。
    返り値: None。全足は固定人工値のみ。
    """
    start = datetime.fromisoformat('2026-10-19T08:45:00+09:00').timestamp()
    frame = pd.DataFrame(dict(time=[datetime.fromtimestamp(start + 60*j).astimezone().isoformat() for j in range(8)],
                              open=np.arange(8.)+100, high=np.arange(8.)+102,
                              low=np.arange(8.)+99, close=np.arange(8.)+101,
                              volume=np.full(8,10.), closed=[True,False,True,True,True,True,True,True],
                              volume_complete=[True]*8))
    view = PandasView(frame)
    env = dict(np=np, pd=view, Path=Path, ROOT=HERE, _BAR_CACHE={})
    functions('work/wave_v23/signals.py', ('_expand', '_efficiency', '_bars'), env)
    ready = dict(seq=np.arange(16), time_s=start+np.arange(16)*30., atr=np.full(16,5.),
                 start=start, symbol='TOPIX', session='人工')
    full = env['_bars'](ready)
    same('1分足は始時120秒後に公開', full['time_s'], start+np.array([120,240,300,360,420]))
    same('closed falseの足を利用しない', full['close'].to_numpy(), np.array([101.,103.,104.,105.,106.]))
    short = dict(ready, seq=ready['seq'][:7], time_s=ready['time_s'][:7], atr=ready['atr'][:7])
    env['_BAR_CACHE'].clear()
    prefix = env['_bars'](short)
    same('公開前の足をprefixへ入れない', prefix['time_s'], np.array([start+120]))
    view.frame.loc[view.frame.index >= 2, ['high','low','close']] += 10000
    env['_BAR_CACHE'].clear()
    changed = env['_bars'](short)
    for name in ('time_s','close','high','low','atr','volume'):
        same('未公開足改変で過去不変_'+name, np.asarray(prefix[name]), np.asarray(changed[name]))


def atr_checks() -> None:
    """
    機能: 確定5分足ATRの公開360秒と未来足非依存を独立確認する。
    引数: なし。
    返り値: None。
    """
    start = datetime.fromisoformat('2026-10-19T08:45:00+09:00').timestamp()
    times = start + np.array([359.,360.,659.,660.,959.,960.,1259.,1260.])
    frame = pd.DataFrame(dict(time=[datetime.fromtimestamp(start+300*j).astimezone().isoformat() for j in range(5)],
                              high=[104.,106.,108.,110.,112.], low=[100.,101.,102.,103.,104.],
                              close=[102.,104.,106.,108.,110.], closed=[True]*5))
    proxy = PandasView(frame)
    env = dict(np=np, pd=proxy, Path=Path, TICKS={'TOPIX':.5}, candle_root=lambda _: HERE)
    functions('work/wave_v11/signals.py', ('read_bars','atr_at'), env)
    actual = env['atr_at']('人工','TOPIX',times)
    tr = np.array([4.,5.,6.,7.])
    expected = np.empty(4);expected[0]=tr[0]
    for j in range(1,4):expected[j]=(11*expected[j-1]+tr[j])/12
    check('最初3本未満のATRは非有限', np.isnan(actual[:5]).all())
    same('3本目は始時360秒後のみに公開', actual[5:7], np.array([expected[2],expected[2]]))
    np.testing.assert_allclose(actual[7], expected[3], rtol=1e-14)
    check('ATR指数平滑alpha1/12', True)
    before = actual[:6].copy()
    proxy.frame.loc[3:, ['high','low','close']] += 50000
    after = env['atr_at']('人工','TOPIX',times[:6])
    same('未公開5分足改変でATRprefix不変', before, after)


def joint_checks() -> None:
    """
    機能: 共同B00の相手strict過去・鮮度・prefixを独立確認する。
    引数: なし。
    返り値: None。
    """
    env = functions('work/wave_v85/strategy.py', ('joint_features',), {'np':np})
    own_times = np.array([10.,11.,12.,13.]);peer_times=np.array([9.,10.,11.,12.,13.])
    inputs={('人工','TOPIX'):{'time_s':own_times},('人工','NK225'):{'time_s':peer_times}}
    features={}
    for key, times in ((('人工','TOPIX'),own_times),(('人工','NK225'),peer_times)):
        columns=[np.ones(len(times),np.int8),np.ones(len(times),np.int8),np.arange(len(times))]
        features[key]=dict(columns=columns,valid=np.ones(len(times),bool))
    result=env['joint_features'](('人工','TOPIX'),inputs,features)
    same('相手同時計の更新は使用しない', result['peer_row'], np.array([0,1,2,3]))
    same('strict先行の共同方向', result['direction'], np.ones(4,np.int8))
    check('相手元時刻は自己時刻より過去', np.all(peer_times[result['peer_row']]<own_times))
    features['人工','NK225']['columns'][1][-1]=-1
    changed=env['joint_features'](('人工','TOPIX'),inputs,features)
    same('同時計及び未来の相手改変で過去不変',result['direction'],changed['direction'])
    before=changed['direction'][:2]
    short={k:dict(v,time_s=v['time_s'][:2]) if k[1]=='TOPIX' else v for k,v in inputs.items()}
    short_features=dict(features)
    short_features['人工','TOPIX']=dict(columns=[v[:2] for v in features['人工','TOPIX']['columns']],valid=np.ones(2,bool))
    prefix=env['joint_features'](('人工','TOPIX'),short,short_features)
    same('自己末尾切断で共同方向prefix不変',before,prefix['direction'])
    stale={('人工','TOPIX'):{'time_s':np.array([100.])},('人工','NK225'):{'time_s':np.array([9.])}}
    sf={key:dict(columns=[np.ones(1,np.int8),np.ones(1,np.int8),np.zeros(1,np.int64)],valid=np.ones(1,bool)) for key in stale}
    sr=env['joint_features'](('人工','TOPIX'),stale,sf)
    check('30秒超の相手B00を利用しない',not sr['valid'][0] and sr['direction'][0]==0)
    stale['人工','TOPIX']['time_s'][0]=9.
    exact=env['joint_features'](('人工','TOPIX'),stale,sf)
    check('同時計しかない相手を未知扱い',not exact['valid'][0] and exact['peer_row'][0]==-1)


def peer_release_checks() -> None:
    """
    機能: 元主方向の相手確認に60秒追加公開待ちがあることを独立確認する。
    引数: なし。
    返り値: None。
    """
    env=functions('work/wave_v27/hierarchy_signals.py',('_size','_asof','_allowed'),{'np':np})
    models={('人工','TOPIX'):dict(time_s=np.array([120.,180.]),direction=np.array([1,-1])),
            ('人工','NK225'):dict(time_s=np.array([120.,180.]),direction=np.array([1,-1]))}
    times=np.array([119.,120.,179.,180.,239.,240.])
    actual=env['_allowed'](('人工','TOPIX'),times,models,dict(peer_confirm=True,peer_multiplier=1.))
    same('相手主方向はさらに60秒待って確認',actual,np.array([0,0,0,0,0,-1],np.int8))
    own=env['_allowed'](('人工','TOPIX'),times,models,dict(peer_confirm=False,peer_multiplier=1.))
    same('相手確認OFF対照の自己公開時刻',own,np.array([0,1,1,-1,-1,-1],np.int8))


def clock_checks() -> None:
    """
    機能: 高水位時計資格と合法CSV末尾表示を独立人工で確認する。
    引数: なし。
    返り値: None。
    """
    base='work/stability124_20261019/e01c/'
    clock=functions(base+'clock_adapter.py',('price_clock','step','transform'),dict(datetime=datetime,math=math),owned=False)
    start=datetime.fromisoformat('2026-10-19T08:45:00+09:00').timestamp();end=start+100
    rows=[dict(CurrentPrice=4000.,CurrentPriceTime=value,Buy1={'Price':3999.5}) for value in
          ('2026-10-19T08:45:02+09:00','2026-10-19T08:45:01+09:00',None,
           '2026-10-19T08:45:03','2026-10-19T08:45:02+09:00','2026-10-19T08:45:04+09:00')]
    before=json.loads(json.dumps(rows))
    actual,reasons=clock['transform'](rows,start,end)
    same('逆行不明時差無しと同時計の資格',np.array(reasons),np.array([0,8,1,1,0,0]))
    check('元入力辞書を変更しない',rows==before)
    check('逆行時計の日付や時刻を推測修正しない',actual[1]['CurrentPriceTime'] is None)
    check('価格と板は不適格時計でも元値',all(v['CurrentPrice']==4000 and v['Buy1']=={'Price':3999.5} for v in actual))
    prefix,_=clock['transform'](rows[:3],start,end)
    check('時計資格は未来行で過去不変',prefix==actual[:3])
    view=functions(base+'csv_view124.py',('view',),dict(csv=csv,StringIO=StringIO,math=math,
                   hashlib=hashlib,clock=SimpleNamespace(price_clock=clock['price_clock'])),owned=False)
    source=('time,close\n2026-10-19T08:45:00+09:00,4000\n'
            '2026-10-19T08:46:00+09:00,4001\n2026-10-19T08:47:00+09:00,99999\n').encode()
    output,diagnosis=view['view'](source,start,start+120)
    check('合法終端足を旧窓外として記録',diagnosis['kept_rows']==2 and diagnosis['excluded_rows']==1)
    check('合法終端の極端価格を過去表示へ入れない',b'99999' not in output)
    malformed=[source.replace(b'08:46:00',b'08:45:00'),source.replace(b'08:46:00',b'08:44:00'),
               source.replace(b'08:47:00',b'08:53:00')]
    for j,payload in enumerate(malformed):
        try:view['view'](payload,start,start+120)
        except AssertionError:check('不正CSV拒否_'+str(j),True)
        else:raise AssertionError(('不正CSVを許可',j))


def execute() -> None:
    """
    機能: 数値源の独立時刻人工だけを実行し、同一源拘束の証拠を保存する。
    引数: なし。
    返り値: None。市場入力読取・金融再生・APIは0。
    """
    bars_checks();atr_checks();joint_checks();peer_release_checks();clock_checks()
    path=HERE/'元E01の足公開と共同時計及び終端の独立人工.json'
    assert not path.exists()
    source_sha=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    proof=dict(passed=True,checks=CHECKS,source_sha256=source_sha,sources=SOURCES,
               execution='関数本体はAST無変更。合成足・合成時刻・合成板のみ。上位module importなし。',
               market_body_reads=0,financial_replays=0,API=0,real_orders=0)
    path.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,checks=len(CHECKS),sources=len(SOURCES),
                          output=path.relative_to(ROOT).as_posix()),ensure_ascii=False))


if __name__=='__main__':
    try:
        execute()
    except Exception as error:
        import time
        failure=HERE/('非金融人工停止_'+str(time.time_ns())+'.json')
        failure.write_text(json.dumps(dict(passed=False,error=repr(error),checks=CHECKS,
            sources=SOURCES,market_body_reads=0,financial_replays=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
