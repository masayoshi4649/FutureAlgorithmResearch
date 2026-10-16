"""完成した小診断だけで公開説明の三比較・二例・期間範囲を確認する。"""

import json
import re
from urllib.parse import unquote

import reader


def main() -> None:
    """
    機能: 公開MDを既保存の新反転小診断へ結び、金額・原seq・料・留保を検算する。
    引数: なし。
    返り値: None。金融元結果・台帳・原入力を追加で読まない。
    """
    data_path=reader.HERE/'反転の実運転と二例の注文及び費用の小診断.json'
    data=json.loads(data_path.read_text(encoding='utf-8'))
    md=reader.ROOT/'アルゴリズム調査/00116_全赤字手法の売買反転を同条件で検証/反転しても残った損失の具体例.md'
    text=md.read_text(encoding='utf-8')
    assert data['新結果SHA256']=='7c0bcadbaaf933669c989cdce5517009b7b4adeec6c58fb27c2a379b2dab8b65'
    main=data['十二条件の比較'][reader.MAIN]
    for cid,groups in data['十二条件の比較'].items():
        assert all(group['新反転実運転']['場数']==33 and group['新反転実運転']['赤字場']==33 for group in groups.values())
    checks=[]
    for label,key in (('元115','元115'),('元の新規・返済時刻を固定して逆売買する参考','固定時刻参考'),
                      ('116：反転した保有方向で出口・場停止を再判定','新反転実運転')):
        line=next(line for line in text.splitlines() if line.startswith('| '+label+' |'))
        for symbol in ('TOPIX','NK225'):
            value=main[symbol][key]['収支']
            assert '−'+f'{abs(value):,.0f}'+'円' in line
            checks.append(dict(比較=label,symbol=symbol,収支=value))
    for symbol,label in (('TOPIX','TOPIX'),('NK225','日経')):
        group=main[symbol]
        c=group['金額分解']
        line=f"| {label} | −{abs(c['中値差粗損益']):,.0f}円 | {c['気配差負担']:,.0f}円 | {c['手数料']:,.0f}円 | −{abs(c['収支']):,.0f}円 |"
        assert line in text
        assert reader.number(c['中値差粗損益'])-reader.number(c['気配差負担'])-reader.number(c['手数料'])==reader.number(c['収支'])
        for label,scope in data['主候補の期間'][symbol].items():
            assert scope['赤字場']==scope['場数'] and scope['黒字場']==scope['無取引場']==0
    for example in data['第一公開二例']:
        assert example['実親保存有無'] is True
        prefix='- **TOPIX' if example['symbol']=='TOPIX' else '- **日経'
        line=next(line for line in text.splitlines() if line.startswith(prefix))
        p,snap=example['parent'],example['snapshots']
        for key in ('公開','新規','最終返済'):
            assert 'seq'+str(snap[key]['raw_seq']) in line
        assert str(p['quantity'])+'枚' in line
        assert '**−'+f"{abs(p['net_yen']):,.0f}"+'円**' in line
        assert example['金額分解']['中値差粗損益']==0
        traces=example['実台帳の理由と受理']
        assert len(traces['orders'])==2 and len(traces['control_events'])==1
        assert int(traces['control_events'][0]['reason'])==141
        assert int(traces['control_events'][0]['row'])==p['entry_row']
        assert traces['control_events'][0]['gross_ticks']==-2
        assert sum(row['fee'] for row in traces['orders'])==p['fee_yen']
        assert traces['orders'][0]['side']==p['side']==-traces['orders'][1]['side']
    for required in ('shadow運転','保存会計だけの再集計','親数は234→184件／188→144件',
                     '原NPZ・event・旧115金融の追加読取は0','約定行を見てから成行注文を取消した利益は算出していない',
                     'どちらも未検証','分母も出口も違う'):
        assert required in text
    links=re.findall(r'\]\(([^)]+)\)',text)
    assert all((md.parent/unquote(link)).exists() for link in links)
    fixed=json.loads(reader.PLAN.read_text(encoding='utf-8'))
    assert reader.sources()==fixed['source_SHA256']
    proof=reader.HERE/'公開反転説明の三比較と二例及び期間の確認.json'
    reader.write(proof,dict(全合格=True,公開MD_SHA256=reader.sha(md.read_bytes()),小診断SHA256=reader.sha(data_path.read_bytes()),
        金融元結果SHA256=data['新結果SHA256'],三比較=checks,リンク数=len(links),source_SHA256=reader.sources(),
        新金融結果追加読=0,新台帳追加読=0,原NPZ=0,eventNPZ=0,旧115金融=0,API=0))
    print(json.dumps(dict(全合格=True,MD_SHA256=reader.sha(md.read_bytes()),証跡SHA256=reader.sha(proof.read_bytes())),ensure_ascii=False))


if __name__=='__main__':main()
