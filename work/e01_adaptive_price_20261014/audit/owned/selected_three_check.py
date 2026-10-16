"""選択三場の小射影だけから、公開票・許容・費用後親と比較範囲を独立確認する。"""

from collections import Counter
from copy import deepcopy
from datetime import datetime,timezone,timedelta
from pathlib import Path
import hashlib
import importlib.util
import json
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
DIAG=ROOT/'work/e01_adaptive_price_20261014/diagnosis_selected'
spec=importlib.util.spec_from_file_location('八条件独立小会計',HERE/'adaptive_finance_check.py')
audit=importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
COUNTS=Counter();audit.COUNTS=COUNTS;audit.helper.COUNTS=COUNTS
same=audit.same
PATHS=(DIAG/'選択三場の票許容と旧勝ち及び後参加の具体診断.json',
       DIAG/'選択三場の票許容と後参加を確認する固定計画.json',
       HERE/'八適応条件528会計と旧24引用及び全実親両寄与の独立監査.json')
READS={}


def read_once(path: Path) -> dict:
    """
    機能: 明示小診断とその計画・既独立証跡だけを各一読する。
    引数: path(Path) は PATHS 内の小 JSON。
    返り値: dict は保存資料。金融 result・input・台帳は再読しない。
    """
    assert path in PATHS and path not in READS
    raw=path.read_bytes();READS[path]=hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def time_check(value: object) -> None:
    """
    機能: 価格代理 epoch と併記された JST を独立に照合する。
    引数: value(object) は再帰対象小射影。
    返り値: None。価格時計を受信・発注時計へ補完しない。
    """
    if isinstance(value,list):
        for item in value:time_check(item)
    elif isinstance(value,dict):
        for key,item in value.items():
            if item is not None and (key.endswith('price_time_s') or key=='受理価格時計'):
                expected=datetime.fromtimestamp(item,timezone(timedelta(hours=9))).isoformat()
                same(value[key+'_JST'],expected)
                COUNTS['価格代理JST']+=1
            time_check(item)


def main() -> None:
    """
    機能: 指定三場の小算術と新旧比較の範囲を監査し、未保存未約定試行の留保を記録する。
    引数: なし。根授権後に小資料だけ一読する。
    返り値: None。成功又は False を自所有域へ保存し共有知見を編集しない。
    """
    target=HERE/'選択三場の実親票許容料と比較範囲の独立監査.json'
    failed=HERE/'選択三場小診断の独立監査False.json'
    assert not target.exists() and not failed.exists()
    try:
        result,plan,previous=[read_once(p) for p in PATHS]
        assert all(p['全合格'] for p in (result,plan,previous))
        assert READS[PATHS[0]]=='a6c245a2d97e12aa7700df6e8af9861239d1997f3485a4358cb8be4fc8e0d56e'
        assert result['計画SHA256']==READS[PATHS[1]]
        assert result['小結果SHA256']==plan['小結果']['SHA256']==previous['正式結果SHA256']=='13f534a10b081db94944d723171214a2132829b66b70f177e0d3055b27116944'
        assert result['source_SHA256']==plan['source_SHA256']
        for name,sha in plan['source_SHA256'].items():assert hashlib.sha256((DIAG/name).read_bytes()).hexdigest()==sha
        assert result['小結果この目的読取数']==1
        for field in ('原input','台帳本文','金融','原板','NPZ','API','金融source変更'):same(result[field],0)
        assert len(result['対象三場'])==3 and len(plan['対象'])==3
        summary=[]
        for record,target_item in zip(result['対象三場'],plan['対象']):
            symbol,session=record['symbol'],record['session'];key=(session,symbol)
            same((symbol,session,record['selected_id'],record['old_comparison_id']),
                 (target_item['symbol'],target_item['session'],target_item['selected_id'],target_item['comparison_id']))
            config=record['selected_config'];same(config['id'],record['selected_id'])
            oldid=record['old_comparison_id'];old_gate,old_exec=oldid.split('_')[2:4]
            oldconfig=dict(min_votes=2,balance_threshold=.5 if old_gate=='G50' else .25,adverse_ticks=int(old_exec=='FAK1'))
            selected=audit.parent_check(record['actual_parents'],config,{key:record['selected_row']},config['id'])
            old=audit.parent_check(record['old_actual_parents'],oldconfig,{key:record['old_row']},oldid)
            same(record['net_change'],record['selected_row']['収支']-record['old_row']['収支'])
            removed=sorted(p[2] for p in old.keys()-selected.keys())
            same(sorted(p['parent'] for p in record['removed_old_parents']),removed)
            expected_rules=record['old_publication_under_selected_rule']
            assert {e['old_parent'] for e in expected_rules}=={p['parent'] for p in record['old_actual_parents']}
            for expectation in expected_rules:
                p=old[key+(expectation['old_parent'],)]
                gate=bool(p['published_known'] and p['published_direction_votes']>=config['min_votes'] and p['published_balance']>=config['balance_threshold'])
                allow=int(p['published_known'] and p['published_direction_votes']>=2 and p['published_balance']>=config['strong_balance_threshold'])
                tick=.5 if symbol=='TOPIX' else 10.
                cap=p['publication_ask']+tick*allow if p['side']==1 else p['publication_bid']-tick*allow
                same(expectation['gate_from_saved_publication'],gate)
                same(expectation['allowance_from_saved_publication'],allow)
                same(expectation['selected_cap_from_saved_publication'],cap)
                same(expectation['old_fill_price'],p['entry']['price'])
                same(expectation['old_fill_outside_selected_cap'],p['side']*(p['entry']['price']-cap)>0)
                assert '新アルゴの未約定試行BBOを補完' in expectation['definition']
                COUNTS['旧公開への新条件算術']+=1
            for execution,index in (('FAK0',0),('FAK1',1)):
                comparison=record['same_gate_comparisons'][execution]
                assert len(comparison)==1
                same(comparison[0]['baseline_id'],config['comparison_ids'][index])
                assert comparison[0]['symbol']==symbol and comparison[0]['session']==session
                same(comparison[0]['収支変化'],comparison[0]['避けた基準損失']-comparison[0]['失った基準利益']+comparison[0]['共通入口の数量/出口差']+comparison[0]['新たな入口の収支'])
            if symbol=='NK225':
                assert config['entry_id']=='G25' and old_gate=='G50'
                same_gate=record['same_gate_adaptive'];assert same_gate['id']=='E01_ADAPT_G50_ADAPT75_P1' and len(same_gate['rows'])==1
                same_config=deepcopy(config);same_config.update(entry_id='G50',balance_threshold=.5,strong_balance_threshold=.75)
                same_parents=audit.parent_check(same_gate['actual_parents'],same_config,{key:same_gate['rows'][0]},same_gate['id'])
                assert set(same_parents)==set(selected)
                for parent_key,p in selected.items():
                    other=same_parents[parent_key]
                    for field in ('parent','side','net_yen','fee_yen','entry','exits','publication_row','publication_raw_seq',
                                  'publication_price_time_s','published_balance','published_direction_votes','published_known',
                                  'actual_entry_quantity'):
                        same(other[field],p[field],'二場だけ同実親/約定/公開票。初受理尺度や許容全体の同値は要求しない。')
                same(same_gate['rows'][0],record['selected_row'])
                COUNTS['入口gateを揃えた補助二場']+=1
                retain='G25選択−G50固定0の場差は入口gateと許容変更を含む。補助G50適応75もこの二場は同実親/同価格/料/net。全33同値とは呼ばない。'
            else:
                assert config['entry_id']==old_gate=='G50'
                bad=[p for p in record['old_actual_parents'] if p['net_yen']<0]
                assert len(bad)==1 and bad[0]['published_balance']==.7 and bad[0]['published_direction_votes']==20
                e=next(v for v in expected_rules if v['old_parent']==bad[0]['parent'])
                assert e['gate_from_saved_publication'] and e['allowance_from_saved_publication']==0 and e['old_fill_outside_selected_cap']
                retain='旧.7/20票親は新入口門を通り許容0になる。旧約定が新cap外である算術だけ確認。新未約定tryのBBO/時刻/個別失効reasonは未保存で独立未確認。'
            d=record['fak_diagnosis'];assert len(d)==1
            first=d[0]['first_actual']
            if selected:
                p=min(selected.values(),key=lambda x:x['entry']['row'])
                same(first['row'],p['entry']['row']);same(first['source_row'],p['publication_row'])
                same(first['paper_parent'],p['parent']);same(first['quantity'],p['actual_entry_quantity'])
                same(first['price'],p['entry']['price'])
            time_check(record)
            summary.append(dict(symbol=symbol,session=session,selected_id=record['selected_id'],old_id=oldid,
                old_net=record['old_row']['収支'],selected_net=record['selected_row']['収支'],net_change=record['net_change'],
                新実親=[dict(parent=p['parent'],net=p['net_yen'],balance=p['published_balance'],votes=p['published_direction_votes'],allowance=p['published_adverse_ticks'],
                    entry=p['entry'],exits=p['exits']) for p in selected.values()],留保=retain))
        output=dict(全合格=True,検査=dict(COUNTS),小資料一読SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            三場独立確認=summary,結論='公開票/許容/capと実親の料/正気配/net及び比較の範囲は整合。未保存の新未約定試行を実績へ補完していない。',
            留保=['対象の選定は金融完了後に旧不振場を診断するため固定したもので、金融前の未知事例選定ではない。',
                'same_gate_comparisonsはselected G25又はG50と同入口の固定0/1対照。NKの冒頭old_comparison_id G50との差と混ぜない。',
                '同入口G50補助が二場で同実親なので、gate変更だけが改善原因という説明は避けられる。全33・全候補の同値証明ではない。',
                '価格代理JSTは受信時計・発注時計ではない。未約定の新tryBBO、板厚/補充、元参加者の心理は未測。'],
            独立sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            金融result再読=0,大入力=0,台帳再読=0,金融再実行=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,検査=dict(COUNTS),三場=[(r['symbol'],r['session'],r['old_net'],r['selected_net']) for r in summary],
            SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),小資料読取SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},検査=dict(COUNTS),
            金融result再読=0,入力=0,台帳=0,金融=0,API=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
