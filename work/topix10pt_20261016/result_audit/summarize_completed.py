"""独立再集計済みの小射影だけから、選択三条件と四群の所見を残す。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent


def small(cell: dict) -> dict:
    """
    機能: 先着・未決・固定対照の分子分母を小さく写す。
    引数: cell(dict) は一期間の一逆行幅。
    返り値: dict は当該条件のcountsと同時点固定買売。率は全候補分母。
    """
    own=cell['全体'];buy=cell['常時買い'];sell=cell['常時売り'];n=own['n']
    return dict(逆行幅=cell['逆行幅'],順先=own['順先'],逆先=own['逆先'],窓末未決=own['窓末未決'],
        EOF未決=own['EOF未決'],基準不可=own['基準不可'],n=n,全候補順先率=own['全候補順先率'],解決内順先率=own['解決内順先率'],
        解決率=own['解決率'],同時点固定買い順先=buy['順先'],同時点固定売り順先=sell['順先'],
        固定最良との差件数=own['順先']-max(buy['順先'],sell['順先']),
        固定最良との差率=(own['順先']-max(buy['順先'],sell['順先']))/n if n else None,
        買い={k:cell['買い'][k] for k in ('順先','逆先','窓末未決','EOF未決','n')},
        売り={k:cell['売り'][k] for k in ('順先','逆先','窓末未決','EOF未決','n')})


def rate(cell: dict) -> str:
    """
    機能: 全候補の順先件数を分母付きで表示する。
    引数: cell(dict) はsmallの返り値。
    返り値: str は順先/nと百分率。
    """
    return f"{cell['順先']}/{cell['n']}（{100*cell['全候補順先率']:.1f}%）" if cell['n'] else '分母なし'


def main() -> None:
    """
    機能: 元結果やpreparedを再読せず、監査射影一読で小結を作る。
    引数: なし。
    返り値: None。正式選択を変更せず、新しい金融実績を作らない。
    """
    source=HERE/'四十四条件全場と選択及び固定モデルの独立再集計.json';body=source.read_bytes();d=json.loads(body)
    assert d['全合格'] and d['指定結果_SHA256']=='b4eefa5f31e36c645fe9c54d2ed715ec074b556524cb024364bd10386121dcf2'
    lookup={v['id']:v for v in d['全44集計']};ids=d['selection']['正式候補']
    periods=('選択','時系列別枠','追加別枠','別枠10','別枠デイ','別枠ナイト')
    chosen={identifier:{p:[small(r) for r in lookup[identifier]['非重複'][p]['risks']] for p in periods} for identifier in ids}
    families=('整列継続','収束拡散','反発','二市場');by_family={family:[] for family in families}
    for row in d['全44集計']:
        if row['family'] in families:
            by_family[row['family']].append(dict(id=row['id'],選択6場=[small(r) for r in row['非重複']['選択']['risks']],
                別枠10場=[small(r) for r in row['非重複']['別枠10']['risks']]))
    notes=[
        '保存値の独立集計は508172項目で一致。完成結果1読と保存prepared37各1読。原raw/event/原金融/API0。first-hit価格列の再測定やモデル再fitはしていない。',
        '選択6場だけで選んだ正式3条件はL04_MA活動板二市場_P65・P02・Q04のまま。別枠10場を見た選び直しはしない。',
        '逆行10ptでもL04は13/26対固定売り14/26、P02は13/30対固定売り13/30、Q04は19/51対固定買い・売り22/51。逆行幅拡大で順先件数が増えても選択方向の優位維持とは言えない。',
        '逆行5ptのP02は11/30で同時点固定最良10/30を1件上回るが、時系列別枠6では3/16・追加4では8/14（その同時点固定売り9/14）。安定した予測優位の確認にはならない。',
        'L04の逆行5ptは日中0/11・夜間7/15。夜間は同時点固定売り7/15と同じ。P02は日中6/17・夜間5/13、Q04は日中5/24・夜間8/27。',
        '整列継続は逆行5ptで4条件すべて固定最良以下。逆行10ptではT01だけ26/47対固定24/47だが、選択期5ptでは11/29対固定12/29だった。',
        '収束拡散のS03は別枠10で5pt19/40対固定17/40、10pt24/40対固定19/40。S02は5pt9/16対固定7/16だが選択期の予兆10件で最低12件資格を満たさなかった。これらは事後比較であり今回の正式選択へ追加しない。',
        '反発4条件の逆行5ptはR03の14/36対固定13/36だけ1件超過、他は固定以下。逆行10ptではR03・R04が固定と同件で、他2条件は固定以下。',
        '二市場M01〜M04の逆行5ptは全条件が固定最良以下、逆行10ptも全条件が固定最良以下。二市場一致自体を独立予測力とする結果ではない。',
        '各条件の予兆は重なり得るため、familyの件数を合算して独立標本やfamily成功率を作らない。表は各IDの分母を保持する。',
        '未決を含む全候補率を主に示す。MFEや十pt到達前MAE、後に一度到達した件数を先着勝ちへ置換しない。Last先着であり、気配差・手数料・注文遅延を負担した収支ではない。']
    result=dict(全合格=True,監査射影_SHA256=hashlib.sha256(body).hexdigest(),元結果_SHA256=d['指定結果_SHA256'],
        正式選択=ids,選択三条件=chosen,四family全16条件=by_family,所見=notes,
        追加読取=dict(独立監査射影=1,完成結果=0,prepared=0,raw=0,event=0,金融=0,API=0))
    target=HERE/'選択三条件の全値幅と四群の事後比較.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    lines=['# 独立再集計と別枠十場の所見','',notes[0],'',notes[1],'',
        '表の「順/逆/未決」は別枠10場・共通非重複の件数。固定方向も全く同じ公開時点の対照である。','',
        '|条件|逆行幅|順/逆/未決|全候補順先率|固定買い/売りの順先|','|---|---:|---:|---:|---:|']
    for identifier in ids:
        for cell in chosen[identifier]['別枠10']:
            lines.append(f"|{identifier}|{cell['逆行幅']:g}pt|{cell['順先']}/{cell['逆先']}/{cell['窓末未決']+cell['EOF未決']}|{100*cell['全候補順先率']:.1f}%|{cell['同時点固定買い順先']}/{cell['同時点固定売り順先']}|")
    lines+=['']+notes[2:5]+['','事後の群別比較を以下に全数示す。選択を変える根拠として使わない。','',
        '|family・ID|5ptの順先/n|5pt固定最良との差件数|10ptの順先/n|10pt固定最良との差件数|',
        '|---|---:|---:|---:|---:|']
    for family,rows in by_family.items():
        for row in rows:
            five,ten=row['別枠10場'][1:]
            lines.append(f"|{family} {row['id']}|{rate(five)}|{five['固定最良との差件数']:+d}|{rate(ten)}|{ten['固定最良との差件数']:+d}|")
    lines+=['']+notes[5:]+['','元結果を再読せず、独立再集計の射影だけから作成した。']
    md=HERE/'選択三条件と値幅別及び各familyの短い所見.md';assert not md.exists();md.write_text('\n\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(JSON=str(target),JSON_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),MD=str(md),MD_SHA256=hashlib.sha256(md.read_bytes()).hexdigest(),JSON_bytes=target.stat().st_size),ensure_ascii=False))


if __name__=='__main__':main()
