"""Deterministic source candidates with locations; never auto-adopt evidence."""
from datetime import date
from html.parser import HTMLParser
import io
import csv
import json
import re
from research_store import digest


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts=[]
        self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style','noscript'):
            self.skip+=1
        if tag in ('p','div','tr','h1','h2','h3','li','br') and not self.skip:
            self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','noscript') and self.skip:
            self.skip-=1
        if tag in ('td','th') and not self.skip:
            self.parts.append(' | ')
        if tag in ('p','div','tr','h1','h2','h3','li') and not self.skip:
            self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip:
            self.parts.append(data)


def segments(document):
    raw,mime = document['raw'],document['mime']
    if mime == 'text/csv':
        try:
            rows = list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))))
            if not rows:
                return [], ['empty:csv']
            header = rows[0]
            out = [{'location': 'row:1', 'text': ' | '.join(header)}]
            for number, row in enumerate(rows[1:], 2):
                if len(row) != len(header):
                    return [], ['parse_failed:csv_column_count']
                out.append({'location': 'row:' + str(number),
                            'text': ' | '.join(f'{h}: {v}' for h, v in zip(header, row))})
            return out, ['CSV candidates; verify codebook, units and missing-value definitions']
        except (UnicodeError, csv.Error):
            return [], ['parse_failed:csv']
    if mime=='application/pdf':
        try:
            from pypdf import PdfReader
        except ImportError:
            return [],['dependency_missing:pypdf']
        try:
            reader=PdfReader(io.BytesIO(raw))
            if len(reader.pages)>400:
                return [],['partial:page_limit']
            out=[{'location':'page:'+str(i+1),'text':page.extract_text() or ''} for i,page in enumerate(reader.pages)]
            warnings=['PDF text extraction; verify tables, charts, footnotes and reading order visually']
            if any(not x['text'].strip() for x in out):
                warnings.append('partial:empty_pages_require_visual_or_OCR_review')
            return out,warnings
        except Exception:
            return [],['parse_failed:pdf']
    if mime in ('text/html','application/xhtml+xml','text/plain'):
        try:
            text=raw.decode('utf-8-sig')
        except UnicodeError:
            return [],['unsupported:non_utf8_text']
        if mime!='text/plain':
            parser=HTMLText();parser.feed(text);text=''.join(parser.parts)
        lines=[re.sub(r'\s+',' ',x).strip() for x in text.splitlines() if x.strip()]
        return [{'location':'block:'+str(i+1),'text':s} for i,s in enumerate(lines)],['HTML/text extraction; navigation may remain; verify tables and embedded charts']
    return [],['unsupported:text_extraction']


def text_packet(document, terms, max_chars=16000, offset=0):
    if not isinstance(terms,list) or not terms or not all(isinstance(t,str) and t.strip() for t in terms):
        raise ValueError('Provide explicit search terms including counterevidence terms')
    if not 100 <= max_chars <= 50000 or offset<0:
        raise ValueError('Invalid query budget or offset')
    blocks,warnings=segments(document)
    terms=[t.casefold() for t in terms]
    selected=set()
    for i,b in enumerate(blocks):
        if any(t in b['text'].casefold() for t in terms):
            selected.update(range(max(0,i-1),min(len(blocks),i+2)))
    matches=[blocks[i] for i in sorted(selected)]
    out=[];used=0;next_offset=None
    for i in range(offset,len(matches)):
        b=matches[i]
        if used+len(b['text'])>max_chars:
            if not out:
                out.append(dict(b,text=b['text'][:max_chars],truncated=True,
                                continuation={'op':'read-document','location':b['location'],'char_offset':max_chars}))
                next_offset=i+1 if i+1<len(matches) else None
            else:
                next_offset=i
            break
        out.append(b);used+=len(b['text'])
    return {'document_id':document['id'],'source_url':document['url'],'sha256':document['sha256'],
            'segments':out,'total_matching_blocks':len(matches),'next_offset':next_offset,
            'warnings':warnings,'query_terms':terms,'scope':'retrieval candidates, not adopted evidence'}


def fact_candidates(document, taxonomy, tag, as_of):
    date.fromisoformat(as_of)
    if document['metadata'].get('adapter')!='sec_companyfacts':
        raise ValueError('Expected SEC companyfacts document')
    value=json.loads(document['raw'])
    concept=value.get('facts',{}).get(taxonomy,{}).get(tag)
    if concept is None:
        return []
    out=[]
    for unit,rows in concept.get('units',{}).items():
        for i,row in enumerate(rows):
            filed=row.get('filed')
            if not filed or filed>as_of:
                continue
            if isinstance(row.get('val'),bool) or not isinstance(row.get('val'),(int,float)):
                continue
            out.append({'document_id':document['id'],'taxonomy':taxonomy,'tag':tag,'unit':unit,
                        'label':concept.get('label'),'description':concept.get('description'),
                        'value':row['val'],'start':row.get('start'),'end':row.get('end'),
                        'filed':filed,'accession':row.get('accn'),'form':row.get('form'),
                        'fy':row.get('fy'),'fp':row.get('fp'),'frame':row.get('frame'),
                        'location':'/facts/'+taxonomy+'/'+tag+'/units/'+unit.replace('~','~0').replace('/','~1')+'/'+str(i),
                        'status':'candidate','warning':'All disclosed periods/vintages retained; do not sum YTD or infer segments/TTM automatically'})
    return out


def filings(document, as_of):
    date.fromisoformat(as_of)
    value=json.loads(document['raw'])
    recent=value['filings']['recent']
    keys=['accessionNumber','filingDate','form','primaryDocument']
    lengths={len(recent[k]) for k in keys}
    if len(lengths)!=1:
        raise ValueError('Mismatched SEC column arrays')
    rows=[]
    for i in range(next(iter(lengths))):
        row={k:recent[k][i] for k in keys}
        if row['filingDate']<=as_of:
            row['url']='https://www.sec.gov/Archives/edgar/data/'+str(int(value['cik']))+'/'+row['accessionNumber'].replace('-','')+'/'+row['primaryDocument']
            row['location']='/filings/recent/accessionNumber/'+str(i)
            row['locations']={k:'/filings/recent/'+k+'/'+str(i) for k in keys}
            rows.append(row)
    return {'rows':rows,'older_files':value['filings'].get('files',[]),
            'warning':'Recent listing only; older files are explicit remaining discovery work'}


def locate(document, location):
    if location.startswith('/'):
        value=json.loads(document['raw'])
        for token in location[1:].split('/'):
            token=token.replace('~1','/').replace('~0','~')
            if isinstance(value,list):
                if not token.isdigit():
                    raise ValueError('Invalid index')
                value=value[int(token)]
            else:
                value=value[token]
        return json.dumps(value,ensure_ascii=False,sort_keys=True)
    blocks,_=segments(document)
    for block in blocks:
        if block['location']==location:
            return block['text']
    raise ValueError('Source location not found')
