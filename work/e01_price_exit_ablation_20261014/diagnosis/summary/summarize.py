"""既診断射影だけで反票OFFの残った負けと紙上/Native量の違いを短く保存する。"""

import hashlib
import importlib.util
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
INPUT=HERE.parent/'反票OFF十二条件の方向と気配不利及び具体損失.json'


def compact(p: dict) -> dict:
    """
    機能: 実価格/時刻/原seqとmid分解・保護線を、具体親の小例にまとめる。
    引数: p(dict) は保存分解済み実親。
    返り値: dict は事後診断。ON未保存経路を補完しない。
    """
    e,x=p['entry'],p['exits'][0]
    return dict(session=p['session'],symbol=p['symbol'],actual_parent=p['parent'],paper_parent=p['paper_parent'],actual_uid=p['actual_uid'],
        side=p['side'],entry_type=p['publication_kind'],native_quantity=p['entry_quantity'],
        publication=e['判断'],actual_entry=dict(price=e['price'],**e['約定']),decision=x['判断'],actual_exit=dict(price=x['price'],**x['約定']),
        exit_reason=x['reason_label'],holding_price_proxy_seconds=p['holding_price_proxy_seconds'],
        initial_paper_quantity=p['entry_paper_remaining_quantity'],decision_paper_quantity=p['exit_decision_paper_remaining_quantity'],
        decision_same_origin_paper=p['exit_decision_paper_matches_origin'],
        gross_direction_mid_yen=p['gross_direction_mid_yen'],crossing_disadvantage_yen=p['crossing_disadvantage_yen'],
        order_fees_yen=p['order_fees_yen'],net_yen=p['net_yen'],cause=p['cause'],
        target_yen=p.get('target_yen'),arm_yen=p.get('arm_yen'),parent_stop_yen=p.get('parent_stop_yen'),
        peak_yen=p['parent_mfe_yen'],peak_point=p['first_parent_liquidation_argmax'],
        minimum_point=p['first_parent_liquidation_argmin'],peak_returned_yen=p['peak_returned_yen'])


def run() -> None:
    """
    機能: 全十二の商品別負親分解・元/追加参加・部分paper量と具体赤字上位三場を保存する。
    引数: なし。
    返り値: None。正式新結果/原108/packet/台帳/金融/APIを再読しない。
    """
    saved=INPUT.read_bytes();sha=hashlib.sha256(saved).hexdigest();d=json.loads(saved.decode('utf-8'))
    assert sha=='833dfe5cdd197a0341cf00bec14774cbe16d0926e5a407eb644529a7dd732a75'
    spec=importlib.util.spec_from_file_location('109保存分解の純集計',HERE.parent/'analysis.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    summaries={};examples={};checks=0
    for cid,parents in d['all_parent_decomposition'].items():
        summaries[cid]={};examples[cid]={}
        for s in m.CAP:
            ps=[p for p in parents if p['symbol']==s];negative=[p for p in ps if p['net_yen']<0]
            full=5 if s=='TOPIX' else 10
            partial=[p for p in ps if p['entry_paper_matches_origin'] and 0<p['entry_paper_remaining_quantity']<full]
            current=dict(all_parents=d['summaries'][cid][s],negative_parents=m.group(negative),
                paper_partial_at_entry=m.group(partial),paper_partial_at_entry_quantity_definition='紙上運転の未返済量。板の数量/約定量や支持の強さではない。',
                negative_without_arm=sum(p.get('arm_yen') is not None and p['parent_mfe_yen']<p['arm_yen'] for p in negative),
                negative_arm_denominator=sum(p.get('arm_yen') is not None for p in negative),
                on_off=d['paired_on_off'][cid][s])
            assert current['negative_parents']['negative_parents']==len(negative);checks+=1
            summaries[cid][s]=current;scenes=[]
            for scene in d['worst_three_red_sessions'][cid][s]:
                scenes.append(dict(row=scene['row'],decomposition=scene['summary'],
                    maximum_two_negative_parents=[compact(p) for p in scene['maximum_two_negative_parents']]))
            examples[cid][s]=scenes
    conclusions=[
        '反対価格票退出だけのOFFでTOP6改善6悪化、NK4改善7悪化1同値。全十二条件は両商品で純赤字のまま。元条件ごとに改善/悪化を区別する。',
        'ORIGIN_TARGET TOPはmid方向粗+17500−気配横断192500−料24244=−199244。NKは+39000−77000−11880=−49880。気配不利は実約定grossを分解した額で、追加の料金ではない。',
        'ORIGIN_TARGETの負親はTOP21/21、NK18/18がmid方向自体の逆行。TOP負親群mid−465000/横断150000/料17556、NK負親群mid−130000/横断56000/料7920。費用だけの敗因にはできない。',
        'TOP ORIGIN_TIGHTはON−114244→OFF−84244（+30000）でも赤字。ON/OFFの親対応/退出経路は未収録なので、全差を同親の追尾改善と断定しない。',
        '紙上部分返済後の3/5/6等を109では観測できるが、Nativeは10/20全量を維持する。紙上量は仮想戦略の残建玉であり、市場の板支持量ではない。',
        '損失親が一度黒字でも目標/armまで足りず、原paper撤回又は親stopへ至る例がある。ピークを取れた仮想利益で救済しない。',
        'TOP ORIGIN_TARGET赤字上位三場は10/6Night−97508、9/23Night−57508、9/22Night−35836。10/6の三親は全て紙上撤回、9/22の一親は親stop。反票OFFだけでは方向の誤りと利益返しが残った。']
    out=dict(全合格=True,診断射影SHA256=sha,正式新結果SHA256=d['結果SHA256'],source_SHA256=d['source_SHA256'],
        小結=conclusions,全条件負親と紙上量=summaries,具体赤字上位三場=examples,実値比較件数=d['net_change_counts'],検算=checks,
        読取=dict(既診断射影=1,正式結果再読=0,原108本文=0,packet=0,台帳=0,新金融=0,API=0),
        留保=['ON各場net差は保存から算術比較できる。ON親対応/時刻経路/P&L内訳は未収録。',
            'trim3は各条件自身の正net上位三場除外。残る場集合が同一とは限らない。',
            'Native保持時間/時刻は価格時計代理。物理受信/注文応答時計ではない。事後高安は診断だけ。'])
    target=HERE/'反票OFFでも残った逆行と気配不利の小結.json';assert not target.exists()
    target.write_text(json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('反票OFF小結合格 '+str(checks)+'確認。SHA '+hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':run()
