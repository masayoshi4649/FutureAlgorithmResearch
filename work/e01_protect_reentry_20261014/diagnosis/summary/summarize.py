"""正式結果の再読なしで、一読診断射影から参加差・料金・具体損失の小結を作る。"""

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
from statistics import median


HERE=Path(__file__).resolve().parent
INPUT=HERE.parent/'十二条件の共通入口と再参加及び具体損失.json'
MODES=('ORIGIN','PULL','BREAK','ADAPTIVE')
LABELS={140:'親純利益目標',141:'親純損失停止',142:'親純益保護',151:'紙上全退出/方向撤回',
        152:'両市場の反対価格更新票',161:'場純損失停止',162:'場純利益停止',92:'予定静観',93:'場内期限'}
KINDS={0:'元paper公開',1:'新しい押し戻り回復',2:'新しい突破'}


def aggregation(parents: list[dict]) -> dict:
    """
    機能: 完結親の料金前後金額、価格代理保有秒、入口/出口別の分母を分ける。
    引数: parents(list[dict]) は保存射影中の同分類親。
    返り値: dict は算術小集計。feesが損失の唯一の原因とは断定しない。
    """
    net=sum(p['net_yen'] for p in parents);fees=sum(p['fees_yen'] for p in parents)
    negative=[p for p in parents if p['net_yen']<0]
    return dict(親数=len(parents),黒親=sum(p['net_yen']>0 for p in parents),赤親=len(negative),
        純収支=net,実支払料=fees,料金前粗収支=net+fees,
        料対純赤字額=fees/(-net) if net<0 else None,料比の分母='分類群の純収支が負ならその絶対額。利益/損失総額比とは別。',
        保有価格代理秒中央値=median([p['holding_price_proxy_seconds'] for p in parents]) if parents else None,
        赤親で一度純黒字=sum(p['parent_mfe_yen']>0 for p in negative),赤親分母=len(negative),
        赤親で一度保護arm到達=sum(p['arm_yen'] is not None and p['parent_mfe_yen']>=p['arm_yen'] for p in negative),
        出口理由={LABELS.get(k,str(k)):v for k,v in Counter(p['exits'][0]['reason'] for p in parents).items()})


def compact(parent: dict) -> dict:
    """
    機能: 入口/反対票/紙上撤回/損失線と費用後ピーク返しを具体時点へ結ぶ。
    引数: parent(dict) は一読射影の実親。
    返り値: dict は原seq/BBO/数量/代理時計の小例。未来高安は診断専用。
    """
    entry=parent['entry'];exit_event=parent['exits'][0]
    return dict(session=parent['session'],symbol=parent['symbol'],actual_parent=parent['parent'],paper_parent=parent['paper_parent'],
        actual_uid=parent['actual_uid'],side=parent['side'],entry_kind=KINDS[parent['publication_kind']],quantity=parent['entry_quantity'],
        公開=entry['判断'],公開価格限界=parent['published_price_cap'],公開不利許容呼値=parent['published_adverse_ticks'],
        公開自己票=[parent['published_own_count'],parent['published_own_balance']],公開相手票=[parent['published_peer_count'],parent['published_peer_balance']],
        初実約定=dict(price=entry['price'],**entry['約定']),退出判断=exit_event['判断'],
        最終実返済=dict(price=exit_event['price'],**exit_event['約定']),理由=LABELS.get(exit_event['reason'],str(exit_event['reason'])),
        判断時親損失線=exit_event['親純損失線'],判断時親利確線=exit_event['親純利益線'],判断時発動保護線=exit_event['発動後保護線'],
        保有価格代理秒=parent['holding_price_proxy_seconds'],実往復料=parent['fees_yen'],粗収支=parent['net_yen']+parent['fees_yen'],純収支=parent['net_yen'],
        実保有中事後ピーク=parent['parent_mfe_yen'],ピーク点=parent['first_parent_liquidation_argmax'],
        実保有中事後最悪清算=parent['worst_parent_liquidation_yen'],最悪点=parent['first_parent_liquidation_argmin'],
        ピークから最終へ返した額=parent['peak_returned_yen'],ピーク対目標=parent['peak_target_ratio'],ピーク対arm=parent['peak_arm_ratio'])


def run() -> None:
    """
    機能: 全十二条件の悪化寄与と各赤字上位三場を診断射影だけから保存する。
    引数: なし。
    返り値: None。正式結果/原packet/台帳/金融は再読又は再実行しない。
    """
    saved=INPUT.read_bytes();data=json.loads(saved.decode('utf-8'));input_sha=hashlib.sha256(saved).hexdigest()
    assert input_sha=='b61765c7e87b99d38587e34d29655b6df41ca6c381d8b436d4a38db618dd2847'
    assert data['結果SHA256']=='c0103c4817c39891f872f18d6491fdd8d8ad171a98b8053842558626d463f02f'
    spec=importlib.util.spec_from_file_location('保存済み再参加差の純算術',HERE.parent/'analysis.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    groups={};worse={};incremental={};october={};checks=0
    for cid,parents in data['parents'].items():
        groups[cid]={};worse[cid]={};october[cid]=[]
        for s in ('TOPIX','NK225'):
            own=[p for p in parents if p['symbol']==s]
            m=aggregation(own);m['入口種別']={KINDS[k]:aggregation([p for p in own if p['publication_kind']==k]) for k in KINDS}
            m['買売']={str(k):aggregation([p for p in own if p['side']==k]) for k in (1,-1)}
            m['昼夜']={kind:aggregation([p for p in own if p['session'].endswith('_'+kind)]) for kind in ('Day','Night')}
            m['全33場平均純収支']=m['純収支']/33;m['活動場']=data['summaries'][cid][s]['active_sessions'];groups[cid][s]=m
            assert m['純収支']==data['summaries'][cid][s]['net_yen'];checks+=1
            worst=[]
            baseline='E01_PROTECT_ORIGIN_'+cid.rsplit('_',1)[-1] if cid.endswith('_TARGET') else (
                'E01_PROTECT_ORIGIN_TIGHT_TRAIL' if cid.endswith('_TIGHT_TRAIL') else 'E01_PROTECT_ORIGIN_WIDE_TRAIL')
            for entry in data['worst_details'][cid][s]['worst_three_red_sessions']:
                session=entry['row']['session'];own_scene=entry['parents']
                original=[p for p in data['parents'][baseline] if p['symbol']==s and p['session']==session]
                difference=module.comparison(original,own_scene)
                worst.append(dict(session=session,場会計=entry['row'],実親集計=aggregation(own_scene),
                    同出口ORIGINとの差={k:difference[k] for k in ('net_difference_yen','avoided_baseline_loss_yen','missed_baseline_profit_yen',
                        'common_entrance_quantity_or_exit_difference_yen','new_entrance_net_yen','common_count','removed_count','added_count')},
                    最大損失二親=[compact(p) for p in sorted(own_scene,key=lambda p:(p['net_yen'],p['parent']))[:2]]))
            worse[cid][s]=worst
        for item in data['topix_20261002_night_buy'][cid]:
            october[cid].append(dict(広気配参照時計との関係=item['classification'],**compact(item['parent'])))
        if cid in data['comparisons_to_same_exit_origin']:
            incremental[cid]={}
            for s,d in data['comparisons_to_same_exit_origin'][cid].items():
                added=d['added_parents'];m=aggregation(added)
                assert m['純収支']==d['new_entrance_net_yen'];checks+=1
                incremental[cid][s]=dict(五寄与={k:d[k] for k in ('net_difference_yen','avoided_baseline_loss_yen','missed_baseline_profit_yen',
                    'common_entrance_quantity_or_exit_difference_yen','new_entrance_net_yen','common_count','removed_count','added_count')},
                    追加親だけの実料前後=m,
                    失った入口=data['comparisons_to_same_exit_origin'][cid][s]['missing_baseline_entrances'])
    statements=[
        '全十二条件は両商品で純赤字。PULLは元入口TOP29/NK27を全て保ち、共通親純収支差は全三出口で零。追加geometry参加が損失を増やした。',
        'TARGETでPULLの追加57/61親はTOP−117652円（料47652円、粗−70000円）/NK−140840円（料26840円、粗−114000円）。費用だけでは説明できない。',
        'TARGETでBREAKはTOP追加160親−958760円、NK追加164親−480160円。ADAPTIVEはTOP追加174親−1345464円、NK追加154親−513760円。一部元入口回避と共通差を含めても悪化した。',
        'ORIGIN_TARGETでもTOP29親中24が反対価格票、NK27親中13が反対価格票/9が親stopで退出。新価格票が短時間の順行継続を保証しない。',
        'ORIGINのTIGHTはTOPでTARGETより75000円改善し実料/参加親数は同じだが、合計は−114244円。NKでは4000円悪化した。低い保護の一部効果と新参加の害を分ける。',
        '10/2Night TOPのORIGIN買いは零。旧107買い親を保護で救った同親比較とはしない。BREAKの新買いは一度利益を得ても後参加で損し、ADAPTIVEの20:05/20:09買いは強い現在票でも負けた。',
        '21:29:50より前に降りた事実は確認できるが、広幅を避けたことで仮想利益を加算しない。MFEから別出口の救済利益を作らない。']
    out=dict(全合格=True,診断射影SHA256=input_sha,正式結果SHA256=data['結果SHA256'],source_SHA256=data['source_SHA256'],
        小結=statements,全条件商品別=groups,同出口元入口との悪化寄与=incremental,各条件赤字上位三場=worse,
        TOP_20261002Night_実買い=october,検算=checks,
        読取計数=dict(既診断射影=1,正式結果再読=0,packet=0,原board=0,NPZ=0,台帳=0,新金融=0,API=0),
        留保=['正常Last更新票は更新回数の方向割合で、順行値幅/板支持/出来高方向を測った証拠ではない。',
            '価格代理秒の保有時間。物理受信/注文応答時間ではない。現在支持/退出のpeer ageも価格時計差。',
            '事後ピークは当該実保有区間だけ。損失の日だけ将来閾値を変える改善案を測定済みとしない。'])
    target=HERE/'保護と再参加で損失が増えた原因の小結.json';assert not target.exists()
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('再参加小結合格。'+str(checks)+'集計確認。SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':run()
