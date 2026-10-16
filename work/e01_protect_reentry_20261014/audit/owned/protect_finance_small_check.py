"""完成小結果だけから十二条件792会計と実親・現在価格票・全場平均を独立検算する。"""

from collections import Counter
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import traceback

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
ENGINE=ROOT/'work/e01_protect_reentry_20261014/engine'
EXPECTED_SHA='c0103c4817c39891f872f18d6491fdd8d8ad171a98b8053842558626d463f02f'
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
    raw=path.read_bytes();READS[key]=hashlib.sha256(raw).hexdigest()
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
    assert ep['own_count']>=2 and ep['peer_count']>=2 and side*ep['own_balance']>=.25 and side*ep['peer_balance']>=.25 and ep['peer_known']
    assert ep['peer_row']>=0 and 0<ep['peer_price_age_seconds']<=60
    tolerance=int(side*ep['own_balance']>=.75 and side*ep['peer_balance']>=.75)
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
def main() -> None:
    """
    機能: 一読した792小会計と全完結実親を親定義/場平均/昼夜/買売へ再集計する。
    引数: なし。根terminal0後の完成結果/固定/計画/独立正式証跡だけを読む。
    返り値: None。源合格と経済未達を別に保存し、Falseを保持する。
    """
    target=HERE/'十二保護792会計と全実CID_UID及び新目標の独立小監査.json';assert not target.exists()
    try:
        result=read(ENGINE/'finance/結果.json');fixed=read(ENGINE/'金融事前固定.json');plan=read(ENGINE/'試行計画.json')
        binding=read(HERE/'十二条件と最終14源及び八spec登録の独立正式接続.json')
        assert READS[(ENGINE/'finance/結果.json').relative_to(ROOT).as_posix()]==EXPECTED_SHA
        assert result['全合格'] and result['source開始終端一致'] and binding['全合格']
        H.same(result['source_SHA256'],fixed['source_SHA256'],'金融source固定');H.same(result['source_SHA256'],binding['最終source_SHA256'],'独立正式source一致')
        H.same(result['case_SHA256'],fixed['case_SHA256'],'12caseSHA');H.same(result['configs'],fixed['configs'],'12条件固定')
        H.same(result['configs'],plan['spec']['entry']['conditions'],'正式八spec条件');H.same(result['sessions'],fixed['sessions'],'33場同一')
        H.same(READS[(ENGINE/'試行計画.json').relative_to(ROOT).as_posix()],fixed['計画SHA256'],'正式計画SHA')
        H.same(result['counts'],{'既input一読':33,'価格票準備口座':66,'新account金融':792},'正式一回実計数')
        for key in ('旧GU再利用','旧台帳本文','原board','NPZ','API','現在入力'):H.same(result[key],0,key)
        H.same(result['comparison_reference'],fixed['comparison_reference'],'旧107候補外小引用の固定同値')
        sessions=result['sessions'];assert len(sessions)==33 and sum(s.endswith('_Day') for s in sessions)==17 and sum(s.endswith('_Night') for s in sessions)==16
        assert len(result['configs'])==len(result['results'])==len(result['actual_parent_diagnostics'])==len(result['boundary'])==len(result['activity'])==12
        evaluations={};all_ledgers=set()
        for config in result['configs']:
            cid=config['id'];entry=result['results'][cid];profiles=result['actual_parent_diagnostics'][cid];bounds=result['boundary'][cid]
            assert len(entry['rows'])==len(entry['ledgers'])==len(bounds)==len(result['activity'][cid])==66
            keys={(s,product) for s in sessions for product in H.CAP}
            assert {(r['session'],r['symbol']) for r in entry['rows']}==keys
            rowmap={(r['session'],r['symbol']):r for r in entry['rows']};activemap={(r['session'],r['symbol']):r for r in result['activity'][cid]}
            assert len(rowmap)==len(activemap)==66
            for b in bounds:
                key=(b['session'],b['symbol']);symbol=key[1];group=sorted([p for p in profiles if (p['session'],p['symbol'])==key],key=lambda p:p['entry']['row'])
                origins={int(o[0]):o for o in b['actual_origins']};H.same(len(origins),len(group),'起点数は実完結親数')
                assert len({p['parent'] for p in group})==len(group)
                assert [int(origins[p['parent']][13]) for p in group]==list(range(len(group)))
                assert [p['parent'] for p in group]==sorted(p['parent'] for p in group)
                scene=[j for j in b['judgments'] if j[3] in (161,162)];first_scene=min((j[0] for j in scene),default=None)
                previous=0.;last_close=-1
                for p in group:
                    assert p['entry']['source_row']>=last_close
                    if first_scene is not None:assert p['entry']['row']<=first_scene
                    parent(p,config,origins[p['parent']],previous,b['judgments']);previous+=p['net_yen'];last_close=p['exits'][0]['row']
                r=rowmap[key];H.compare_mapping(r,H.metric([p['net_yen'] for p in group]),'場親net正負')
                H.compare_mapping(r,dict(費用=sum(p['fees_yen'] for p in group),新規枚数=sum(p['entry_quantity'] for p in group),
                    勝ち枚数=sum(p['entry_quantity'] for p in group if p['net_yen']>0),負け枚数=sum(p['entry_quantity'] for p in group if p['net_yen']<0),
                    零枚数=sum(p['entry_quantity'] for p in group if p['net_yen']==0),注文件数=len(group)*2,
                    最大買枚数=H.CAP[symbol] if any(p['side']>0 for p in group) else 0,最大売枚数=H.CAP[symbol] if any(p['side']<0 for p in group) else 0),'場料/数量/二注文')
                assert r['全会計合格'];COUNTS['場会計']+=1
                act=activemap[key]
                H.same(act['新規fill'],len(group),'activity fill数');H.same(act['候補'],act['origin候補']+act['pull候補']+act['break候補'],'候補枝を分離')
                H.same(act['受理'],act['新規fill']+act['一回FAK失効']+act['未試行取消'],'受理一回の三終端')
                H.same(act['候補'],act['受理']+sum(act['拒否理由'].values()),'公開採否全数')
                assert all(isinstance(v,int) and v>=0 for k,v in act.items() if k not in ('session','symbol','拒否理由'))
                COUNTS['activity場']+=1
            evaluations[cid]={}
            for symbol in H.CAP:
                rows=[r for r in entry['rows'] if r['symbol']==symbol];ps=[p for p in profiles if p['symbol']==symbol]
                excluded=[r['session'] for r in sorted((r for r in rows if r['収支']>0),key=lambda r:(-r['収支'],r['session']))[:3]]
                scopes={'全33':sessions,'前16':sessions[:16],'後17':sessions[16:],'上位3正収支場除外':[s for s in sessions if s not in excluded]}
                H.same(entry['periods'][symbol]['除外場'],excluded,'上位三正net除外')
                values={}
                for name,scope in scopes.items():
                    rr=[r for r in rows if r['session'] in scope];pr=[p for p in ps if p['session'] in scope]
                    a=H.aggregate(rr,pr);e=H.economy(rr,pr,symbol);s=H.stability(rr,e);saved=entry['periods'][symbol][name]
                    H.compare_mapping(saved['aggregate'],a,name+'/会計');H.compare_mapping(saved['economic'],e,name+'/経済')
                    H.compare_mapping(saved['stability'],s,name+'/三基準円床');H.same(saved['sessions'],scope,name+'/分母場')
                    values[name]=dict(net_yen=a['収支'],**e,**{k:s[k] for k in ('active_sessions','positive_sessions','losing_sessions','no_trade_sessions',
                        'profit_share','red_full_rate','mean_positive_session_net_yen','worst_negative_session_abs_yen','all_targets','all_economic_targets')})
                    COUNTS['保存商品期間']+=1
                for label,ending in (('Day','_Day'),('Night','_Night')):
                    rr=[r for r in rows if r['session'].endswith(ending)];pr=[p for p in ps if p['session'].endswith(ending)]
                    a=H.aggregate(rr,pr);e=H.economy(rr,pr,symbol);s=H.stability(rr,e)
                    values[label]=dict(net_yen=a['収支'],**e,**{k:s[k] for k in ('active_sessions','positive_sessions','losing_sessions','profit_share','all_targets','all_economic_targets')})
                    COUNTS['追加昼夜期間']+=1
                H.compare_mapping(entry['symbols'][symbol],H.aggregate(rows,ps),'全33商品集計')
                H.compare_mapping(entry['economic'][symbol],H.economy(rows,ps,symbol),'全33経済')
                H.compare_mapping(entry['stability'][symbol],H.stability(rows,H.economy(rows,ps,symbol)),'全33主基準')
                H.compare_mapping(entry['actual_leg_symbols'][symbol],H.metric([p['net_yen'] for p in ps]),'全量二注文の玉副表')
                for label,side in (('long',1),('short',-1)):
                    group=[p for p in ps if p['side']==side];m=H.metric([p['net_yen'] for p in group]);m['枚数']=sum(p['entry_quantity'] for p in group)
                    H.compare_mapping(entry['directional_symbols'][symbol][label],m,'完結実親買売別')
                evaluations[cid][symbol]=values
            for item in entry['ledgers']:
                path=item['path'];assert path not in all_ledgers and path.startswith('work/e01_protect_reentry_20261014/engine/finance/ledgers/'+cid+'/')
                assert len(item['SHA256'])==64 and set(item['SHA256'])<=set('0123456789abcdef');all_ledgers.add(path);COUNTS['台帳参照形式']+=1
        assert COUNTS['場会計']==COUNTS['activity場']==COUNTS['台帳参照形式']==792 and COUNTS['保存商品期間']==96
        both=[cid for cid,v in evaluations.items() if all(v[s]['全33']['all_economic_targets'] for s in H.CAP)]
        assert not both and all(v[s]['全33']['net_yen']<0 for v in evaluations.values() for s in H.CAP)
        output=dict(全合格=True,小資料SHA256=READS,検査=dict(COUNTS),金融source_SHA256=result['source_SHA256'],評価=evaluations,
            両商品主目標合格=both,全12両商品合計収支負=True,
            純補助source=dict(path=HELPER_PATH.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(HELPER_PATH.read_bytes()).hexdigest()),
            留保=['全33meanは損失/無取引込み。親平均/活動場平均で目標を代用しない。',
                  '場線の最初観測Lastは小結果へ独立保存されず、線の起点をこの監査で再測定しない。',
                  '正常中間行全列/物理受信順/実FAK板深度は未保存で、最初正常行の最短性を小結果だけでは再確認しない。',
                  '事後MAE/MFEは保存極値との算術一致だけ。全normal列からの再極値測定や救済PL計算はしない。',
                  '会計合格と経済未達を分離。既知33場の結果から市場一般での無効を証明しない。'],
            金融再実行=0,保存入力=0,台帳本文=0,原板=0,NPZ=0,API=0,旧107結果=0)
    except BaseException:
        output=dict(全合格=False,小資料SHA256=READS,検査=dict(COUNTS),原因=traceback.format_exc(),
                    金融再実行=0,保存入力=0,台帳本文=0,原板=0,NPZ=0,API=0,旧107結果=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8');raise
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),検査=dict(COUNTS),両商品主目標合格=both,全12両商品合計収支負=True),ensure_ascii=False))


if __name__=='__main__':main()
