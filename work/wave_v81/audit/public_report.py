"""公開HTMLの埋込数値・期間・手法説明・READMEを保存会計へ照合する。"""

import hashlib
import json
import re

from accounts import HERE,WORK,study


PUBLIC=study.ROOT/'アルゴリズム調査/00077_保有時間を決めない二市場方向追従'
MAIN='時間で区切らない方向追従と全セッション損益.html'
ALL='全条件の前半比較.html'


def embedded(path) -> tuple:
    """機能: HTMLの計算済みデータを表示コードから分離して読む。

    引数: path(Path)。返り値: HTML本文・埋込JSON(tuple)。
    """
    body=path.read_text(encoding='utf8')
    match=re.search(r'<script id="report-data" type="application/json">(.*?)</script>',body,re.S)
    assert match
    return body,json.loads(match.group(1))


def main() -> None:
    """機能: 主27経路・品質3条件・前半188条件の公開値と解釈を照合する。

    引数: なし。返り値: なし(None)。ブラウザ描画自体は別担当の検査と区別する。
    """
    body,data=embedded(PUBLIC/MAIN);allbody,all_data=embedded(PUBLIC/ALL)
    assert data==study.load(WORK/'report/描画資料.json')
    selection=study.load(WORK/'前半選定.json');fixed=study.load(WORK/'初回事前固定.json')
    assert data['sessions']==fixed['全30'] and data['front']==fixed['前16'] and data['back']==fixed['後14']
    assert data['initial']==[c['id'] for c in selection['初回']]
    assert data['repaired']==[c['id'] for c in selection['改修']]
    assert data['controls']==[c['id'] for c in selection['単独対照']]
    assert len(data['methods'])==9 and data['count']==all_data['count']==188
    packets=accounts=0
    for delay,methods in data['final'].items():
        assert len(methods)==9
        for identifier,packet in methods.items():
            original=study.load(WORK/'final'/f'delay{delay}'/'results'/f'{identifier}.json')
            assert packet==original
            assert len(packet['rows'])==60
            packets+=1;accounts+=len(packet['rows'])
    for identifier,metrics in data['strict'].items():
        original=study.load(WORK/'quality3/results'/f'{identifier}.json')
        assert metrics==original['periods']['対象']
    for row in all_data['rows']:
        stage='first' if row['stage']=='初回' else 'improved'
        original=study.load(WORK/stage/'results'/f'{row["config"]["id"]}.json')
        assert row['config']==original['config'] and row['metrics']==original['periods']['前16']
    public=study.load(PUBLIC/'公開会計.json')
    assert public['期間']==data['sessions'] and public['前半']==data['front'] and public['後半']==data['back']
    assert public['遅延別']==data['final']
    for identifier,packet in public['相手鮮度3秒'].items():
        assert packet==study.load(WORK/'quality3/results'/f'{identifier}.json')
    conditions=study.load(PUBLIC/'検証条件と固定記録.json')
    for label,name in [('初回','初回事前固定.json'),('改修','改修前固定.json'),('選定','前半選定.json')]:
        assert conditions[label]==study.load(WORK/name)

    # ----------------------------------------
    # 原因説明の数値は、前半だけの比較から再計算する。
    improvements=[]
    for oldid,newid in zip(data['initial'],data['repaired']):
        old=data['final']['5'][oldid]['periods']['前16']
        new=data['final']['5'][newid]['periods']['前16']
        for symbol in ['TOPIX','NK225']:
            a,b=old[symbol],new[symbol]
            if oldid.startswith('D1'):assert b['average_net']<a['average_net']
            if oldid.startswith('D3'):
                reduction=a['spread_drag']+a['fees']-b['spread_drag']-b['fees']
                share=reduction/(b['net']-a['net'])
                assert .70<share<.90
                improvements.append(dict(商品=symbol,前半D3改善の気配差料金割合=share))
    for identifier in data['repaired']:
        both=data['final']['5'][identifier]['periods']['対象']
        solo=data['final']['5'][identifier+'_自己のみ']['periods']['対象']
        for symbol in ['TOPIX','NK225']:
            assert both[symbol]['net']>solo[symbol]['net']
            assert both[symbol]['net']<0
        if identifier.startswith('D1'):
            assert all(data['final']['5'][identifier]['periods']['後14'][s]['net']>0 for s in ['TOPIX','NK225'])
        if identifier.startswith(('D2','D3')):
            assert data['strict'][identifier]['TOPIX']['net']>0 and data['strict'][identifier]['NK225']['net']<0
        if identifier.startswith('D2'):
            for symbol in ['TOPIX','NK225']:
                a=both[symbol]
                assert a['gross']+a['spread_drag']>0
                assert abs((a['gross']+a['spread_drag'])-a['spread_drag']-a['fees']-a['net'])<1e-8

    # ----------------------------------------
    # 大きな省略が誤認へ繋がる文言だけを検査する。
    assert '選んだ方向の出口条件が成立するまで' in body
    assert '待機秒数はゼロ' not in body
    assert '実受信から5秒以内の成績を保証' in body
    assert '既知データ' in body and '後14も過去調査で既知' in (PUBLIC/'README.md').read_text(encoding='utf8')
    assert '固定代表' in allbody and '前16場' in allbody
    for method in data['methods']:
        if 'ticks' in method['entry_model']:
            assert '最初の有効中値' in method['entry']
        if method['config'].get('solo') and method['config']['exit_mode']!=0:
            assert '中立だけでは返済しない' in method['exit']
        if method['config']['exit_mode']==2 and not method['config'].get('solo'):
            assert '両市場が有効' in method['exit'] and '反対方向に揃った' in method['exit']
    readme=(PUBLIC/'README.md').read_text(encoding='utf8')
    for identifier in data['repaired']:
        assert identifier in readme
        for symbol in ['TOPIX','NK225']:
            assert f'{data["final"]["5"][identifier]["periods"]["対象"][symbol]["net"]:,.0f}円' in readme
    result=dict(合格=True,主HTML会計経路数=packets,主HTML口座数=accounts,相手鮮度条件数=len(data['strict']),
        前半一覧全条件数=len(all_data['rows']),公開会計と原会計完全一致=True,
        表示解釈=['D1の初回基準と以後の極値反転を区別。','X2は双方反対を待ち、中立や片方反対を継続。',
            '長期保持・赤字削減・金額利益割合の改善を採用成功とは呼ばない。',
            '中値プラスを全く無意味とは断定せず、取引費用を超える優位不足と説明。',
            '188条件は前半比較、全30は固定代表の確認と区別。',
            '代理時計・ラージ板代用・後半も既知を明記。'],
        原因の独立計数=improvements,
        HTML_SHA256={name:hashlib.sha256((PUBLIC/name).read_bytes()).hexdigest() for name in [MAIN,ALL]},
        注意='公開会計の監査欄はこの記録を加えて再出力されるため、数値欄だけを原結果と比較した。ブラウザの描画・操作は別の実ブラウザ検査。')
    (HERE/'公開HTMLと説明の最終監査.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
