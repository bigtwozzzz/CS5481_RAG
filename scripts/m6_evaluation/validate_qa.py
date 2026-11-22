"""Validate authored QA against a local corpus without retrieval or API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def validate_dataset(root, corpus):
    folder=root/'data/evaluation'
    load=lambda p:json.loads(p.read_text(encoding='utf-8'))
    manifest=load(folder/'m5_dataset_manifest.json')
    assert sha(corpus)==manifest['corpus_sha256'], 'Corpus snapshot hash differs'
    assert sha(folder/'qa_reviewed.json')==manifest['historical_qa_sha256'], 'Historical QA changed'
    for name,expected in manifest['files'].items():
        path=(root/name).resolve()
        assert path.is_relative_to(root.resolve()), 'Unsafe manifest path'
        assert sha(path)==expected, f'Sealed artifact hash differs: {name}'
    # JSON strings may contain Unicode line separators; JSONL boundaries are LF.
    with corpus.open(encoding='utf-8') as stream:
        documents=[json.loads(line) for line in stream if line.strip()]
    docs={d['document_id']:d for d in documents}
    assert len(docs)==len(documents)==manifest['corpus_document_count']
    registry=load(folder/'m5_event_registry.json')
    events={r['event_id']:r for r in registry}
    assert len(events)==len(registry)
    exclusion=load(folder/'m5_exclusion_audit.json')
    excluded=set(exclusion['excluded_document_ids'])
    old_questions=set()
    normalize=lambda s:' '.join(re.findall(r'\w+',s.lower()))
    def historical_questions(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('question','query','QUESTION') and isinstance(item,str):
                    old_questions.add(normalize(item))
                historical_questions(item)
        elif isinstance(value,list):
            for item in value:historical_questions(item)
    for name,expected in exclusion['historical_artifact_sha256'].items():
        path=(root/name).resolve()
        assert path.is_relative_to(root.resolve()) and sha(path)==expected, 'Historical exclusion input changed: '+name
        if path.suffix=='.jsonl':
            with path.open(encoding='utf-8') as stream:
                for line in stream:
                    if line.strip():historical_questions(json.loads(line))
        else:historical_questions(load(path))
    event_documents={}
    for event in registry:
        assert event['anchor_document_id'] in event['related_document_ids']
        assert not excluded.intersection(event['related_document_ids']), event['event_id']
        actual={d['document_id'] for d in documents if all(
            re.search(p,d['title']+'\n'+d['body_text'],re.I) for p in event['candidate_match_patterns'])}
        assert actual==set(event['related_document_ids']), event['event_id']+' candidate sweep differs'
        for did in event['related_document_ids']:
            if did in event_documents:
                assert event_documents[did]==event['split'], 'Related event article crosses splits'
            event_documents[did]=event['split']
    old=load(folder/'qa_reviewed.json')
    old_questions.update(normalize(r['question']) for r in old)
    seen_ids=set();seen_questions=set();counts={};all_rows=[]
    for split in ('dev','holdout'):
        rows=load(folder/f'm5_{split}.json')
        inputs=[json.loads(line) for line in (folder/'inputs'/f'm5_{split}.questions.jsonl').read_text().splitlines()]
        assert len(inputs)==len(rows)
        for row,request in zip(rows,inputs):
            qid=row['id']; assert qid not in seen_ids,qid
            seen_ids.add(qid)
            normalized=normalize(row['question'])
            assert normalized not in old_questions|seen_questions,qid+' repeated question'
            seen_questions.add(normalized)
            assert row['schema_version']=='m6_qa.v1'
            assert row['split']==split and events[row['event_id']]['split']==split,qid
            assert set(request)=={'id','question'},qid+' gold leakage into generation input'
            assert request=={'id':qid,'question':row['question']},qid
            assert isinstance(row['answerable'],bool) and row['question'].strip(),qid
            assert row['source_document_ids']==[events[row['event_id']]['anchor_document_id']],qid
            assert row['review']['agent_source_check']=='PASS',qid
            if not manifest['holdout']['human_review_complete']:
                assert row['review']['human_review_status']=='PENDING',qid+' false human approval'
                assert row['review']['human_reviewer'] is None,qid
            ev=row['gold_evidence']+row['context_evidence']
            assert ev,qid+' needs source evidence or negative context'
            evidence_ids=set()
            for item in ev:
                did=item['document_id'];assert did in docs and did not in excluded,qid
                assert did in events[row['event_id']]['related_document_ids'],qid
                assert item['evidence_id'] not in evidence_ids,qid
                evidence_ids.add(item['evidence_id'])
                doc=docs[did];text=doc['body_text']
                a,b=item['start_char'],item['end_char']
                assert type(a) is int and type(b) is int and 0<=a<b<=len(text),qid
                assert text[a:b]==item['quote'],qid+' quote/offset mismatch'
                assert hashlib.sha256(text.encode()).hexdigest()==item['document_body_sha256'],qid
                for key in ('title','url','published_at_utc'):assert item[key]==doc[key],qid
            if row['answerable']:
                assert row['required_facts'] and row['gold_evidence'] and not row['context_evidence'],qid
                assert row['no_answer_reason'] is None and row['unanswerability_audit'] is None,qid
                assert row['expected_status']=='ANSWERED',qid
                fact_ids=set()
                for fact in row['required_facts']:
                    assert fact['fact_id'] not in fact_ids and fact['text'].strip(),qid
                    fact_ids.add(fact['fact_id'])
                    assert fact['weight']==1 and fact['evidence_ids'],qid
                    assert set(fact['evidence_ids'])<=evidence_ids,qid
            else:
                assert not row['required_facts'] and not row['gold_evidence'],qid
                assert row['no_answer_reason'] and row['expected_status']=='INSUFFICIENT_SOURCES',qid
                audit=row['unanswerability_audit']
                assert audit['corpus_documents_scanned']==len(documents),qid
                assert set(c['document_id'] for c in audit['checked_documents'])==set(events[row['event_id']]['related_document_ids']),qid
                assert audit['missing_information'] and audit['absence_is_not_proven_by_search_failure'],qid
        counts[split]={'total':len(rows),'answerable':sum(r['answerable'] for r in rows),
                       'unanswerable':sum(not r['answerable'] for r in rows),'events':len({r['event_id'] for r in rows})}
        assert counts[split]==manifest['counts'][split],split+' count mismatch'
        all_rows+=rows
    assert {r['event_id'] for r in all_rows if r['split']=='dev'}.isdisjoint(
        {r['event_id'] for r in all_rows if r['split']=='holdout'})
    holdout=manifest['holdout']
    assert holdout['sealed'] and not any(holdout[k] for k in
        ('retrieval_executed','generation_executed','used_for_configuration_selection'))
    return {'status':'PASS','counts':counts,'source_quotes_checked':sum(len(r['gold_evidence'])+len(r['context_evidence']) for r in all_rows),
            'api_requests':0,'retrieval_requests':0,'human_review':'PENDING',
            'meaning':'Structural, provenance and source-span verification; not independent human or semantic validation.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--corpus',type=Path,default=ROOT/'.local-m4/m3_data/data/documents/documents.jsonl')
    args=parser.parse_args()
    print(json.dumps(validate_dataset(ROOT,args.corpus),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
