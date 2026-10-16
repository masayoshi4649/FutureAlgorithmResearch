"""初版保存Falseを残し、JSON型修正の人工→固定継承→根授権の別目的再読を分ける。"""

import argparse
from collections import Counter
import gc
import gzip
import hashlib
import pickle
import time
import traceback

import analysis
import artificial
import common
import plan


def prepare() -> None:
    """
    機能: 実本文を読まず合成人工とSOURCE_ONLY計画を保存する。
    引数: なし。
    返り値: None。準備成功を大型読取授権と扱わない。
    """
    assert not (common.HERE/plan.ART_NAME).exists() and not (common.HERE/'準備False.json').exists()
    before=common.sources();old=common.old_sources()
    preserved,preserved_sha=common.verify_preservation()
    copies={'price_features.py':'work/e01_fak_evidence_20261014/engine/price_votes.py',
            'volume_reference.py':'work/wave_v106/trade_gate/votes.py','normal_reference.py':'work/wave_v106/e01_trade_exit/features.py'}
    for target,source in copies.items():assert (common.HERE/target).read_bytes()==(common.ROOT/source).read_bytes()
    value=artificial.run();assert common.sources()==before and common.old_sources()==old
    value.update(source_SHA256=before,source111不変=True,旧源同bytes複製=copies)
    value['保存不具合初版保全']=dict(SHA256=preserved_sha,FalseSHA256=preserved['小資料']['診断False.json']['SHA256'],
        修正='completed_paper_directionをbool、元公開のcount/balanceをint/floatへ保存時cast。資格/経済/窓/順序変更0。',
        原読取計数=preserved['元読取計数'],修正後cache本文再読=0)
    retained=common.HERE/'archive/初回人工のSELL資格期待誤りFalse保持/準備False.json'
    if retained.exists():value['初回False保全']=dict(path=retained.relative_to(common.ROOT).as_posix(),SHA256=common.digest(retained),
        原因='合成SELLの現在volume資格は通るのに、checkerが入口拒否95を期待した誤り。期待0へ訂正、未知100行の95も別確認。診断ルール変更0。')
    common.write(common.HERE/plan.ART_NAME,value)
    common.write(common.HERE/plan.PLAN_NAME,plan.prepared(common.digest(common.HERE/plan.ART_NAME)))
    print('SOURCE_ONLY人工 '+str(value['検査数'])+' 検査合格、本文0/金融0/API0。計画SHA '+common.digest(common.HERE/plan.PLAN_NAME),flush=True)


def fix_manifests() -> None:
    """
    機能: 初版fixedの同じ33組path/SHAを継承し、新源と保存修正理由へ束縛する。
    引数: なし。CLIの根小目録review完了flagが前提。
    返り値: None。原小目録3つ/cache/原NPZ/台帳本文の再読0。
    """
    assert not (common.HERE/plan.FIXED_NAME).exists() and not (common.HERE/'小目録固定False.json').exists()
    intent,intent_sha=common.read_json(common.HERE/plan.PLAN_NAME)
    art,art_sha=common.read_json(common.HERE/plan.ART_NAME)
    before=common.sources();assert intent['source_SHA256']==art['source_SHA256']==before and intent['人工SHA256']==art_sha
    preserved,preserved_sha=common.verify_preservation();original=preserved['小資料'][plan.FIXED_NAME]
    inherited,inherited_sha=common.read_json(common.ROOT/original['archive_path'])
    assert inherited_sha==original['SHA256'] and inherited['全合格']
    assert inherited['計画SHA256']==preserved['小資料'][plan.PLAN_NAME]['SHA256']
    assert inherited['人工SHA256']==preserved['小資料'][plan.ART_NAME]['SHA256']
    assert inherited['source_SHA256']=={name:item['SHA256'] for name,item in preserved['原23source'].items()}
    sessions=inherited['sessions'];assert len(sessions)==33 and len(set(sessions))==33 and set(inherited['inputs'])==set(sessions)
    fingerprints=inherited['input_manifests']
    inputs={}
    for session in sessions:
        inputs[session]={}
        for name,base in (('TradeGate','work/wave_v106/e01_trade_gate/input'),('TradeExit','work/wave_v106/e01_trade_exit/input')):
            item=dict(inherited['inputs'][session][name]);path=(common.ROOT/item['path']).resolve()
            assert path.is_relative_to((common.ROOT/base).resolve()) and len(item['SHA256'])==64 and all(c in '0123456789abcdef' for c in item['SHA256'])
            assert path.is_file() and item['stat_bytes']==path.stat().st_size
            inputs[session][name]=item
    assert inputs==inherited['inputs'] and fingerprints==inherited['input_manifests']
    assert common.sources()==before
    common.write(common.HERE/plan.FIXED_NAME,dict(全合格=True,source_SHA256=before,計画SHA256=intent_sha,人工SHA256=art_sha,
        input_manifests=fingerprints,sessions=sessions,inputs=inputs,小目録追加読取数=0,初版owned_fixed一読=1,cache_stat数=66,
        初版入力固定SHA256=inherited_sha,初版保全SHA256=preserved_sha,元本文読取履歴=preserved['元読取計数'],
        修正後大型本文読取=0,金融=0,API=0,再読目的=intent['再読理由'],
        補完='初版が束縛済みの最終TradeExit目録/有限時計補完を継承。元目録3の内容再読0、全66path/SHA/stat不変。'))
    print('初版33組path/SHA/statを不変継承、本文再読0。固定SHA '+common.digest(common.HERE/plan.FIXED_NAME),flush=True)


def load(item: dict,name: str,counts: Counter,seen: set) -> dict:
    """
    機能: 明示固定cacheを同bytes一読し、SHA検算後だけ展開する。
    引数: item(dict)、name(str)、counts(Counter)、seen(set) は位置指紋と読取台帳。
    返り値: dict は保存packet。原板/NPZ/金融/実台帳を読まない。
    """
    path=(common.ROOT/item['path']).resolve();key=str(path);assert key not in seen
    assert path.is_relative_to((common.ROOT/('work/wave_v106/e01_trade_gate/input' if name=='TradeGate' else 'work/wave_v106/e01_trade_exit/input')).resolve())
    seen.add(key);counts[name+'本文読取試行']+=1
    saved=path.read_bytes();counts[name+'本文一読']+=1
    assert hashlib.sha256(saved).hexdigest()==item['SHA256'],item['path']
    return pickle.loads(gzip.decompress(saved))


def execute(counts: Counter) -> None:
    """
    機能: 根が固定・授権したcache33組を各一読し、全場診断射影を保存する。
    引数: counts(Counter) は失敗時にも残す読取計数。
    返り値: None。金融再生/試行登録/原データ取得を行わない。
    """
    fixed,fixed_sha=common.read_json(common.HERE/plan.FIXED_NAME)
    intent,intent_sha=common.read_json(common.HERE/plan.PLAN_NAME)
    before=common.sources();old=common.old_sources()
    assert fixed['全合格'] and fixed['source_SHA256']==intent['source_SHA256']==before
    assert fixed['計画SHA256']==intent_sha and fixed['人工SHA256']==intent['人工SHA256']
    assert common.digest(common.HERE/plan.ART_NAME)==fixed['人工SHA256']
    assert old==intent['source111不変の確認対象']
    common.write(common.HERE/'診断開始guard.json',dict(source_SHA256=before,固定SHA256=fixed_sha,金融=0,自動再開始=False))
    outputs={};seen=set();started=time.monotonic()
    for session in fixed['sessions']:
        counts['処理中場順']=fixed['sessions'].index(session)+1
        gate=load(fixed['inputs'][session]['TradeGate'],'TradeGate',counts,seen)
        ex=load(fixed['inputs'][session]['TradeExit'],'TradeExit',counts,seen)
        assert gate['session']==ex['session']==session
        value=analysis.analyze(gate,ex);outputs[session]=value;counts['完了場']+=1
        del gate,ex,value;gc.collect();print(session+' strictjoin/PUB/継続窓診断、金融0',flush=True)
    assert counts['TradeGate本文一読']==counts['TradeExit本文一読']==counts['完了場']==33 and len(seen)==66
    assert common.sources()==before and common.old_sources()==old
    common.verify_preservation()
    common.write(common.HERE/'元公開と紙上継続窓の資格診断.json',dict(全合格=True,状態='非金融観測診断。新入口/取引/勝率/利益機会の検証ではない。',
        source_SHA256=before,source111不変=True,固定SHA256=fixed_sha,計画SHA256=intent_sha,input_manifests=fixed['input_manifests'],
        sessions=fixed['sessions'],cases=outputs,読取計数=dict(counts),初版保存FalseSHA256=intent['初版保全']['FalseSHA256'],
        元本文読取履歴=fixed['元本文読取履歴'],今回別目的再読=intent['再読理由'],
        金融=0,元111実台帳=0,原NPZ=0,原board=0,API=0,
        注意=['全normalBUY/SELLと紙上方向条件付き区間は別母集団。','normal行や連続資格区間を独立機会/正答率と呼ばない。',
             '実busy/FAK失効/場停止のexactstateは未測。','未来MFE/勝ち方向や心理を現在資格へ使わない。'],経過秒=time.monotonic()-started))
    print('非金融33組診断完了。結果SHA '+common.digest(common.HERE/'元公開と紙上継続窓の資格診断.json'),flush=True)


def main() -> None:
    """
    機能: 人工・小目録固定・本文診断を別CLIと明示授権で開始する。
    引数: CLI --prepare/--fix-small-manifests/--run、根review完了flag(bool)。
    返り値: None。失敗と読取計数を保全して自動再開始しない。
    """
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare',action='store_true');group.add_argument('--fix-small-manifests',action='store_true');group.add_argument('--run',action='store_true')
    parser.add_argument('--root-metadata-review-complete',action='store_true');parser.add_argument('--root-input-review-complete',action='store_true')
    args=parser.parse_args();counts=Counter()
    if args.prepare:kind='準備';assert not args.root_metadata_review_complete and not args.root_input_review_complete
    elif args.fix_small_manifests:kind='小目録固定';assert args.root_metadata_review_complete and not args.root_input_review_complete
    else:
        kind='診断';assert args.root_input_review_complete and not args.root_metadata_review_complete
        assert not any((common.HERE/name).exists() for name in ('診断開始guard.json','診断False.json','元公開と紙上継続窓の資格診断.json'))
    try:
        if args.prepare:prepare()
        elif args.fix_small_manifests:fix_manifests()
        else:execute(counts)
    except Exception:
        common.write(common.HERE/(kind+'False.json'),dict(全合格=False,原因=traceback.format_exc(),読取計数=dict(counts),source_SHA256=common.sources(),
            測定できた範囲='失敗前にstrictjoinを完了した場だけ。未完了を成功又は零資格へ補完しない。',
            不足の扱い='不一致列/型/source/系譜を原因に記録し根へ戻す。金融へ進めない。',金融=0,原NPZ=0,元実台帳=0,API=0,自動再開始=False))
        raise


if __name__=='__main__':main()
