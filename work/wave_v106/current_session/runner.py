"""登録後だけ現在Nightの固定3政策を接頭再生し、実現と残玉清算価を分離する。"""

import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import time

import numpy as np

import common
import core
import partial_accounting


TRIAL_ID='106_未見現ナイト接頭の固定三政策答え合わせ'
META=common.HERE/'未完了ナイトの入力準備.json'
DRAFT=common.HERE/'現在ナイト三政策の試行計画草案.json'
PLAN=common.HERE/'現在ナイト三政策の試行計画.json'
FIXED=common.HERE/'現在金融の結果前固定.json'
ARTIFICIAL=common.HERE/'接頭会計と新規約定及び未返済の人工検査.json'


def runtime(install: bool=False) -> object:
    """
    機能: 確定interface/engineの同一bytesを私有域へ複製し、新JITも現在場だけに隔離する。
    引数: install(bool)は金融前の人工段階で未存在snapshotを作る指定。
    返り値: objectは数学不変の私有interface。旧source/cacheへ書かない。
    """
    previous=common.ROOT/'work/wave_v106/range_price';target=common.HERE/'finance_runtime'
    for name in ('interface.py','engine/core.py'):
        path=target/name;source=previous/name
        if install and not path.exists():path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(source.read_bytes())
        assert path.exists() and common.digest(path)==common.digest(source)
    return common.module('106現在場の数学不変range接口',target/'interface.py')


def sources() -> dict:
    """
    機能: 固定旧入力源に、新consumer/独立partial会計/私有執行のSHAを追加する。
    引数: なし。
    返り値: dict[str,str]は小source指紋。現在NDJSON又は入力gzipを再hashしない。
    """
    before=json.loads((common.HERE/'現在入力の結果前固定.json').read_text(encoding='utf8'))
    result=dict(before['source_SHA256'])
    for name in ('runner.py','partial_accounting.py','finance_artificial.py','finance_runtime/interface.py','finance_runtime/engine/core.py'):
        path=common.HERE/name;result[path.relative_to(common.ROOT).as_posix()]=common.digest(path)
    return result


def check_sources(values: dict) -> None:
    """
    機能: 金融前固定sourceの開始/終端一致を検査する。
    引数: values(dict[str,str])はroot相対path→SHA。
    返り値: None。不一致を救済せず停止する。
    """
    for path,expected in values.items():assert common.digest(common.ROOT/path)==expected,path


def draft() -> None:
    """
    機能: 未取得のまま新データ3接頭政策の八部品草案を保存する。
    引数: なし。
    返り値: None。本文/現在入力gzip/金融結果を読まない。
    """
    assert not DRAFT.exists();proof=json.loads(ARTIFICIAL.read_text(encoding='utf8'));assert proof['全合格']
    assert proof['source_SHA256']==sources();check_sources(sources())
    original=json.loads((common.ROOT/'work/wave_v106/range_price/試行計画.json').read_text(encoding='utf8'))
    spec=deepcopy(original['spec']);spec['entry']['conditions']=core.configs();spec['entry']['condition_count']=3
    spec['entry']['modes']='事前固定AUTO_ER40_M2_LIMIT、R_ONLY_ER40_M2_LIMIT、C_ONLY_B2_ER40_B4のみ。C_ONLYはAUTOから価格Rを除き旧C全行資格へ復元。'
    spec['management']['prefix']='取得後の価格を追加せず、未約定/未返済を残す。通常end/limit/force/cutは変更しない。'
    spec['exit']['finish']='finish=False接頭。元の予定退出だけ、取得最終quoteの人工強制清算なし。'
    spec['allocation']['C_ONLY_comparison']='旧C_ONLY2bp/ER0.4/B4相当を同じ初回TOP5/NK10で接頭因果実行。過去全量を現在場へ流用しない。'
    spec['execution']['endpoint']='未返済は当時正常bid/askのentry料/残返済料込み清算代理。実際の返済又は全Night収支とは表示しない。'
    spec['data']=dict(sessions=[core.SESSION],
        input_manifests=[dict(path='work/wave_v106/current_session/現在入力の結果前固定.json',sha256=common.digest(common.HERE/'現在入力の結果前固定.json'))],
        known='過去33既知場とは分離した未見1Night接頭。根が各book1回、Completeトレーラーと同世代を確認。',
        source='根current_capture保存NDJSON各1抽出。consumerは完了新gzip1読取のみ、原本/旧33/API0。',
        registration='現入力完了metadataの指紋を加えた最終計画を根が登録後、初めて金融を一回実行。')
    spec['implementation']=sources()
    value=dict(id=TRIAL_ID,name='未見現ナイトの反発単独・自動選択・追従単独の接頭答え合わせ',purpose='新データ',
        question='既知33場で条件を替えず固定した3政策は、未見の取得済みNight接頭でどの実現/残玉リスクになるか。',
        change='データだけ追加、三条件は取得前固定。未完了場のため全flat会計を使わず独立partial検算。',
        repeat_reason='既知33場と未見現在場を区別し、1回だけ取得した保存原行で答え合わせする。',
        compares_to=['106_純価格レンジ境界反発と二市場AUTO24対照'],
        prior_similar='同じ条件は歴史側で既検証。今回は未見データ追加であり、履歴条件の再探索ではない。',
        sacrifices=['通常終端前のため全Nightの成否は分からない。','未返済の清算代理は実約定損益ではない。',
            '受信時計不明、ラージ気配代理、mini/micro全量約定と待ち順位は未検証。'],
        evidence=[dict(path=ARTIFICIAL.relative_to(common.ROOT).as_posix(),sha256=common.digest(ARTIFICIAL))],
        spec=spec,状態='未取得/現在入力未読/金融0の草案。最終input manifest追加後に根check/registerを行う。')
    common.write(DRAFT,value);print('3接頭政策の八部品草案を保存、現金融0',flush=True)


def bind() -> None:
    """
    機能: 完了新入力の小metadataだけを最終計画へ結び、根登録前固定を保存する。
    引数: なし。
    返り値: None。gzip/本文/新金融をまだ読まず、条件再選定もしない。
    """
    assert not PLAN.exists() and not FIXED.exists();meta=json.loads(META.read_text(encoding='utf8'))
    assert meta['全合格'] and meta['session']==core.SESSION and meta['finish'] is False and meta['configs']==core.configs()
    for path,sha in meta['source_SHA256'].items():assert common.digest(common.ROOT/path)==sha,path
    value=json.loads(DRAFT.read_text(encoding='utf8'));check_sources(value['spec']['implementation'])
    assert value['spec']['entry']['conditions']==meta['configs']
    value['spec']['data']['input_manifests'].insert(0,dict(path=META.relative_to(common.ROOT).as_posix(),sha256=common.digest(META)))
    value['状態']='完了新入力metadataを固定、条件変更0。根の登録通知後だけ3×2接頭金融を実行する。'
    common.write(PLAN,value)
    common.write(FIXED,dict(全合格=True,session=core.SESSION,configs=core.configs(),source_SHA256=sources(),
        input_manifest_SHA256=common.digest(META),plan_SHA256=common.digest(PLAN),新金融再生=0,
        現入力gzip読取=0,金融対象口座=6,finish=False))
    print('現在入力metadataを3政策へ固定、登録待ち・金融0',flush=True)


def registered() -> bool:
    """
    機能: 共通台帳に固定3政策と実装版が正式登録されている事を確認する。
    引数: なし。
    返り値: boolは完全同一specの登録あり。未登録なら金融へ進まない。
    """
    trials=json.loads((common.ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json').read_text(encoding='utf8'))['trials']
    plan=json.loads(PLAN.read_text(encoding='utf8'));matches=[v for v in trials if v['id']==TRIAL_ID]
    assert len(matches)==1 and matches[0]['spec']==plan['spec']
    return True


def run() -> None:
    """
    機能: 登録済み3政策×2商品の新入力gzipを一読取し、接頭台帳/会計を保存する。
    引数: なし。
    返り値: None。原本/API/追加取得をせず、失敗は再実行せずFalseで保存する。
    """
    destination=common.HERE/'finance';assert not destination.exists() and registered()
    fixed=json.loads(FIXED.read_text(encoding='utf8'));assert fixed['全合格'] and fixed['configs']==core.configs()
    before=sources();assert before==fixed['source_SHA256'];check_sources(before)
    assert common.digest(META)==fixed['input_manifest_SHA256'] and common.digest(PLAN)==fixed['plan_SHA256']
    meta=json.loads(META.read_text(encoding='utf8'));saved=(common.ROOT/meta['cache']['path']).read_bytes()
    assert hashlib.sha256(saved).hexdigest()==meta['cache']['SHA256']
    packet=pickle.loads(gzip.decompress(saved));del saved;common.immutable(packet)
    assert packet['session']==core.SESSION and packet['configs']==core.configs()
    engine=runtime();result={};started=time.monotonic()
    for config in core.configs():
        result[config['id']]={}
        for symbol in core.SYMBOLS:
            prepared=packet['prepared'][symbol];normal=packet['normal_cases'][config['id']][symbol]
            output=engine.play(prepared,normal,config,quantity=config['quantity'][symbol],finish=False)
            account=partial_accounting.inspect(prepared['record'],output,normal,config)
            path=destination/'ledgers'/f"{config['id']}_{symbol}.pkl.gz"
            sha=common.write(path,dict(output=output,normal=normal,account=account,session=core.SESSION,symbol=symbol))
            account['ledger']=dict(path=path.relative_to(common.ROOT).as_posix(),SHA256=sha)
            result[config['id']][symbol]=account
            print(config['id']+' '+symbol+'：接頭会計・残玉検算が完成',flush=True)
            del output
    check_sources(before)
    common.write(destination/'結果.json',dict(全合格=True,session=core.SESSION,途中終端=True,finish=False,
        configs=core.configs(),cases=result,accounts=6,source_SHA256=before,開始終端source一致=True,
        入力metadataSHA256=common.digest(META),入力gzipSHA256=meta['cache']['SHA256'],試行計画SHA256=common.digest(PLAN),
        現入力gzip読取=1,新接頭金融口座=6,原本読取=0,旧33cache読取=0,API取得=0,実注文=0,
        所要秒=time.monotonic()-started,
        制限='未見1Nightの取得済み接頭。実現と未決済清算代理を分離、無取引を勝ちに含めない。全Night収支又は将来安定性とは呼ばない。'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='未見Nightの固定3接頭policyだけを登録後実行')
    modes=parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--draft-only',action='store_true');modes.add_argument('--bind-current-input',action='store_true')
    modes.add_argument('--root-current-finance-registered',action='store_true');args=parser.parse_args()
    if args.draft_only:draft()
    elif args.bind_current_input:bind()
    else:
        try:run()
        except BaseException as error:
            path=common.HERE/'現在接頭金融False.json'
            if not path.exists():common.write(path,dict(全合格=False,例外=repr(error),自動再実行=False,原本読取=0,API取得=0))
            raise
