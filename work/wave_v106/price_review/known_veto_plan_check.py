"""既知中立二出口の事前固定を、大型入力を開かず独立照合する。"""

from pathlib import Path
import ast
import json

from range_engine_check import digest


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/e01_known_veto'
OLD = ROOT/'work/wave_v106/e01_trade_gate'


def read(path: Path) -> dict:
    """
    機能: 読取専用の小さな固定資料だけを解析する。
    引数: path(Path)はJSONの位置。
    返り値: dictは保存内容。大型金融cacheを読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def body(path: Path, name: str) -> str:
    """
    機能: sourceから指定した関数の構文木を取り出す。
    引数: path(Path)、name(str)はsourceと関数名。
    返り値: strは数値及び分岐を含む構文表現。
    """
    tree = ast.parse(path.read_text(encoding='utf-8'))
    matched = [node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name==name]
    assert len(matched)==1
    return ast.dump(matched[0],include_attributes=False)


def main() -> None:
    """
    機能: 八部品・source・旧数値関数・保存入力と二旧対照を事前固定へ独立接続する。
    引数: なし。新金融の保存結果は読まない。
    返り値: Noneは小固定接続の証跡。原資料や経済再生はない。
    """
    target = HERE/'known_veto_八部品と保存入力及び旧対照の独立接続.json'; assert not target.exists()
    plan = read(SOURCE/'試行計画.json'); fixed = read(SOURCE/'金融事前固定.json')
    art = read(SOURCE/'既知逆票見送りの真偽表と旧経済及び接頭の人工検査.json')
    independent = read(HERE/'known_veto_三政策境界と影実玉接頭の独立人工.json')
    meta = read(OLD/'全33場のE01取引更新準備.json'); old = read(OLD/'finance/結果.json')
    current = {p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    assert set(plan['spec'])=={'entry','management','exit','allocation','costs','execution','data','implementation'}
    assert current==fixed['source_SHA256']==plan['spec']['implementation']==art['source_SHA256']==independent['source_SHA256']
    assert art['全合格'] and independent['全合格'] and fixed['全合格']
    assert fixed['計画SHA256']==digest(SOURCE/'試行計画.json')
    assert fixed['sessions']==meta['sessions']==plan['spec']['data']['sessions']==old['sessions'] and len(fixed['sessions'])==33
    assert fixed['input_cache']==meta['cache'] and len(fixed['input_cache'])==33
    assert fixed['configs']==plan['spec']['entry']['conditions'] and len(fixed['configs'])==2
    for c in fixed['configs']:
        assert c['window_seconds']==60 and c['mode']=='KNOWN_VETO' and c['execution']=='D0' and c['offset_atr']==0
        assert c['quantity']=={'TOPIX':5,'NK225':10} and c['cap']=={'TOPIX':10,'NK225':20}
        baseline = fixed['baseline'][c['id']]; oldcase = old['results'][c['baseline_id']]
        assert baseline['id']==c['baseline_id'] and baseline['rows']==oldcase['rows'] and baseline['symbols']==oldcase['symbols']
        assert baseline['ledgers']=={p['session']+'|'+p['symbol']:p for p in oldcase['ledgers']} and len(baseline['ledgers'])==66
    for item in plan['spec']['data']['input_manifests']: assert digest(ROOT/item['path'])==item['sha256']
    for filename in ('common.py','engine.py','order_kernel.py','daily.py','interface.py','old_engine.py'):
        assert digest(SOURCE/filename)==digest(OLD/filename)
    for name in ('aggregate','delta','stored'): assert body(SOURCE/'storage.py',name)==body(OLD/'runner.py',name)
    assert plan['counts']==dict(新engine=66,新政策会計=132,保存対照ledger読取=132,既input読取=33,元paper再計算=0)
    runner = (SOURCE/'runner.py').read_text(encoding='utf-8')
    assert "found[0]['spec']==plan['spec']" in runner and "assert not (common.HERE/'finance').exists()" in runner
    assert "values=interface.execute(a,configs[0])" in runner and "fresh=interface.account_output(session,a,c,values)" in runner
    assert 'except BaseException:' in runner and '自動再開始=False' in runner
    assert current=={p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    proof = dict(全合格=True,scope='結果前八部品・独立人工・保存inputロケータ33と旧VETO二対照132ロケータを小metadataのみで照合。',
        source_SHA256=current,計画SHA256=digest(SOURCE/'試行計画.json'),固定SHA256=digest(SOURCE/'金融事前固定.json'),
        人工SHA256=digest(SOURCE/'既知逆票見送りの真偽表と旧経済及び接頭の人工検査.json'),
        独立人工SHA256=digest(HERE/'known_veto_三政策境界と影実玉接頭の独立人工.json'),
        レビューsource_SHA256=digest(Path(__file__)),旧数値六source同bytes=True,旧集計三関数同構文=True,
        新金融=0,大型cache=0,旧ledger=0,原板=0,原NPZ=0,API=0,registry変更=0,
        留意点=['KNOWN_VETO の金融条件は二出口だけ。人工境界真偽表の枝を追加金融政策として数えない。',
            '既知33は再探索用で、未見の成功確認ではない。現在板の時計不適合を補完していない。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('既知中立の独立事前接続合格',digest(target))


if __name__=='__main__': main()
