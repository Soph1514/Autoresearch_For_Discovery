"""Freeze external labels and small source-derived contrast probes before scoring."""
import hashlib
import json
import re
from pathlib import Path
from collections import Counter
from transformers import AutoTokenizer
from experiment import MODEL

ROOT = Path(__file__).parent
RAW = ROOT/'artifacts/ood-sources'
OUT = ROOT/'artifacts/ood-v1'

def norm(s): return ' '.join(re.findall(r'\w+|[∀∃≤≥≠]',s.lower()))
def shingles(s):
    words=norm(s).split()
    return set(tuple(words[i:i+5]) for i in range(max(1,len(words)-4)))
def strip_comments(s):
    # Corpus snippets have no comment delimiters in string literals.
    s=re.sub(r'/\-.*?\-/','',s,flags=re.S)
    return re.sub(r'--[^\n]*','',s)
def render(nl,context,candidate):
    return f'<problem>\n{nl}\n</problem>\n<lean_context>\n{context.strip()}\n</lean_context>\n<candidate>\n{candidate.strip()}\n</candidate>\nFaithfulness:'

def prepare():
    OUT.mkdir(exist_ok=False)
    RAW.mkdir(exist_ok=True)
    critic_revision='6225522bce304f62d4907aedb9642255f9417bf0'
    from datasets import load_dataset
    critic=list(load_dataset('m-a-p/CriticLeanBench', revision=critic_revision, split='test'))
    manifest=json.loads((ROOT/'artifacts/manifest.json').read_text())
    tok=AutoTokenizer.from_pretrained(MODEL,revision=manifest['model_revision'])
    seen=[]
    for split in ('train','dev','calibration','test'):
        for r in json.loads((ROOT/f'artifacts/{split}.json').read_text()):
            nl=r['text'].split('<problem>\n',1)[1].split('\n</problem>',1)[0]
            seen.append((split,r['id'],norm(nl),shingles(nl)))
    rows=[];excluded=[]
    for r in critic:
        rid='critic:'+str(r['id'])
        if r['tag']=='compile_false':
            excluded.append({'id':rid,'reason':'compile_failure_not_semantic_label'});continue
        assert r['tag'] in ('compile_right_is_right','compile_right_is_false')
        nl=r['refined_statement']; n=norm(nl); sh=shingles(nl)
        overlap=[(split,i) for split,i,s,t in seen if n==s or len(sh&t)/max(1,len(sh|t))>=.5]
        if overlap:
            excluded.append({'id':rid,'reason':'possible_ProofNet_overlap','matches':overlap});continue
        code=strip_comments(r['autoformalization']).strip()
        code=re.sub(r':=\s*(?:by\s+)?sorry\b','',code)
        if re.search(r':=\s*by\b|\bsorry\b',code):
            excluded.append({'id':rid,'reason':'unhandled_proof'});continue
        m=re.search(r'\b(?:theorem|lemma|example)\b',code) or re.search(r'\bdef\b',code)
        if not m:
            excluded.append({'id':rid,'reason':'missing_statement'});continue
        text=render(nl,code[:m.start()],code[m.start():])
        tokens=len(tok(text)['input_ids'])
        if tokens>4096:
            excluded.append({'id':rid,'reason':'context_overflow','tokens':tokens});continue
        rows.append({'id':rid,'group':'critic:'+hashlib.sha256(n.encode()).hexdigest()[:16],
            'dataset':'CriticLeanBench','source':r['source'],'text':text,
            'label':int(r['tag']=='compile_right_is_right'),'tokens':tokens,
            'label_origin':'published_semantic_tag','published_tag':r['tag']})
    probes=json.loads((ROOT/'ood_probes.json').read_text())
    for r in probes:
        text=render(r['english'],r['context'],r['candidate'])
        tokens=len(tok(text)['input_ids']);assert tokens<=4096
        sh=shingles(r['english'])
        assert not any(norm(r['english'])==n or len(sh&t)/max(1,len(sh|t))>=.5 for _,_,n,t in seen)
        rows.append(dict(r,text=text,tokens=tokens,label_origin='agent_curated_synthetic_probe_not_independent_benchmark'))
    (OUT/'rows.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
    (OUT/'excluded.json').write_text(json.dumps(excluded,indent=2)+'\n')
    meta={'critic_revision':critic_revision,
        'library_revisions':{r['source']:r['source_revision'] for r in probes},
        'counts':dict(Counter(r['dataset'] for r in rows)),
        'label_counts':{k:dict(Counter(r['label'] for r in rows if r['dataset']==k)) for k in {r['dataset'] for r in rows}},
        'exclusions':dict(Counter(r['reason'] for r in excluded)),
        'overlap_screen':'Compared normalized English and 5-token shingle Jaccard >=0.5 against ALL ProofNet splits. Does not exclude semantic paraphrase or pretraining contamination.',
        'limits':'No independent human label audit or local Lean build of library probes. Small hand-curated source-derived contrast probes are diagnostic only; original library authors did not supply these binary labels.',
        'rows_sha256':hashlib.sha256((OUT/'rows.json').read_bytes()).hexdigest(),
        'proof_handling':'Removed comments and placeholder proofs; passed context before first theorem separately. Critic messages and tags never enter model input.',
        'max_tokens':max(r['tokens'] for r in rows)}
    (OUT/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2))
if __name__=='__main__':prepare()
