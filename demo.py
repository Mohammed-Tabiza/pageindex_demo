"""Real PageIndex SDK integration; offline checks never simulate answers."""
import argparse, hashlib, importlib.metadata, json, os, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
INSTRUCTIONS=("Réponds en français uniquement à partir des documents fictifs fournis. "
              "Signale explicitement les informations absentes. Applique les exceptions. "
              "Suis les renvois vers les autres documents accessibles jusqu’à trouver la règle applicable. "
              "Ne demande pas à l’utilisateur de consulter à ta place un document accessible. "
              "Donne directement la réponse finale, sans annoncer tes recherches. "
              "Cite les pages justificatives. N'invente aucune coordonnée.")
def write(path,value):
 path.write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
def offline():
 from PyPDF2 import PdfReader
 questions=json.loads((ROOT/'questions.json').read_text(encoding='utf-8'))
 pages={}
 for pdf in sorted((ROOT/'data').glob('*.pdf')):
  reader=PdfReader(pdf)
  assert len(reader.pages)==4, pdf.name
  for i,p in enumerate(reader.pages,1):
   text=p.extract_text()
   assert 'FICTIF' in text and len(text)>100
   pages[f'{pdf.name}:{i}']=text
 for q in questions:
  assert all(s in pages for s in q['sources'])
 assert '30 minutes' in pages['incidents.pdf:3']
 assert 'animateur' in pages['astreintes.pdf:2']
 result={'mode':'offline_validation','pdfs':3,'pages':len(pages),'questions':len(questions),
         'pageindex_inference':'NON TESTÉ','status':'PASS','python':sys.version.split()[0]}
 print(json.dumps(result,ensure_ascii=False,indent=2))
 return result

def configuration():
 from dotenv import load_dotenv
 load_dotenv(ROOT/'.env',override=False)
 fallback=os.getenv('DEMO_MODEL','').strip()
 index_model=os.getenv('DEMO_INDEX_MODEL','').strip() or fallback
 chat_model=os.getenv('DEMO_CHAT_MODEL','').strip() or fallback
 key=os.getenv('OPENAI_API_KEY','').strip()
 url=os.getenv('OPENAI_BASE_URL','').strip()
 if not index_model or not chat_model or not key or not url:
  raise ValueError('Renseignez DEMO_INDEX_MODEL et DEMO_CHAT_MODEL (ou DEMO_MODEL), OPENAI_API_KEY et OPENAI_BASE_URL dans .env. Aucun appel effectué.')
 for model in (index_model,chat_model):
  if model.lower() in ('cloud','local'):
   raise ValueError('Les modèles doivent être les noms des modèles servis, pas cloud/local.')
 return index_model,chat_model,key,url

def pageindex_client(index_model,chat_model,key,url):
 # Disable SDK tracing; retain only observable tool events, not model thinking.
 os.environ['OPENAI_AGENTS_DISABLE_TRACING']='1'
 from pageindex import PageIndexClient
 backend={'api_key':key,'base_url':url}
 return PageIndexClient(index={'model':index_model,'backend':backend,'storage_path':str(ROOT/'.pageindex')},
                        chat={'model':chat_model,'backend':backend},instructions=INSTRUCTIONS)

def indexed_manifest(index_model=None):
 manifest=json.loads((ROOT/'index_manifest.json').read_text(encoding='utf-8'))
 stored_model=manifest.get('index_model',manifest.get('model'))
 # Older manifests may omit the OpenAI-compatible provider prefix.
 if index_model is not None and (not stored_model or stored_model.removeprefix('openai/')!=index_model.removeprefix('openai/')):
  raise ValueError('Modèle d’indexation modifié : réindexer. Le modèle de génération peut changer sans réindexation.')
 for d in manifest['docs']:
  if hashlib.sha256((ROOT/'data'/d['file']).read_bytes()).hexdigest()!=d['sha256']:
   raise ValueError('Corpus modifié : réindexer.')
 return manifest

def worker(args):
 index_model,chat_model,key,url=configuration()
 client=pageindex_client(index_model,chat_model,key,url)
 out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
 if args.action=='index':
  manifest={'model':index_model,'index_model':index_model,'pageindex':importlib.metadata.version('pageindex'),'docs':[]}
  start=time.monotonic()
  for pdf in sorted((ROOT/'data').glob('*.pdf')):
   print('INDEX',pdf.name,flush=True)
   doc=client.submit_document(str(pdf),mode='flash')
   tree=client.get_tree(doc['doc_id'],node_summary=True,include_text=False)
   write(out/(pdf.stem+'_tree.json'),tree)
   manifest['docs'].append({'file':pdf.name,'doc_id':doc['doc_id'],
                            'sha256':hashlib.sha256(pdf.read_bytes()).hexdigest()})
  manifest['seconds']=time.monotonic()-start
  write(ROOT/'index_manifest.json',manifest);write(out/'index_manifest.json',manifest)
  return
 manifest=indexed_manifest(index_model)
 questions=json.loads((ROOT/'questions.json').read_text(encoding='utf-8'))
 q=next(q for q in questions if q['id']==args.case)
 start=time.monotonic()
 meta={'case':q['id'],'question':q['question'],'model':chat_model,'index_model':manifest.get('index_model',manifest['model']),'mode':args.action,
       'pageindex':importlib.metadata.version('pageindex'),'expected':q['expected'],
       'expected_sources':q['sources'],'verdict':'À ÉVALUER MANUELLEMENT'}
 write(out/'metadata.json',meta)
 if args.action=='ask':
  with (out/'trace.txt').open('w',encoding='utf-8') as f:
   for chunk in client.chat(q['question'],doc_id=[d['doc_id'] for d in manifest['docs']],
                           citations=True,stream=True,max_turns=8,
                           show_process={'thinking':False,'tool_call':True,'tool_result':True,'max_chars':4000}):
    text=str(chunk);print(text,end='',flush=True);f.write(text);f.flush()
  # Trace deliberately includes tool events: evaluate final answer separately by inspection.
 else:
  from PyPDF2 import PdfReader
  from litellm import completion
  parts=[]
  for d in manifest['docs']:
   for i,p in enumerate(PdfReader(ROOT/'data'/d['file']).pages,1):
    parts.append(f"SOURCE {d['file']} PAGE {i}\n{p.extract_text()}")
  response=completion(model=chat_model,api_key=key,api_base=url,timeout=60,
                      messages=[{'role':'system','content':INSTRUCTIONS},
                                {'role':'user','content':'\n\n'.join(parts)+'\nQUESTION : '+q['question']}])
  answer=response.choices[0].message.content
  (out/'answer.txt').write_text(answer or '',encoding='utf-8');print(answer)
  meta['usage']=response.usage.model_dump() if response.usage else None
 meta['seconds']=time.monotonic()-start
 write(out/'metadata.json',meta)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('action',choices=['check','index','ask','baseline'])
 p.add_argument('--case',default='renvoi',choices=['nominal','renvoi','exception','absent','validation'])
 p.add_argument('--timeout',type=int,default=120)
 p.add_argument('--worker',action='store_true',help=argparse.SUPPRESS)
 p.add_argument('--output',help=argparse.SUPPRESS)
 args=p.parse_args()
 if args.action=='check':offline();return
 if args.worker:worker(args);return
 configuration() # fail fast, before spawning or sending anything
 out=ROOT/'runs'/f'{time.strftime("%Y%m%d-%H%M%S")}-{time.time_ns()%1000000}-{args.action}-{args.case}'
 out.mkdir(parents=True)
 cmd=[sys.executable,str(Path(__file__).resolve()),args.action,'--case',args.case,'--worker','--output',str(out)]
 try:
  result=subprocess.run(cmd,timeout=args.timeout)
  write(out/'execution.json',{'returncode':result.returncode,'timeout_seconds':args.timeout})
  raise SystemExit(result.returncode)
 except subprocess.TimeoutExpired:
  write(out/'execution.json',{'status':'TIMEOUT','timeout_seconds':args.timeout})
  print('Délai dépassé : processus interrompu. Des appels déjà reçus peuvent rester facturés.',file=sys.stderr)
  raise SystemExit(124)
if __name__=='__main__':
 try:main()
 except Exception as e:
  # Do not dump backend exception strings: they may contain headers or secrets.
  print(f'Échec ({type(e).__name__}). Vérifiez configuration, accès réseau et traces locales.',file=sys.stderr)
  if isinstance(e,ValueError): print(str(e),file=sys.stderr)
  raise SystemExit(1)
