"""495唯一と99同値及び198PRICE保存を分け、入口代理の署名と全場会計を検算する。"""

from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_entry_information_20261014/engine'
EXPECTED_SHA='9c4ec0cb94e09f27a98c6c9462a5de1cc4b6532e5c447f7fa3fc94202a647000'
READS={}
COUNTS=Counter()
HELPER_PATH=ROOT/'work/e01_economic_scale_20261014/audit/owned/economic_finance_small_check.py'
spec=importlib.util.spec_from_file_location('独立親会計の純補助',HELPER_PATH)
H=importlib.util.module_from_spec(spec);spec.loader.exec_module(H)
H.COUNTS=COUNTS


def read(path: Path) -> dict:
    """
    機能: 根terminal0後に許可された小結果/固定/計画だけを同bytes一目的一読する。
    引数: path(Path) は明示JSON。指定大型packetや台帳へ拡張しない。
    返り値: dict は保存値と一致するJSON辞書。
    """
    key=path.relative_to(ROOT).as_posix();assert key not in READS
    captured={ENGINE/'finance/結果.json':'result.json',ENGINE/'金融事前固定.json':'fixed.json',ENGINE/'試行計画.json':'plan.json'}
    source=HERE/'captured_small_finance'/captured[path] if path in captured else path
    raw=source.read_bytes();READS[key]=hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


# ----------------------------------------
def parent(p: dict, config: dict, origin: list, previous_net: float, judgments: list) -> None:
    """
    機能: 一実CIDの二注文だけからnet/料/N/capと当時判断系譜を独立に求める。
    引数: p/config(dict)、origin(list)、previous_net(float)、judgments(list) は同親小資料。
    返り値: None。paper数量や事後MFEを実現PLへ転用しない。
    """
    symbol=p['symbol'];side=p['side'];entry=p['entry'];assert side in (-1,1) and len(p['exits'])==1
    exit=p['exits'][0];q=H.CAP[symbol];mult=H.MULT[symbol]
    H.same(p['entry_quantity'],q,'全実初回q');H.same(p['capacity'],q,'片方向cap')
    H.same(p['maximum_held_quantity'],q,'最大実同時q');H.same(exit['quantity'],q,'全実返済q')
    total_fee=H.fee(q,symbol)*2
    for event,is_new in ((entry,True),(exit,False)):
        fill,decision=event['約定'],event['判断'];row,source=event['row'],event['source_row']
        assert 0<=source<row and decision['normal_row']==source and fill['normal_row']==row
        assert decision['raw_index']<=fill['raw_index'] and decision['raw_seq']<=fill['raw_seq']
        assert fill['normal'] and 0<fill['bid']<fill['ask']
        order_side=side if is_new else -side
        H.same(event['price'],fill['ask' if order_side>0 else 'bid'],'正BBO実約定')
        H.same(event['quantity'],q,'注文枚数');H.same(event['fee_yen'],H.fee(q,symbol),'実注文ごとfloor料')
        COUNTS['実注文小BBO料']+=1
    H.same(entry['reason'],90,'一回FAK新規理由')
    N=entry['price']*q*mult;H.same(p['notional_yen'],N,'初実fillN')
    H.same(p['parent_stop_yen'],N*config['parent_stop_fraction'],'親損失線N固定')
    H.same(p['target_yen'],N*config['parent_target_fraction'] if config['exit_id']=='TARGET' else None,'親目標又は対象外')
    H.same(p['arm_yen'],N*config['arm_fraction'] if config['exit_id']!='TARGET' else None,'追尾arm又は対象外')
    gross=side*q*(exit['price']-entry['price'])*mult
    H.same(p['net_yen'],gross-total_fee,'一実親gross-minus-fee');H.same(p['fees_yen'],total_fee,'親料合計')
    ep=entry['判断'];xp=exit['判断']
    assert ep['normal'] and ep['Last'] is not None and ep['Last']>0
    H.same(ep['paper_parent'],p['paper_parent'],'公開時paper親系譜')
    H.same(ep['paper_direction'],side,'公開paper方向')
    H.same(p['published_own_count'],ep['own_count'],'公開自己票数');H.same(p['published_peer_count'],ep['peer_count'],'公開peer票数')
    H.same(p['published_own_balance'],ep['own_balance'],'公開自己balance');H.same(p['published_peer_balance'],ep['peer_balance'],'公開peerbalance')
    current_price_ok=bool(ep['own_balance'] is not None and ep['peer_known'] and ep['peer_balance'] is not None
        and ep['own_count']>=2 and ep['peer_count']>=2 and side*ep['own_balance']>=.25 and side*ep['peer_balance']>=.25)
    if ep['peer_known']:
        assert ep['peer_row']>=0 and 0<ep['peer_price_age_seconds']<=60
    information=p['published_entry_information'];volume=information['volume'];count=volume['direction_votes']
    H.same(information['entry_id'],config['entry_id'],'原公開入口情報ID')
    assert volume['known'] and volume['window_seconds']==60 and volume['reason']==0
    assert isinstance(volume['up_votes'],int) and isinstance(volume['down_votes'],int) and count==volume['up_votes']+volume['down_votes'] and count>=2
    H.same(volume['balance'],side*(volume['up_votes']-volume['down_votes'])/count,'出来高代理の既signedを再sideしない')
    assert volume['balance']>=config['volume_balance_threshold'][symbol]
    for key,value in (('candidate_raw_row',ep['raw_index']),('candidate_raw_seq',ep['raw_seq']),('candidate_price_time_s',ep['price_time_s'])):
        H.same(volume[key],value,'原公開volume署名/'+key)
    H.same(information['volume_accepted'],True,'元出来高入口資格')
    H.same(information['price_accepted'],current_price_ok,'現在価格資格は独立測定')
    H.same(information['accepted'],True,'原公開入口採否')
    if config['entry_id']=='VOL25_PRICE_BOTH':assert current_price_ok
    if not current_price_ok:COUNTS['VOL単独の価格資格不足親']+=1
    tolerance=int(ep['own_balance'] is not None and ep['peer_known'] and ep['peer_balance'] is not None
        and side*ep['own_balance']>=.75 and side*ep['peer_balance']>=.75)
    H.same(p['published_adverse_ticks'],tolerance,'公開両支持で0/1Tを固定')
    public_quote=ep['ask' if side>0 else 'bid'];pricecap=public_quote+side*tolerance*H.TICK[symbol]
    H.same(p['published_price_cap'],pricecap,'公開価格cap')
    assert entry['price']<=pricecap if side>0 else entry['price']>=pricecap
    H.same(p['published_spread'],ep['ask']-ep['bid'],'公開spread')
    cost=(ep['ask']-ep['bid'])*q*mult+total_fee
    assert cost<=.5*public_quote*q*mult*config['parent_stop_fraction']+1e-5
    assert p['publication_kind'] in (0,1,2)
    if config['reentry_id']=='ORIGIN':assert p['publication_kind']==0
    for i,value in ((0,p['parent']),(1,p['paper_parent']),(2,entry['row']),(3,entry['source_row']),(4,side),(5,q),(6,entry['price']),
                    (7,N),(8,previous_net),(9,p['published_paper_price']),(10,p['published_paper_atr']),(11,pricecap),(12,tolerance)):
        H.same(origin[i],value,'実起点列'+str(i))
    assert int(origin[13])==origin[13] and origin[13]>=0
    reason=exit['reason'];assert reason in (92,93,140,141,142,151,152,161,162)
    assert config['enable_opposed_price_exit'] is False and reason!=152
    for event in (entry,exit):
        for point in (event['判断'],event['約定']):
            amount=point['paper_remaining_quantity']
            assert isinstance(amount,int) and 0<=amount<=q and (amount==0)==(point['paper_direction']==0)
    assert ep['paper_remaining_quantity']>0
    H.same(exit['親純損失線'],N*config['parent_stop_fraction'],'返済判断親損失線')
    H.same(exit['親純利益線'],N*config['parent_target_fraction'] if config['exit_id']=='TARGET' else None,'返済判断親利益線')
    if reason not in (92,93):
        matches=[j for j in judgments if j[0]==exit['source_row'] and j[1]==p['parent'] and j[3]==reason]
        assert matches,'当時判断と実返済理由を結ぶ小judgment無し'
        for j in matches:
            H.same(j[4],xp['parent_liquidation_yen'],'判断local系譜');H.same(j[5],xp['parent_liquidation_yen']+previous_net,'場清算と前親net分離')
            H.same(j[9],N,'途中判断N不変');H.same(j[8],q,'途中判断実held数量')
        if reason==140:
            assert config['exit_id']=='TARGET' and xp['normal'] and xp['parent_liquidation_yen']>=N*config['parent_target_fraction']-1e-5
        elif reason==141:
            assert xp['normal'] and xp['parent_liquidation_yen']<=-N*config['parent_stop_fraction']+1e-5
        elif reason==142:
            assert config['exit_id']!='TARGET' and xp['normal'] and xp['parent_peak_yen']>=N*config['arm_fraction']-1e-5
            line=max(N*config['floor_fraction'],xp['parent_peak_yen']-N*config['draw_fraction'])
            H.same(exit['発動後保護線'],line,'当時高水準からの保護線')
            assert xp['parent_liquidation_yen']<=line+1e-5
        elif reason==151:
            assert xp['paper_direction'] in (0,-side)
        elif reason==152:
            assert xp['peer_known'] and xp['own_count']>=2 and xp['peer_count']>=2 and side*xp['own_balance']<=-.25 and side*xp['peer_balance']<=-.25
        else:
            assert all(j[5]<=-j[7]+1e-5 if reason==161 else j[5]>=j[7]-1e-5 for j in matches)
    H.same(p['parent_mae_yen'],max(0.,-p['worst_parent_liquidation_yen']),'事後局所MAE')
    H.same(p['parent_mfe_yen'],p['best_parent_liquidation_yen'],'事後局所MFE')
    assert p['worst_parent_liquidation_yen']<=p['net_yen']+1e-4<=p['best_parent_liquidation_yen']+2e-4
    for name,value in (('argmin',p['worst_parent_liquidation_yen']),('argmax',p['best_parent_liquidation_yen'])):
        point=p['first_parent_liquidation_'+name]
        assert entry['row']<=point['normal_row']<=exit['row'] and point['normal']
        H.same(point['parent_liquidation_yen'],value,'事後極値保存'+name)
    H.same(p['holding_price_proxy_seconds'],exit['約定']['price_time_s']-entry['約定']['price_time_s'],'価格代理保有秒')
    assert p['hindsight_only'];COUNTS['完結実親']+=1


# ----------------------------------------
def saved_price(case: dict,sessions: list[str]) -> dict:
    """
    機能: 保存PRICE三対照の198行を旧経路無しで商品別各範囲へ独立再集計する。
    引数: case(dict)、sessions(list[str]) は保存公開小引用と固定33場。
    返り値: dict は再算術した主評価。旧親時刻又は注文経路を補完しない。
    """
    assert len(case['rows'])==66
    output={}
    for symbol in H.CAP:
        rows=[r for r in case['rows'] if r['symbol']==symbol]
        assert len(rows)==33 and {r['session'] for r in rows}==set(sessions)
        removed=[r['session'] for r in sorted((r for r in rows if r['net']>0),key=lambda r:(-r['net'],r['session']))[:3]]
        scopes={'full':sessions,'top3':[s for s in sessions if s not in removed],
            'first':sessions[:16],'last':sessions[16:],'day':[s for s in sessions if s.endswith('_Day')],'night':[s for s in sessions if s.endswith('_Night')]}
        metrics=case['metrics'][symbol]
        for r in rows:
            H.same(r['net'],r['profit']-r['loss'],'保存PRICE場net恒等')
            H.same(r['fees'],r['campaigns']*2*H.fee(H.CAP[symbol],symbol),'保存PRICE全量二注文料')
            H.same(r['winning_lots'],r['winning_campaigns']*H.CAP[symbol],'保存PRICE勝ち新規枚数')
            H.same(r['losing_lots'],r['losing_campaigns']*H.CAP[symbol],'保存PRICE負け新規枚数')
            assert 0<=r['winning_campaigns']+r['losing_campaigns']<=r['campaigns'] and r['profit']>=0 and r['loss']>=0
            if not r['campaigns']:H.same(r['net'],0.,'保存PRICE無取引零net')
            COUNTS['保存PRICE場']+=1
        values={}
        for name,scope in scopes.items():
            rr=[r for r in rows if r['session'] in scope];n=len(rr);saved=metrics[name]
            gain=sum(r['profit'] for r in rr);loss=sum(r['loss'] for r in rr);net=sum(r['net'] for r in rr);parents=sum(r['campaigns'] for r in rr)
            positives=[r['net'] for r in rr if r['net']>0];red=[-r['net'] for r in rr if r['net']<0];active=sum(r['campaigns']>0 for r in rr)
            share=gain/(gain+loss) if gain+loss else None;meanpos=sum(positives)/len(positives) if positives else None;worst=max([0.]+red)
            tests=dict(share65=share is not None and share>=.65,red20=len(red)/n<=.2,coverage=meanpos is not None and worst<=meanpos)
            mean=net/n;floor=100000 if symbol=='TOPIX' else None;economic=mean>=floor if floor is not None else None
            expected=dict(profit=gain,loss=loss,net=net,profit_share=share,sessions=n,positive=len(positives),negative=len(red),active=active,no_trade=n-active,
                red_all=len(red)/n,mean_positive_session_net=meanpos,worst_session_loss=worst,campaigns=parents,
                winning_campaigns=sum(r['winning_campaigns'] for r in rr),losing_campaigns=sum(r['losing_campaigns'] for r in rr),
                winning_lots=sum(r['winning_lots'] for r in rr),losing_lots=sum(r['losing_lots'] for r in rr),fees=sum(r['fees'] for r in rr),
                tests=tests,pass_all=all(tests.values()),mean_parent_net=net/parents if parents else None,mean_session_net=mean,economic_floor=floor,economic_pass=economic,
                primary_pass=all(tests.values()) and (economic if floor is not None else True),capacity_net_points=net/(H.CAP[symbol]*H.MULT[symbol]),
                mean_parent_capacity_net_points=net/parents/(H.CAP[symbol]*H.MULT[symbol]) if parents else None,
                mean_session_capacity_net_points=mean/(H.CAP[symbol]*H.MULT[symbol]))
            H.compare_mapping(saved,expected,'保存PRICE/'+symbol+'/'+name);values[name]=expected;COUNTS['保存PRICE商品期間']+=1
        H.same(metrics['top3']['removed_sessions'],removed,'保存PRICE上位三正net除外')
        robust=values['top3']['tests']['share65'] and values['top3']['tests']['coverage']
        H.same(metrics['robustness_pass'],robust,'保存PRICE頑健性')
        H.same(metrics['economic_robustness_pass'],robust and (values['top3']['economic_pass'] if symbol=='TOPIX' else True),'保存PRICE経済頑健性は別')
        H.same(metrics['qualified'],values['full']['primary_pass'] and robust,'保存PRICE参考資格')
        direction=case['directions'][symbol]
        H.same(sum(direction[s]['利益'] for s in ('long','short')),values['full']['profit'],'保存PRICE買売利益和')
        H.same(sum(direction[s]['損失'] for s in ('long','short')),values['full']['loss'],'保存PRICE買売損失和')
        H.same(sum(direction[s]['収支'] for s in ('long','short')),values['full']['net'],'保存PRICE買売収支和')
        H.same(sum(direction[s]['親数'] for s in ('long','short')),values['full']['campaigns'],'保存PRICE買売親数和')
        output[symbol]=values
    return output


def aliases(result: dict) -> dict:
    """
    機能: NK内部同値99場の同台帳・親・経済数値を実行元へ照合する。
    引数: result(dict) は同一金融保存小結果。
    返り値: dict はaliasごとの掲載親数。追加標本へ数えない。
    """
    output={}
    for item in result['internal_aliases']:
        cid=item['id'];source=item['source_id'];assert item['symbol']=='NK225' and item['保存会計']==33 and item['新金融']==0
        a=result['results'][cid];b=result['results'][source]
        for field in ('periods','symbols','stability','economic','directional_symbols','actual_leg_symbols'):
            H.same(a[field]['NK225'],b[field]['NK225'],'NKalias同経済/'+field)
        H.same([r for r in a['rows'] if r['symbol']=='NK225'],[r for r in b['rows'] if r['symbol']=='NK225'],'NKalias同33場会計')
        before={r['session']:r for r in b['ledgers'] if r['symbol']=='NK225'}
        for r in a['ledgers']:
            if r['symbol']!='NK225':continue
            H.same(r['economic_alias_source_id'],source,'NKalias台帳由来')
            H.same(r['path'],before[r['session']]['path'],'NKalias同台帳path')
            H.same(r['SHA256'],before[r['session']]['SHA256'],'NKalias同台帳SHA')
            COUNTS['内部同値台帳参照']+=1
        ap=[r for r in result['actual_parent_diagnostics'][cid] if r['symbol']=='NK225'];bp=[r for r in result['actual_parent_diagnostics'][source] if r['symbol']=='NK225']
        assert len(ap)==len(bp)
        for left,right in zip(ap,bp):
            normalized=dict(left);H.same(normalized.pop('economic_alias_source_id'),source,'NKalias実親由来')
            information=dict(normalized['published_entry_information']);H.same(information['entry_id'],'VOL25','NKalias表示入口名')
            information['entry_id']='VOL_SELECTED';normalized['published_entry_information']=information
            H.same(normalized,right,'NKalias実親の表示名以外同値')
        for field in ('boundary','activity'):
            left=[r for r in result[field][cid] if r['symbol']=='NK225'];right=[r for r in result[field][source] if r['symbol']=='NK225']
            for aa,bb in zip(left,right):
                own=dict(aa);H.same(own.pop('economic_alias_source_id'),source,'NKalias/'+field+'/由来');H.same(own,bb,'NKalias/'+field+'/同値')
        output[cid]=dict(実行元=source,掲載親数=len(ap),追加金融=0)
    assert len(output)==3
    return output


# ----------------------------------------
def main() -> None:
    """
    機能: 一目的保全した495唯一会計＋99同値＋198PRICEを親/全場定義で検査する。
    引数: なし。根terminal0後の同bytes私有コピーだけを読む。
    返り値: None。計算合格と経済未達を分離し、金融・元資料は再読しない。
    """
    target=HERE/'495唯一金融と99同値及び198PRICEの独立小会計監査.json';assert not target.exists()
    try:
        result=read(ENGINE/'finance/結果.json');fixed=read(ENGINE/'金融事前固定.json');plan=read(ENGINE/'試行計画.json')
        binding=read(HERE/'四入口十二掲載と495唯一及び最終17源の独立正式接続.json')
        capture=read(HERE/'captured_small_finance/同一金融三小資料の保全.json')
        assert READS[(ENGINE/'finance/結果.json').relative_to(ROOT).as_posix()]==EXPECTED_SHA
        assert result['全合格'] and result['source開始終端一致'] and binding['全合格'] and capture['全合格']
        current={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in ENGINE.glob('*.py')}
        H.same(current,result['source_SHA256'],'金融後source17不変');H.same(current,fixed['source_SHA256'],'金融固定source一致')
        H.same(current,binding['最終source_SHA256'],'独立source接続一致');H.same(result['case_SHA256'],fixed['case_SHA256'],'12全項目caseSHA')
        H.same(result['configs'],fixed['configs'],'12固定条件');H.same(result['configs'],plan['spec']['entry']['conditions'],'12正式spec条件')
        H.same(result['sessions'],fixed['sessions'],'同33場');H.same(READS[(ENGINE/'試行計画.json').relative_to(ROOT).as_posix()],fixed['計画SHA256'],'正式計画SHA')
        H.same(result['counts'],dict(既input一読=33,価格票準備口座=66,新account金融=495,内部同値会計再利用=99),'正式一回counter')
        for key in ('PRICE再金融','内部同値再金融','旧GU再利用','旧台帳本文','原board','NPZ','API','現在入力'):H.same(result[key],0,key)
        for key,value in (('新account金融',495),('内部同値会計再利用',99),('保存PRICE条件',3),('保存PRICE会計',198),('掲載口座',792)):H.same(result[key],value,key)
        H.same(result['comparison_reference'],fixed['comparison_reference'],'旧PRICE小引用同値')
        sessions=result['sessions'];assert len(sessions)==33 and sum(s.endswith('_Day') for s in sessions)==17 and sum(s.endswith('_Night') for s in sessions)==16
        configs=[c for c in result['configs'] if c['actual_financial']]
        assert len(configs)==len(result['results'])==len(result['actual_parent_diagnostics'])==len(result['boundary'])==len(result['activity'])==9
        aliascheck=aliases(result)
        evaluations={};all_ledgers=set();unique_parents=display_parents=0
        for config in configs:
            cid=config['id'];entry=result['results'][cid];profiles=result['actual_parent_diagnostics'][cid];bounds=result['boundary'][cid]
            assert len(entry['rows'])==len(entry['ledgers'])==len(bounds)==len(result['activity'][cid])==66
            keys={(s,product) for s in sessions for product in H.CAP};rowmap={(r['session'],r['symbol']):r for r in entry['rows']}
            activemap={(r['session'],r['symbol']):r for r in result['activity'][cid]}
            assert len(rowmap)==len(activemap)==66 and rowmap.keys()==keys
            for b in bounds:
                key=(b['session'],b['symbol']);symbol=key[1];group=sorted([p for p in profiles if (p['session'],p['symbol'])==key],key=lambda p:p['entry']['row'])
                origins={int(o[0]):o for o in b['actual_origins']};H.same(len(origins),len(group),'実完結親起点数')
                assert len({p['parent'] for p in group})==len(group)
                assert [int(origins[p['parent']][13]) for p in group]==list(range(len(group)))
                scene=[j for j in b['judgments'] if j[3] in (161,162)];first_scene=min((j[0] for j in scene),default=None)
                previous=0.;lastclose=-1
                for p in group:
                    assert p['entry']['source_row']>=lastclose
                    if first_scene is not None:assert p['entry']['row']<=first_scene
                    parent(p,config,origins[p['parent']],previous,b['judgments']);previous+=p['net_yen'];lastclose=p['exits'][0]['row']
                r=rowmap[key];H.compare_mapping(r,H.metric([p['net_yen'] for p in group]),'場親net正負')
                H.compare_mapping(r,dict(費用=sum(p['fees_yen'] for p in group),新規枚数=len(group)*H.CAP[symbol],
                    勝ち枚数=sum(p['entry_quantity'] for p in group if p['net_yen']>0),負け枚数=sum(p['entry_quantity'] for p in group if p['net_yen']<0),
                    零枚数=sum(p['entry_quantity'] for p in group if p['net_yen']==0),注文件数=len(group)*2,
                    最大買枚数=H.CAP[symbol] if any(p['side']>0 for p in group) else 0,最大売枚数=H.CAP[symbol] if any(p['side']<0 for p in group) else 0),'場料/数量/二注文')
                assert r['全会計合格'];COUNTS['掲載VOL場会計']+=1;display_parents+=len(group)
                if config['actual_financial_by_symbol'][symbol]:COUNTS['唯一金融場会計']+=1;unique_parents+=len(group)
                else:COUNTS['内部同値場会計']+=1
                act=activemap[key]
                H.same(act['新規fill'],len(group),'activity実fill');H.same(act['候補'],act['origin候補'],'全ORIGINだけ')
                H.same(act['pull候補']+act['break候補'],0,'geometry追加無し');H.same(act['受理'],act['新規fill']+act['一回FAK失効']+act['未試行取消'],'FAK三終端')
                H.same(act['候補'],act['受理']+sum(act['拒否理由'].values()),'候補全採否')
                COUNTS['activity場']+=1
            evaluations[cid]={}
            for symbol in H.CAP:
                rows=[r for r in entry['rows'] if r['symbol']==symbol];ps=[p for p in profiles if p['symbol']==symbol]
                removed=[r['session'] for r in sorted((r for r in rows if r['収支']>0),key=lambda r:(-r['収支'],r['session']))[:3]]
                scopes={'全33':sessions,'前16':sessions[:16],'後17':sessions[16:],'上位3正収支場除外':[s for s in sessions if s not in removed]}
                H.same(entry['periods'][symbol]['除外場'],removed,'上位三正net除外')
                values={}
                for name,scope in scopes.items():
                    rr=[r for r in rows if r['session'] in scope];pr=[p for p in ps if p['session'] in scope]
                    a=H.aggregate(rr,pr);e=H.economy(rr,pr,symbol);s=H.stability(rr,e);saved=entry['periods'][symbol][name]
                    H.compare_mapping(saved['aggregate'],a,name+'/会計');H.compare_mapping(saved['economic'],e,name+'/経済')
                    H.compare_mapping(saved['stability'],s,name+'/三基準');H.same(saved['sessions'],scope,name+'/場分母')
                    values[name]=dict(net_yen=a['収支'],**e,**{k:s[k] for k in ('active_sessions','positive_sessions','losing_sessions','no_trade_sessions',
                        'profit_share','red_full_rate','mean_positive_session_net_yen','worst_negative_session_abs_yen','all_targets','all_economic_targets')})
                    COUNTS['保存VOL商品期間']+=1
                for label,ending in (('Day','_Day'),('Night','_Night')):
                    rr=[r for r in rows if r['session'].endswith(ending)];pr=[p for p in ps if p['session'].endswith(ending)]
                    a=H.aggregate(rr,pr);e=H.economy(rr,pr,symbol);s=H.stability(rr,e)
                    values[label]=dict(net_yen=a['収支'],**e,**{k:s[k] for k in ('active_sessions','positive_sessions','losing_sessions','profit_share','all_targets','all_economic_targets')})
                H.compare_mapping(entry['symbols'][symbol],H.aggregate(rows,ps),'全33商品集計');H.compare_mapping(entry['economic'][symbol],H.economy(rows,ps,symbol),'全33経済')
                H.compare_mapping(entry['stability'][symbol],H.stability(rows,H.economy(rows,ps,symbol)),'全33主判定')
                H.compare_mapping(entry['actual_leg_symbols'][symbol],H.metric([p['net_yen'] for p in ps]),'全量二注文実玉副表')
                for label,side in (('long',1),('short',-1)):
                    group=[p for p in ps if p['side']==side];m=H.metric([p['net_yen'] for p in group]);m['枚数']=len(group)*H.CAP[symbol]
                    H.compare_mapping(entry['directional_symbols'][symbol][label],m,'完結親買売別')
                evaluations[cid][symbol]=values
            for item in entry['ledgers']:
                path=item['path'];symbol=item['symbol'];expected_id=config['economic_source_id_by_symbol'][symbol]
                assert path.startswith('work/e01_entry_information_20261014/engine/finance/ledgers/'+expected_id+'/')
                assert len(item['SHA256'])==64 and set(item['SHA256'])<=set('0123456789abcdef')
                if config['actual_financial_by_symbol'][symbol]:assert path not in all_ledgers;all_ledgers.add(path)
                else:assert path in all_ledgers
                COUNTS['掲載台帳参照']+=1
        reused=result['reused_price_cases'];assert len(reused)==3
        old_parent_count=0;old_rows=0
        for cid,item in reused.items():
            config=next(c for c in result['configs'] if c['id']==cid)
            H.same(item['config'],config,'保存PRICE条件');H.same(item['paired_price_id'],config['paired_price_id'],'保存PRICE同退出ID')
            H.same(item['saved_public_case'],fixed['comparison_reference']['cases'][config['paired_price_id']],'保存PRICE小引用全項目')
            evaluations[cid]=saved_price(item['saved_public_case'],sessions)
            old_parent_count+=sum(r['campaigns'] for r in item['saved_public_case']['rows']);old_rows+=len(item['saved_public_case']['rows'])
        H.same(COUNTS['唯一金融場会計'],495,'唯一金融495場');H.same(COUNTS['内部同値場会計'],99,'同値99場')
        H.same(COUNTS['保存PRICE場'],old_rows,'保存PRICE198場');assert old_rows==198 and len(all_ledgers)==495
        both_new=[cid for cid,v in evaluations.items() if cid in result['results'] and all(v[s]['全33']['all_economic_targets'] for s in H.CAP)]
        both_old=[cid for cid,v in evaluations.items() if cid in reused and all(v[s]['full']['primary_pass'] for s in H.CAP)]
        assert not both_new and not both_old
        output=dict(全合格=True,小資料SHA256=READS,検査=dict(COUNTS),金融source_SHA256=current,評価=evaluations,
            両商品主目標合格=both_new+both_old,内部同値確認=aliascheck,
            母数=dict(唯一金融口座=495,内部同値掲載=99,保存PRICE掲載=198,全掲載=792,唯一新親=unique_parents,
                唯一新注文=unique_parents*2,VOL掲載親=display_parents,VOL掲載注文=display_parents*2,PRICE保存親=old_parent_count,
                全掲載親=display_parents+old_parent_count,全掲載注文=(display_parents+old_parent_count)*2),
            留保=['未保存の正常中間行を使わないためfirstnormal最短性と全行極値は未独立再測定。判断後の正常BBOとsource人工へ限定。',
                  'own knownはpointで直接未保存。正常価格票源のknown時だけbalance有限という契約から現価格資格を読む。',
                  '場stopの最初場観測Lastは未直接保存。線の起点をこの監査で再測定しない。',
                  '保存PRICEは旧親経路/時計/UID未コピー。場/期間/買売小集計だけの再算術。',
                  'NK同値99とPRICE198を新金融又は独立標本へ数えない。','出来高代理票は真の攻撃注文量・受信因果の証明ではない。',
                  '全33平均は赤字/無取引を含む。既知内の対照で未知成功とは呼ばない。'],
            原結果読取=1,原fixed読取=1,原plan読取=1,金融再実行=0,保存入力=0,台帳本文=0,元109金融本文=0,原板=0,NPZ=0,API=0)
    except BaseException:
        output=dict(全合格=False,小資料SHA256=READS,検査=dict(COUNTS),原因=traceback.format_exc(),金融再実行=0,保存入力=0,台帳本文=0,元109金融本文=0,API=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');raise
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),検査=dict(COUNTS),母数=output['母数'],両商品主目標合格=output['両商品主目標合格']),ensure_ascii=False))


if __name__=='__main__':
    main()


