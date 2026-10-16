"""ALIGNEDの既知無RとC同経済への派生根拠を、金融前に確認する。"""

import argparse
from pathlib import Path

import numpy as np

import catalog
import common
import data
import derivation
import selection


def run() -> None:
    """
    機能: 33入力でALIGNED全6のC同値を確かめ、旧基準ID/66行の目録を束縛する。
    引数: なし。新cache各一読、旧小結果目録と準備一致証跡のみを読む。
    返り値: None。金融関数/旧板/旧104/旧金融台帳は再生も読取もしない。
    """
    target=common.HERE/'ALIGNED全6の無RとC同入口の非金融確認.json';assert not target.exists()
    meta=common.read(data.METADATA);assert meta['全合格'] and len(meta['sessions'])==33
    prior,c_prior=derivation.baseline_metadata(meta['sessions'],catalog.catalog())
    source_path=common.ROOT/'work/wave_v106/range_price/全33場の価格境界反発準備.json'
    source=common.read(source_path);assert source['全合格'] and source['sessions']==meta['sessions']
    art_path=common.HERE/'実行部と半量C派生の結合人工検査.json';art=common.read(art_path);assert art['全合格']
    source_paths=[Path(__file__),common.HERE/'derivation.py',common.HERE/'catalog.py',common.HERE/'selection.py',
        common.HERE/'selection_snapshot.py',common.HERE/'features.py',common.HERE/'interface.py',common.HERE/'engine/core.py',common.HERE/'data.py']
    before={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in source_paths}
    checked={};count=0;candidate_count=0
    aliases=[cfg for cfg in catalog.catalog() if cfg['local_policy']=='ALIGNED'];assert len(aliases)==6
    for session in meta['sessions']:
        packet=data.load_session(session);values={}
        previous_count=sum(np.count_nonzero((packet['cases'][s]['C_OWN']['event']!=0)|(packet['cases'][s]['R_OWN']['event']!=0)) for s in ('TOPIX','NK225'))
        assert source['一致検査'][session]['旧候補値対応']==previous_count
        for symbol in ('TOPIX','NK225'):
            reference=derivation.c_normal(packet,symbol);values[symbol]={};candidate_count+=len(reference['decisions'])
            for cfg in aliases:
                normal=selection.build(packet,symbol,cfg);values[symbol][cfg['id']]=derivation.verify_alias(packet,symbol,normal);count+=1
        checked[session]=values
        del packet
    assert count==396
    assert before=={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in source_paths}
    common.write(target,dict(全合格=True,場数=33,商品口座数=66,alias照合口座数=count,条件数=6,元C候補数=candidate_count,
        checks=checked,開始終端source一致=True,source_SHA256=before,
        SHA256={p.relative_to(common.ROOT).as_posix():common.digest(p) for p in
            (data.METADATA,source_path,derivation.RANGE_RESULTS,derivation.C_RESULTS,art_path)},
        比較元ID=derivation.C_ID,基準AUTO一覧=sorted({cfg['base_id'] for cfg in catalog.catalog()}),
        元半量=dict(source_quantity={'TOPIX':10,'NK225':20},quantity={'TOPIX':5,'NK225':10},
            元片道料={'TOPIX':418,'NK225':220},派生片道料={'TOPIX':209,'NK225':110}),
        原理='旧入力準備が全C/R候補の六点値を旧regimeとexact照合した証跡を利用。現C_ONLYは同状態/同イベント式で再構成。C当行と静観mapは全一致、非event未使用値は全同値と主張しない。',
        新入力cache読取=33,旧金融台帳読取=0,新金融再生=0,原板読取=0,旧104読取=0,API取得=0,
        限界='ALIGNEDのR候補0は既知33期間だけ。この6を新しい反転成功又は独立金融証拠へ数えない。'))
    print('ALIGNED全6/33の無RとC同経済入力を確認、金融0',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='ALIGNED経済aliasの非金融証明')
    parser.add_argument('--input-equivalence-approved',action='store_true',required=True)
    parser.parse_args();run()
