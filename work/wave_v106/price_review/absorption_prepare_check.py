"""逆板維持の入口接続と、未許可入力を開かない非金融準備を独立確認する。"""

from pathlib import Path
import ast
import json
import sys

import numpy as np

from range_engine_check import digest, load


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SOURCE = ROOT/'work/wave_v106/e01_absorption_gate'


def read(path: Path) -> dict:
    """
    機能: 小さい静的証跡だけを解析する。
    引数: path(Path)はJSONの位置。
    返り値: dictは資料内容。保存cacheやNPZを読まない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main() -> None:
    """
    機能: 公開ゲートの独立真偽表と、準備の八部品・guard・当時対応を静的確認する。
    引数: なし。fix/run/loadを呼ばず金融・正式入力を未測定のまま残す。
    返り値: Noneは所有領域の独立接続証跡。
    """
    target = HERE/'absorption_元公開門の保持と非金融準備の独立接続.json'; assert not target.exists()
    sources = {p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    pure_path = HERE/'absorption_同価格数量支持と当時接頭の独立人工.json'
    pure = read(pure_path); art = read(SOURCE/'表示維持述語と元公開門の人工検査.json')
    assert pure['全合格'] and art['全合格'] and pure['source_SHA256']==art['source_SHA256']==sources
    C = load('吸収接続独立catalog',SOURCE/'catalog.py'); sys.modules['catalog']=C
    K = load('吸収接続独立known',SOURCE/'known_policy.py'); sys.modules['known_policy']=K
    G = load('吸収接続独立gate',SOURCE/'gate.py')
    assert digest(SOURCE/'known_policy.py')==digest(ROOT/'work/wave_v106/e01_known_veto/policy.py')
    assert digest(SOURCE/'votes.py')==digest(ROOT/'work/wave_v106/e01_trade_gate/votes.py')
    checks = 0; table = []
    feed = np.array([[0,0,0,1,5,4000,0,1,0,10],[2,0,0,-1,5,4000,0,0,0,0],
        [4,0,1,-1,5,4000,0,1,0,10],[6,0,1,1,5,4000,0,0,0,0]],float)
    baseline_cases = [dict(known=False,reason=8,direction_votes=None,balance=None),
        dict(known=True,reason=0,direction_votes=1,balance=1.),
        dict(known=True,reason=0,direction_votes=2,balance=-.25),
        dict(known=True,reason=0,direction_votes=2,balance=0.),
        dict(known=True,reason=0,direction_votes=2,balance=.25)]
    for base in baseline_cases:
        for eligible in (False,True):
            for known in (False,True):
                for hit in (None,False,True):
                    features = {0:dict(base),4:dict(base)}
                    values = {0:dict(side=1,eligible=eligible,known=known,hit=hit),
                        4:dict(side=-1,eligible=eligible,known=known,hit=hit)}
                    allowed,reasons = G.mask(feed,7,features,values)
                    qualified = bool(base['known'] and base['direction_votes']>=2)
                    old_allow = bool(qualified and base['balance']>-.25)
                    added_reject = old_allow and eligible and known and bool(hit)
                    expected = np.ones(7,bool); expected[[0,4]]=old_allow and not added_reject
                    old_reason = 0 if old_allow else 100+base['reason'] if not base['known'] else 200 if base['direction_votes']<2 else 202
                    expected_reason = np.zeros(7,np.int32); expected_reason[[0,4]]=501 if added_reject else old_reason
                    np.testing.assert_array_equal(allowed,expected); np.testing.assert_array_equal(reasons,expected_reason)
                    assert np.all(allowed[[1,2,3,5,6]]) and np.all(reasons[[1,2,3,5,6]]==0)
                    table.append(dict(元既知=base['known'],元票=base['direction_votes'],元釣合=base['balance'],
                        追加対象=eligible,追加既知=known,追加成立=hit,採否=bool(allowed[0]),理由=int(reasons[0]))); checks += 3
    bad = {0:dict(side=-1,eligible=True,known=True,hit=True),4:dict(side=-1,eligible=True,known=True,hit=True)}
    try: G.mask(feed,7,{0:baseline_cases[-1],4:baseline_cases[-1]},bad)
    except AssertionError: checks += 1
    else: raise AssertionError('追加特徴の逆方向を補完した')
    # ----------------------------------------
    # 巨大入力を読まず、source上の接続と開く順番だけを確認する。
    code = (SOURCE/'prepare.py').read_text(encoding='utf-8'); tree = ast.parse(code)
    functions = {node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    fix = ast.get_source_segment(code,functions['fix']); run = ast.get_source_segment(code,functions['run'])
    main_text = ast.get_source_segment(code,functions['main']); loader = ast.get_source_segment(code,functions['load'])
    assert not any(isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='load' for node in ast.walk(functions['fix']))
    assert "independent['source_SHA256'] == current" in fix and "len(raw_meta['raw_inputs']) == 66" in fix
    assert "assert args.fix_only != args.root_input_reviewed" in main_text
    assert "assert not (common.HERE/'入力測定開始.json').exists()" in main_text
    assert "assert not (common.HERE/'入力測定False.json').exists()" in main_text
    assert "自動再開始=False" in main_text and "金融=0" not in loader
    assert "saved = path.read_bytes()" in loader and "hashlib.sha256(saved).hexdigest() == item['SHA256']" in loader
    assert "np.load(io.BytesIO(saved), allow_pickle=False)" in loader and "array.flags.writeable = False" in loader
    assert "old = load(fixed['cache'][session])" in run and "raw = load(fixed['raw_inputs'][session+'|'+symbol], True)" in run
    assert "np.testing.assert_array_equal(mapping, account['mapping'])" in run
    assert "(('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'))" in run
    assert "np.testing.assert_array_equal(raw[name][mapping], account['quotes'][name])" in run
    assert "entries = account['feed'][account['feed'][:, 7] == 1]" in run
    assert "assert measured == base[normal_row]" in run
    assert "raw_row = int(mapping[normal_row])" in run and "feature.measure(raw, context, raw_row, side, base[normal_row])" in run
    assert "for j in sorted(set((0, len(entries)//2, len(entries)-1)))" in run
    assert "assert shorter_base == base[normal_row]" in run and "== added[normal_row]" in run
    assert "own = dict(account, absorption_features=added," in run and "del raw, context" in run
    assert "checks['保存E01cache一読'] == 33" in run and "checks['原行NPZ一読'] == 66" in run
    assert "新金融=0, 勝敗照合=0, API=0" in run
    assert 'import requests' not in code and 'urllib' not in code and 'interface.execute' not in code
    # ----------------------------------------
    # 入力ロケータの対象数・原行対応は小metadataだけで確認し、ファイルbytesを開かない。
    meta = read(ROOT/'work/wave_v106/e01_trade_gate/全33場のE01取引更新準備.json')
    rawmeta = read(ROOT/'work/wave_v106/e01_trade_gate/入力測定前の固定.json')
    assert meta['全合格'] and rawmeta['全合格'] and meta['sessions']==rawmeta['sessions'] and len(meta['sessions'])==33
    assert set(meta['cache'])==set(meta['sessions']) and len(rawmeta['raw_inputs'])==66
    assert set(rawmeta['raw_inputs'])=={s+'|'+m for s in meta['sessions'] for m in ('TOPIX','NK225')}
    assert C.BASELINE_ID=='E01_TRADE_W60_KNOWN_VETO_D0_P1L8' and C.WINDOW==60 and C.MINIMUM_TOUCHES==2 and C.MINIMUM_ACTIVITY_RATIO==1
    assert C.QUANTITY=={'TOPIX':5,'NK225':10} and C.CAP=={'TOPIX':10,'NK225':20}
    assert sources=={p.relative_to(ROOT).as_posix():digest(p) for p in SOURCE.glob('*.py')}
    proof = dict(全合格=True,範囲='純述語人工とのsource接続、元公開拒否保持の60真偽、prepareの静的guardと入力ロケータだけ。prepare.fix/run/load未実行。',
        入口真偽数=len(table),入口検査数=checks,入口真偽=table,source_SHA256=sources,source開始終端一致=True,
        レビューsource_SHA256=digest(Path(__file__)),純述語独立人工SHA256=digest(pure_path),所有人工SHA256=digest(SOURCE/'表示維持述語と元公開門の人工検査.json'),
        保存cacheロケータ=33,原行NPZロケータ=66,実測は未実施=True,大型入力=0,NPZ=0,原板=0,金融=0,API=0,
        留意点=['追加観測がunknownでも元拒否を解除しない。元許可だけを既知成立時に501で拒否する。非公開行と返済feedはそのまま。',
            '正確なrawseq/mapping/価格時計/Last/BBOと保存票同値は、実prepareが開いたときにassertする契約。この独立確認は未開封入力の一致を主張しない。',
            '実入力接頭検査は各商品各場の先頭・中央・末尾公開。全公開候補の全接頭を実二重測定した主張ではない。',
            '固定直下全*.pyの指紋を使う。入力固定後の金融source追加は別所有域へ置き、この8pyを変更しない。',
            '追加判定候補数は実取引数ではない。勝敗と金融差は別目的の検証まで未測定。'])
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('逆板維持の独立入口接続と静的準備合格',len(table),digest(target))


if __name__=='__main__': main()
