"""保存済みROTATEの一場明細だけを表示し、新しい売買再生は行わない。"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import html
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=HERE.parents[2]
PUBLIC=ROOT/'アルゴリズム調査/00120_段階トレーリング新規と利益玉の部分回転'
SESSION='2026-09-24_Day'
METHOD='ROTATE_S2_T1'
NAME='2026-09-24_Dayの売買と利確明細.html'
JST=timezone(timedelta(hours=9))


def sha(payload: bytes) -> str:
    """
    機能: 保存済み会計と保全コピーの同一性を確認する。
    引数: payload(bytes)は完成会計又は既存NPZ。
    返り値: strはSHA256。金融再生を行わない。
    """
    return hashlib.sha256(payload).hexdigest()


def stamp(epoch: float) -> str:
    """
    機能: 保存UNIX秒をその日の日本時刻へ変換する。
    引数: epoch(float)は保存注文又は玉の約定時刻。
    返り値: strはHH:MM:SS。同日であることも確認する。
    """
    value=datetime.fromtimestamp(float(epoch),JST)
    assert value.strftime('%Y-%m-%d')==SESSION.split('_')[0]
    return value.strftime('%H:%M:%S')


def save(path: Path, value: dict) -> None:
    """
    機能: 新しい表示用小資料をUTF-8で保存する。
    引数: path(Path)は未使用先、value(dict)は保存会計からの派生値。
    返り値: None。既存の金融結果を上書きしない。
    """
    assert not path.exists(),path
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def combine(lots: list[dict]) -> list[dict]:
    """
    機能: 新規・返済の時刻と価格・理由が同一の一枚玉だけをまとめる。
    引数: lots(list[dict])は実完結一枚UIDの一覧。
    返り値: list[dict]は時刻順の表示行。別々の一枚注文の手数料をそのまま合計する。
    """
    buckets=defaultdict(list)
    for lot in lots:
        key=tuple(lot[k] for k in ('side','entry_epoch','entry_price','exit_epoch','exit_price','reason',
                                   'entry_decision_epoch','exit_decision_epoch'))
        buckets[key].append(lot)
    output=[]
    for members in buckets.values():
        row=dict(members[0])
        row.update(quantity=len(members),uids=[v['uid'] for v in members],
            gross=sum(v['gross'] for v in members),fees=sum(v['fees'] for v in members),net=sum(v['net'] for v in members))
        output.append(row)
    return sorted(output,key=lambda r:(r['exit_epoch'],r['entry_epoch'],r['side'],r['uids']))


def number(value: float, signed: bool=False) -> str:
    """
    機能: 価格・値幅・円を不要な小数ゼロなしに整える。
    引数: value(float)は有限数、signed(bool)は正の符号の有無。
    返り値: strは日本語表に用いる数値。
    """
    return format(value,('+' if signed and value>0 else '')+',g')


def table(rows: list[dict], unit: str) -> str:
    """
    機能: 同時刻同価格の実売買を、値幅・枚数・円額付きで表示する。
    引数: rows(list[dict])は表示用完結玉、unit(str)はpt又は指数円。
    返り値: strはHTML表。新規と返済の判断時刻も展開せず確認できる。
    """
    body=[]
    for i,row in enumerate(rows,1):
        values=[str(i),'買い→売り' if row['side']==1 else '売り→買い',
            row['entry_time'],number(row['entry_price']),row['exit_time'],number(row['exit_price']),
            number(row['points'],True)+unit,str(row['quantity']),number(row['gross'],True),
            number(row['fees']),number(row['net'],True),
            '場末返済' if row['reason']==9 else ('追尾利確' if row['net']>0 else '追尾返済・損失')]
        title='UID '+','.join(map(str,row['uids']))+'／新規判断 '+row['entry_decision_time']+'／返済判断 '+row['exit_decision_time']
        body.append('<tr data-net="'+str(row['net'])+'" title="'+html.escape(title,quote=True)+'">'+''.join('<td>'+html.escape(v)+'</td>' for v in values)+'</tr>')
    headers=('番号','新規→返済','新規時刻','新規価格','返済時刻','返済価格','値幅／枚','枚数','粗損益円','手数料円','純損益円','返済理由')
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+x+'</th>' for x in headers)+'</tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'


def main() -> None:
    """
    機能: 同じ完成会計の二商品一場を取り出し、全注文対応と純損益を照合して公開する。
    引数: なし。固定した既存結果と独立監査所有NPZだけを一読する。
    返り値: None。元book・quotes列・売買エンジン・現在APIを読まない。
    """
    assert not (PUBLIC/NAME).exists()
    owned=HERE/'owned'
    owned.mkdir(exist_ok=False)
    plan=dict(session=SESSION,method=METHOD,source='recovery_e1の保存完了会計',
        input_scope='独立監査所有TOPIX/NK225当該一場のNPZ各一読、orders/lotsのみ。quotes未読。',
        original_market_reads=0,financial_replay=0,API=0,新規試行登録='保存結果の表示だけなので行わない')
    save(HERE/'表示計画.json',plan)
    payload=(BASE/'root_owned_e/カバーを維持する組全体追尾と全四十場.json').read_bytes()
    assert sha(payload)=='63766637c69f8572465b1ec3cc3c735e8eef234c1657b3ca0542bd3b6fa9f2ba'
    (owned/'完成結果.json').write_bytes(payload)
    source=json.loads(payload)
    policy_index=next(i for i,s in enumerate(source['specs']) if s['id']==METHOD)
    all_data={}
    contents=[]
    for symbol,label,multiple,fee,unit in (('TOPIX','TOPIXミニ',1000,82,'pt'),('NK225','日経マイクロ',10,22,'円')):
        reference=next(r for r in source['cache'] if r['symbol']==symbol and r['session']==SESSION)
        path=BASE/'audit_result120e1/owned'/symbol/(SESSION+'.npz')
        raw=path.read_bytes()
        assert sha(raw)==reference['sha256']
        (owned/(symbol+'.npz')).write_bytes(raw)
        with np.load(BytesIO(raw),allow_pickle=False) as data:
            o=data['orders'];v=data['lots']
            orders=o[o[:,0]==policy_index,1:].copy()
            values=v[v[:,0]==policy_index,1:].copy()
        assert orders.shape[1]==18 and values.shape[1]==19
        lots=[]
        for v in values:
            uid=int(v[0]);entry=orders[(orders[:,0]==uid)&(orders[:,1]==1)]
            exit_=orders[(orders[:,0]==uid)&(orders[:,1]==2)]
            assert len(entry)==len(exit_)==1
            e,x=entry[0],exit_[0]
            assert e[2]==v[1] and x[2]==-v[1] and e[7]==v[6] and x[7]==v[10]
            assert e[11]==x[11]==1 and e[4]==v[4] and x[4]==v[8]
            points=float(v[1]*(v[10]-v[6]))
            assert v[12]==fee and points*multiple==v[11] and v[11]-v[12]==v[13]
            lots.append(dict(uid=uid,side=int(v[1]),rung=int(v[2]),entry_epoch=float(v[5]),exit_epoch=float(v[9]),
                entry_time=stamp(v[5]),exit_time=stamp(v[9]),entry_price=float(v[6]),exit_price=float(v[10]),
                entry_row=int(v[4]),exit_row=int(v[8]),entry_decision_epoch=float(e[5]),exit_decision_epoch=float(x[5]),
                entry_decision_time=stamp(e[5]),exit_decision_time=stamp(x[5]),
                points=points,quantity=1,gross=float(v[11]),fees=float(v[12]),net=float(v[13]),reason=int(v[14])))
        expected=next(r for r in source['runs'] if r['symbol']==symbol and r['session']==SESSION and r['method']==METHOD)
        assert len(lots)==expected['closed_lots']==expected['entries'] and len(orders)==2*len(lots)
        assert sum(max(r['net'],0) for r in lots)==expected['profit']
        assert -sum(min(r['net'],0) for r in lots)==expected['loss']
        assert sum(r['net'] for r in lots)==expected['net']
        assert sum(r['fees'] for r in lots)==expected['fees']
        groups=combine(lots)
        assert sum(r['quantity'] for r in groups)==len(lots)
        assert sum(r['net'] for r in groups)==expected['net']
        all_data[symbol]=dict(label=label,multiplier=multiple,roundtrip_fee_per_lot=fee,unit=unit,
            expected=expected,lot_count=len(lots),group_count=len(groups),lots=lots,groups=groups,reference=reference)
        contents.append('<section id="'+symbol+'"><h2>'+label+'</h2><p><strong>利益 '+number(expected['profit'])+'円（'+str(int(expected['wins']))+'枚）／損失 '+number(expected['loss'])+'円（'+str(int(expected['losses']))+'枚）／収支 '+number(expected['net'],True)+'円</strong></p><p>完結'+str(len(lots))+'枚、手数料合計'+number(expected['fees'])+'円。入口の一単位 '+number(expected['step'])+unit+'、返済トレーリング '+number(expected['step'])+unit+'。</p>'+table(groups,unit)+'</section>')
    save(HERE/'表示用の全玉と同時約定集約.json',dict(passed=True,**plan,symbols=all_data))
    doc='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>2026-09-24 デイの売買・利確明細</title><style>
body{margin:0;background:#0c1422;color:#e4ecf7;font:15px/1.65 system-ui,sans-serif}main{max-width:1550px;margin:auto;padding:22px 15px}h1{font-size:25px}h2{margin-top:28px}a{color:#98ceff}.note{color:#b8c8dc}.scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:13px}th,td{padding:8px;border-bottom:1px solid #354155;text-align:right}th{background:#1b2b43}td:last-child,td:nth-child(2){text-align:left}tr:hover{background:#1b2b43}strong{color:#f2ce83}
</style></head><body><!--
[コンポーネント概要]
mainは一場の両銘柄について新規と返済を一行で対応付けます。
.scroll内だけ横スクロールし、同じ新規・返済時刻と価格の一枚注文を枚数で集約します。
各行のtitleにはUIDと新規・返済の判断時刻を残します。画面に出す時刻は実約定です。
--><main><h1>2026-09-24 デイ：売買と利確明細</h1><p>手法：<b>ROTATE_S2_T1</b>（上下対称の段階新規・利益玉だけを個別追尾返済）。<a href="#TOPIX">TOPIX</a> ／ <a href="#NK225">日経</a></p><p class="note">時刻は日本時間の実約定。同じ新規・返済時刻と価格の一枚注文だけをまとめ、枚数を表示。値幅は一枚当たりの手数料前。純損益は全枚数の往復手数料込みです。TOPIXは1pt＝1,000円/枚・往復82円/枚、日経は指数1円＝10円/枚・往復22円/枚。数量は累計約定枚数で、片方向の同時上限はTOPIX10枚・日経20枚。</p>'''+''.join(contents)+'''<p class="note">利確条件で発注しても、次の売買気配で損失となった行は「追尾返済・損失」と表示。場末返済を利益利確へ混ぜません。ラージ売買気配による小型商品の代理約定の既存保存結果です。新しい売買再生・実注文・現在データ取得はありません。</p><p><a href="段階トレーリングの結論と全セッション損益.html">全40場・全条件の結果</a></p></main></body></html>'''
    (PUBLIC/NAME).write_text(doc,encoding='utf-8')
    save(HERE/'生成証跡.json',dict(passed=True,session=SESSION,method=METHOD,source_sha256=sha(payload),
        html_path=(PUBLIC/NAME).relative_to(ROOT).as_posix(),html_sha256=sha((PUBLIC/NAME).read_bytes()),
        independent_evidence=False,financial_replay=0,original_market_reads=0,quotes_columns_read=0,
        summaries={s:dict(net=v['expected']['net'],lots=v['lot_count'],groups=v['group_count']) for s,v in all_data.items()}))
    print(json.dumps({s:dict(summary=v['expected'],first_profits=[r for r in v['groups'] if r['net']>0][:4],
        largest_loss=min(v['groups'],key=lambda r:r['net']),largest_profit=max(v['groups'],key=lambda r:r['net'])) for s,v in all_data.items()},ensure_ascii=False))


if __name__=='__main__':
    main()
