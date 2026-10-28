"""実台帳を使わず、小さな仮正本で登録・保存・復元を検査する。"""

from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
sys.path.insert(0,str(HERE))
import control166 as control
import registry166 as registry


def put(path: Path,value: object) -> None:
    """一時仮台帳のみを書き込む。

    引数: path(Path)、value(JSON変換可能)。返り値: None。
    """
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


class 仮台帳検査(unittest.TestCase):
    """本物の共通validate/check/bundleを仮DATAへ接続する。"""

    def setUp(self):
        """2旧行と1対象行だけの隔離台帳を用意する。

        引数: self(仮台帳検査)。返り値: None。
        """
        self.temp=tempfile.TemporaryDirectory(prefix='registry166_人工_')
        self.root=Path(self.temp.name).resolve();self.study=self.root/'work/research166';self.study.mkdir(parents=True)
        self.data=self.root/'仮台帳/data';self.data.mkdir(parents=True)
        manager_path=PROJECT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'
        spec=importlib.util.spec_from_file_location('共通管理器_仮正本166',manager_path)
        self.m=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.m)
        self.m.ROOT=self.root;self.m.DATA=self.data
        self.patchers=[]
        for module,name,value in [(registry,'ROOT',self.root),(registry,'HERE',self.study),
                                  (control,'ROOT',self.root),(control,'HERE',self.study),
                                  (registry,'__file__',str(self.study/'registry166.py')),
                                  (registry,'manager',lambda:self.m)]:
            p=patch.object(module,name,value);p.start();self.patchers.append(p)
        (self.study/'registry166.py').write_text('# 人工源',encoding='utf-8')
        self.manifest=self.root/'入力.json';put(self.manifest,{'sessions':['人工Night']})
        self.implementation=self.root/'源.py';self.implementation.write_text('# 人工コード',encoding='utf-8')
        self.index=self.root/'索引.md';self.index.write_text('当時の索引',encoding='utf-8')
        self.old_index_sha=control.sha(self.index)
        self.spec={'entry':{'kind':'旧入口'},'management':{'kind':'旧継続'},'exit':{'kind':'旧出口'},
                   'allocation':{'quantity':10},'costs':{'fee':0},'execution':{'fill':'次正常板'},
                   'data':{'sessions':['人工Night'],'input_manifests':[control.record(self.manifest)]},
                   'implementation':{'源.py':control.sha(self.implementation)}}
        self.original=[{'id':'旧A','name':'旧A','status':'検証済み','spec':copy.deepcopy(self.spec),
                        'evidence':[{'path':'索引.md','sha256':self.old_index_sha}]},
                       {'id':'旧B','name':'旧B','status':'未実行','spec':dict(copy.deepcopy(self.spec),entry={'kind':'別入口'})}]
        put(self.data/'rules.json',{'rules':[]});put(self.data/'knowledge.json',{'findings':[]})
        put(self.data/'studies.json',{'studies':[]})
        put(self.data/'trials.json',{'trials':self.original,'repetition_audit':[],'updated_at':'元時計'})
        (self.data/'view-data.js').write_text(self.m.bundle(self.m.load(deep=False)),encoding='utf-8',newline='\n')
        # 過去の索引は現在内容へ変わるが、旧試行の当時SHAは更新しない。
        self.index.write_text('追加研究が増えた現在の索引',encoding='utf-8')
        self.plan={'id':registry.IDENT,'name':'人工の条件比較','purpose':'条件比較','question':'人工比較',
                   'change':'入口だけを変更','repeat_reason':'保存手法との差分を検査','compares_to':['旧A'],
                   'spec':dict(copy.deepcopy(self.spec),entry={'kind':'新入口166'})}
        self.before=(self.data/'trials.json').read_bytes();self.before_view=(self.data/'view-data.js').read_bytes()

    def tearDown(self):
        """一時正本と定数差替えだけを後始末する。

        引数: self(仮台帳検査)。返り値: None。
        """
        for p in reversed(self.patchers):p.stop()
        self.temp.cleanup()

    def prepared(self) -> tuple:
        """追加予定の対象行と、変更前の対象外指紋を返す。

        引数: self(仮台帳検査)。返り値: tuple(value,sha,row,others)。
        """
        value=self.m.load(deep=False);old_sha=value['source_sha256']['trials.json']
        others=registry.old_rows(value['trials']['trials'],set())
        row=dict(copy.deepcopy(self.plan),status='未実行')
        value['trials']['trials'].append(row)
        return value,old_sha,row,others

    def assert_unchanged(self):
        """正本とビューが初期値のままか確認する。

        引数: self(仮台帳検査)。返り値: None。
        """
        self.assertEqual((self.data/'trials.json').read_bytes(),self.before)
        self.assertEqual((self.data/'view-data.js').read_bytes(),self.before_view)

    def assert_clean(self):
        """この呼出しが作った一時ファイルとロックが残っていないか確認する。

        引数: self(仮台帳検査)。返り値: None。
        """
        for name in ['trials.json.tmp','view-data.js.tmp','trials.json.rollback166.tmp','trials.json.write166.lock']:
            self.assertFalse((self.data/name).exists(),name)

    def test_全行構造と対象deepを分け旧索引SHA保持(self):
        """過去の更新可能索引だけで対象の厳密検査が止まらない。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared()
        with self.assertRaises(AssertionError):self.m.validate(v,deep=True)
        with patch.object(self.m,'validate',wraps=self.m.validate) as spy:
            result=registry.write_registry(self.m,v,s,[row],others)
        self.assertEqual([c.kwargs.get('deep') for c in spy.call_args_list],[False,True])
        self.assertEqual([r['id'] for r in spy.call_args_list[1].args[0]['trials']['trials']],[registry.IDENT])
        saved=self.m.load(deep=False)
        self.assertEqual(saved['trials']['trials'][:2],self.original)
        self.assertEqual(saved['trials']['trials'][0]['evidence'][0]['sha256'],self.old_index_sha)
        self.assertEqual((self.data/'view-data.js').read_text(encoding='utf-8'),self.m.bundle(saved))
        self.assertEqual(result['other_row_count'],2);self.assert_clean()

    def test_対象外行の変更を拒否(self):
        """呼出し前に採った他IDの内容指紋を保持する。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();v['trials']['trials'][0]['status']='不正変更'
        with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[row],others)
        self.assert_unchanged();self.assert_clean()

    def test_対象deep行と保存行のすり替え拒否(self):
        """良い検査用行を渡し、別の行を保存する抜け道を拒否する。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();valid=copy.deepcopy(row);row['spec']['exit']={'kind':'別の出口'}
        with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[valid],others)
        self.assert_unchanged();self.assert_clean()

    def test_今回対象の根拠SHA不一致拒否(self):
        """既存索引の例外を新試行の実装不一致へ広げない。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();row['spec']['implementation']['源.py']='0'*64
        with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[row],others)
        self.assert_unchanged();self.assert_clean()

    def test_開始時SHA違いを拒否(self):
        """別更新を上書きせず残す。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();table=control.read(self.data/'trials.json');table['別更新']=True;put(self.data/'trials.json',table)
        changed=(self.data/'trials.json').read_bytes()
        with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[row],others)
        self.assertEqual((self.data/'trials.json').read_bytes(),changed);self.assert_clean()

    def test_ビュー生成中の並行変更を拒否(self):
        """検査後に別更新されても正本を差し替えない。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();original=self.m.bundle
        def concurrent(value):
            """人工的な外部更新を発生させる。

            引数: value(dict)。返り値: ビュー(str)。
            """
            table=control.read(self.data/'trials.json');table['並行更新']='保存';put(self.data/'trials.json',table)
            return original(value)
        with patch.object(self.m,'bundle',side_effect=concurrent):
            with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[row],others)
        self.assertEqual(control.read(self.data/'trials.json')['並行更新'],'保存');self.assert_clean()

    def test_ビュー生成失敗では書き込まない(self):
        """生成途中の例外で正本も旧ビューも変更しない。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared()
        with patch.object(self.m,'bundle',side_effect=RuntimeError('人工生成失敗')):
            with self.assertRaises(RuntimeError):registry.write_registry(self.m,v,s,[row],others)
        self.assert_unchanged();self.assert_clean()

    def test_一時ファイル準備中の変更を置換前に拒否(self):
        """最後のSHA確認が一時保存後の競合も検出する。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();original=Path.open
        def concurrent(path,*args,**kwargs):
            """ビュー一時保存直前に別更新を挿入する。

            引数: path(Path)、args(tuple)、kwargs(dict)。返り値: file。
            """
            if path==self.data/'view-data.js.tmp':
                table=control.read(self.data/'trials.json');table['直前変更']=True;put(self.data/'trials.json',table)
            return original(path,*args,**kwargs)
        with patch.object(Path,'open',new=concurrent):
            with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[row],others)
        self.assertTrue(control.read(self.data/'trials.json')['直前変更'])
        self.assertEqual((self.data/'view-data.js').read_bytes(),self.before_view);self.assert_clean()

    def test_ビュー置換失敗で旧正本を完全復元(self):
        """正本置換後のビュー失敗をバイト単位で巻き戻す。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();replace=Path.replace
        def fail_view(path,destination):
            """ビューだけの置換を失敗させる。

            引数: path/destination(Path)。返り値: Path。
            """
            if path==self.data/'view-data.js.tmp':raise OSError('人工ビュー失敗')
            return replace(path,destination)
        with patch.object(Path,'replace',new=fail_view):
            with self.assertRaises(OSError):registry.write_registry(self.m,v,s,[row],others)
        self.assert_unchanged();self.assert_clean()
        self.assertEqual((self.data/'history'/('trials_'+s+'.json')).read_bytes(),self.before)

    def test_旧退避の壊れた内容で復元しない(self):
        """既存退避ファイルの名前だけを信頼しない。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();backup=self.data/'history'/('trials_'+s+'.json');put(backup,{'壊れた退避':True})
        with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[row],others)
        self.assert_unchanged();self.assert_clean()

    def test_既存ロックと一時ファイルを消さない(self):
        """他の処理が所有する保存途中ファイルを維持する。

        引数: self(仮台帳検査)。返り値: None。
        """
        v,s,row,others=self.prepared();lock=self.data/'trials.json.write166.lock';lock.write_text('別処理',encoding='utf-8')
        with self.assertRaises(FileExistsError):registry.write_registry(self.m,v,s,[row],others)
        self.assertEqual(lock.read_text(encoding='utf-8'),'別処理');lock.unlink()
        staged=self.data/'trials.json.tmp';staged.write_text('別一時保存',encoding='utf-8')
        with self.assertRaises(AssertionError):registry.write_registry(self.m,v,s,[row],others)
        self.assertEqual(staged.read_text(encoding='utf-8'),'別一時保存');staged.unlink();self.assert_unchanged();self.assert_clean()

    def test_実check全文を別JSONへ保存し仕様を保持(self):
        """同じ共通check関数の全文と、追加前後の旧行を照合する。

        引数: self(仮台帳検査)。返り値: None。
        """
        expected=self.m.check(self.plan)
        with patch.object(self.m,'check',wraps=self.m.check) as spy:
            result=registry.register_plan(copy.deepcopy(self.plan))
        self.assertEqual(spy.call_count,1);self.assertEqual(spy.call_args.args[0],self.plan)
        self.assertEqual(control.read(self.root/result['path']),expected)
        saved=self.m.load(deep=False)['trials']['trials'];self.assertEqual(saved[:2],self.original)
        self.assertEqual(saved[2]['spec'],self.plan['spec']);self.assertNotIn('matches',saved[2]['preflight'])
        self.assertEqual(saved[2]['preflight']['complete_result'],result)
        self.assertTrue(control.read(self.study/'登録更新証跡166.json')['passed']);self.assert_clean()

    def test_完全同一なら登録しない(self):
        """完全同一の保存条件を新規研究として追加しない。

        引数: self(仮台帳検査)。返り値: None。
        """
        self.plan['spec']=copy.deepcopy(self.spec)
        with self.assertRaises(AssertionError):registry.register_plan(self.plan)
        self.assert_unchanged();self.assertFalse((self.study/'事前照合166.json').exists())

    def test_照合の途中で台帳が変われば登録しない(self):
        """照合対象と実際の保存基準が異なる状態を拒否する。

        引数: self(仮台帳検査)。返り値: None。
        """
        check=self.m.check
        def concurrent(plan):
            """check後に人工の台帳変更を挿入する。

            引数: plan(dict)。返り値: 元check結果(dict)。
            """
            result=check(plan);table=control.read(self.data/'trials.json');table['並行']=1;put(self.data/'trials.json',table);return result
        with patch.object(self.m,'check',side_effect=concurrent):
            with self.assertRaises(AssertionError):registry.register_plan(self.plan)
        self.assertEqual(control.read(self.data/'trials.json')['並行'],1)
        self.assertEqual(len(control.read(self.data/'trials.json')['trials']),2)


if __name__=='__main__':
    unittest.main(verbosity=2)
