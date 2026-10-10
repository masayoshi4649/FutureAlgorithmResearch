"""入口の対応比較と安定領域を、全件終了後に同じ物差しで集計する。"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

import numpy as np

import component_signals as signals

HERE=Path(__file__).resolve().parent
BASES=('A0__V000','G000_F25_N1__V000','G150_F50_N1__V000')
SYMBOLS=('TOPIX','NK225')


def read(path: Path) -> object:
    """機能: 通常又は圧縮JSONを読む。

    引数: path(Path)。返り値: 保存内容(object)。
    """
    raw=path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix=='.gz' else raw)


def save(path: Path,value: object) -> None:
    """機能: 今作業の固定規則又は集計を保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(HERE)
    path.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n',encoding='utf-8')


def rules() -> dict:
    """機能: 単一最高益ではなく主時計の近傍も含めた評価規則を返す。

    引数: なし。返り値: 固定規則(dict)。
    """
    return dict(新ナイト使用=False,条件数=78,
        基礎='全13と後半7の両銘柄で収支>0・勝ち1枚平均/負け1枚平均>1・上位利益2組除外後>0。',
        主時計領域='相手有無と短期仕様を固定し、主倍率0.8/1/1.2の3条件が全て基礎を通る領域を数える。',
        相手遅延='中央相手48/72秒は単独感度として表示し、主時計3点の代わりにしない。',
        採用='部品単独で自動採用しない。主時計領域の合格・管理器間の再現・出口診断を合わせて統合条件を別固定する。',
        対応差='同じ管理器・同じ主時計・同じ短期窓で相手有無を比較。短期は主方向直接保持との運用差でありTTLの差も含む。',
        確度='過去13は繰り返し探索済み。因果実装・条件付き差の再現と、将来利益の確率保証を区別。')


def main() -> None:
    """機能: 規則を先に固定し、全78条件と対応差を間引かず集計する。

    引数: --freeze(bool)なら固定だけ。返り値: なし(None)。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--freeze',action='store_true');args=parser.parse_args()
    path=HERE/'入口判定規則.json'
    if path.exists(): assert read(path)==rules()
    else:save(path,rules())
    if args.freeze:return
    rows=[]; lookup={}; session_lookup={}
    late=read(HERE.parent/'wave_v38/探索条件の固定.json')['後半7セッション']
    for entry in signals.catalog():
        assert read(HERE/'entry_completed'/(entry['id']+'.json'))['全合格']
        for base in BASES:
            identifier=entry['id']+'__'+base
            summary=read(HERE/'entry_summaries'/(identifier+'.json'))
            sessions=read(HERE/'entry_sessions'/(identifier+'.json.gz'))
            assert len(sessions)==26 and summary['全合格']
            for period in ('all_symbols','symbols'):
                for symbol in SYMBOLS:
                    value=summary[period][symbol]
                    chosen=[r for r in sessions if r['symbol']==symbol and (period=='all_symbols' or r['session'] in late)]
                    top=sorted([v for r in chosen for v in r['two_largest_cycle_profits']],reverse=True)[:2]
                    removed=value['net_yen']-sum(top)
                    payoff=value['average_unit_payoff']
                    passed=value['net_yen']>0 and payoff is not None and payoff>1 and removed>0
                    row=dict(id=identifier,entry=entry,base_id=base,period=period,symbol=symbol,
                             top2_removed=removed,基礎合格=passed,**value)
                    rows.append(row);lookup[entry['id'],base,period,symbol]=row
            session_lookup[entry['id'],base]={(r['session'],r['symbol']):r for r in sessions}
    regions=[]
    for peer in (False,True):
        for short in (None,.8,1.,1.2):
            members=[signals.specification(main_scale=m,short_scale=short or 1.,peer_confirm=peer,
                                          short_confirm=short is not None)['id'] for m in (.8,1.,1.2)]
            for base in BASES:
                group=[lookup[e,base,p,s] for e in members for p in ('all_symbols','symbols') for s in SYMBOLS]
                regions.append(dict(peer=peer,short=short,base_id=base,members=members,
                    全12セル合格=all(r['基礎合格'] for r in group),不合格セル=[dict(entry=r['entry']['id'],
                    period=r['period'],symbol=r['symbol'],net_yen=r['net_yen'],payoff=r['average_unit_payoff'],
                    top2_removed=r['top2_removed']) for r in group if not r['基礎合格']]))
    # ----------------------------------------
    # 集計だけでなく、各セッションの対応差も保存する。
    pairs=[]
    for main in (.8,1.,1.2):
        for short in (None,.8,1.,1.2):
            off=signals.specification(main,short or 1.,False,short is not None)['id']
            on=signals.specification(main,short or 1.,True,short is not None)['id']
            for base in BASES:
                for key,a in session_lookup[on,base].items():
                    b=session_lookup[off,base][key]
                    pairs.append(dict(部品='相手あり－なし',主倍率=main,短期倍率=short,base_id=base,
                        session=key[0],symbol=key[1],差円=a['net_yen']-b['net_yen'],差R=a['net_r']-b['net_r']))
        for peer in (False,True):
            off=signals.specification(main,1.,peer,False)['id']
            for short in (.8,1.,1.2):
                on=signals.specification(main,short,peer,True)['id']
                for base in BASES:
                    for key,a in session_lookup[on,base].items():
                        b=session_lookup[off,base][key]
                        pairs.append(dict(部品='短期あり－なし',主倍率=main,相手あり=peer,短期倍率=short,base_id=base,
                            session=key[0],symbol=key[1],差円=a['net_yen']-b['net_yen'],差R=a['net_r']-b['net_r']))
    assert len(rows)==312 and len(regions)==24
    save(HERE/'entry_assessment.json',dict(全合格=True,完了条件数=78,期間銘柄セル=rows,主時計領域=regions,対応差=pairs))
    print(json.dumps(dict(全78完了=True,合格領域=[{k:v for k,v in r.items() if k not in ('不合格セル','members')}
        for r in regions if r['全12セル合格']]),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
