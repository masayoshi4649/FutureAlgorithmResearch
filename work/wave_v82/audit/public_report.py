"""公開HTMLに埋め込まれた全会計と、固定条件の説明を確かめる。"""

import re
from context import *


def read_html(path: Path) -> tuple:
    """機能: 公開HTMLのテキストと埋込みJSONを抽出する。

    引数: path(Path)。返り値: テキスト・JSON(tuple)。
    """
    text=path.read_text(encoding='utf8')
    match=re.search(r'<script id="report-data" type="application/json">(.*?)</script>',text,re.S)
    assert match
    return text,json.loads(match.group(1))


def main() -> None:
    """機能: 公開金額を保存再生結果へ全件照合し、断定範囲を検査する。

    引数: なし。返り値: なし(None)。ブラウザ描画検査は別担当が行う。
    """
    public=ROOT/'アルゴリズム調査/00078_安定赤字手法の売買反転検証'
    mainpath=public/'安定して負ける手法の反転と全セッション損益.html'
    allpath=public/'全188条件の前半反転比較.html'
    text,data=read_html(mainpath);alltext,all_data=read_html(allpath)
    assert data==load(WORK/'report/描画資料.json')
    fixed=load(WORK/'事前固定.json')
    assert data['sessions']==fixed['全30']
    for pair in data['pairs']:
        source=next(p for p in fixed['pairs'] if p['label']==pair['label'])
        assert all(pair[k]==v for k,v in source.items())
    packets=accounts=0
    for delay,group in data['final'].items():
        for name,packet in group.items():
            assert packet==load(WORK/'final'/f'delay{delay}'/'results'/f'{name}.json')
            packets+=1;accounts+=len(packet['rows'])
    for name,period in data['strict'].items():
        packet=load(WORK/'quality3/results'/f'{name}.json')
        assert period==packet['periods']['対象'];packets+=1;accounts+=len(packet['rows'])
    assert len(all_data['rows'])==188
    sources={p['config']['id']:load(ROOT/p['path']) for p in fixed['parents']}
    for row in all_data['rows']:
        name=row['parent_id'];packet=sources[name]
        assert row['config']==packet['config']
        assert row['original']==packet['periods']['対象']
        assert row['reverse']==load(WORK/'first/results'/f'R__{name}.json')['periods']['対象']
    # ----------------------------------------
    # 相場分類は取引では使わず、各商品の同じ場の会計だけを集計している。
    regimes=load(WORK/'diagnosis/相場分類.json');groups=0
    for label,rows in data['regimes'].items():
        pair=next(p for p in fixed['pairs'] if p['label']==label)
        for row in rows:
            sessions={r['session'] for r in regimes['rows'] if r['symbol']==row['symbol'] and r['regime']==row['regime']}
            assert row['sessions']==len(sessions)
            for side in ['original','reverse']:
                chosen=[r for r in data['final']['5'][pair[side]['id']]['rows'] if r['session'] in sessions and r['symbol']==row['symbol']]
                for field in ['profit','loss','net','fees','trades']:
                    assert row[side][field]==sum(r[field] for r in chosen)
                assert row[side]['winning_sessions']==sum(r['net']>0 for r in chosen)
                assert row[side]['losing_sessions']==sum(r['net']<0 for r in chosen)
                groups+=1
    for path,h in data['audit']['入力'].items():assert digest(ROOT/path)==h,path
    required=['反転収支＝−元収支−2×（気配差＋手数料）','Cは前半の反転余地を計算して選んだ',
        'Aは元と反転で約定経路が変わる','中値で約定できた成績ではありません',
        '全30場は旧研究でも既知','5秒は実待ち時間の上限ではありません','取引や候補選択へ使っていません',
        'ミニ／マイクロ実板、真の受信時刻','20個の独立した成功証拠ではありません']
    for phrase in required:assert phrase in text,phrase
    assert 'TOPIX21,480円、日経−192,800円' in data['conclusion']['補足']
    # ----------------------------------------
    # 公開会計は監査自身を同梱するため、その全体指紋との循環参照を避ける。
    published=load(public/'公開会計.json');conditions=load(public/'検証条件と固定記録.json')
    assert published['元と反転']==data['final']
    assert published['相場別']==data['regimes']
    assert published['相手鮮度3秒']==data['strict']
    assert published['期間']==fixed['全30'] and published['前半']==fixed['前16'] and published['後半']==fixed['後14']
    assert conditions['事前固定']==fixed
    assert conditions['元前半順位']==load(WORK/'元前半の選定順位.json')
    assert conditions['相場分類']==regimes
    for path,h in conditions['旧成果保持'].items():assert digest(ROOT/'アルゴリズム調査'/path)==h,path
    readme=(public/'README.md').read_text(encoding='utf8')
    for pair in fixed['pairs']:
        original=data['final']['5'][pair['original']['id']]['periods']['対象']
        reverse=data['final']['5'][pair['reverse']['id']]['periods']['対象']
        for symbol in ['TOPIX','NK225']:
            expected=f'{original[symbol]["net"]:+,.0f} → {reverse[symbol]["net"]:+,.0f}円'
            assert expected in readme,expected
    for phrase in ['前半探索','未知期間の成績とは呼びません','5秒以内の実約定を保証するモデルではありません',
                   '売買条件や代表の選択にも使いません','現在API取得・実注文は0']:
        assert phrase in readme,phrase
    result=dict(合格=True,公開元逆最終条件数=packets,公開全30口座数=accounts,
        前半比較条件数=len(all_data['rows']),事後分類の独立集計数=groups,
        入力指紋照合数=len(data['audit']['入力']),必須限定表現=required,
        公開HTML_SHA256={mainpath.name:digest(mainpath),allpath.name:digest(allpath)},
        README_SHA256=digest(public/'README.md'),公開会計と固定記録一致=True,旧成果保持一致数=len(conditions['旧成果保持']),
        解釈='元A/Bを反転しても両商品各30場すべて赤字。Cは前半探索内では両黒字、後14両赤字。一般の全反転法や価格方向情報の無効までは断定しない。')
    save('公開HTMLの数値と解釈の独立監査.json',result)
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
