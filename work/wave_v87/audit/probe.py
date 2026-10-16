import sys,os,importlib.util,pickle,json
from pathlib import Path
sys.dont_write_bytecode=True
root=Path.cwd(); out=root/'work/wave_v87/audit';os.environ['NUMBA_CACHE_DIR']=str(out/'cache')
s=importlib.util.spec_from_file_location('probe85',root/'work/wave_v85/strategy.py');m=importlib.util.module_from_spec(s);sys.modules[s.name]=m;s.loader.exec_module(m)
print('gate',m.base.gate.__file__,'prior',m.base.prior.__file__,'entry',m.base.gate.replay.entry.__file__)
m.base.gate.replay.entry.set_root(root)
p=json.loads((root/'work/wave_v85/prepared/入力準備の完了.json').read_text(encoding='utf8'))
q=next(v for v in p['入力対応'] if 'old23' in v['inputs'])
r=pickle.loads((root/q['inputs']).read_bytes()); sig=pickle.loads((root/q['signals']).read_bytes()); print(q, list(r)); print({k:type(v).__name__ for k,v in sig.items()})
k=next(iter(r)); print('ready',r[k].keys());print('sig_entry',type(sig['entry'][k]),str(sig['entry'][k])[:200]);print('B00',sig['B00'][k].keys());print('model',m.base.gate.model(r[k]).keys())
