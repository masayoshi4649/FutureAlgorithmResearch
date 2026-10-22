"""既監査済み二口座の場末金額だけを独立に加算する。"""

import hashlib
import json
from pathlib import Path
import statistics


def summarize(rows: list[dict]) -> dict:
    """
    機能: 同じ場の二口座合算値から期間指標を独立集計する。
    引数: rows(list[dict])は場末収支と活動状態。
    返り値: dictは金額と黒赤無取引数。共同保有中のDDや資金上限は算出しない。
    """
    nets=[r['net'] for r in rows];black=[v for v in nets if v>0]
    return dict(sessions=len(rows),black=len(black),red=sum(v<0 for v in nets),inactive=sum(not r['active'] for r in rows),
        net=sum(nets),profit=sum(r['profit'] for r in rows),loss=sum(r['loss'] for r in rows),fees=sum(r['fees'] for r in rows),
        median=float(statistics.median(nets)),mean=sum(nets)/len(rows),worst=min(nets),mean_positive=sum(black)/len(black) if black else None,
        top3_removed=sum(nets)-sum(sorted(nets,reverse=True)[:3]))


def main() -> None:
    """
    機能: 所有済みh結果と根の一読保全済み合算JSONから全40場の和を照合する。
    引数: なし。
    返り値: None。小証跡を保存し原市場・cache・金融・新政策は再実行しない。
    """
    here=Path(__file__).resolve().parent
    source_path=here/'owned/完成結果.json';source_bytes=source_path.read_bytes()
    assert hashlib.sha256(source_bytes).hexdigest()=='d0f1f86cb955a2da7016f0a33f6ff097eb64edb14068e8d0a0b4278aebca963b'
    saved_path=here/'owned/少額E01二口座の場末収支合算.json';saved_bytes=saved_path.read_bytes()
    assert hashlib.sha256(saved_bytes).hexdigest()=='db9e9376d3b055d0ebe3393a7ce514928d18b1ad6ee8e24323ca30d3041735d0'
    original=json.loads(source_bytes);saved=json.loads(saved_bytes)
    assert saved['全合格'] is True and saved['source_SHA256']==hashlib.sha256(source_bytes).hexdigest()
    assert saved['new_financial_replay']==saved['raw_reads']==0 and saved['new_independent_evidence'] is False
    lookup={(r['session'],r['symbol']):r for r in original['rows']};rows=[]
    for scene in original['sessions']:
        own=[lookup[scene,symbol] for symbol in ('TOPIX','NK225')]
        row={key:sum(r[key] for r in own) for key in ('profit','loss','net','fees','campaigns')}
        row.update(session=scene,active=any(r['campaigns']>0 for r in own),origin='旧33保存会計の合算' if scene in original['old_sessions'] else '新7会計の合算')
        assert abs(row['profit']-row['loss']-row['net'])<1e-7
        rows.append(row)
        for child in own:
            if scene in original['old_sessions']:
                assert child['unclosed'] is None and child['verified_flat'] is True and child['verified_flat_basis']
            else:assert child['unclosed']==0 and child['verified_flat'] is True
    assert rows==saved['rows'] and len(rows)==40
    independent={name:summarize([r for r in rows if r['session'] in scenes]) for name,scenes in (('全40',original['sessions']),('旧33',original['old_sessions']),('追加7',original['new_sessions']))}
    assert independent==saved['metrics']
    h_proof=here/'h旧六十六引用と新十四口座の全注文親UID及び全行時価の独立監査.json'
    assert json.loads(h_proof.read_bytes())['全合格'] is True
    proof={'全合格':True,'確認範囲':'既監査済み独立二口座の場末収支のみの算術合算。新政策の運転又は新有効性標本ではない。',
        '合算結果SHA256':hashlib.sha256(saved_bytes).hexdigest(),'元h結果SHA256':hashlib.sha256(source_bytes).hexdigest(),
        '元h会計監査':{'path':h_proof.name,'SHA256':hashlib.sha256(h_proof.read_bytes()).hexdigest()},'全四十場の利益損失収支費用活動一致':True,
        '期間別指標':independent,'旧終端数量null保持':66,'旧flat保証は元検証へ委譲':True,'新14終端保証は元直接検査へ委譲':True,
        '未検証':['保有中の共同MTMとDD','共通資金上限','共同の場内停止','実小型板での約定量と受信順'],
        '今回目的の合算原JSON一読保全':1,'原市場読取':0,'新cache読取':0,'旧33再金融':0,'金融再実行':0,'新政策試行':0,'独立有効性標本追加':0}
    target=here/'二独立口座の場末四十和と期間指標だけの独立監査.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
