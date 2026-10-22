"""全二十四政策の架空小会計だけで、表示・母集団・政策切替の保存を調べる。"""

from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import statistics

from bs4 import BeautifulSoup

import sys
sys.path.insert(0,str(Path(__file__).resolve().parent/'recovery_d'))
import catalog120d as C
import report120d as R


HERE=Path(__file__).resolve().parent
OUT=HERE/'report_artificial_d'
COUNTS=Counter()


def check(value: bool,label: str) -> None:
    """
    機能: 合成表示の検査件数を記録し、不一致を停止する。
    引数: value(bool)は期待、label(str)は検査名。
    返り値: None。経済源や実結果は変更しない。
    """
    assert value,label
    COUNTS[label]+=1


def number(value: float|None,signed: bool=False) -> str:
    """
    機能: 表示期待値を生成器とは別の関数で組み立てる。
    引数: value(float|None)、signed(bool)は表示する値と正負指定。
    返り値: str。未評価は—。
    """
    if value is None:return '—'
    if abs(value)<1e-7:return '0'
    return f'{value:+,.0f}' if signed else f'{value:,.0f}'


def fixture() -> dict:
    """
    機能: 原市場・金融を使わず、24政策×架空40場×2商品を作る。
    引数: なし。
    返り値: dictは完全合成のschema入力。実在の場を有効標本にしない。
    """
    specs=C.specifications();scenes=['合成場'+str(i+1).zfill(2) for i in range(40)];rows=[]
    for index,spec in enumerate(specs):
        for i,scene in enumerate(scenes):
            for si,symbol in enumerate(R.SYMBOLS):
                active=i%10!=0 and index!=23;unclosed=int(index==22 and i==39)
                p=100+index*7+si*13 if active and i%8 else 0;loss=60+index if active and not p else 0
                realized=p-loss;fees=22+si*60 if active else 0
                rows.append(dict(method=spec['id'],session=scene,symbol=symbol,profit=p,loss=loss,net=realized-250*unclosed,realized_net=realized,cash=realized-11*unclosed,
                    fees=fees,closed_lots=int(active),wins=int(p>0),losses=int(loss>0),unclosed=unclosed,max_long=int(active),max_short=unclosed,
                    max_drawdown=30+index if active else 0,min_equity=-30-index if active else 0,entries=int(active)+unclosed,canceled=0,clock_rejected=0,step=1 if active else None,
                    forced_loss=loss,forced_profit=0,trail_net=p,long_net=realized*.25,short_net=realized*.75))
    return dict(sessions=scenes,specs=specs,runs=rows,source_SHA256={'完全合成/source.py':'a'*64},cache=[],order_columns=['合成'],lot_columns=['合成'],curve_columns=['合成'])


def main() -> None:
    """
    機能: 全セル・全合計・未返済・無取引・可変政策数を合成入力で照合する。
    引数: なし。
    返り値: None。正式金融の検証と混同しない私有証跡を保存する。
    """
    target=OUT/'可変政策と全四十場及び玉別損益の純表示検査.json';assert not target.exists()
    data=fixture();generated=R.generate(data,OUT/'public','b'*64,'完全合成/金融ではない.json',True)
    page=BeautifulSoup((OUT/'public'/R.HTML_NAME).read_text(encoding='utf8'),'html.parser');public=json.loads((OUT/'public/data.json').read_text(encoding='utf8'))
    check(generated['fixture'] and public['fixture'] and generated['policies']==24 and generated['symbol_sessions']==1920,'正式と異なる合成保存')
    source={(r['method'],r['session'],r['symbol']):r for r in data['runs']};tables=page.select('table.sessions')
    check(len(tables)==len(page.select('#policy option'))==24,'全政策の選択肢と全表を残す')
    for table in tables:
        ident=table['data-method'];check(len(table.select('tbody tr'))==40,'全四十場を省略しない')
        for tr,scene in zip(table.select('tbody tr'),data['sessions']):
            cells=[]
            for symbol in R.SYMBOLS:
                r=source[ident,scene,symbol];cells.extend([number(r['profit']),number(r['loss']),number(r['realized_net'],True),number(r['net'],True),number(r['fees']),str(r['closed_lots']),str(r['unclosed']),f"{r['max_long']}/{r['max_short']}"])
            check(tr['data-session']==scene and [td.get_text(strip=True) for td in tr.select('td')]==cells,'全1920商品場の確定と時価及び枚数を表示')
        foot=[]
        for symbol in R.SYMBOLS:
            rr=[source[ident,s,symbol] for s in data['sessions']];m=public['cases'][ident]['metrics'][symbol]
            values={k:sum(r[k] for r in rr) for k in ('profit','loss','realized_net','net','fees','closed_lots')}
            check(all(abs(m[k]-v)<1e-7 for k,v in values.items()),'玉別損益合計と時価合計を別々に足算')
            check(m['median']==statistics.median(r['net'] for r in rr) and m['worst']==min(r['net'] for r in rr),'中央値と最悪の母集団')
            check(m['unclosed_sessions']==sum(r['unclosed']>0 for r in rr),'未返済を勝ちから分離')
            foot.extend([number(values['profit']),number(values['loss']),number(values['realized_net'],True),number(values['net'],True),number(values['fees']),str(values['closed_lots']),str(sum(r['unclosed'] for r in rr)),f"{max(r['max_long'] for r in rr)}/{max(r['max_short'] for r in rr)}"])
        check([td.get_text(strip=True) for td in table.select('tfoot td')]==foot,'全場合計と最大保有の足算')
    no=data['specs'][23]['id'];openid=data['specs'][22]['id']
    check(all(public['cases'][no]['metrics'][s]['inactive']==40 and public['cases'][no]['metrics'][s]['black']==0 for s in R.SYMBOLS),'全無取引を四十勝にしない')
    check(not next(r['qualified'] for r in public['common_ranking'] if r['id']==openid) and all(public['cases'][openid]['metrics'][s]['top3_removed'] is None for s in R.SYMBOLS),'残玉時価の黒字でも未返済は資格なし')
    check(len(public['main_ids'])==len({public['cases'][v]['spec']['mode'] for v in public['main_ids']})==3,'共通上位三件は異系統')
    text=page.get_text(' ',strip=True)
    check('完結1枚玉' in text and '確定収支＝利益−損失' in text and '利益玉の返済だけで残る損失を隠しません' in text,'玉の利益だけを成功へ変えない説明')
    check('四捨五入' in text and '次正常原行' in text and '末尾に架空返済は作らず' in text and '未知検証の成功ではありません' in text,'時点と約定と既知開発の留保')
    check(public['baseline_reference']['reference_only'] and public['baseline_reference']['financial_replay']==0 and 'baseline_cases' not in public,'bは参照だけで会計へ足さない')
    check('最初は1枚で試します' in text and '入口の極値・再準備・上げ下げだけ保存Lastへ変更' in text and '単位の起点はBBO中値' in text and '同方向の全残玉清算net' in text and '観測1刻みを超えれば失効' in text,'dのLast入口とBBO及び方向停止を区別')
    for count in (1,7):
        reduced=deepcopy(data);reduced['specs']=reduced['specs'][:count];ids={s['id'] for s in reduced['specs']};reduced['runs']=[r for r in reduced['runs'] if r['method'] in ids]
        _,out,_=R.render(reduced,'c'*64,'完全合成',True);check(len(out['cases'])==count,'政策数を二十四へ固定しない')
    for kind in ('欠行','重複','玉会計改変','枚数上限超過'):
        broken=deepcopy(data)
        if kind=='欠行':broken['runs'].pop()
        elif kind=='重複':broken['runs'].append(broken['runs'][0])
        elif kind=='玉会計改変':broken['runs'][2]['realized_net']+=1
        else:broken['runs'][2]['max_long']=21
        try:R.validate(broken)
        except AssertionError:check(True,kind+'を拒否')
        else:raise AssertionError(kind)
    for link in page.select('[href],[src]'):
        value=link.get('href',link.get('src'));check(':' not in value,'表示で外部取得しない')
        if value.startswith('#'):check(page.find(id=value[1:]) is not None,'政策選択リンクの実在')
        else:check((OUT/'public'/value).exists(),'案内と会計へのリンク実在')
    proof=dict(passed=True,fixture=True,scope='24政策×架空40場×両商品の純表示だけ。市場や金融の性能証拠ではない。',counts=dict(COUNTS),total_checks=sum(COUNTS.values()),generation=generated,
        source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'report120d.py',Path(__file__),HERE/'recovery_d/catalog120d.py')},actual_result_reads=0,NPZ_reads=0,market_reads=0,financial_replay=0,API=0)
    target.write_bytes(R.encoded(proof));print(json.dumps(dict(passed=True,checks=sum(COUNTS.values()),proof_sha256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
