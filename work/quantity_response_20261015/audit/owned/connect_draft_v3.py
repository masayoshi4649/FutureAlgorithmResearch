"""実登録前の草案照合と、現formal builderの生成仕様を純メモリで照合する。"""

import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]


def main() -> None:
    """
    機能: actual草案check終端と現freeze生成物の一致をsource-onlyで確認する。
    引数: なし。
    返り値: None。正式freeze・登録・実測を起動しない。
    """
    target = HERE / '三辞書部品の草案照合と現正式builderの独立接続_v3.json'
    assert not target.exists()
    old_proof_path = HERE / '完成五sourceと実読取前guard及び窓終了分母の独立接続_v3.json'
    old_proof = json.loads(old_proof_path.read_bytes())
    assert old_proof['全合格']
    sources = old_proof['source_SHA256']
    assert all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == sha for name, sha in sources.items())
    captured = HERE / '草案metadataの一読保全_v3'
    captured.mkdir(exist_ok=False)
    metadata = {}
    for name in ('辞書形式修正の照合草案.json', '辞書形式修正の草案照合全出力.json'):
        path = BASE / name
        assert path.stat().st_size < 20_000_000
        raw = path.read_bytes()
        (captured / name).write_bytes(raw)
        metadata[name] = dict(SHA256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), 原読取=1)
    draft = json.loads((captured / '辞書形式修正の照合草案.json').read_bytes())
    checked = json.loads((captured / '辞書形式修正の草案照合全出力.json').read_bytes())
    assert checked['終了コード'] == 0 and checked['入力本文'] == 0
    outcome = json.loads(checked['stdout'])
    assert outcome['proposal_complete'] is True
    fixed = json.loads((BASE / '入力と観測の小固定.json').read_bytes())
    generated = {}
    audit = dict(全合格=True, 入力本文=0, source_SHA256=sources,
        evidence=[dict(path=old_proof_path.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(old_proof_path.read_bytes()).hexdigest())])
    def read(path: Path) -> dict:
        """
        機能: 現freezeに既存小目録と合成監査だけを渡す。
        引数: path(Path)は要求metadata。
        返り値: dictは入力目録又はSOURCE_ONLYの合成監査。
        """
        return fixed if path.name == '入力と観測の小固定.json' else audit
    def write(path: Path, value: dict) -> None:
        """
        機能: 現freeze生成物をメモリへ捕捉する。
        引数: path(Path)、value(dict)は予定出力。
        返り値: None。元の正式計画は書き換えない。
        """
        generated[path.name] = copy.deepcopy(value)
    def digest(path: Path) -> str:
        """
        機能: 捕捉済みJSON又は小資料の指紋だけを返す。
        引数: path(Path)は予定metadata。
        返り値: strは指紋又は未保存合成値。
        """
        if path.name in generated:
            raw = (json.dumps(generated[path.name], ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
            return hashlib.sha256(raw).hexdigest()
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else '未保存の合成監査'
    plan_tree = ast.parse((BASE / 'plan.py').read_text(encoding='utf-8'))
    freeze = next(node for node in plan_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'freeze')
    namespace = dict(HERE=BASE, ROOT=ROOT, TRIAL=draft['id'], read=read, write=write, digest=digest,
        sources=lambda: sources, json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[freeze], type_ignores=[])), '正式builderの合成捕捉のみ', 'exec'), namespace)
    namespace['freeze']()
    assert generated['試行計画.json'] == draft
    duplicate_path = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/duplicate_check.py'
    spec = importlib.util.spec_from_file_location('数量草案の独立完全性', duplicate_path)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    pure = checker.analyze(generated['試行計画.json'], [])
    assert pure['proposal_complete'] and pure['提案指紋'] == outcome['提案指紋']
    output = dict(全合格=True, source_SHA256=sources, 現freeze生成物と草案全項目一致=True,
        実草案check終了コード=0, 実草案proposal_complete=True, 現builder提案完全=True,
        提案指紋=outcome['提案指紋'], metadata=metadata,
        先行独立接続=dict(path=old_proof_path.relative_to(ROOT).as_posix(), SHA256=hashlib.sha256(old_proof_path.read_bytes()).hexdigest()),
        実登録='未実施。根がこれからformal freeze後の実登録終端を確認する。',
        入力本文=0, NPZ=0, cache=0, 元金融=0, 原板=0, API=0, 新金融=0,
        監査sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, SHA256=hashlib.sha256(target.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
