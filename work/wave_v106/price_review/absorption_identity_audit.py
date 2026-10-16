"""追加の全公開mask同値と、保存金融を再利用できる来歴を独立確認する。"""

from collections import Counter
from pathlib import Path
import ast
import gzip
import hashlib
import json
import pickle
import sys

import numpy as np

from range_engine_check import digest, load


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/e01_absorption_gate'
BASE = ROOT/'work/wave_v106/e01_known_veto'


def read(path: Path) -> dict:
    """
    機能: 小資料を読取専用で解析する。
    引数: path(Path)はJSON位置。
    返り値: dictは保存資料。元の大型cacheを読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def fingerprint(value: object) -> object:
    """
    機能: 新preparedの受け継いだ実行引数を、種類・形・bytes又は有限scalarへ指紋化する。
    引数: value(object)は配列又はscalar。
    返り値: objectは未来再照合用指紋。元cacheとのbytes同値の証明ではない。
    """
    if isinstance(value,np.ndarray):
        return dict(型=str(value.dtype),形=list(value.shape),SHA256=hashlib.sha256(value.tobytes(order='C')).hexdigest())
    if isinstance(value,np.generic): return value.item()
    return value


def root_name(node: ast.AST) -> str | None:
    """
    機能: 左辺の添字・属性をたどり、変更される最上位の変数名を求める。
    引数: node(ast.AST)は構文左辺。
    返り値: str|Noneは変数名。入力の破壊的代入を静的に探す。
    """
    while isinstance(node,(ast.Subscript,ast.Attribute)): node=node.value
    return node.id if isinstance(node,ast.Name) else None


def main() -> None:
    """
    機能: 新prepared33だけを各一読し、全mask・299小観測・元会計再利用の限定来歴を確認する。
    引数: なし。原cache/NPZ/金融/現在APIは読まず再生しない。
    返り値: Noneは小射影と同値証跡。新介入の有効性を数えない。
    """
    target = HERE/'absorption_全公開mask同値と保存66会計再利用の独立確認.json'; assert not target.exists()
    start = HERE/'absorption_同値診断開始.json'; assert not start.exists()
    meta = read(SOURCE/'全33場の表示維持公開観測の準備.json'); fixed = read(SOURCE/'入力測定前の固定.json')
    plan = read(SOURCE/'八部品と非金融測定の計画.json'); baseline_fixed = read(BASE/'金融事前固定.json'); result = read(BASE/'finance/結果.json')
    assert meta['全合格'] and fixed['全合格'] and result['全合格']
    sources = {p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    assert sources==meta['source_SHA256']==fixed['source_SHA256']==plan['spec']['implementation']
    assert meta['入力固定SHA256']==digest(SOURCE/'入力測定前の固定.json')
    assert fixed['計画SHA256']==digest(SOURCE/'八部品と非金融測定の計画.json')
    assert meta['sessions']==fixed['sessions']==baseline_fixed['sessions']==result['sessions'] and len(meta['sessions'])==33
    assert fixed['cache']==baseline_fixed['input_cache']
    assert meta['新金融']==meta['原paper再計算']==meta['旧金融読取']==meta['API']==0
    for p,h in baseline_fixed['source_SHA256'].items(): assert digest(ROOT/p)==h
    for item in fixed['input_manifests']: assert digest(ROOT/item['path'])==item['SHA256']
    for p,h in fixed['original_sources'].items(): assert digest(ROOT/p)==h
    # ----------------------------------------
    # 元accountに添字代入せず三列だけ追加する実装経路。元33bytesの再読比較はしていない。
    source_text = (SOURCE/'prepare.py').read_text(encoding='utf-8'); tree = ast.parse(source_text)
    run = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    for node in ast.walk(run):
        if isinstance(node,(ast.Assign,ast.AugAssign,ast.AnnAssign)):
            targets = node.targets if isinstance(node,ast.Assign) else [node.target]
            for left in targets:
                if isinstance(left,(ast.Subscript,ast.Attribute)):
                    assert root_name(left) not in ('account','old','base','entries','mapping')
    assert 'own = dict(account, absorption_features=added,' in source_text
    assert 'absorption_gate_accepted=accepted, absorption_gate_reasons=reason)' in source_text
    C = load('吸収同値独立catalog',SOURCE/'catalog.py'); sys.modules['catalog']=C
    K = load('吸収同値独立旧policy',SOURCE/'known_policy.py')
    assert digest(SOURCE/'known_policy.py')==digest(BASE/'policy.py')
    initial = dict(目的='新prepared33の全normal公開mask同値と小観測の独立射影。元cache/NPZ/金融再生なし。',新prepared予定33=True,
        source_SHA256=sources,準備SHA256=digest(SOURCE/'全33場の表示維持公開観測の準備.json'),金融再生=0,原cache=0,NPZ=0,API=0)
    start.write_text(json.dumps(initial,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    observed = []; reads = {}; aggregates = {m:Counter() for m in ('TOPIX','NK225')}; gates = {}; fingerprints = {}; actual_normal = 0
    projection = HERE/'absorption_全299公開観測の独立射影.json'; assert not projection.exists()
    for session in meta['sessions']:
        item = meta['cache'][session]; path = ROOT/item['path']; saved = path.read_bytes()
        assert hashlib.sha256(saved).hexdigest()==item['SHA256']; reads[item['path']]=item['SHA256']
        packet = pickle.loads(gzip.decompress(saved)); assert packet['session']==session
        for symbol in ('TOPIX','NK225'):
            a = packet['accounts'][symbol]; n = len(a['record']['price']); actual_normal += n
            assert set(a)=={'symbol','record','quotes','feed','quiet','quiet_force','quiet_windows','paper_SHA256','mapping','trade_features',
                'absorption_features','absorption_gate_accepted','absorption_gate_reasons'}
            assert a['symbol']==symbol and len(a['mapping'])==n and len(a['quiet'])==len(a['quiet_force'])==n
            base = a['trade_features']['60']; accepted,reasons = K.mask(a['feed'],n,base,'KNOWN_VETO')
            np.testing.assert_array_equal(a['absorption_gate_accepted'],accepted)
            np.testing.assert_array_equal(a['absorption_gate_reasons'],reasons)
            for name in ('bid','ask','quote_valid'): assert len(a['quotes'][name])==n
            inherited = dict(時間=a['record']['time_s'],価格=a['record']['price'],買気配=a['quotes']['bid'],売気配=a['quotes']['ask'],
                正常資格=a['quotes']['quote_valid'],全feed=a['feed'],静観=a['quiet'],強制静観=a['quiet_force'],
                返済期限=a['record']['limit'],観測呼値=a['record']['tick'],初回=C.QUANTITY[symbol],片方向上限=C.CAP[symbol])
            fingerprints[session+'|'+symbol] = {k:fingerprint(v) for k,v in inherited.items()}
            entries = a['feed'][a['feed'][:,7]==1]; assert len(set(int(e[0]) for e in entries))==len(entries)
            count = Counter(紙上公開候補数=len(entries),元KNOWN_VETO許可数=0,元票未知数=0,元票既知二票未満数=0,
                追加述語対象数=0,追加述語既知数=0,追加述語未知数=0,全公開の成立数=0,元許可から追加見送り数=0,追加後公開許可数=0)
            fail = Counter(); joint = Counter()
            for e in entries:
                row,side = int(e[0]),int(e[3]); v = a['absorption_features'][row]; b = base[row]
                qualified = bool(b['known'] and b['direction_votes']>=2)
                allow = bool(qualified and b['balance']>-.25)
                assert v['side']==side and v['eligible']==qualified and v['candidate_raw_row']==int(a['mapping'][row])
                assert v['candidate_raw_seq']==int(a['record']['seq'][row])
                count['元KNOWN_VETO許可数'] += allow; count['追加後公開許可数'] += bool(a['absorption_gate_accepted'][row])
                count['元票未知数'] += not b['known']; count['元票既知二票未満数'] += bool(b['known'] and b['direction_votes']<2)
                count['追加述語対象数'] += v['eligible']; count['追加述語既知数'] += bool(v['eligible'] and v['known'])
                count['追加述語未知数'] += bool(v['eligible'] and not v['known']); count['全公開の成立数'] += bool(v['eligible'] and v['known'] and v['hit'])
                count['元許可から追加見送り数'] += bool(allow and v['eligible'] and v['known'] and v['hit'])
                criteria = None
                if qualified and v['known']:
                    q = v['initial_quantity']; minimum = v['minimum_quantity']; progress = v['maximum_support_advance']; volume = v['touch_activity_volume']; ratio = v['touch_activity_to_initial_ratio']
                    assert all(np.isfinite(x) for x in (q,minimum,progress,volume,ratio)) and q>0 and minimum>0 and progress>=0 and volume>=0
                    assert np.isclose(ratio,volume/q,rtol=1e-12,atol=0)
                    assert v['touch_count']==len(v['touch_rows'])==len(v['touch_raw_seq'])
                    startrow = v['episode_start_raw_row']; endrow = v['candidate_raw_row']
                    assert v['first_window_raw_row']<=startrow<=endrow
                    assert v['episode_start_raw_seq']-v['candidate_raw_seq']==startrow-endrow
                    assert all(startrow<j<=endrow for j in v['touch_rows']) and all(j<k for j,k in zip(v['touch_rows'],v['touch_rows'][1:]))
                    assert all(s-v['candidate_raw_seq']==j-endrow for j,s in zip(v['touch_rows'],v['touch_raw_seq']))
                    criteria = dict(数量非減少=minimum>=q,支持非進行=progress<=0,二接触=v['touch_count']>=2,活動比一以上=ratio>=1)
                    assert v['hit']==all(criteria.values())
                    failure_names = [k for k,okay in criteria.items() if not okay]
                    for name in failure_names: fail[name] += 1
                    joint['＋'.join(failure_names) if failure_names else '成立'] += 1
                observed.append(dict(session=session,symbol=symbol,normal_row=row,side=side,元許可=allow,base=b,
                    feature=v,保存成分再構成=criteria))
            saved_count = meta['activity'][session][symbol]
            for k,num in count.items(): assert saved_count[k]==num,(session,symbol,k,num,saved_count[k])
            assert saved_count['追加未知理由']=={} and count['追加述語未知数']==0
            aggregates[symbol].update(count)
            gates[session+'|'+symbol] = dict(normal行数=n,全行採否同値=True,全行理由同値=True,公開=len(entries),対象=count['追加述語対象数'],成分失敗数=dict(fail),共同失敗型=dict(joint))
        del packet,saved
    assert len(reads)==33 and len(observed)==299
    for symbol,count in aggregates.items():
        for k,num in count.items(): assert meta['aggregate'][symbol][k]==num
        assert count['全公開の成立数']==count['元許可から追加見送り数']==0
    projection_value = dict(全合格=True,規模=299,新prepared一読=33,公開小観測=observed,元raw再読=0,原cache再読=0,金融再生=0,API=0)
    projection.write_text(json.dumps(projection_value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    baseline_case = result['results'][C.BASELINE_ID]; assert len(baseline_case['rows'])==len(baseline_case['ledgers'])==66
    proof = dict(全合格=True,範囲='新prepared33の全normal行mask/理由と299小観測の独立再構成。元33bytes再比較・新金融・NPZ oracleは未実行。',
        source_SHA256=sources,レビューsource_SHA256=digest(Path(__file__)),結果準備SHA256=digest(SOURCE/'全33場の表示維持公開観測の準備.json'),
        新prepared読取=33,新prepared指紋=reads,全normal行数=actual_normal,全公開小観測=299,集計={k:dict(v) for k,v in aggregates.items()},
        全場採否同値=gates,受継実行引数の新prepared指紋=fingerprints,射影SHA256=digest(projection),
        再利用=dict(id=C.BASELINE_ID,path=(BASE/'finance/結果.json').relative_to(ROOT).as_posix(),SHA256=digest(BASE/'finance/結果.json'),
            保存66小会計=baseline_case['rows'],商品集計=baseline_case['symbols'],新金融再生=0,
            理由='同じ旧33cache SHAから元accountを変えず構築し、唯一追加するmask/理由は全normal同値。元engine/日次出口/数量/費用/静観を保持するaliasだけが成立。'),
        原cache再読=0,原板=0,NPZ再読=0,新金融=0,API=0,
        留意点=['保存66会計再利用は介入がなかった同値確認。新しい予測力や損失軽減の成功例ではない。',
            '追加hit0は全公開候補の範囲。市場全原行でこの現象が存在しないという結論ではない。',
            '成分再構成は保存した最小数量/最大支持進行/接触活動量からの検算。元rawを新たに読み当該値を再測定した証明ではない。',
            '原accountとの全propertybytes同値を独立二読で確認した主張はしない。入力SHAと不変構築sourceへ限定している。'])
    assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('逆板維持の全mask同値と保存会計再利用の独立確認合格',len(observed),actual_normal,digest(target))


if __name__=='__main__': main()
