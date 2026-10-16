"""三源配分の保存結果を、短い説明と全30場の暗色レポートへ接続する。"""
from pathlib import Path
import hashlib
import json

HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]
OUT=ROOT/'アルゴリズム調査/00084_異なる戦略への配分と同時運転'
NAME='異なる3手法の配分と全セッション損益.html'


def read(path):
    """
    機能: 保存済み日本語JSONを読む。
    引数: path(Path)。
    返り値: dict。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    """
    機能: 完了済み22条件だけを読み、公開HTMLと入力指紋を保存する。
    引数: なし。
    返り値: None。源再生・条件選定・損益の変更は行わない。
    """
    fixed=read(WORK/'事前固定.json')
    analysis=read(WORK/'analysis/比較結果.json')
    results={c['id']:read(WORK/'results'/f"{c['id']}.json") for c in fixed['catalog']}
    assert len(results)==22
    if 'results' in analysis:assert analysis['results']==results
    selected=analysis.get('selected')
    assert selected is None or selected in results
    primary=analysis.get('primary','A0622')
    assert primary=='A0622'
    pure=[]
    for source in ('GU','M3','C03'):
        pure.append(next(c['id'] for c in fixed['catalog'] if c['budgets'][source]==10))
    highlights=list(dict.fromkeys([primary]+([selected] if selected else [])+['A0820']+pure+['GU_HALF']))
    data=dict(results=results,catalog=fixed['catalog'],sessions=fixed['全30'],primary=primary,selected=selected,
        highlights=highlights,periods={p:fixed[p] for p in ('前16','後14','全30')},
        diversity=analysis.get('diversity',{}),conclusion=analysis.get('conclusion',[]),source_contributions=analysis.get('source_contributions',{}),risk_attribution=analysis.get('risk_attribution',{}),
        diagnosis=analysis.get('diagnosis',{}),selection_proof=analysis.get('selection_proof'),specification=fixed['specification'])
    for result in results.values():
        assert len(result['rows'])==60
        for row in result['rows']:
            assert abs(row['profit']-row['loss']-row['net'])<1e-6
            assert abs(row['gross']-row['fees']-row['net'])<1e-6
    payload=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    page=(HERE/'template.html').read_text(encoding='utf-8')
    page=page.replace('__STYLE__',(HERE/'style.css').read_text(encoding='utf-8'))
    page=page.replace('__DATA__',payload).replace('__SCRIPT__',(HERE/'main.js').read_text(encoding='utf-8'))
    OUT.mkdir(parents=True,exist_ok=True)
    target=OUT/NAME;target.write_text(page,encoding='utf-8')
    paths=[WORK/'事前固定.json',WORK/'analysis/比較結果.json',*sorted((WORK/'results').glob('*.json')),
        HERE/'build.py',HERE/'template.html',HERE/'style.css',HERE/'main.js']
    proof=dict(全合格=True,条件数=len(results),各条件の口座数=60,主仮説=primary,前16選定=selected,
        HTML=str(target.relative_to(ROOT)),HTML_SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),
        使用資料SHA256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    (HERE/'生成結果.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
