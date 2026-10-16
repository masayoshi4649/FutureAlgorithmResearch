"""完成前の独立小状態機械で、実親尺度・再参加・部分返済・paper phase の反例を固定する。"""

from copy import deepcopy
from pathlib import Path
import hashlib
import importlib.util
import json
import traceback
import economic_reference_v3 as reference

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
OLD=ROOT/'work/e01_improve_20261014/audit/owned/fak_reference.py'
spec=importlib.util.spec_from_file_location('旧独立注文参照',OLD)
old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)


def main() -> None:
    """
    機能: 所有経済 source を import する前に純小feedと原GU別対照の期待値を固定する。
    引数: なし。読み取るのは旧独立純参照 source だけ。
    返り値: None。人工の成功又は False を所有領域へ保存する。
    """
    target=HERE/'初実fill名目と実親独立及び量出口分離の純参照_v3.json'
    failed=HERE/'経済規模の純参照False_v3.json'
    assert not target.exists() and not failed.exists()
    counts={};cases=[];core_examples=[]
    kinds=('独立親と再参加','paper継続中targetclose','paper先取消','paper同行firstnormal',
           '少量partial','q0後別親','第一FAK失効','追尾後の返済gap','場損失後停止','partial予約後quiet')
    try:
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for kind in kinds:
                    source=reference.fixture(symbol,side,kind)
                    for quantity in ('HALF','FULL','RISK'):
                        for exit_mode in ('GU','TARGET','TRAIL','PARTIAL'):
                            value=reference.run(source,quantity,exit_mode)
                            new=[o for o in value['orders'] if o['new']]
                            assert len(value['parents'])==len(new)
                            assert len({p['uid'] for p in value['parents']})==len(new)
                            assert value['states'][-1]['real_quantity']==0
                            assert sum(o['fee'] for o in value['orders'])==sum(p['fee'] for p in value['parents'])==value['curve'][-1]['paid']
                            assert abs(sum(p['net'] for p in value['parents'])-value['curve'][-1]['liquidation'])<1e-6
                            for p in value['parents']:
                                selected=[o for o in value['orders'] if (o['uid']==p['uid'] if o['new'] else o['target_uid']==p['uid'])]
                                entry=next(o for o in selected if o['new'])
                                assert p['nominal']==entry['price']*p['quantity']*source['multiplier']
                                assert sum(o['quantity'] for o in selected if not o['new'])==p['quantity']
                                assert p['quantity']<=source['cap']
                            for cut in (1,2,4,5,7,8,10,15):
                                prefix=deepcopy(source);prefix['rows']=prefix['rows'][:cut+1]
                                prefix['feed']=[o for o in prefix['feed'] if o['row']<=cut]
                                p=reference.run(prefix,quantity,exit_mode)
                                assert p['states']==value['states'][:cut+1] and p['curve']==value['curve'][:cut+1]
                                assert p['orders']==[o for o in value['orders'] if o['row']<=cut]
                                assert p['parents']==[o for o in value['parents'] if o['exit_row']<=cut]
                                counts['未来未読接頭']=counts.get('未来未読接頭',0)+1
                            if kind in ('paper先取消','第一FAK失効'):
                                assert not any(o['paper_parent']==0 for o in value['orders'])
                            if kind=='paper同行firstnormal':
                                assert any(o['paper_parent']==0 and o['new'] and o['row']==2 for o in value['orders'])
                            if kind=='q0後別親' and quantity=='RISK':
                                assert value['publications'][0]['quantity']==0 and not value['publications'][0]['accepted']
                                assert not any(o['paper_parent']==0 for o in value['orders'])
                                if new:assert new[0]['uid']==0 and new[0]['paper_parent']!=0
                            if kind=='少量partial' and quantity=='RISK' and exit_mode=='PARTIAL':
                                first=[o for o in new if o['paper_parent']==0]
                                assert first and first[0]['quantity']<4
                                assert not any(o['reason']=='四分の一' and o['paper_parent']==0 for o in value['orders'])
                            if kind=='partial予約後quiet' and exit_mode=='PARTIAL':
                                assert not any(o['reason']=='四分の一' and o['paper_parent']==0 for o in value['orders'])
                            counts['独立人工']=counts.get('独立人工',0)+1
                            cases.append(dict(symbol=symbol,side=side,kind=kind,quantity=quantity,exit=exit_mode,
                                closed_parents=len(value['parents']),orders=len(value['orders']),net=value['curve'][-1]['liquidation']))
                source=reference.fixture(symbol,side,'paper継続中targetclose')
                v=reference.run(source,'FULL','TARGET')
                first=v['parents'][0]
                assert first['exit_row']<18 and v['states'][first['exit_row']]['paper_quantity']!=0
                assert v['states'][first['exit_row']]['real_quantity']==0 and len(v['parents'])==1
                core_examples.append(dict(symbol=symbol,side=side,case='paper未完結中の実完結',parent=first,paperqty=v['states'][first['exit_row']]['paper_quantity']))
                # 原GUと長出口の基準を同じechoで照合しない。
                source=reference.fixture(symbol,side)
                books={e:reference.run(source,'FULL',e) for e in ('GU','TARGET','TRAIL','PARTIAL')}
                assert books['GU']['parents'][0]['exit_row']!=books['TARGET']['parents'][0]['exit_row']
                for e in ('TRAIL','PARTIAL'):
                    b=books[e]
                    assert b['publications'][1]['busy'] and not b['publications'][1]['accepted']
                    assert b['states'][8]['real_parent']==0 and b['states'][8]['paper_cid']==1
                    assert b['states'][8]['nominal']==b['parents'][0]['nominal']
                for p in books['TARGET']['parents'][1:]:
                    start=p['entry_row'];expected=-source['tick']*p['quantity']*source['multiplier']-2*reference.fee(p['quantity'],symbol)
                    assert abs(books['TARGET']['states'][start]['local_net']-expected)<1e-6
                # 新場損失/親損失をOFFにしたHALF原GUだけを旧純FAK1と別に比較する。
                gu=reference.run(source,'HALF','GU',guards=False)
                prior=deepcopy(source);prior['full_quantity']=source['shadow_full'];prior['gate']={o['row']:True for o in prior['feed'] if o['new']}
                for o in prior['feed']:o['reason']=1 if o['new'] else 2
                before=old.run(prior,'FAK1',sizing=False)
                fields=('row','source','side','quantity','price','new','uid','fee')
                assert [{k:o[k] for k in fields} for o in gu['orders']]==[{k:o[k] for k in fields} for o in before['orders']]
                assert gu['curve'][-1]['liquidation']==before['fee_curve'][-1]['liquidation']
                counts['原GU別純対照']=counts.get('原GU別純対照',0)+1
        assert counts['独立人工']==480 and counts['未来未読接頭']==3840 and counts['原GU別純対照']==4
        output=dict(全合格=True,状態='新 source 完成前の純参照のみ。正式 source/金融への合格ではない。',
            検査=counts,人工結果=cases,paperと実親の分母反例=core_examples,
            法則=['実完結親は actualUID の残数量0で成立し、paper vcore が未完結でも分母から除外しない。',
                '親名目Nは初実fill価格×実初q×倍率。当時以降のpaper親番号・価格・部分返済で再選択しない。',
                '親清算netは場清算から当親entry直前の確定場netを引く。前親利益を新親のprofit armへ使わない。',
                'scene名目は最初観測session Last×満容量×倍率で別固定。新受理や初実fillへ付け替えない。',
                '実保有時のnative退出はpaper返済を無視するが、未約定entry予約は最初paper返済で永久取消。同行はfirstgoodfill先。',
                'GU累積返済はactualQ/virtualVで予約量を算術。nativequarterは初Qのfloor1/4を一度だけ、q<4は無し。'],
            留保=['14条件の原GUも新親/場損失線を追加する変更済み対照。旧exactはguardsOFF/HALFの別純対照だけ。',
                'target/trailの判断は費用後だが次正常返済の価格gapで実利確は目標/floorを下回り得る。',
                'この人工値幅は実市場成績ではない。物理FAK、native mini/micro部分執行、板厚/補充は未測。',
                '初版 source/False を保持。旧注文UIDは新規だけ、返済注文は-1と別対象UIDなので純参照もこれを分離した。新経済source変更は0。'],
            仕様精密化='根がRISK BQ+min(0,場清算)と前予約→FAK→paper→親/場判定、GU既予約保持＋stop未予約残の別注文を承認。v2/source/proofは別保存で不変更。',
            referenceSHA256=hashlib.sha256((HERE/'economic_reference_v3.py').read_bytes()).hexdigest(),
            checkerSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),旧純参照SHA256=hashlib.sha256(OLD.read_bytes()).hexdigest(),
            新源import=0,金融=0,入力=0,台帳=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,検査=counts,SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),検査=counts,
            referenceSHA256=hashlib.sha256((HERE/'economic_reference_v3.py').read_bytes()).hexdigest(),checkerSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            新源import=0,金融=0,入力=0,台帳=0,API=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':main()
