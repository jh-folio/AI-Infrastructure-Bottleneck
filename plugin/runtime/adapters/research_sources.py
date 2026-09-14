"""Bounded public acquisition; preserve source bytes and explicit failure states."""
from datetime import date
import importlib.util
import io
import ipaddress
import json
import math
import os
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

LIMIT = 24 * 1024 * 1024
_SEC_LAST = 0.0


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def public_url(url, hosts, resolve=True):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username
            or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None,443)):
        raise ValueError('Expected registered public HTTPS host without credentials or query')
    if resolve:
        for address in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(address[4][0]).is_global:
                raise ValueError('Nonpublic destination')
    return parsed


def fetch(store, url, producer, kind, published_at=None, opener=None):
    hosts = {'data.sec.gov', 'www.sec.gov'} if kind.startswith('sec_') else set(store.config.get('ir_hosts', []))
    public_url(url, hosts, resolve=False)
    if kind not in ('sec_submissions', 'sec_companyfacts', 'ir'):
        raise ValueError('Unsupported source kind')
    if published_at:
        date.fromisoformat(published_at)
    source = {'url': url, 'producer': producer}
    metadata = {'adapter': kind, 'parser_version': '1.0', 'published_at': published_at}
    agent = os.environ.get('SEC_USER_AGENT') if kind.startswith('sec_') else 'AI-Bottleneck-Research/0.2'
    if not agent:
        return store.capture(source, None, '', metadata, 'configuration_required', {'reason':'SEC_USER_AGENT required'})
    try:
        if opener is None:
            public_url(url,hosts)
            if kind.startswith('sec_'):
                global _SEC_LAST
                time.sleep(max(0,0.2-(time.monotonic()-_SEC_LAST)))
                _SEC_LAST=time.monotonic()
        req = Request(url, headers={'User-Agent':agent,'Accept':'application/json' if kind.startswith('sec_') else 'text/html,application/pdf'})
        with (opener or build_opener(NoRedirect()).open)(req, timeout=30) as response:
            if response.geturl() != url:
                raise ValueError('redirect_not_supported')
            mime = response.headers.get('Content-Type','').split(';')[0].strip().lower()
            raw = response.read(LIMIT+1)
            if not raw or len(raw)>LIMIT:
                return store.capture(source,None,mime,metadata,'partial',{'reason':'empty_or_oversize'})
            if kind.startswith('sec_'):
                value = json.loads(raw, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('nonfinite')))
                if mime != 'application/json' or not isinstance(value,dict) or not value.get('cik'):
                    raise ValueError('invalid_SEC_document')
                if kind == 'sec_submissions' and not isinstance(value.get('filings'),dict):
                    raise ValueError('missing_filings')
                if kind == 'sec_companyfacts' and not isinstance(value.get('facts'),dict):
                    raise ValueError('missing_facts')
            elif mime == 'application/pdf':
                if not raw.startswith(b'%PDF-'):
                    raise ValueError('invalid_pdf')
            elif mime not in ('text/html','application/xhtml+xml','text/plain'):
                raise ValueError('unsupported_content_type')
            return store.capture(source,raw,mime,metadata,detail={'http_status':response.status})
    except HTTPError as exc:
        status = {401:'auth_required',403:'forbidden',404:'not_found',429:'rate_limited'}.get(exc.code,'http_error')
        code = exc.code
        exc.close()
        return store.capture(source,None,'',metadata,status,{'http_status':code})
    except (URLError,TimeoutError,OSError):
        return store.capture(source,None,'',metadata,'network_error',{'reason':'network_request_failed'})
    except (ValueError,UnicodeError):
        return store.capture(source,None,'',metadata,'parse_failed',{'reason':'unexpected_or_invalid_response'})


def sec(store, cik, dataset, opener=None):
    cik = str(cik)
    if not re.fullmatch(r'\d{1,10}',cik) or int(cik)==0:
        raise ValueError('CIK must be a positive 1-10 digit identifier')
    paths = {'submissions':'submissions/', 'companyfacts':'api/xbrl/companyfacts/'}
    url = 'https://data.sec.gov/'+paths[dataset]+'CIK'+cik.zfill(10)+'.json'
    return fetch(store,url,'SEC / issuer CIK'+cik.zfill(10),'sec_'+dataset,opener=opener)


def prices(store, ticker, start, end, factory=None):
    if not re.fullmatch(r'[A-Za-z0-9.^=_-]{1,24}',ticker):
        raise ValueError('Invalid ticker')
    if date.fromisoformat(start) >= date.fromisoformat(end):
        raise ValueError('Price interval must be start < end (exclusive)')
    source = {'url':'https://finance.yahoo.com/quote/'+ticker+'/', 'producer':'Yahoo Finance'}
    metadata = {'adapter':'yfinance','start':start,'end_exclusive':end,'ticker':ticker,
                'auto_adjust':False,'actions':True,'repair':False,'parser_version':'1.0',
                'warning':'Current vendor history; not guaranteed historical vintage. Close may reflect split normalization; do not derive share-based valuation without review.'}
    if factory is None:
        try:
            import yfinance as yf
        except ImportError:
            return store.capture(source,None,'',metadata,'dependency_missing',{'dependency':'yfinance'})
        factory= yf.Ticker
        metadata['library_version'] = yf.__version__
    try:
        obj=factory(ticker)
        frame=obj.history(start=start,end=end,auto_adjust=False,actions=True,repair=False,raise_errors=True,timeout=20)
        meta=obj.get_history_metadata()
        if frame.empty:
            return store.capture(source,None,'',metadata,'empty',{'reason':'No price rows; not zero'})
        rows=[]
        for timestamp,row in frame.iterrows():
            entry={'date':timestamp.isoformat()}
            for column,value in row.items():
                numeric=float(value)
                entry[str(column)] = numeric if math.isfinite(numeric) else None
            rows.append(entry)
        metadata['currency']=meta.get('currency')
        metadata['exchange_timezone']=meta.get('exchangeTimezoneName')
        data={'rows':rows,'metadata':metadata}
        raw=json.dumps(data,sort_keys=True,allow_nan=False).encode()
        if len(raw)>LIMIT:
            return store.capture(source,None,'',metadata,'partial',{'reason':'oversize_price_response'})
        return store.capture(source,raw,'application/json',metadata,
                             'success' if metadata['currency'] and metadata['exchange_timezone'] else 'partial',
                             {'representation':'yfinance-returned rows; not raw HTTP bytes'})
    except Exception:
        return store.capture(source,None,'',metadata,'provider_error',{'reason':'Price provider failed; no retry or zero fill'})


def capabilities():
    return {'python':True,'sqlite':True,'SEC_USER_AGENT_configured':bool(os.environ.get('SEC_USER_AGENT')),
            'yfinance':importlib.util.find_spec('yfinance') is not None,
            'pypdf':importlib.util.find_spec('pypdf') is not None,
            'work_storage':'must verify in target environment','deep_research':'host tool required',
            'scheduled_execution':'host registration and execution verification required',
            'monitoring':'checkpointed source collection; judgments require review',
            'interactive_dashboard':'standalone HTML export; Work rendering verification required',
            'deep_research_handoff':'stored inputs and returned artifacts; host execution required'}
