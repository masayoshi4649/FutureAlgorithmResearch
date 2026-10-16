"""根が完了した同一金融の三小資料を一目的各一読し、parse前の同bytesを保全する。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENGINE = ROOT / 'work/e01_fak_evidence_20261014/engine'
EXPECTED = 'fb23ebf7d0f81c8607cc58eb8c97c628a5a56c406d8db934c441718321f995c6'


def main() -> None:
    """
    機能: 完了通知で指定された結果/fixed/planだけを同bytes保存し独立算術へ渡す。
    引数: なし。root terminal0後の監査目的だけで実行する。
    返り値: None。三JSONの保全証跡とschema見取りだけを出力する。
    """
    folder = HERE / 'captured_small_finance'
    assert len(EXPECTED)==64 and all(c in '0123456789abcdef' for c in EXPECTED), '根terminal0とSHA通知までは読取禁止。'
    assert not folder.exists()
    folder.mkdir()
    items = {}
    parsed = {}
    for path, name in ((ENGINE/'finance/結果.json','result.json'), (ENGINE/'金融事前固定.json','fixed.json'), (ENGINE/'試行計画.json','plan.json')):
        raw = path.read_bytes()
        assert len(raw) <= (40_000_000 if name == 'result.json' else 20_000_000)
        sha = hashlib.sha256(raw).hexdigest()
        if name == 'result.json':
            assert sha == EXPECTED
        copy = folder / name
        copy.write_bytes(raw)
        items[path.relative_to(ROOT).as_posix()] = dict(コピー=copy.relative_to(ROOT).as_posix(),SHA256=sha,bytes=len(raw),原読取回数=1)
        parsed[name] = json.loads(raw.decode('utf-8-sig'))
    result = parsed['result.json']
    source = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in ENGINE.glob('*.py')}
    assert source == result['source_SHA256'] == parsed['fixed.json']['source_SHA256'] == parsed['plan.json']['spec']['implementation']
    case = next(iter(result['reused_economic_cases'].values()))['saved_public_case']
    firstrow = case['rows'][0]
    firstsymbol = next(iter(case['metrics']))
    schema = dict(金融key=list(result),保存PRICEkey=list(case),保存PRICE行key=list(firstrow),保存PRICE全場key=list(case['metrics'][firstsymbol]['full']),
                  alias例=result['internal_aliases'][0],保存PRICE方向key=list(case['directions'][firstsymbol]['long']))
    proof = dict(全合格=True,目的='00111独立金融会計監査の同一金融保全とschema確認。原再読無しでこのコピーだけを検算する。',
                 資料=items,最終source_SHA256=source,schema=schema,原金融結果読取=1,原fixed読取=1,原plan読取=1,
                 金融再実行=0,原input=0,旧110金融本文=0,台帳本文=0,API=0)
    target = folder/'同一金融三小資料の保全.json'
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,SHA256=hashlib.sha256(target.read_bytes()).hexdigest(),schema=schema),ensure_ascii=False))


if __name__ == '__main__':
    main()
