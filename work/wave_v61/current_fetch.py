"""取得前固定後に一回だけ現在板を取得し、既知前半と追加行を区別する。"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import subprocess


HERE=Path(__file__).resolve().parent
LIVE=HERE/'live'
PREVIOUS=HERE.parent/'wave_v60'


def digest(path: Path) -> str:
    """機能: 読み取り専用の原本や実装のSHAを計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h=hashlib.sha256()
    with path.open('rb') as f:
        while part:=f.read(4*1024*1024):
            h.update(part)
    return h.hexdigest()


def save(name: str, value: dict) -> None:
    """機能: 現在確認用の証跡をUTF-8で保存する。

    引数: name(str)、value(dict)。返り値: なし(None)。
    """
    (LIVE/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def parser_module():
    """機能: 前回監査済みパーサーを読み、今回の出力先だけ分離する。

    引数: なし。返り値: モジュール(ModuleType)。旧ファイルの編集はしない。
    """
    spec=importlib.util.spec_from_file_location('snapshot_v60',PREVIOUS/'live'/'parse_snapshot.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE=LIVE
    module.WORK=PREVIOUS
    return module


def prepare() -> None:
    """機能: ネット接続せず、使用実装・既知前半原本・契約を固定する。

    引数: なし。返り値: なし(None)。開始済み又は固定済みなら上書きしない。
    """
    LIVE.mkdir(exist_ok=True)
    if (LIVE/'取得開始.json').exists() or (LIVE/'取得準備固定.json').exists():
        raise RuntimeError('今回の取得準備は既に固定済みです')
    parser_module().save_baseline()
    paths=[Path(__file__),PREVIOUS/'live'/'fetch_once.exe',PREVIOUS/'live'/'fetch_once.go',PREVIOUS/'live'/'parse_snapshot.py',
           PREVIOUS/'live'/'取得記録.json',PREVIOUS/'live'/'inputs.pkl',PREVIOUS/'live'/'quotes.pkl',
           PREVIOUS/'live'/'TOPIX.jsonl',PREVIOUS/'live'/'NK225.jsonl',HERE/'調査仕様.json',LIVE/'契約照合基準.json']
    save('取得準備固定.json',dict(時刻=datetime.now(timezone.utc).isoformat(),外部取得=0,
        ファイル={str(p):digest(p) for p in paths},説明='前回監査済み一回取得器・パーサーを変更せず再利用。出力先は今回の新規フォルダ。'))


def fetch() -> None:
    """機能: 候補と原実装を照合し、状態1回・板各1回だけ取得して既知前半を確認する。

    引数: なし。返り値: なし(None)。失敗時も再取得せず記録を残す。
    """
    frozen=json.loads((LIVE/'取得準備固定.json').read_text(encoding='utf-8'))
    for name,sha in frozen['ファイル'].items():
        assert digest(Path(name))==sha,(name,'取得前固定と不一致')
    selection=json.loads((LIVE/'候補固定.json').read_text(encoding='utf-8'))
    assert set(selection['selected'])=={'directional','inventory'}
    for branch,sha in selection['sources'].items():
        assert digest(HERE/branch/'集計結果.json')==sha
    if (LIVE/'取得開始.json').exists():
        raise RuntimeError('再取得しません')
    save('取得直前照合.json',dict(候補SHA=digest(LIVE/'候補固定.json'),親GO=True,実注文=0))
    try:
        subprocess.run([str(PREVIOUS/'live'/'fetch_once.exe'),'-authorized','-directory',str(LIVE)],check=True)
        parser_module().main()
        known=pickle.loads((PREVIOUS/'live'/'inputs.pkl').read_bytes())
        fresh=pickle.loads((LIVE/'inputs.pkl').read_bytes())
        rows=[]
        for key,ready in fresh.items():
            item=dict(セッション=key[0],銘柄=key[1],同場の既知前半あり=key in known)
            if key in known:
                old_path=PREVIOUS/'live'/f'{key[1]}.jsonl'
                old_size=old_path.stat().st_size
                with (LIVE/f'{key[1]}.jsonl').open('rb') as f:
                    prefix_hash=hashlib.sha256(f.read(old_size)).hexdigest()
                assert prefix_hash==digest(old_path),'以前の取得原本と現在原本の前半が一致しません'
                prior=known[key]
                assert len(ready['seq'])>=len(prior['seq'])
                assert (ready['seq'][:len(prior['seq'])]==prior['seq']).all()
                assert (ready['time_s'][:len(prior['seq'])]==prior['time_s']).all()
                item.update(既知有効行数=len(prior['seq']),既知最終時計=float(prior['time_s'][-1]),
                    追加有効行数=len(ready['seq'])-len(prior['seq']),原本前半完全一致=True)
            else:
                item.update(既知有効行数=0,追加有効行数=len(ready['seq']))
            rows.append(item)
        save('既知前半と追加区間.json',dict(照合=rows,追加取得=0,
            解釈='同じ場の既知前半は未知成績と呼ばない。追加行における資産変化を別集計する。'))
        manifest=json.loads((LIVE/'現在原本の照合.json').read_text(encoding='utf-8'))
        manifest['同場の既知前半あり']=any(r['同場の既知前半あり'] for r in rows)
        if manifest['同場の既知前半あり']:
            manifest['未見検証と呼べるか']=False
            manifest['注記']='場全体には前回取得済み区間を含む。取得前に未参照だった追加行だけを別集計する。'
        save('現在原本の照合.json',manifest)
    except Exception as error:
        save('現在確認停止.json',dict(理由=str(error),再取得=False,条件を変更しない=True))
        raise


if __name__=='__main__':
    args=argparse.ArgumentParser()
    args.add_argument('--prepare',action='store_true')
    args.add_argument('--authorized-fetch',action='store_true')
    options=args.parse_args()
    assert options.prepare != options.authorized_fetch
    prepare() if options.prepare else fetch()
