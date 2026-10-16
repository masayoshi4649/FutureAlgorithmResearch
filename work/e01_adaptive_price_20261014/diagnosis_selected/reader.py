"""選択条件の三固定場を小結果一読だけで射影し、固定許容の旧勝負と比較する。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
FINANCE=ROOT/'work/e01_adaptive_price_20261014/engine/finance/結果.json'
EXPECTED='13f534a10b081db94944d723171214a2132829b66b70f177e0d3055b27116944'
TARGETS=(('NK225','2026-09-22_Day','E01_ADAPT_G25_ADAPT100_P1','E01_FAK_G50_FAK0_P1'),
         ('NK225','2026-10-06_Night','E01_ADAPT_G25_ADAPT100_P1','E01_FAK_G50_FAK0_P1'),
         ('TOPIX','2026-09-30_Night','E01_ADAPT_G50_ADAPT75_P1','E01_FAK_G50_FAK1_P1'))


def sha(path: Path) -> str:
    """
    機能: 所有reader又は小計画の指紋を求める。
    引数: path(Path) は明示source又は小資料。
    返り値: str はSHA256。金融本文をこの関数で再読しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, data: dict) -> None:
    """
    機能: 診断所有域の未保存JSONだけをUTF-8で保存する。
    引数: name(str)、data(dict) は計画又は小射影。
    返り値: None。金融source23や公共資料を変更しない。
    """
    target=HERE/name;assert not target.exists() and target.resolve().is_relative_to(HERE)
    target.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')


def timed(value: object) -> object:
    """
    機能: 保存系譜の価格代理epochを日本日付のJST表示へ併記する。
    引数: value(object) は小射影の辞書又は配列。
    返り値: object は再帰射影。代理時計を受信時計へ読み替えない。
    """
    if isinstance(value,list):return [timed(v) for v in value]
    if not isinstance(value,dict):return value
    out={k:timed(v) for k,v in value.items()}
    for key,v in value.items():
        if v is not None and (key.endswith('price_time_s') or key in ('受理価格時計',)):
            out[key+'_JST']=datetime.fromtimestamp(v,ZoneInfo('Asia/Tokyo')).isoformat()
    return out


def prepare() -> None:
    """
    機能: 小結果本文を読む前に対象三場・範囲・指紋と一読規則を保存する。
    引数: なし。
    返り値: None。input/台帳/金融本文は読まない。
    """
    write('選択三場の票許容と後参加を確認する固定計画.json',dict(全合格=True,
        読取目的='旧G50固定0の勝ち喪失後の赤字二場、旧TOP固定1の唯一敗が選択条件でどう変わるかを具体系譜で確認。',
        source_SHA256={Path(__file__).name:sha(Path(__file__))},小結果=dict(path=FINANCE.relative_to(ROOT).as_posix(),SHA256=EXPECTED),
        対象=[dict(symbol=s,session=t,selected_id=c,comparison_id=b) for s,t,c,b in TARGETS],
        同入口補助='NK二場は同gateG50_ADAPT75_P1も射影し、G25変更との混同を避ける。勝敗で他場へ選び直さない。',
        使用='actual/reused_parent_diagnostics、対象rows、両cap五寄与、初受理/実初回小診断、候補件数だけ。',
        境界='未約定親の未保存試行価格は補完しない。MAE極値は事後診断専用。受信時刻や板厚補充を推定しない。',
        小結果読取予定=1,原input=0,台帳本文=0,原板=0,NPZ=0,金融=0,API=0,金融source変更=0))


def run() -> None:
    """
    機能: 事前固定の小結果を一読し、対象の実親・票/公開許容・純差と未保存事項を保存する。
    引数: なし。CLI --root-small-result-read-permitted の明示後だけ呼ぶ。
    返り値: None。保存勝敗を使った新金融やsource修正は行わない。
    """
    plan_path=HERE/'選択三場の票許容と後参加を確認する固定計画.json'
    plan=json.loads(plan_path.read_text(encoding='utf-8'));assert plan['source_SHA256'][Path(__file__).name]==sha(Path(__file__))
    target=HERE/'選択三場の票許容と旧勝ち及び後参加の具体診断.json';assert not target.exists()
    raw=FINANCE.read_bytes();assert hashlib.sha256(raw).hexdigest()==EXPECTED
    result=json.loads(raw.decode('utf-8-sig'));assert result['全合格'] and result['source開始終端一致']
    configs={c['id']:c for c in result['configs']};records=[]
    for symbol,session,selected,old in TARGETS:
        fresh=[p for p in result['actual_parent_diagnostics'][selected] if p['symbol']==symbol and p['session']==session]
        previous=[p for p in result['reused_parent_diagnostics'][old] if p['symbol']==symbol and p['session']==session]
        fresh_rows=[r for r in result['results'][selected]['rows'] if r['symbol']==symbol and r['session']==session]
        old_rows=[r for r in result['reused_results'][old]['rows'] if r['symbol']==symbol and r['session']==session]
        assert len(fresh_rows)==len(old_rows)==1
        assert sum(p['net_yen'] for p in fresh)==fresh_rows[0]['収支']
        assert sum(p['net_yen'] for p in previous)==old_rows[0]['収支']
        ids={p['parent'] for p in fresh};missing=[p for p in previous if p['parent'] not in ids]
        config=configs[selected];expected=[]
        for p in previous:
            v=p['published_balance'];votes=p['published_direction_votes']
            gate=p['published_known'] and votes>=config['min_votes'] and v>=config['balance_threshold']
            allowance=int(p['published_known'] and votes>=2 and v>=config['strong_balance_threshold'])
            side=p['side'];cap=(p['publication_ask']+allowance*(.5 if symbol=='TOPIX' else 10.)) if side>0 else (p['publication_bid']-allowance*(.5 if symbol=='TOPIX' else 10.))
            expected.append(dict(old_parent=p['parent'],gate_from_saved_publication=gate,allowance_from_saved_publication=allowance,
                selected_cap_from_saved_publication=cap,old_fill_price=p['entry']['price'],
                old_fill_outside_selected_cap=(p['entry']['price']>cap if side>0 else p['entry']['price']<cap),
                definition='旧同公開資料への機械条件計算。新アルゴの未約定試行BBOを補完したものではない。'))
        item=dict(symbol=symbol,session=session,selected_id=selected,old_comparison_id=old,
            selected_config=config,selected_row=fresh_rows[0],old_row=old_rows[0],net_change=fresh_rows[0]['収支']-old_rows[0]['収支'],
            actual_parents=fresh,old_actual_parents=previous,removed_old_parents=missing,old_publication_under_selected_rule=expected,
            fak_diagnosis=[r for r in result['fak_diagnosis'][selected] if r['symbol']==symbol and r['session']==session],
            same_gate_comparisons={kind:[r for r in result['comparisons'][kind]['各場寄与'][selected] if r['symbol']==symbol and r['session']==session] for kind in ('FAK0','FAK1')})
        if symbol=='NK225':
            same='E01_ADAPT_G50_ADAPT75_P1'
            item['same_gate_adaptive']=dict(id=same,rows=[r for r in result['results'][same]['rows'] if r['symbol']==symbol and r['session']==session],
                actual_parents=[p for p in result['actual_parent_diagnostics'][same] if p['symbol']==symbol and p['session']==session])
        records.append(timed(item))
    assert sha(Path(__file__))==plan['source_SHA256'][Path(__file__).name]
    write(target.name,dict(全合格=True,source_SHA256=plan['source_SHA256'],計画SHA256=sha(plan_path),小結果SHA256=EXPECTED,
        対象三場=records,小結果この目的読取数=1,原input=0,台帳本文=0,金融=0,原板=0,NPZ=0,API=0,金融source変更=0,
        限界=['NK選択はG25なのでG50固定0との差に入口gate変更も含む。same_gate_adaptiveを別保存。',
            '新しい拒否親の試行価格は小結果に未保存。旧親の公開capと旧fill価格への機械条件を、未見試行実績と呼ばない。',
            '当時までの公開票だけで許容を選ぶ。事後清算極値/旧勝敗は規則へ使用しない。']))
    for item in records:
        print(item['symbol'],item['session'],'旧',item['old_row']['収支'],'選択',item['selected_row']['収支'],
            '実親',[(p['parent'],p['net_yen']) for p in item['actual_parents']],flush=True)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();group=parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare-only',action='store_true');group.add_argument('--root-small-result-read-permitted',action='store_true')
    args=parser.parse_args();prepare() if args.prepare_only else run()
