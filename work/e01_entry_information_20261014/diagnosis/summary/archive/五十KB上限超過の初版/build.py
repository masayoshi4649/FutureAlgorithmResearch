"""一読済み診断射影だけから、全親を再コピーしない五十KB以内の小結を保存する。"""

from collections import Counter
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
DIAGNOSIS=HERE.parent
ROOT=DIAGNOSIS.parents[2]
SOURCE=DIAGNOSIS/'出来高代理入口の金額分解と具体損失及びPRICE保存比較.json'


def compact(parent: dict,index: int,case_id: str) -> dict:
    """
    機能: 一実親の公開/約定/退出と票・BBO・純損益だけを短い観測配列へ射影する。
    引数: parent(dict)、index(int)、case_id(str) は既射影の親と参照位置。
    返り値: dict は全経路を再コピーしない代表例。事後峰値を救済利益へ変換しない。
    """
    info=parent['entry_information'];volume=info['volume'];own=info['published_price_own'];peer=info['published_price_peer']
    def point(p: dict) -> list:
        """
        機能: 保存済み観測点を共通列順に並べる。
        引数: p(dict) は既保存の価格代理観測点。
        返り値: list はrow/seq/代理JST/BBO/局所清算/紙上残量。欠測を零にしない。
        """
        return [p['normal_row'],p['raw_seq'],p['JST_price_proxy'],p['bid'],p['ask'],p['parent_liquidation_yen'],p['paper_remaining_quantity']]
    exit_event=parent['exits'][0]
    pub=parent['entry']['判断'];actual=parent['entry']['約定'];side=parent['side']
    cap0_firstquote=actual['ask']<=pub['ask'] if side>0 else actual['bid']>=pub['bid']
    return dict(session=parent['session'],parent=parent['parent'],paper_parent=parent['paper_parent'],uid=parent['actual_uid'],side=side,
        q=parent['entry_quantity'],pub=point(pub),entry=point(actual),exit_decision=point(exit_event['判断']),exit=point(exit_event['約定']),
        peak=point(parent['first_parent_liquidation_argmax']),minimum=point(parent['first_parent_liquidation_argmin']),
        prices=[parent['entry']['price'],exit_event['price']],exit_reason=exit_event['reason_label'],
        volume=[volume['known'],volume['direction_votes'],volume['balance']],
        price=[own['known'],own['count'],own['side_balance'],peer['known'],peer['count'],peer['side_balance'],info['price_accepted']],
        allowance=[parent['published_adverse_ticks'],parent['published_price_cap']],
        cap0_same_firstquote_price_condition=cap0_firstquote,
        economics=[parent['gross_direction_mid_yen'],parent['crossing_disadvantage_yen'],parent['order_fees_yen'],parent['net_yen'],
            parent['parent_mfe_yen'],parent.get('target_yen'),parent['parent_stop_yen']],
        pointer='/all_parent_decomposition/'+case_id+'/'+str(index))


def metric(parents: list[dict]) -> dict:
    """
    機能: 観測完結親の分母と金額分解だけを集計する。
    引数: parents(list[dict]) は同条件又は診断分類の実親。
    返り値: dict は件数/正負額。公開資格率又は未来勝率を推定しない。
    """
    mid=sum(p['gross_direction_mid_yen'] for p in parents);cross=sum(p['crossing_disadvantage_yen'] for p in parents)
    fees=sum(p['order_fees_yen'] for p in parents);net=sum(p['net_yen'] for p in parents)
    assert abs(mid-cross-fees-net)<.0001
    return dict(n=len(parents),black=sum(p['net_yen']>0 for p in parents),red=sum(p['net_yen']<0 for p in parents),net=net,
        mid=mid,cross=cross,fees=fees,negative_once_positive=sum(p['net_yen']<0 and p['parent_mfe_yen']>0 for p in parents),
        negative_mid_reverse=sum(p['net_yen']<0 and p['gross_direction_mid_yen']<0 for p in parents))


def run() -> None:
    """
    機能: 全九表示の集計・各赤字三場の一親と商品別勝ち反証を小結へ固定する。
    引数: なし。
    返り値: None。新結果/packet/旧台帳/元金融/board/APIを再読しない。
    """
    saved=SOURCE.read_bytes();sha=hashlib.sha256(saved).hexdigest();data=json.loads(saved.decode('utf-8'))
    assert data['全合格'] and data['読取']['新110結果']==1
    aggregates={};examples={};counterexamples={};activity={};index_map={}
    for cid,parents in data['all_parent_decomposition'].items():
        index_map[cid]={(p['session'],p['symbol'],p['parent']):i for i,p in enumerate(parents)}
        aggregates[cid]={};examples[cid]={};activity[cid]={}
        for symbol in ('TOPIX','NK225'):
            own=[p for p in parents if p['symbol']==symbol];s=data['summaries'][cid][symbol]
            cross_groups={label:metric([p for p in own if p['entry_information']['price_accepted']==accepted])
                for label,accepted in (('価格も通過',True),('価格不通過で出来高採用',False))}
            aggregates[cid][symbol]=dict(actual_financial=s['actual_financial'],source_id=s['economic_source_id'],
                all=metric(own),price_qualification=cross_groups,
                first_last={label:metric([p for p in own if p['session'] in {q['session'] for q in parents if q['symbol']==symbol} and
                    p['session'] in ([r['session'] for r in data['paired_saved_price'][cid][symbol]['by_session']][:16] if label=='前16' else
                        [r['session'] for r in data['paired_saved_price'][cid][symbol]['by_session']][16:])]) for label in ('前16','後17')},
                day_night={label:metric([p for p in own if p['session'].endswith('_'+label)]) for label in ('Day','Night')},
                buy_sell={label:metric([p for p in own if p['side']==side]) for label,side in (('買',1),('売',-1))},
                exit_reasons=s['exit_reasons'])
            values=[v for v in data['activity'][cid] if v['symbol']==symbol]
            activity[cid][symbol]={key:sum(v[key] for v in values) for key in ('候補','受理','新規fill','一回FAK失効','未試行取消')}
            if not s['actual_financial']:
                examples[cid][symbol]=dict(alias_reference=s['economic_source_id'],independent_evidence=False);continue
            examples[cid][symbol]=[]
            for scene in data['worst_three_red_sessions'][cid][symbol]:
                selected=scene['maximum_two_negative_parents'][0]
                pos=index_map[cid][selected['session'],symbol,selected['parent']]
                examples[cid][symbol].append(dict(session_net=scene['row']['収支'],example=compact(selected,pos,cid)))
    cid='E01_INFO_VOL_SELECTED_TARGET';sparse={}
    for symbol in ('TOPIX','NK225'):
        own=[p for p in data['all_parent_decomposition'][cid] if p['symbol']==symbol]
        thin=[p for p in own if p['published_adverse_ticks']==1 and (p['published_own_count']<2 or p['published_peer_count']<2)]
        sparse[symbol]=dict(metric=metric(thin),cap0_same_firstquote_pass=sum(
            p['entry']['約定']['ask']<=p['entry']['判断']['ask'] if p['side']>0 else p['entry']['約定']['bid']>=p['entry']['判断']['bid'] for p in thin))
        counterexamples[symbol]=[]
        for predicate in (lambda p:not p['entry_information']['price_accepted'],
            lambda p:p['published_adverse_ticks']==1 and (p['published_own_count']<2 or p['published_peer_count']<2)):
            winners=sorted((p for p in own if p['net_yen']>0 and predicate(p)),key=lambda p:(-p['net_yen'],p['session'],p['parent']))
            if not winners:continue
            p=winners[0];pos=index_map[cid][p['session'],symbol,p['parent']]
            if all(v['pointer']!='/all_parent_decomposition/'+cid+'/'+str(pos) for v in counterexamples[symbol]):counterexamples[symbol].append(compact(p,pos,cid))
    out=dict(全合格=True,source=dict(path=SOURCE.relative_to(ROOT).as_posix(),SHA256=sha,結果SHA256=data['結果SHA256']),
        source_scope='一読済み110射影だけ。新495唯一口座/366親、NK99は内部alias、PRICE198は旧保存小会計。',
        denominator='各条件・商品・当該政策で実新規から全量返済まで完結した親。元paper候補/公開資格数/勝率予測へ一般化しない。',
        point_columns=['normal_row','raw_seq','JST_price_proxy','bid','ask','parent_local_liquidation','paper_remaining_quantity'],
        volume_columns=['known','direction_votes','already_signed_balance'],
        price_columns=['own_known_or_unsaved_None','own_count','own_side_balance','peer_known','peer_count','peer_side_balance','saved_price_accepted'],
        economics_columns=['mid_direction_gross','crossing_disadvantage','actual_order_fees','net','observed_parent_peak','fixed_target_or_None','parent_stop'],
        aggregates=aggregates,activity=activity,worst_three_one_parent=examples,winning_counterexamples=counterexamples,sparse_price_FAK1=sparse,
        findings=['SELECTED_TARGETのTOPはmid方向+112500−横断112500−料15048＝−15048、18親の負12/12はmid自体逆行、一度黒字9/12。',
            '同NKは+219000−101000−16280＝+101720、37親の負19/19はmid自体逆行、一度黒字14/19。費用だけを敗因としない。',
            'price不通過・volume採用はTOP10親4勝6負+56640、NK20親11勝9負+83200。単純ANDへ戻す案には勝ち喪失の反証がある。',
            'TOPのTIGHTはTARGETより15000悪化、NKも24000悪化。単純な保護幅調整だけで改善したとは言えない。'],
        next_component_hypothesis=dict(rule='1T追随許容に現在両価格票各2以上も要求し、不足時は入口を消さず0Tへ落とす。既volume資格/出口/枚数は同じ。',
            rationale='1票balance1を複数更新による強支持と同一視する問題を分ける。現在1Tかつ価格どちらか2票未満はTOP3親0勝3負−62508、NK5親2勝3負+1800。',
            falsification='NKの同薄票群に勝ち2親がある。cap0でも同firstquoteが通る親があり、群の損益を削って改善額にしない。',
            status='未実装/未検証。既試行照合と結果前固定後に全feed再運転し、失効後の参加/busy/後損益を含む対照が必要。'),
        limits=['横断不利は実約定grossの分解。既netへ追加費用として二重控除しない。',
            '全候補のvolume×price交差資格は未保存。ここは完結実親の交差分類、activity受理/fill/失効とは別の分母。',
            'own_known単独列は未保存None。PRICE旧親対応/経路は未保存で共通親効果は未測。',
            '時刻は価格代理時計。事後MFEは既実保有期間だけ、別出口救済利益又は当時の採否入力にしない。',
            '現強さ群の敗/勝は同33場の観測記述。未来勝率又は新部品の改善を保証しない。'])
    target=HERE/'出来高代理入口の逆行と気配不利及び勝ち反証の小結.json';assert not target.exists()
    rendered=json.dumps(out,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    assert len(rendered.encode('utf-8'))<=50*1024,len(rendered.encode('utf-8'))
    target.write_text(rendered,encoding='utf-8')
    print('bounded小結 '+str(len(rendered.encode('utf-8')))+'bytes SHA '+hashlib.sha256(target.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':run()
