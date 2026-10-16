"""一読済み111比較射影から、五寄与と具体時刻を五十KiB以内へ保存する。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SOURCE=HERE.parent/'FAK追随票の新旧親対応と実価格損失の診断.json'


def compact(p: dict,pointer: str) -> dict:
    """
    機能: 既射影の一実親を公開/約定/退出と票・金額だけへ射影する。
    引数: p(dict)、pointer(str) は既保存親と出典位置。
    返り値: dict は代表観測点。全経路又は旧金融をコピーしない。
    """
    def point(v: dict) -> list:
        """
        機能: 原seqと代理時計/BBO/親局所清算を共通列順へ写す。
        引数: v(dict) は保存観測点。
        返り値: list は未補完の点。Noneを零にしない。
        """
        return [v['normal_row'],v['raw_seq'],v['JST_price_proxy'],v['bid'],v['ask'],v['parent_liquidation_yen']]
    pub=p['entry']['判断'];e=p['entry']['約定'];x=p['exits'][0];v=p['entry_information']['volume']
    own=p['entry_information']['published_price_own'];peer=p['entry_information']['published_price_peer']
    cap0=e['ask']<=pub['ask'] if p['side']>0 else e['bid']>=pub['bid']
    return dict(session=p['session'],parent=p['parent'],paper_parent=p['paper_parent'],uid=p['actual_uid'],side=p['side'],q=p['entry_quantity'],
        pub=point(pub),entry=point(e),exit_decision=point(x['判断']),exit=point(x['約定']),
        prices=[p['entry']['price'],x['price']],reason=x['reason_label'],volume=[v['known'],v['direction_votes'],v['balance']],
        price=[own['known'],own['count'],own['side_balance'],peer['known'],peer['count'],peer['side_balance'],p['entry_information']['price_accepted']],
        allowance=[p['published_adverse_ticks'],p['published_price_cap']],cap0_same_old_firstquote_pass=cap0,
        economics=[p['gross_direction_mid_yen'],p['crossing_disadvantage_yen'],p['order_fees_yen'],p['net_yen'],p['parent_mfe_yen'],p.get('target_yen'),p['parent_stop_yen']],
        peak_time=p['first_parent_liquidation_argmax']['JST_price_proxy'],pointer=pointer)


def run() -> None:
    """
    機能: 同公開五寄与/赤字三場/失勝/新負親と0T共通親を小結へ保存する。
    引数: なし。
    返り値: None。新旧金融本文/旧診断原本/input/ledger/APIの追加読取はしない。
    """
    saved=SOURCE.read_bytes();sha=hashlib.sha256(saved).hexdigest();data=json.loads(saved.decode('utf-8'));assert data['全合格']
    assert data['読取']['新111結果']==data['読取']['旧110診断']==1
    aggregates={};red_examples={};activity={}
    for cid,by_symbol in data['summaries'].items():
        aggregates[cid]={};red_examples[cid]={};activity[cid]={}
        old_id=cid.replace('E01_EVID_','E01_INFO_')
        for symbol,s in by_symbol.items():
            change=data['paired_parents'][cid][symbol]
            aggregates[cid][symbol]=dict(actual_financial=s['actual_financial'],source_id=s['source_id'],
                new={k:s[k] for k in ('parent_count','net_yen','gross_direction_mid_yen','crossing_disadvantage_yen','fees_yen','positive_parents','negative_parents','negative_once_positive')},
                old={k:s['old'][k] for k in ('parent_count','net_yen')},five_contribution=change['contribution'],
                common=len(change['common']),removed=len(change['removed']),added=len(change['added']),
                causes=s['causes'],exit_reasons=s['exit_reasons'])
            current=[v for v in data['activity'][cid] if v['symbol']==symbol];old=[v for v in data['previous_activity'][old_id] if v['symbol']==symbol]
            activity[cid][symbol]={k:dict(old=sum(v[k] for v in old),new=sum(v[k] for v in current)) for k in ('候補','受理','新規fill','一回FAK失効','未試行取消')}
            if not s['actual_financial']:
                red_examples[cid][symbol]=dict(alias_reference=s['source_id'],independent_evidence=False);continue
            parents=data['all_parent_decomposition'][cid];index={ (p['session'],p['symbol'],p['parent']):i for i,p in enumerate(parents)}
            red_examples[cid][symbol]=[dict(session_net=v['net'],parent=compact(v['maximum_negative_parent'],
                '/all_parent_decomposition/'+cid+'/'+str(index[v['session'],symbol,v['maximum_negative_parent']['parent']])))
                for v in data['worst_three_red_sessions'][cid][symbol]]
    cid='E01_EVID_VOL_SELECTED_TARGET';changed={};common_cap0={}
    for symbol in ('TOPIX','NK225'):
        paired=data['paired_parents'][cid][symbol]
        changed[symbol]=dict(removed=[compact(p,'/paired_parents/'+cid+'/'+symbol+'/removed/'+str(i)) for i,p in enumerate(paired['removed'])],
            added=[compact(p,'/paired_parents/'+cid+'/'+symbol+'/added/'+str(i)) for i,p in enumerate(paired['added'])])
        common_keys={tuple(p['entry_key']) for p in paired['common']};old_thin=[]
        parents=data['all_parent_decomposition'][cid]
        # 新旧同じ公開で0Tfillの勝ち/負けをそれぞれ一親保存。旧三負親全削除の誤りを防ぐ。
        common_cap0[symbol]=[]
        for sign in (-1,1):
            eligible=[]
            for i,p in enumerate(parents):
                key=(p['session'],p['symbol'],p['paper_parent'],p['entry']['判断']['raw_seq'],p['side'])
                if p['symbol']==symbol and key in common_keys and p['published_adverse_ticks']==0 and (p['published_own_count']<2 or p['published_peer_count']<2) and sign*p['net_yen']>0:eligible.append((i,p))
            if eligible:
                i,p=sorted(eligible,key=lambda v:(-abs(v[1]['net_yen']),v[1]['session'],v[1]['parent']))[0]
                common_cap0[symbol].append(compact(p,'/all_parent_decomposition/'+cid+'/'+str(i)))
    added_top=data['paired_parents']['E01_EVID_VOL25_TARGET']['TOPIX']['added']
    replacements=[compact(p,'/paired_parents/E01_EVID_VOL25_TARGET/TOPIX/added/'+str(i)) for i,p in enumerate(added_top[:2])]
    out=dict(全合格=True,source=dict(path=SOURCE.relative_to(ROOT).as_posix(),SHA256=sha,new_result=data['結果SHA256']),
        scope='新297唯一金融/258実親。NK99は内部alias、旧396は保存経済同値。新111結果一読＋旧110診断一読の保存射影だけ。',
        point_columns=['normal_row','raw_seq','JST_price_proxy','bid','ask','parent_local_liquidation'],
        volume_columns=['known','direction_votes','already_signed_balance'],
        price_columns=['own_known_or_unsaved_None','own_count','own_side_balance','peer_known','peer_count','peer_side_balance','saved_price_accepted'],
        economics_columns=['mid_direction_gross','crossing_disadvantage','actual_fees','net','observed_peak','target_or_None','parent_stop'],
        match_key=['session','symbol','paper_parent','publication_raw_seq','side'],
        aggregates=aggregates,activity=activity,worst_three_red_sessions_one_parent=red_examples,
        selected_target_changed_parents=changed,common_thin_price_cap0_counterexamples=common_cap0,vol25_top_new_parent_counterexample=replacements,
        findings=['SELECTED_TARGET TOP +41672は旧負二親41672の消失のみ。共通16親の出口/実gross/料差0、新親0。全3薄票負親の削除62508ではない。',
            '同NKは避け旧負10440−失い旧勝15560＝−5120。共通35親出口/実gross/料差0、新親0。薄票群を一律拒否すると勝ちも失う。',
            'VOL25のTOPは旧負31672の消失に対して新参加−5836があり差+25836。保存負親削除だけなら改善を5836過大評価する。',
            '0Tでも公開価格と同じfirstgoodなら新規は通る。残った薄票負親や勝ちを削除効果としない。'],
        limits=['消失した旧親と新FAK失効の個別公開点対応は未保存。activity件数と親対応を別にし、全消失を価格失効由来とは断言しない。',
            '旧same firstquote cap0通過は保存旧BBOの算術だけ。新運転でbusy/場停止が変われば同予約が存在するとは限らない。',
            '価格横断不利は実grossの分解であり追加費用ではない。料を二重控除しない。',
            '旧own_knownは未保存None、新111は当時bool。時刻は価格代理時計、MFEは事後の既実保有区間だけ。',
            '全12はTOP全33平均10万円及び従来三基準の共通主達成無し。NK金額床未指定。微黒を目標達成と言わない。'],
        next_hypothesis=dict(status='未測定・条件未固定',
            direction='FAK価格だけで残るmid逆行は解消しない。volume情報の実量又は価格応答を同じ公開時点で区別する入口仮説を、既試行と照合して別検証する。',
            falsification='強票数だけを増やすことは勝ちの薄票群を失う可能性がある。0Tや価格ANDにも残負親/失勝があり、事後の負親群を消して効果を代用しない。'))
    target=HERE/'少ない価格票で追わない効果と失った勝ち及び後参加の小結.json';assert not target.exists()
    rendered=json.dumps(out,ensure_ascii=False,separators=(',',':'),allow_nan=False)+'\n'
    assert len(rendered.encode('utf-8'))<=50*1024,len(rendered.encode('utf-8'))
    target.write_text(rendered,encoding='utf-8')
    print(str(len(rendered.encode('utf-8')))+'bytes SHA '+hashlib.sha256(target.read_bytes()).hexdigest(),flush=True)


if __name__=='__main__':run()
