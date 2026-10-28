"""市場原資料を読まず、人工27夜だけで00165の段階管理を検査する。"""

from __future__ import annotations
import copy
from datetime import datetime, timezone, timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('制御165人工', HERE/'control165.py')
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def put(path: Path, value: object) -> None:
    """人工フィクスチャだけを生成又は改変する。

    引数: path(Path)、value(JSON変換可能)。返り値: None。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


def case(definition: dict, net: int, trade: bool = True) -> dict:
    """実売買ではない最小会計構造を作る。

    引数: definition(dict)、net(int)、trade(bool)。返り値: 人工case(dict)。
    """
    events = [{'HoldID':'人工玉','Pieces':None},
              {'HoldID':'','Pieces':[{'Gross':net,'Quantity':10}]}] if trade else []
    ledger = {'Pending':[], 'Lots':{'人工玉':{'Remaining':0}} if trade else {},
              'Events':events,'Realized':net,
              'Risk':{'Minimum':min(0,net),'MaxDD':max(0,-net),'MaxLong':10 if trade else 0,
                      'MaxShort':0,'HeldSeconds':1 if trade else 0,'GrossSeconds':10 if trade else 0}}
    return {'config':copy.deepcopy(definition),'actual':ledger}


class 人工制御検査(unittest.TestCase):
    """一時フォルダへ隔離した人工結果で制御の失敗境界を検査する。"""

    def setUp(self):
        """源の定数だけを隔離し、偽の登録証跡を人工で作る。

        引数: self(人工制御検査)。返り値: None。
        """
        self.temp = tempfile.TemporaryDirectory(prefix='control165_人工_')
        self.root = Path(self.temp.name).resolve(); self.base = self.root/'work/research165'
        self.base.mkdir(parents=True)
        self.patchers=[]
        names={'ROOT':self.root,'HERE':self.base,'MANIFEST':self.base/'inputs165.json',
               'BASELINE':self.base/'baseline165.json','CONFIGS':self.base/'night_engine/configs165.json',
               'SPEC':self.base/'計画165.md','RECEIPT':self.base/'登録受領165.json',
               'PREFLIGHT':self.base/'audit/preflight165.json',
               'FREEZE':self.base/'results/selection_frozen165.json','__file__':str(self.base/'control165.py')}
        for name,value in names.items():
            p=patch.object(control,name,value);p.start();self.patchers.append(p)
        (self.base/'control165.py').write_text('# 人工源\n',encoding='utf-8')
        control.SPEC.write_text('人工計画・金融0',encoding='utf-8')
        self.definitions=[{'id':f'NK225_U165_{i:02d}','scope':'PostUS','rule_hash':f'{i:064x}','parameter':i} for i in range(1,15)]
        put(control.CONFIGS,self.definitions)
        start=datetime(2030,1,1,17,tzinfo=timezone(timedelta(hours=9))).timestamp()
        self.scenes=[]
        for i in range(27):
            self.scenes.append({'session':f'人工{i+1:02d}_Night','kind':'Night','partial':False,
                'start':start+i*86400,'end':start+i*86400+46800,'force_close':start+i*86400+46200,
                'us_open':start+i*86400+19800,'cutoff':start+i*86400+46860,
                'books':{'NK225':'人工板'},'candles':{},'fingerprints':[{'path':'人工板','sha256':'a'*64}],
                'split':'train' if i<15 else 'validation' if i<20 else 'test'})
        put(control.MANIFEST,{'sessions':self.scenes})
        baseline=[{'scene':s,'case':case({'id':'NK225_U164_00'},25 if i<20 else 99999999)} for i,s in enumerate(self.scenes)]
        put(control.BASELINE,{'cases':baseline})
        dummy=self.base/'人工根拠.json';put(dummy,{'人工':True})
        source=[control.record(p) for p in (control.MANIFEST,control.BASELINE,control.CONFIGS,control.SPEC)]
        put(control.RECEIPT,{'registered':True,'returncode':0,'id':control.IDENT,'sources':source,
                            'implementation':control.record(dummy),'plan':control.record(dummy),'preflight':control.record(dummy)})

    def tearDown(self):
        """人工定数を復元し、隔離した一時フォルダだけを除く。

        引数: self(人工制御検査)。返り値: None。
        """
        for p in reversed(self.patchers):p.stop()
        self.temp.cleanup()

    def stage(self, stage: str, negative: bool = False) -> dict:
        """各候補を売買せず、既知の人工損益を成果形式で保存する。

        引数: stage(str)、negative(bool)。返り値: 人工完了証跡(dict)。
        """
        selected=self.scenes[:20] if stage=='train_validation' else self.scenes[20:]
        folder=self.base/'results'/stage; files=[]
        for scene in selected:
            cases=[]
            for d in self.definitions:
                amount=-int(d['parameter']) if negative else int(d['parameter'])*10
                if d['id'] in control.CONTROLS:amount=999999
                cases.append(case(d,amount))
            path=folder/(scene['session']+'.json');put(path,{'scene':scene,'cases':cases})
            files.append(dict(control.record(path),session=scene['session']))
        information={'stage':stage,'manifest_sha256':control.sha(control.MANIFEST),
                     'spec_sha256':control.sha(control.SPEC),'configs_sha256':control.sha(control.CONFIGS)}
        if stage=='confirmation':
            fixed=control.read(control.FREEZE)
            information.update(freeze_sha256=control.sha(control.FREEZE),selected=fixed['selected'])
        proof={'completed':True,'returncode':0,'sources_unchanged':True,'sessions':len(selected),
               'cases':len(selected)*14,'stage':information,'results':files}
        put(folder/('再生完了165_'+stage+'.json'),proof)
        return proof

    def rows(self, values: list[int], trades: list[bool] | None = None) -> list[dict]:
        """手計算可能な損益から表の行を作る。

        引数: values(list[int])、trades(list[bool]|None)。返り値: list[dict]。
        """
        return [control.row_from_case(self.scenes[i],case(self.definitions[0],v,True if trades is None else trades[i]))
                for i,v in enumerate(values)]

    def test_全20の悪い5場で平均損失を測る(self):
        """赤字だけの四分位や正負込み平均との混同を拒む。

        引数: self(人工制御検査)。返り値: None。
        """
        s=control.summary(self.rows([-100,-50,0]+[10]*17))
        self.assertEqual(s['worst_quarter_loss'],30)
        self.assertEqual(s['worst_quarter_mean'],-26)
        self.assertEqual(s['mean_loss'],75)
        self.assertEqual(s['negative_sessions'],2)
        self.assertEqual(s['excluding_top3'],-10)
        self.assertEqual(s['net'],20)

    def test_無取引と収支ゼロと赤字を分ける(self):
        """0円の取引を無取引や負けへ分類しない。

        引数: self(人工制御検査)。返り値: None。
        """
        s=control.summary(self.rows([0,0,-10,10],[False,True,True,True]))
        self.assertEqual((s['no_entries'],s['negative_sessions'],s['new_orders']),(1,1,3))

    def test_配賦損益と残玉を検査(self):
        """確定益損の相殺と未完済拒否を確認する。

        引数: self(人工制御検査)。返り値: None。
        """
        c=case(self.definitions[0],15);c['actual']['Events'][1]['Pieces']=[{'Gross':20,'Quantity':5},{'Gross':-5,'Quantity':5}]
        r=control.row_from_case(self.scenes[0],c)
        self.assertEqual((r['profit'],r['loss'],r['net']),(20,5,15))
        c['actual']['Lots']['人工玉']['Remaining']=1
        with self.assertRaises(AssertionError):control.row_from_case(self.scenes[0],c)

    def test_数量対照を除き黒字参加通常損失を優先(self):
        """合計額だけの並べ替えや数量対照の選抜を防ぐ。

        引数: self(人工制御検査)。返り値: None。
        """
        default={'net':100,'no_entries':0,'excluding_top3':1,'negative_sessions':1,
                 'worst_quarter_loss':10,'mean_loss':30,'minimum_equity':-40}
        methods=[{'id':name,'summary':dict(default,**changes)} for name,changes in
                 [('NK225_U165_01',{'net':99999}),('通常',{}),('大勝ち',{'net':10000,'negative_sessions':2}),
                  ('無取引',{'no_entries':1,'negative_sessions':0}),('上位依存',{'excluding_top3':0}),('赤字',{'net':-1})]]
        self.assertEqual([x['id'] for x in control.rank(methods)],['通常','大勝ち','上位依存','無取引','赤字'])

    def test_後半新結果を読まず前20だけで固定(self):
        """既知旧基準の後7を選抜母数へ混ぜず、新しい後半成果を開かない。

        引数: self(人工制御検査)。返り値: None。
        """
        self.stage('train_validation'); original=control.read;opened=[]
        def guarded(path):
            """後半新結果を開いた場合だけ人工検査を停止する。

            引数: path(Path)。返り値: JSON構造。
            """
            self.assertNotIn('confirmation',Path(path).parts);opened.append(str(path));return original(path)
        with patch.object(control,'read',side_effect=guarded):control.freeze()
        f=original(control.FREEZE)
        self.assertEqual(f['selected'],{'PostUS':'NK225_U165_14'})
        self.assertEqual((len(f['comparisons']),len(f['ranking'])),(15,13))
        self.assertTrue(f['selected_eligible']);self.assertFalse(f['adoption_confirmed'])
        self.assertEqual(next(x for x in f['comparisons'] if x['id']=='NK225_U164_00')['summary']['net'],500)

    def test_資格なしでも比較固定は完成推薦にしない(self):
        """全主候補赤字でも数量対照を採用と呼ばない。

        引数: self(人工制御検査)。返り値: None。
        """
        b=control.read(control.BASELINE)
        for x in b['cases']:x['case']=case({'id':'NK225_U164_00'},-50)
        put(control.BASELINE,b)
        receipt=control.read(control.RECEIPT)
        receipt['sources']=[control.record(Path(control.ROOT/s['path'])) for s in receipt['sources']]
        put(control.RECEIPT,receipt)
        self.stage('train_validation',negative=True);control.freeze();f=control.verified_freeze()
        self.assertFalse(f['selected_eligible']);self.assertFalse(f['adoption_confirmed'])

    def test_後半開封済みなら固定拒否(self):
        """後半成果が既に存在する状態で初回固定しない。

        引数: self(人工制御検査)。返り値: None。
        """
        self.stage('train_validation');put(self.base/'results/confirmation/既に開封.json',{})
        with self.assertRaises(AssertionError):control.freeze()

    def test_凍結なしと登録失敗で次段階拒否(self):
        """未固定の確認許可と登録失敗の前半許可を拒否する。

        引数: self(人工制御検査)。返り値: None。
        """
        with self.assertRaises(FileNotFoundError):control.allow('confirmation')
        r=control.read(control.RECEIPT);r['returncode']=1;put(control.RECEIPT,r)
        with self.assertRaises(AssertionError):control.allow('train_validation')

    def test_凍結の再署名だけでは選択を変えられない(self):
        """内容SHAを再計算した誤変更も保存順位との不一致で拒否する。

        引数: self(人工制御検査)。返り値: None。
        """
        self.stage('train_validation');control.freeze();f=control.read(control.FREEZE)
        f['selected']={'PostUS':'NK225_U165_01'}
        f['content_sha256']=control.canonical({k:v for k,v in f.items() if k!='content_sha256'});put(control.FREEZE,f)
        with self.assertRaises(AssertionError):control.allow('confirmation')

    def test_前半成果の変更で後半許可拒否(self):
        """金融開始前に前半の保存内容を差し替えられない。

        引数: self(人工制御検査)。返り値: None。
        """
        proof=self.stage('train_validation');control.freeze()
        p=self.root/proof['results'][0]['path'];p.write_text('{}',encoding='utf-8')
        with self.assertRaises(AssertionError):control.allow('confirmation')

    def test_場重複と分割境界違いを拒否(self):
        """20件という件数だけ合う重複場や前後混在を防ぐ。

        引数: self(人工制御検査)。返り値: None。
        """
        s=copy.deepcopy(self.scenes);s[0]['session']=s[1]['session'];put(control.MANIFEST,{'sessions':s})
        with self.assertRaises(AssertionError):control.scenes_for_stage('train_validation')
        s=copy.deepcopy(self.scenes);s[19]['split']='test';put(control.MANIFEST,{'sessions':s})
        with self.assertRaises(AssertionError):control.scenes_for_stage('train_validation')

    def test_同IDの定義差替えを拒否(self):
        """成果ファイルのSHAが正しくても条件本体不一致を拒否する。

        引数: self(人工制御検査)。返り値: None。
        """
        proof=self.stage('train_validation');p=self.root/proof['results'][0]['path'];r=control.read(p)
        r['cases'][0]['config']['parameter']=999;put(p,r);proof['results'][0]['sha256']=control.sha(p)
        put(self.base/'results/train_validation/再生完了165_train_validation.json',proof)
        with self.assertRaises(AssertionError):control.stage_results('train_validation')

    def test_基準の診断メタは許すが経済入力変更は拒否(self):
        """旧基準の使い回しに必要な入力境界を確認する。

        引数: self(人工制御検査)。返り値: None。
        """
        old=copy.deepcopy(self.scenes[0]);current=copy.deepcopy(old)
        current['confirmation']=False;current['fingerprints'][0]['audit']='新記録'
        self.assertTrue(control.baseline_scene_matches(old,current))
        current['force_close']+=60
        self.assertFalse(control.baseline_scene_matches(old,current))

    def test_全段階378人工条件場が完了する(self):
        """許可・前半・固定・許可・後半・完了を順に接続する。

        引数: self(人工制御検査)。返り値: None。
        """
        control.allow('train_validation');self.stage('train_validation');control.freeze()
        control.allow('confirmation');self.stage('confirmation');control.complete()
        p=control.read(self.base/'再生全完了165.json')
        self.assertEqual((p['sessions'],p['cases']),(27,378))
        self.assertFalse(p['reselection_after_confirmation']);self.assertFalse(p['adoption_confirmed'])

    def test_証跡上書きと非有限値を拒否(self):
        """再保存とNaNが正常結果に紛れないことを確認する。

        引数: self(人工制御検査)。返り値: None。
        """
        path=self.base/'一意.json';control.save(path,{'人工':1})
        with self.assertRaises(FileExistsError):control.save(path,{'人工':2})
        path.write_text('{"値":NaN}',encoding='utf-8')
        with self.assertRaises(ValueError):control.read(path)

    def test_登録計画8部品と条件比較を人工受渡し(self):
        """実台帳を開かず登録計画と固定源ZIPの構造を接続する。

        引数: self(人工制御検査)。返り値: None。
        """
        control.RECEIPT.unlink()
        registry=self.base/'registry165.py';registry.write_text('# 人工管理器',encoding='utf-8')
        required=[control.MANIFEST,control.BASELINE,control.CONFIGS,control.SPEC,
                  Path(control.__file__),registry]
        put(control.PREFLIGHT,{'passed':True,'new_financial_replays':0,'sources':[control.record(p) for p in required]})
        received=[]
        def register_plan(plan):
            """計画だけを受け取り、巨大台帳への書込みを行わない。

            引数: plan(dict)。返り値: 人工照合証跡(dict)。
            """
            received.append(plan)
            self.assertEqual(set(plan['spec']),{'entry','management','exit','allocation','costs','execution','data','implementation'})
            self.assertEqual(plan['purpose'],'条件比較')
            self.assertIn('00099',plan['repeat_reason'])
            self.assertEqual(len(plan['spec']['data']['sessions']),27)
            return control.record(control.PREFLIGHT)
        with patch.object(control,'module',return_value=SimpleNamespace(register_plan=register_plan)):
            control.register()
        self.assertEqual(len(received),1)
        self.assertTrue(control.verify_receipt()['registered'])
        self.assertTrue((self.base/'再生前実装165.zip').is_file())


if __name__=='__main__':
    unittest.main(verbosity=2)
