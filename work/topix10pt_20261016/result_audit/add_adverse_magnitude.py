"""保存signed MAEを保持し、意味を明示した非負逆行幅を別項目へ加える。"""

import hashlib
import json
from pathlib import Path

from project_posthoc import distribution


HERE=Path(__file__).resolve().parent


def magnitude(value: float|None):
    """
    機能: signed最小値と未取得を保持しながら非負の逆行幅だけを派生する。
    引数: value(float|None) は保存signed MAE。
    返り値: float|None。正のMAEは逆行なし0、未知はNone。
    """
    return None if value is None else max(0.,-value)


def annotate_records(value) -> None:
    """
    機能: 保存recordと例に同じ意味の非負逆行幅を追加する。
    引数: value(dict|list|any) は既小射影の原始型。
    返り値: None。既signedMAE・ラベルは書き換えない。
    """
    if isinstance(value,dict):
        if '十pt到達前MAE' in value and not isinstance(value['十pt到達前MAE'],dict):
            value['十pt到達前の非負逆行幅']=magnitude(value['十pt到達前MAE'])
        for child in list(value.values()):annotate_records(child)
    elif isinstance(value,list):
        for child in value:annotate_records(child)


def add_group(group: dict,records: list) -> None:
    """
    機能: 同じ有限分母の非負逆行幅分布を、signed分布の隣へ加える。
    引数: group(dict)、records(list[dict]) は対象群と保存予兆。
    返り値: None。未到達/空の観測はNoneのまま。
    """
    reached=[r for r in records if r['十pt到達原row']>=0]
    recovered=[r for r in reached if r['labels'][1]==-1]
    group['十pt到達前の非負逆行幅全予兆']=distribution([magnitude(r['十pt到達前MAE']) for r in records])
    group['十pt到達した予兆の非負逆行幅']=distribution([magnitude(r['十pt到達前MAE']) for r in reached])
    group['五pt逆先後に到達した予兆の非負逆行幅']=distribution([magnitude(r['十pt到達前MAE']) for r in recovered])
    assert group['十pt到達前の非負逆行幅全予兆']['有限分母']==group['十pt到達前MAE全予兆']['有限分母']


def main() -> None:
    """
    機能: 初版射影だけを一読し、加算型のv2を新規保存する。
    引数: なし。
    返り値: None。元結果/同bytes大copy/preparedの追加読取0。
    """
    assert [magnitude(v) for v in (None,3.,0.,-2.5)]==[None,0.,0.,2.5]
    source=HERE/'S03とT01の事後値幅比較及び到達前経路の小射影.json';body=source.read_bytes()
    assert hashlib.sha256(body).hexdigest()=='2429189275b9b3de5a8dec2d8176b6abceb0a73a3bf78b887bf4cde75834fd2c'
    data=json.loads(body);records=data['S03_別枠10_records'];annotate_records(data)
    all_sessions=[v['session'] for v in data['by_session']['S03']]
    groups=dict(全別枠10=records,買い=[r for r in records if r['方向']==1],売り=[r for r in records if r['方向']==-1],
        デイ=[r for r in records if r['session'].endswith('_Day')],ナイト=[r for r in records if r['session'].endswith('_Night')],
        時系列別枠6=[r for r in records if r['session'] in all_sessions[27:33]],追加別枠4=[r for r in records if r['session'] in all_sessions[33:]])
    for name,selected in groups.items():add_group(data['S03_到達経路集計'][name],selected)
    for session,group in data['S03_到達経路集計']['各場'].items():add_group(group,[r for r in records if r['session']==session])
    data['source']['初版射影_SHA256']=hashlib.sha256(body).hexdigest()
    data['signed_MAEと非負逆行幅の定義']=dict(signed='保存十pt到達前MAE=minの方向付き値。そのまま保持し正値も変更しない。',
        非負逆行幅='finiteならmax(0,−signedMAE)。正signed値は0幅、NoneはNone。別の意味の派生列。',
        観測空='到達前観測空/未到達のNoneを0に置換しない。各分布の有限分母を併記。')
    data['追加読取']['v2化の初版小射影']=1
    path=HERE/'S03とT01の事後値幅比較及び到達前経路の小射影_v2.json';assert not path.exists()
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,path=str(path),SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size,
        非負逆行幅=data['S03_到達経路集計']['全別枠10']['十pt到達した予兆の非負逆行幅']),ensure_ascii=False))


if __name__=='__main__':main()
