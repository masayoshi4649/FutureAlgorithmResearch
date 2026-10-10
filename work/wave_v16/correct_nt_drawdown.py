"""売買を変更せず、NTの間引き前の区間極値から表示用の期間最大下落を訂正する。"""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

import reference
import selection
import details

OUT = reference.OUT


def compare_csv(before: pd.DataFrame, after: pd.DataFrame, changes: list[dict]) -> int:
    """機能: 指定したNT極値以外の全セルが不変であることを確認する。

    引数: before/after (DataFrame)、changes (list[dict])。返り値: 確認したセル数 (int)。
    """
    assert before.shape == after.shape and list(before.columns) == list(after.columns)
    expected = before.copy()
    for item in changes:
        mask = expected['方式'].eq(item['方式']) & expected['銘柄'].eq('NT') & expected['セッション'].eq(item['セッション'])
        assert mask.sum() == 1
        expected.loc[mask, item['項目']] = item['原本全行値']
    for column in expected.columns:
        a, b = expected[column], after[column]
        if pd.api.types.is_numeric_dtype(a.dtype):
            np.testing.assert_allclose(a.to_numpy(dtype=float), b.to_numpy(dtype=float),
                                       rtol=1e-12, atol=1e-9, equal_nan=True)
        else:
            assert a.fillna('欠損').equals(b.fillna('欠損')), column
    return int(before.size)


def compare_bundles(before: list[dict], after: list[dict]) -> list[dict]:
    """機能: 期間全体DD以外の全週集計項目と、非NTの全項目が不変か確認する。

    引数: before/after (list[dict])。返り値: 訂正した期間DD一覧 (list[dict])。
    """
    assert len(before) == len(after)
    changes = []
    for old, new in zip(before, after):
        assert old['method'] == new['method'] and old['symbol'] == new['symbol']
        if old['symbol'] != 'NT':
            assert old == new, old['method']
            continue
        expected = json.loads(json.dumps(old, ensure_ascii=False))
        for period in old['指標']:
            key = '期間全体の最大下落円'
            a, b = old['指標'][period][key], new['指標'][period][key]
            if a != b:
                changes.append(dict(方式=old['method'], 期間=period, 訂正前円=a, 訂正後円=b))
            expected['指標'][period][key] = b
        assert expected == new, old['method']
    return changes


def main() -> None:
    """機能: 独立会計で見つかった極値だけを訂正し、凍結コードの集計関数を再利用する。

    引数: なし。返り値: None。注文再生も候補再選択も行わない。
    """
    selection.freeze_check()
    audit_path = OUT / 'NT最終保留_独立監査.json'
    audit = json.loads(audit_path.read_text(encoding='utf-8'))
    assert audit['固定4条件のみ'] and audit['週全行会計セル数'] == 40
    changes = audit['表示間引きによる区間極値の差']
    if not changes and audit['成功']:
        print(json.dumps(dict(成功=True, 訂正不要=True, 理由='独立監査で既に原本全行DDと一致しています。'), ensure_ascii=False))
        return
    assert len(changes) == 58
    backup = OUT / 'NT下落訂正前'
    version = 1
    while backup.exists():
        version += 1
        backup = OUT / f'NT下落訂正前_{version:02d}'
    backup.mkdir(exist_ok=False)
    affected = ['代表_セッション集計.csv', '追加_セッション集計.csv', '週合計指標.json',
                '時間順実評価.csv', '時間順合計.json', 'NT最終保留_独立監査.json']
    hashes = {name: reference.sha256(OUT / name) for name in affected}
    for name in affected:
        shutil.copy2(OUT / name, backup / name)
    preserved = ['最終選択.json', '時間順選択.json', '代表_全取引.json', '代表_サイクル.json',
                 '代表_資産曲線.json', '追加_全取引.json', '追加_サイクル.json', '追加_資産曲線.json']
    preserved_hashes = {name: reference.sha256(OUT / name) for name in preserved}
    checked_cells, correction_rows = 0, []
    for name in ['代表_セッション集計.csv', '追加_セッション集計.csv']:
        before = pd.read_csv(OUT / name)
        after = before.copy()
        selected = changes if name.startswith('代表') else [x for x in changes if x['セッション'] in reference.SESSIONS[8:]]
        for item in selected:
            mask = after['方式'].eq(item['方式']) & after['銘柄'].eq('NT') & after['セッション'].eq(item['セッション'])
            assert mask.sum() == 1
            np.testing.assert_allclose(after.loc[mask, item['項目']].iloc[0], item['保存値'], atol=1e-5)
            after.loc[mask, item['項目']] = item['原本全行値']
            correction_rows.append(dict(資料=name, **item))
        after.to_csv(OUT / name, index=False, encoding='utf-8-sig')
        checked_cells += compare_csv(before, pd.read_csv(OUT / name), selected)
    before_bundles = json.loads((backup / '週合計指標.json').read_text(encoding='utf-8'))
    details.aggregate()
    after_bundles = json.loads((OUT / '週合計指標.json').read_text(encoding='utf-8'))
    period_changes = compare_bundles(before_bundles, after_bundles)
    for expected in audit['週下落照合']:
        actual = next(x for x in after_bundles if x['method'] == expected['方式'] and x['symbol'] == 'NT')
        np.testing.assert_allclose(actual['指標']['全10区間']['期間全体の最大下落円'],
                                   expected['原本全行週下落円'], atol=1e-5)
    for name, digest in preserved_hashes.items():
        assert reference.sha256(OUT / name) == digest, name
    for name in ['時間順実評価.csv', '時間順合計.json']:
        assert reference.sha256(OUT / name) == hashes[name], name
    selection.freeze_check()
    record = dict(成功=True, 原因='NT区間極値を表示用の間引き曲線から得ていた。全原本行の両脚時価へ訂正。',
                  売買条件変更=False, 候補選択変更=False, 損益変更=False, 注文再生回数=0,
                  凍結済みコード変更=False, API取得回数=0, 修正前保存先=str(backup),
                  訂正CSV極値項目数=len(correction_rows), CSV全項目確認セル数=checked_cells,
                  CSV訂正=correction_rows, 期間下落訂正=period_changes,
                  訂正前SHA256=hashes, 訂正後SHA256={name: reference.sha256(OUT / name) for name in affected},
                  不変資料SHA256=preserved_hashes,
                  再現順序=['details.py --finalで固定代表の売買結果を出力',
                            'audit_nt_holdout.pyで原本極値と元の表示極値との差を記録',
                            'correct_nt_drawdown.pyでCSVのNT極値と期間DDだけ訂正',
                            'audit_nt_holdout.pyで訂正結果を再照合',
                            '報告生成スクリプトでHTMLと報告書を再生成'],
                  再出力時の注意='凍結済みdetails.py --finalは訂正前のNT極値を再出力する。必ず独立監査・独立補正後に報告生成する。再実行時は訂正前バックアップへ枝番を付け、過去バックアップを上書きしない。既に訂正済みなら無変更で終了する。')
    reference.save(OUT / 'NT期間下落_訂正記録.json', record)
    print(json.dumps(dict(成功=True, CSV極値訂正数=len(correction_rows), 期間DD訂正数=len(period_changes),
                          CSV全項目確認セル数=checked_cells, 凍結コードと売買と損益不変=True), ensure_ascii=False))


if __name__ == '__main__':
    main()
