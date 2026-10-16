"""旧00060〜00062の保存小資料から、方向到達と先着・実勝敗の根拠を分ける。"""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def digest(path: Path) -> str:
    """
    機能: 読取済み小資料と再現用sourceの指紋を計算する。
    引数: path(Path)。
    返り値: SHA256文字列(str)。原NPZ・台帳を読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name: str) -> dict:
    """
    機能: 自所有域に保存した旧公開小JSONだけを読む。
    引数: name(str)。
    返り値: dict。市場APIや新しい金融を呼ばない。
    """
    return json.loads((HERE/name).read_text(encoding='utf-8'))


def main() -> None:
    """
    機能: 全六候補商品群の保存行と集計を照合し、日本語の根拠監査を保存する。
    引数: なし。
    返り値: None。新規予測や新売買の有効性測定はしない。
    """
    score=read('最大順行と入口採点.json')
    sensitivity=read('限界値の気配感度検査.json')
    old=read('比較3候補.json')
    follow=read('00062_独立検査.json')
    assert old['meta']['セッション数']==25 and old['meta']['全場既知'] is True
    assert old['meta']['期間']=='2026-09-21_Day〜2026-10-07_Day'
    assert score['新規数']==len(score['rows'])==281 and score['除外数']==0
    records=[]
    for method in score['methods']:
        for symbol,saved in method['summary'].items():
            rows=[r for r in score['rows'] if r['method']==method['id'] and r['symbol']==symbol]
            n=len(rows)
            assert n==saved['新規数']
            labels=[row['extent']['到達']['0.10'] for row in rows]
            reached=sum(row['順行到達'] for row in labels)
            reverse=sum(row['逆行到達'] for row in labels)
            first=Counter(row['先着'] for row in labels)
            both=sum(row['順行到達'] and row['逆行到達'] for row in labels)
            late=sum(row['順行到達'] and row['先着']==-1 for row in labels)
            summary=saved['到達']['0.10']
            assert (reached,reverse,first[1],first[-1],first[0],both)==tuple(summary[k] for k in
                ('順行到達','逆行到達','順行先着','逆行先着','未到達','両側到達'))
            assert abs(summary['順行到達率']-reached/n)<1e-14
            assert abs(summary['全入口での順行先着率']-first[1]/n)<1e-14
            before=[row['extent']['最大順行前の逆行'] for row in rows if row['extent']['最大順行前の逆行'] is not None]
            assert len(before)==saved['最大順行前の逆行']['件数']
            assert statistics.median(before)==saved['最大順行前の逆行']['中央値']
            assert max(before)==saved['最大順行前の逆行']['最大']
            quote=[item for item in sensitivity['summary'] if item['候補']==method['number'] and item['銘柄']==symbol]
            assert len(quote)==1 and quote[0]['新規数']==n and quote[0]['中値0_10到達']==reached
            active=len({row['session'] for row in rows})
            records.append(dict(候補=method['number'],id=method['id'],名称=method['name'],symbol=symbol,
                既知場数=25,活動場数=active,入口数=n,順行到達=reached,逆行到達=reverse,
                順行先着=first[1],逆行先着=first[-1],未到達=first[0],両側到達=both,
                逆先着後に順行到達=late,順行到達率=reached/n,全入口順先率=first[1]/n,
                解決内順先率=first[1]/(first[1]+first[-1]) if first[1]+first[-1] else None,
                最大順行前逆行の有効件数=len(before),最大順行前逆行中央値=statistics.median(before),
                最大順行前逆行最大=max(before),
                判断時新規気配から返済気配の到達=quote[0]['判断時新規気配から返済気配0_10到達']))
    assert sum(r['入口数'] for r in records)==281
    stages=follow['旧14先着から新11勝の分解']
    assert stages['段階件数']['旧判断mid同幅']['1']==14
    assert stages['段階件数']['新建値からmid同幅']['1']==12
    assert stages['段階件数']['開始0_11']['1']==11
    assert stages['段階件数']['実決済勝敗']['1']==11
    stage_rows=stages['全23入口']
    assert len(stage_rows)==23
    for name,counts in stages['段階件数'].items():
        counted=Counter(str(row['stages'][name]) for row in stage_rows)
        assert all(counted[key]==value for key,value in counts.items())
    record=dict(全合格=True,整理日='2026-10-16',商品群=records,
        既知期間=old['meta']['期間'],既知場数=25,新旧区別='過去の保存採点の再加算。新たな方向予測標本ではない。',
        候補3の全力トレール=follow['主案'],NK候補3の段階=stages['段階件数'],
        参照SHA256={name:digest(HERE/name) for name in
            ('最大順行と入口採点.json','比較3候補.json','限界値の気配感度検査.json','00062_独立検査.json')},
        元NPZ=0,台帳=0,巨大金融結果=0,新金融=0,API=0)
    target=HERE/'旧三候補の方向到達と先着及び実取引の小根拠.json'
    assert not target.exists()
    target.write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,群数=len(records),入口数=281,SHA256=digest(target),records=records),ensure_ascii=False))


if __name__=='__main__':main()
