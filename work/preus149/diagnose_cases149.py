"""時計変更と全初期化で増減した保存取引を具体時刻で比較する。"""

import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

HERE=Path(__file__).resolve().parent
JST=timezone(timedelta(hours=9))


def clock(seconds):
    """時刻を日付付き日本時間にする。

    引数: seconds(float)。返り値: strは日付時刻。
    """
    return datetime.fromtimestamp(seconds,JST).strftime('%m/%d %H:%M:%S')


def events_table(case,start,end):
    """比較対象時間にある約定の表を作る。

    引数: case(dict)、start/end(float)は保存事象と範囲。
    返り値: list[str]はMarkdown表。
    """
    lines=['|判断|約定|担当|売買|枚数|価格|返済損益円|理由|','|---|---|---|---|---:|---:|---:|---|']
    for e in case['events'] or []:
        s,f=e['signal'],e['fill']
        if not start<=f['Time']<end:continue
        action=('新規' if s['action']=='new' else '返済')+('買い' if s['side']>0 else '売り')
        lines.append(f"|{clock(s['time'])}|{clock(f['Time'])}|{s['owner']}|{action}|{f['Quantity']}|{f['Price']:,.0f}|{e['gross']:+,.0f}|{s['reason']}|")
    return lines


def main():
    """最悪3夜と初期化による最大差を、元の注文列を変えずに抽出する。

    引数: なし。返り値: None。新たな金融再生は行わない。
    """
    report=json.loads((HERE/'first_report149.json').read_text(encoding='utf-8'))
    methods={m['id']:m for m in report['methods']}
    c05=methods['C05']['rows'];r02={r['session']:r for r in methods['R02']['rows']}
    scenes=sorted(c05,key=lambda r:r['pre']['net'])[:3]
    losses=sorted(c05,key=lambda r:r02[r['session']]['post']['net']-r['post']['net'])[:3]
    lines=['# 時刻制限を外した時と全初期化した時の具体的な売買','',
           '日経mini上限10枚、手数料0円、判断後の次正常ラージBBO。元の約定を変更せず抽出した。表の返済損益は部分返済ごと、全体比較の利益損失は親取引合計である。','']
    for row in scenes:
        scene=row['session']; data=json.loads((HERE/'results_go'/f'{scene}.json').read_text(encoding='utf-8'))
        case=next(c for c in data['cases'] if c['config']['id']=='C05')
        lines += [f"## 早期化 C05 {scene} 前半 {row['pre']['net']:+,.0f}円",'']
        lines += events_table(case,data['scene']['start'],data['scene']['us_open'])+['']
    for row in losses:
        scene=row['session'];data=json.loads((HERE/'results_go'/f'{scene}.json').read_text(encoding='utf-8'))
        diff=r02[scene]['post']['net']-row['post']['net']
        lines += [f'## 全初期化の後半差 {scene} {diff:+,.0f}円','',
                  'この差には指標破棄・売買状態の再初期化・後半入口時計変更が含まれる。第二巡で要因を分離する。','']
        for identifier in ('C05','R02'):
            case=next(c for c in data['cases'] if c['config']['id']==identifier)
            lines += [f'### {identifier}','']+events_table(case,data['scene']['us_open'],data['scene']['end']+1)+['']
    (HERE/'時刻変更と全初期化の具体例.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print([(r['session'],r['pre']['net']) for r in scenes])
    print([(r['session'],r02[r['session']]['post']['net']-r['post']['net']) for r in losses])


if __name__=='__main__':main()
