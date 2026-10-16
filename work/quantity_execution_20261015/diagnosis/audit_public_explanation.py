"""小診断だけを使い、公開説明の金額・具体時点・未検証範囲を確認する。"""

from pathlib import Path
import json
import re
from urllib.parse import unquote

import reader


def main() -> None:
    """
    機能: 完成MDの二例を実新規・各返済BBOから再確認し、集計とリンクへ結ぶ。
    引数: なし。
    返り値: None。元金融・元台帳・原入力・eventを追加で読まない。
    """
    md = reader.ROOT/'アルゴリズム調査/00115_板の短期方向性を実約定と損益へ接続/損失の具体例と次の改善.md'
    source = md.read_text(encoding='utf-8')
    detail = json.loads(reader.OUTPUT.read_text(encoding='utf-8'))
    projection_path = reader.HERE/'主候補全親の公開後変化と損失単位の追加射影.json'
    projection = json.loads(projection_path.read_text(encoding='utf-8'))
    assert detail['結果SHA256'] == projection['金融結果SHA256'] == 'f2a61c69044487164dd119aa97faf37be71f1a48683e784bea2531e237861a80'
    checks = []
    for symbol, label in (('TOPIX','TOPIXmini10枚'),('NK225','NK225micro20枚')):
        data = projection['商品'][symbol]
        d = data['金額分解']
        expected = f"| {label} | +{d['中値差粗損益']:,.0f}円 | {d['気配差負担']:,.0f}円 | {d['手数料']:,.0f}円 | **−{abs(d['収支']):,.0f}円** |"
        assert expected in source
        assert reader.number(d['中値差粗損益'])-reader.number(d['気配差負担'])-reader.number(d['手数料']) == reader.number(d['収支'])
        assert all(p['public_spread_ticks'] == 1 for p in data['親小観測'])
        assert data['件数']['新規時すでに粗損切線以下'] == data['件数']['新規時すでに粗損切線以下_負け親']
        assert data['件数']['保有中粗ピーク2T未達_負け親'] == data['件数']['負け親']
        assert data['件数']['公開から新規で両気配が同方向1T以上'] == 36
        checks.append(dict(symbol=symbol, 全親=data['全親'], 金額分解=d, 件数=data['件数']))
    concrete = []
    for symbol, session, parent, name in (('TOPIX','2026-09-24_Night',0,'TOPIX・9月24日'),('NK225','2026-10-01_Night',0,'日経・10月1日')):
        scene = next(s for s in detail['対象'] if s['symbol']==symbol and s['session']==session)
        obs = next(p for p in scene['負け親'] if p['parent']['parent']==parent)
        p, snap = obs['parent'], obs['snapshots']
        decomposition = obs['親全体の中値と気配差分解']
        assert decomposition['中値差粗損益'] == 0
        snippet = next(line for line in source.splitlines() if line.startswith('- **'+name))
        assert f"新規後の中値移動0円−気配差{decomposition['気配差負担']:,.0f}円−手数料{decomposition['手数料']:,.0f}円＝**−{abs(p['net_yen']):,.0f}円**" in snippet
        for label in ('公開','新規','最終返済'):
            row = snap[label]
            assert 'seq'+str(row['raw_seq']) in snippet
        for label in ('公開','新規'):
            row = snap[label]
            assert f"{row['bid']:g}／{row['ask']:g}" in snippet
            assert f"数量{row['bid_qty']:g}／{row['ask_qty']:g}" in snippet
        stop = [c for c in scene['実注文経過']['control_events'] if int(c['parent']) == parent]
        assert len(stop)==1 and int(stop[0]['reason'])==141
        assert int(stop[0]['row'])==p['entry_row'] and stop[0]['gross_ticks']==-2
        concrete.append(dict(symbol=symbol, session=session, parent=parent,
            公開=snap['公開'], 新規=snap['新規'], 返済=snap['最終返済'], 親金額分解=decomposition,
            損切り判断=stop[0]))
    top = projection['商品']['TOPIX']['件数']
    nk = projection['商品']['NK225']['件数']
    assert f"{top['新規時拡幅']}／234件・日経{nk['新規時拡幅']}／188件" in source
    assert f"{top['負け親_中値も逆行']}件／{nk['負け親_中値も逆行']}件" in source
    assert f"{top['負け親_中値非負だが気配差後負']}件／{nk['負け親_中値非負だが気配差後負']}件" in source
    assert f"35／234件・25／188件" in source
    assert f"{top['保有中粗ピーク0T未満']}件／{nk['保有中粗ピーク0T未満']}件" in source
    for symbol in ('TOPIX','NK225'):
        comparison = detail['十二条件の実運転対照'][symbol]
        assert len(comparison)==12 and all(value['収支']<0 for value in comparison.values())
    required = ('中値移動による粗損益は両商品ともプラス', '約定行を見た後で今回の成行を取消せばカンニング',
                '逆選択', '赤字上位3場ずつ', '真の受信順', '未測定', '損切りを広げても黒字や安全性の保証はなく')
    assert all(text in source for text in required)
    links = re.findall(r'\]\(([^)]+)\)',source)
    assert all((md.parent/unquote(link)).exists() for link in links)
    fixed = json.loads(reader.PLAN.read_text(encoding='utf-8'))
    assert reader.sources()==fixed['source_SHA256']
    proof = dict(全合格=True, 公開MD_SHA256=reader.digest(md.read_bytes()),
        集計根拠=checks, 二例の実新規起点再検算=concrete, リンク数=len(links),
        source_SHA256=reader.sources(), 金融結果SHA256=projection['金融結果SHA256'],
        元金融追加読=0, 元台帳追加読=0, 原NPZ=0, eventNPZ=0, API=0,
        制限='新規時拡幅を事後取消する収益は算出しない。先着1Tと実親勝敗の分母を区別。未検証の注文改善だけ提示。')
    target=reader.HERE/'公開損失説明の算術と原seq及び未測範囲の確認.json'
    reader.write(target, proof)
    print(json.dumps(dict(全合格=True, MD_SHA256=proof['公開MD_SHA256'], 証跡SHA256=reader.digest(target.read_bytes())), ensure_ascii=False))


if __name__=='__main__':
    main()
