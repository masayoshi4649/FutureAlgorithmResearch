"""計算済み台帳の集約保存型エラーを記録し、金融再生をしない復元へ渡す。"""

import plan119 as plan


def main() -> None:
    """
    機能: 全40場の台帳保存後のJSON型停止を記録し、復元で補えない値を先に定める。
    引数: なし。存在・statと80行の読取記録だけを確認する。
    返り値: None。cache数値・原市場・新金融の読取はしない。
    """
    import json
    assert plan.sources() == plan.read(plan.HERE / '正式固定.json')['source_SHA256']
    out = plan.HERE / 'measurement'
    assert not (out / '戦略自動選択と全四十場の結果.json').exists()
    log = [json.loads(line) for line in (out / '入力読取.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(log) == 80 and len({r['path'] for r in log}) == 80
    files = sorted((out / 'prepared').glob('*/*.npz')) + sorted((out / 'portfolio').glob('*/*.npz'))
    assert len(files) == 160
    plan.write(plan.HERE / '保存型停止と台帳会計復元の事前記録.json', dict(全合格=True,
        停止="40/40と実数量PORTの全cache保存後、最終json.dumpsがwinsのnumpy.int64を拒否。",
        エラー="TypeError: Object of type int64 is not JSON serializable / item 'wins' / item 'runs'",
        source_SHA256=plan.sources(), 完成処理原入力80=80, 初回初期化停止原入力2=2,
        合計原入力読取82=82, 保存cache=160,
        復元='独立算術で同じ保存約定を集計。元市場再読・金融再生・閾値変更は0。',
        方針='約定/BBO/費用/親net/quoteごとMTMと原公開資産trace照合。選択6の元順位と完全一致。',
        未清算='2正常閉場後観測と全親qty完結が確認できない場は未知・昇格不可。',
        未保存='指値取消数canceled・不確定halted・原入力skip内訳等はnull又は未保存で示し、推測しない。',
        規模=[dict(path=p.relative_to(plan.ROOT).as_posix(), bytes=p.stat().st_size, mtime_ns=p.stat().st_mtime_ns) for p in files],
        原市場本文読取=0, cache本文読取=0, 新金融=0, API=0))
    print('全40場・160保存台帳の集約型停止を記録。数値を変えない会計復元へ渡します。')


if __name__ == '__main__':
    main()
