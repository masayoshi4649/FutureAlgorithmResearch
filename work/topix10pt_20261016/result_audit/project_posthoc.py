"""事後注目S03/T01を、既監査射影と同bytes参照だけから公開追補用に射影する。"""

import hashlib
import json
from pathlib import Path

import numpy as np


HERE=Path(__file__).resolve().parent
RESULT_SHA='b4eefa5f31e36c645fe9c54d2ed715ec074b556524cb024364bd10386121dcf2'
AUDIT_SHA='c049bd108d162cfe72bfdbe28b51a1c28990cd2185cb51917d9db6c35d9a78bc'
OUTPUT=HERE/'S03とT01の事後値幅比較及び到達前経路の小射影.json'


def write(path: Path,value: dict) -> None:
    """
    機能: 計画・小射影を未知Noneを保ち新規保存する。
    引数: path(Path)、value(dict) は出力先とJSON原始型。
    返り値: None。源・結果・旧射影は変更しない。
    """
    assert path.parent==HERE and not path.exists()
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def distribution(values: list) -> dict:
    """
    機能: 保存済み有限値だけで分布を作る。
    引数: values(list[float|None]) はsigned MAE又は代理秒。
    返り値: dict は有限分母/未知数と最小・分位・最大。空を0で補わない。
    """
    finite=[v for v in values if v is not None]
    assert all(isinstance(v,(float,int)) and np.isfinite(v) for v in finite)
    quantiles=np.quantile(finite,[0,.25,.5,.75,1]).tolist() if finite else [None]*5
    return dict(対象数=len(values),有限分母=len(finite),未知数=len(values)-len(finite),
        minimum=quantiles[0],q25=quantiles[1],median=quantiles[2],q75=quantiles[3],maximum=quantiles[4])


def pathway(records: list[dict]) -> dict:
    """
    機能: 一度到達と各幅先着を区別し、到達前逆行・代理所要秒を集計する。
    引数: records(list[dict]) は既保存されたS03の予兆。
    返り値: dict は別分母を保持した到達/未決・MAE・時刻経路。救済利益を算出しない。
    """
    reached=[r for r in records if r['十pt到達原row']>=0];not_reached=[r for r in records if r['十pt到達原row']<0]
    lost5=[r for r in records if r['labels'][1]==-1]
    lost5_then_reached=[r for r in lost5 if r['十pt到達原row']>=0]
    for r in lost5_then_reached:assert r['十pt到達原row']>r['終端原row'][1]
    assert len(records)==len(reached)+len(not_reached)
    return dict(予兆数=len(records),一度十pt到達数=len(reached),未到達数=len(not_reached),
        十pt順先数=sum(r['labels'][2]==1 for r in records),十pt逆先数=sum(r['labels'][2]==-1 for r in records),
        十pt窓末未決数=sum(r['labels'][2]==0 for r in records),十ptEOF未決数=sum(r['labels'][2]==2 for r in records),
        五pt逆先数=len(lost5),五pt逆先後の十pt到達数=len(lost5_then_reached),
        五pt逆先後の十pt未到達数=len(lost5)-len(lost5_then_reached),
        十pt到達前MAE全予兆=distribution([r['十pt到達前MAE'] for r in records]),
        十pt到達した予兆の到達前MAE=distribution([r['十pt到達前MAE'] for r in reached]),
        十pt到達した予兆の代理所要秒=distribution([r['十pt到達までの価格代理秒'] for r in reached]),
        五pt逆先後に到達した予兆の到達前MAE=distribution([r['十pt到達前MAE'] for r in lost5_then_reached]),
        五pt逆先後に到達した予兆の代理所要秒=distribution([r['十pt到達までの価格代理秒'] for r in lost5_then_reached]))


def main() -> None:
    """
    機能: 根が許可した別目的で既owncopyと既監査射影を各一読し追補する。
    引数: なし。
    返り値: None。元measurement/37prepared/原raw/新金融は読まない。
    """
    source_path=HERE/'根完成結果の同bytes参照.json';audit_path=HERE/'四十四条件全場と選択及び固定モデルの独立再集計.json'
    write(HERE/'S03事後経路の派生読取計画.json',dict(目的='正式3を変更せず、10pt対称幅で見えたS03/T01の事後注目を限定追補する。',
        予定読取=dict(監査時同bytes参照=1,独立監査射影=1,元measurement結果=0,prepared=0,raw=0,event=0,金融=0,API=0),
        同bytes参照=dict(path=str(source_path),SHA256=RESULT_SHA),独立監査射影=dict(path=str(audit_path),SHA256=AUDIT_SHA),
        対象=dict(候補=['S03','T01'],期間='固定八期間と37場。S03別枠十場の40保存records。'),
        変更='読取・算術派生のみ。既source10/結果/正式選択は変更しない。',自動再実行=False))
    body=source_path.read_bytes();assert hashlib.sha256(body).hexdigest()==RESULT_SHA;result=json.loads(body);del body
    body=audit_path.read_bytes();assert hashlib.sha256(body).hexdigest()==AUDIT_SHA;audited=json.loads(body);del body
    lookup={r['id']:r for r in audited['全44集計']};ids=['S03','T01'];test=result['periods']['別枠10']
    periods={identifier:lookup[identifier]['非重複'] for identifier in ids}
    by_session={identifier:[] for identifier in ids};s03=[]
    for account in result['accounts']:
        if account['id'] not in ids:continue
        by_session[account['id']].append({key:account[key] for key in ('session','公開候補数','採用予兆数','買い数','売り数','risks')})
        if account['id']!='S03' or account['session'] not in test:continue
        for record in account['records']:
            value=dict(session=account['session'],**record)
            reached=value['十pt到達原row']>=0
            assert reached==(value['十pt到達秒'] is not None)
            value['十pt到達までの価格代理秒']=value['十pt到達秒']-value['公開秒'] if reached else None
            assert not reached or value['十pt到達までの価格代理秒']>=0
            value['五pt逆先後に十pt到達']=bool(value['labels'][1]==-1 and reached)
            s03.append(value)
    for identifier in ids:
        assert len(by_session[identifier])==37 and [r['session'] for r in by_session[identifier]]==result['sessions']
        for period,pool in result['periods'].items():
            rows=[r for r in by_session[identifier] if r['session'] in pool]
            expected=periods[identifier][period]
            assert sum(r['採用予兆数'] for r in rows)==expected['予兆数']
            for ri in range(3):
                for group in ('全体','買い','売り','常時買い','常時売り'):
                    for field in ('順先','逆先','窓末未決','EOF未決','基準不可','n'):
                        total=sum((r['risks'][ri] if group=='全体' else r['risks'][ri][group])[field] for r in rows)
                        assert total==expected['risks'][ri][group][field]
    assert len(s03)==40
    groups=dict(全別枠10=s03,買い=[r for r in s03 if r['方向']==1],売り=[r for r in s03 if r['方向']==-1],
        デイ=[r for r in s03 if r['session'].endswith('_Day')],ナイト=[r for r in s03 if r['session'].endswith('_Night')],
        時系列別枠6=[r for r in s03 if r['session'] in result['splits']['時系列別枠']],
        追加別枠4=[r for r in s03 if r['session'] in result['splits']['追加別枠']])
    aggregate={name:pathway(rows) for name,rows in groups.items()}
    aggregate['各場']={session:pathway([r for r in s03 if r['session']==session]) for session in test}
    references=[r for r in s03 if r['五pt逆先後に十pt到達']]
    examples=dict(五pt逆先後到達=references[:3],十pt逆先後も未到達=[r for r in s03 if r['labels'][2]==-1 and r['十pt到達原row']<0][:2],
        十pt順先=[r for r in s03 if r['labels'][2]==1][:2])
    output=dict(全合格=True,source=dict(元結果_SHA256=RESULT_SHA,監査射影_SHA256=AUDIT_SHA,
        source_SHA256=result['source_SHA256'],正式選択=result['selection']['正式候補']),
        留保=[
            'S03/T01は44条件・三逆行幅を見た後に注目した事後候補。新たな未知成績ではなく、多重比較/後選択を含む。正式選択三つは変更しない。',
            'S03の選択6場risk5は10/29で同時点固定売り12/29を下回る。T01は11/29で固定売り12/29を下回る。',
            '全候補順先率、解決内順先率、解決率とMFE/MAEは別指標。未決や未到達を0逆行/成功へ補完しない。',
            '十pt到達前MAEは到達rowを除くsigned最小値。未到達又は到達までの先行観測が空ならNoneのまま。finite分母を併記する。',
            '五pt逆先後に十pt到達してもrisk5の先着失敗は失敗のまま。別出口なら救済できる収支や的中率を作らない。',
            '時間はCurrentPriceTimeの代理秒。真の受信/発注時刻ではない。原rowを原seqと推定しない。価格Lastの先着で実約定/手数料後利益ではない。',
            '同じ候補の3riskで共通非重複を用いるが、異なる候補同士の重複を独立標本に数えない。'],
        periods=periods,by_session=by_session,S03_別枠10_records=s03,S03_到達経路集計=aggregate,少数例=examples,
        追加読取=dict(監査時同bytes参照=1,独立監査射影=1,元measurement結果=0,prepared=0,raw=0,event=0,金融=0,API=0))
    write(OUTPUT,output)
    print(json.dumps(dict(全合格=True,出力=str(OUTPUT),SHA256=hashlib.sha256(OUTPUT.read_bytes()).hexdigest(),bytes=OUTPUT.stat().st_size,
        S03_別枠10=aggregate['全別枠10']),ensure_ascii=False))


if __name__=='__main__':main()
