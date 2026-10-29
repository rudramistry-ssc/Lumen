"""Paired OCR evaluation CLI. Not a test suite; never changes pipeline code."""
from __future__ import annotations
import argparse,hashlib,json,os,platform,statistics,subprocess,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT.parent/'src'


def digest_tree(path):
    return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.rglob('*.py'))}


def worker(image,mode,psm,reference_enabled=False):
    from signspeak_ocr import PipelineConfig,TesseractConfig,extract_image
    from signspeak_ocr.validate import validate_result
    arguments={'tesseract':TesseractConfig(psm=psm,omp_thread_limit=1)}
    if mode=='enabled' or reference_enabled:
        from signspeak_ocr import PreprocessConfig
        arguments['preprocessing']=PreprocessConfig(enabled=True)
    result=extract_image(image,PipelineConfig(**arguments),include_debug=True)
    problems=validate_result(result)
    if problems:raise ValueError(problems)
    if result['validation']['overall_status']=='failed':raise ValueError(result['errors'])
    result['evaluation_environment']={'python':platform.python_version(),'source_module':__import__('signspeak_ocr').__file__}
    json.dump(result,sys.stdout,ensure_ascii=False,allow_nan=False)


def run(output,baseline_source,psm,reference_enabled=False):
    manifest=json.loads((output/'manifest.json').read_text(encoding='utf-8'))
    if not (baseline_source/'signspeak_ocr/pipeline.py').is_file():raise ValueError('Supply a saved original Phase 1 source directory containing signspeak_ocr/')
    (output/'results').mkdir(exist_ok=True)
    provenance={'reference_preprocessing_enabled':reference_enabled,'psm':psm,'languages':['eng','fra'],'omp_thread_limit':1,'source_hashes':{'phase1':digest_tree(baseline_source),'enabled':digest_tree(SOURCE)},
                'image_hashes':{i['id']:i['sha256'] for i in manifest},'order':'alternated; fresh process for each image and mode'}
    for i,item in enumerate(manifest):
        image=Path(item['image'])
        if not image.is_file():
            candidates=[output/'images'/image.name,ROOT/'generated/images'/image.name,output.parent/'images'/image.name]
            image=next((p for p in candidates if p.is_file()),image)
        if hashlib.sha256(image.read_bytes()).hexdigest()!=item['sha256']:raise ValueError('Image hash mismatch')
        for mode in (['baseline','enabled'] if i%2==0 else ['enabled','baseline']):
            env=dict(os.environ,PYTHONPATH=str(baseline_source if mode=='baseline' else SOURCE))
            result=subprocess.run([sys.executable,__file__,'worker',str(image),mode,str(psm),str(int(reference_enabled and mode=='baseline'))],env=env,capture_output=True,text=True,encoding='utf-8',check=False)
            if result.returncode:
                raise RuntimeError(f"OCR worker failed for {item['id']} ({mode}): {result.stderr}")
            (output/'results'/f"{item['id']}-{mode}.json").write_text(result.stdout,encoding='utf-8')
        print(i+1,item['id'],flush=True)
    if provenance['source_hashes']['enabled']!=digest_tree(SOURCE):raise ValueError('Source changed during evaluation')
    (output/'run.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')


def summarize(output):
    sys.path.insert(0,str(SOURCE))
    from scoring import metrics,align
    rows=[]
    for item in json.loads((output/'manifest.json').read_text(encoding='utf-8')):
        row={'id':item['id'],'condition':item['condition'],'origin':item['origin']}
        for mode in ('baseline','enabled'):
            result=json.loads((output/'results'/f"{item['id']}-{mode}.json").read_text(encoding='utf-8'))
            row[mode]=metrics(item,result)
        # Accuracy is measured without flags. Flag effects are separately counted.
        newly_correct=set(row['enabled']['recognized_truth_ids'])-set(row['baseline']['recognized_truth_ids'])
        row['newly_correct_words']=len(newly_correct)
        row['newly_correct_withheld']=len(newly_correct&set(row['enabled']['correct_withheld_ids']))
        row['recovered_words']=row['baseline']['omitted_words']-row['enabled']['omitted_words']
        row['baseline_insertions']=sum(op=='insert' for op,_,_ in align(item['text'].split(),row['baseline']['display'].split())[1])
        row['enabled_insertions']=sum(op=='insert' for op,_,_ in align(item['text'].split(),row['enabled']['display'].split())[1])
        for mode in ('baseline','enabled'):
            expected=Counter(item['text'].split());actual=Counter(row[mode]['display'].split())
            row[mode]['bag_missing_words']=sum((expected-actual).values())
            row[mode]['bag_extra_words']=sum((actual-expected).values())
        rows.append(row)
    sums={mode:{key:sum(r[mode][key] for r in rows) for key in ('character_edits','reference_characters','word_edits','reference_words','omitted_words','numeric_errors','silent_numeric_errors','reference_numeric_tokens','numeric_token_format_errors','unit_errors','spatial_numeric_errors','spatial_silent_numeric_errors','bag_missing_words','bag_extra_words','correct_words','correct_withheld','correct_flagged')} for mode in ('baseline','enabled')}
    report={'rows':rows,'totals':sums,'improved':sum(r['enabled']['cer']<r['baseline']['cer'] for r in rows),
            'degraded':sum(r['enabled']['cer']>r['baseline']['cer'] for r in rows)}
    (output/'summary.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    for mode,values in sums.items():
        print(mode, json.dumps(values),'CER',values['character_edits']/values['reference_characters'],'WER',values['word_edits']/values['reference_words'])
    print('improved',report['improved'],'degraded',report['degraded'])

if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='worker':worker(sys.argv[2],sys.argv[3],int(sys.argv[4]),bool(int(sys.argv[5])) if len(sys.argv)>5 else False);sys.exit(0)
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['run','summarize']);parser.add_argument('--output',type=Path,default=ROOT/'generated');parser.add_argument('--phase1-source',type=Path,default=ROOT/'generated/sources/phase1');parser.add_argument('--psm',type=int,default=3);parser.add_argument('--reference-enabled',action='store_true')
    args=parser.parse_args()
    if args.command=='run':run(args.output,args.phase1_source,args.psm,args.reference_enabled)
    else:summarize(args.output)
