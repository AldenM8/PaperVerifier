import csv
import io
import json
from dataclasses import replace
from pathlib import Path
import pytest
import requests
from verifier import *

@pytest.fixture
def c():
    return crossref_record(json.loads(Path('data/offline_records.json').read_text(encoding='utf-8'))[0])

@pytest.fixture
def ref(c):
    return Reference(c.title,'; '.join(c.authors),c.year,c.venue,c.doi)

def test_exact(c,ref):
    assert verify(ref,[c])['判定']=='書目一致'
    assert '正式發表' in verify(ref,[c])['發表類型']

@pytest.mark.parametrize('change',[
 {'authors':'Chen, M. L.; Wang, D.'}, {'authors':'Wang, David; Chen, Mei Ling'},
 {'authors':'Chen, Mei Ling'}, {'authors':'Chen, Mei Ling; et al.'}, {'year':'2023'},
 {'venue':'SMJ'}, {'doi':'10.0000/wrong'}, {'authors':''}, {'year':''}, {'venue':''},
 {'authors':'Chen, Mei; Wang, David'}, {'title':'Conservative verification of synthetic reference'}])
def test_conservative(c,ref,change):
    assert verify(replace(ref,**change),[c])['判定']!='書目一致'

def test_initials(c):
    assert author_check('Chen, M. L.; Wang, D.',c)=='縮寫相容（待確認）'
    assert name_match('Mei Ling Chen','Chen, Mei Ling')=='一致'
    assert name_match('John Smith','Jane Smith')=='不一致'
    assert name_match('Smith','Smith, John')=='不一致'

def test_no_results(ref):
    r=verify(ref,[])
    assert r['判定']=='無法確認'
    assert '不代表' in r['說明'][0]

def test_errors(c,ref):
    assert verify(ref,[c],['Crossref: HTTP 429'])['判定']=='需人工確認'

def test_wrong_doi_candidate(c,ref):
    assert verify(replace(ref,title='Completely unrelated work'),[c])['判定']!='書目一致'

def test_conflict(c,ref):
    other=replace(c,source='OpenAlex',year='2023',record_url='https://openalex.org/W1')
    result=verify(ref,[c,other])
    assert result['判定']=='需人工確認'
    assert any('年份' in note and 'Crossref' in note and 'OpenAlex' in note and '2023' in note for note in result['說明'])
    assert '正式發表紀錄' in result['發表類型']

def test_ambiguity(c,ref):
    assert verify(ref,[c,replace(c,doi='10.0000/version2')])['發表類型']=='無法確認'

def test_preprint(c,ref):
    assert '預印本' in verify(ref,[replace(c,kind='posted-content')])['發表類型']
    assert publication(replace(c,kind='dataset'))=='無法確認'

def test_truncated(c,ref):
    assert verify(ref,[replace(c,complete_authors=False)])['判定']=='需人工確認'

def test_parse():
    r=parse_reference('Chen, Mei Ling; Wang, David (2024). A title. A journal. https://doi.org/10.0000/test')
    assert r.title=='A title' and r.doi=='10.0000/test' and r.parse_note
    assert parse_reference('unknown format').parse_note

def test_export(c,ref):
    r=verify(replace(ref,title='=HYPERLINK("evil")'),[c])
    data=csv_export([r])
    assert data.startswith(b'\xef\xbb\xbf')
    row=next(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
    assert row['輸入標題'].startswith("'")
    assert json.loads(row['候選資料JSON'])[0]['作者']==c.authors

def test_25_batch():
    candidates=[crossref_record(x) for x in json.loads(Path('data/offline_records.json').read_text(encoding='utf-8'))]
    with open('data/sample_25.csv',encoding='utf-8-sig') as f:
        results=[verify(Reference(**x),candidates) for x in csv.DictReader(f)]
    assert len(results)==25
    assert results[0]['判定']=='書目一致'
    assert results[1]['判定']=='需人工確認'
    assert results[-1]['判定']=='無法確認'

class Response:
    def __init__(self,status,data=None): self.status_code,self.data=status,data
    def json(self): return self.data

def test_http_error_and_cache(monkeypatch):
    client=Client(api_key='secret')
    calls=[]
    def get(*a,**kw): calls.append(kw); return Response(403)
    monkeypatch.setattr(client.session,'get',get)
    assert '403' in client.get('https://api.openalex.org/works',source='OpenAlex')[1]
    client.get('https://api.openalex.org/works',source='OpenAlex')
    assert len(calls)==1 and calls[0]['headers']['Authorization']=='Bearer secret'
    assert 'secret' not in str(client.cache)

def test_timeout(monkeypatch):
    client=Client()
    def get(*a,**kw): raise requests.Timeout('secret')
    monkeypatch.setattr(client.session,'get',get)
    assert 'secret' not in client.get('https://api.crossref.org/works',source='Crossref')[1]

def test_openalex_full_fetch(monkeypatch):
    client=Client()
    calls=[]
    work={'id':'https://openalex.org/W1','display_name':'Example','authorships':[{'author':{'display_name':'Alex Chen'}}],'authors_count':2}
    def get(url,params=None,source=''):
        calls.append(url)
        if source=='Crossref': return {'message':{'items':[]}},''
        if url.endswith('/W1'): return work,''
        return {'results':[work]},''
    monkeypatch.setattr(client,'get',get)
    candidates,errors=client.search(Reference(title='Example'))
    assert 'https://api.openalex.org/works/W1' in calls
    assert not candidates[0].complete_authors

def test_ui(monkeypatch, c):
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_file(Path('app.py').resolve(), default_timeout=15).run()
    assert not at.exception
    assert not any('class="result-guide"' in item.value for item in at.markdown)
    at.text_input(key='manual_title').input(c.title)
    at.text_input(key='manual_author_0').input('; '.join(c.authors))
    at.text_input(key='manual_year').input(c.year)
    at.text_input(key='manual_venue').input(c.venue)
    at.text_input(key='manual_doi').input(c.doi)
    next(b for b in at.button if b.label=='加入清單').click().run()
    assert not at.exception
    monkeypatch.setattr(Client, 'check_connection', lambda self: [{'來源':s, '連線成功':True, '訊息':'API 回應正常'} for s in ['Crossref','OpenAlex']])
    monkeypatch.setattr(Client, 'search', lambda self, ref: ([c, replace(c, title='Other study', doi='10.0000/other', authors=['Someone, Else'])], []))
    next(b for b in at.button if b.label=='驗證').click().run()
    assert not at.exception
    assert at.session_state['results'][0]['判定']=='書目一致'
    guide = next(item.value for item in at.markdown if 'class="result-guide"' in item.value)
    assert all(tone in guide for tone in ['guide-green','guide-amber','guide-blue'])
    assert not at.get('download_button')
    assert not at.get('json')
    assert not any('資料來源' in link.label for link in at.get('link_button'))
    original = next(item.value for item in at.markdown if 'result-link' in item.value and 'href=' in item.value)
    assert 'href="https://doi.org/10.0000/demo-only"' in original
    assert 'pill green result-link' in original
    at.selectbox[0].select(1).run()
    assert not at.exception
    assert any('Other study' in element.value for element in at.markdown)


def test_significant_title_symbols(c,ref):
    other=replace(c,title='C++ for science')
    assert verify(replace(ref,title='C for science'),[other])['判定']!='書目一致'

def test_unrelated_same_title_not_ambiguous(c,ref):
    other=replace(c,doi='10.0000/unrelated',authors=['Different, Someone'])
    assert verify(ref,[c,other])['判定']=='書目一致'

def test_invalid_payload(monkeypatch):
    client=Client()
    monkeypatch.setattr(client.session,'get',lambda *a,**kw:Response(200,[]))
    data,error=client.get('https://api.crossref.org/works',source='Crossref')
    assert data is None and error

def test_malformed_record(monkeypatch):
    client=Client()
    monkeypatch.setattr(client,'get',lambda *a,**kw:({'message':{'items':[None]},'results':[None]},''))
    candidates,errors=client.search(Reference(title='Example'))
    assert not candidates and errors

def test_no_candidate_with_errors_is_query_failure(ref):
    result = verify(ref, [], ['Crossref: 連線失敗', 'OpenAlex: 連線失敗'])
    assert result['判定'] == '查詢失敗／未完成'
    assert '未找到' not in '；'.join(result['說明'])
    exported = next(csv.DictReader(io.StringIO(csv_export([result]).decode('utf-8-sig'))))
    assert exported['判定'] == '查詢失敗／未完成'

def test_unrelated_candidates_with_failed_source(ref,c):
    result = verify(ref, [replace(c,title='Wholly unrelated study',doi='10.0000/other')], ['OpenAlex: HTTP 403'])
    assert result['判定'] == '查詢失敗／未完成'

@pytest.mark.parametrize('exception,fragment', [
    (requests.exceptions.ConnectionError('[WinError 10013] secret'), '10013'),
    (requests.exceptions.SSLError('secret'), 'TLS'),
    (requests.exceptions.Timeout('secret'), '逾時'),
    (requests.exceptions.ConnectionError('secret'), '無法建立連線'),
])
def test_diagnostic_without_secret(monkeypatch,exception,fragment):
    client = Client()
    def get(*a,**kw): raise exception
    monkeypatch.setattr(client.session,'get',get)
    data,error = client.get('https://api.crossref.org/works',source='Crossref')
    assert data is None and fragment in error and 'secret' not in error

def test_preflight_both_sources(monkeypatch):
    client = Client()
    def get(url,params=None,source=''):
        return ({'message':{'items':[]}},'') if source=='Crossref' else (None,'OpenAlex: HTTP 403')
    monkeypatch.setattr(client,'get',get)
    checks = client.check_connection()
    assert checks[0]['連線成功'] and not checks[1]['連線成功']

def test_ui_stops_before_batch_on_connection_failure(monkeypatch):
    from streamlit.testing.v1 import AppTest
    monkeypatch.setattr(Client,'check_connection', lambda self: [
        {'來源':s,'連線成功':False,'訊息':'WinError 10013'} for s in ['Crossref','OpenAlex']])
    def search(*a,**kw): raise AssertionError('Batch must not start')
    monkeypatch.setattr(Client,'search',search)
    at = AppTest.from_file(Path('app.py').resolve(), default_timeout=15).run()
    at.text_input(key='manual_title').input('Example')
    next(b for b in at.button if b.label=='加入清單').click().run()
    next(b for b in at.button if b.label=='驗證').click().run()
    assert not at.exception
    assert any('批次未開始' in e.value for e in at.error)
    with pytest.raises(KeyError):
        at.session_state['results']

def test_thirty_failed_queries(ref):
    results = [verify(ref,[],['Crossref: 連線失敗','OpenAlex: 連線失敗']) for _ in range(30)]
    assert all(r['判定']=='查詢失敗／未完成' for r in results)

@pytest.mark.parametrize('content_type,fragment', [('text/html','HTML'),('application/json','有效 JSON')])
def test_non_json_response_diagnostic(monkeypatch,content_type,fragment):
    client=Client()
    class NonJSON:
        status_code=200
        headers={'Content-Type':content_type}
        def json(self): raise ValueError('secret response body')
    monkeypatch.setattr(client.session,'get',lambda *a,**kw:NonJSON())
    data,error=client.get('https://api.openalex.org/works',source='OpenAlex')
    assert data is None and fragment in error and 'InvalidJSON' in error and 'secret' not in error

@pytest.mark.parametrize('exc,code', [
    (requests.exceptions.ContentDecodingError('secret'),'ContentDecodingError'),
    (requests.exceptions.ChunkedEncodingError('secret'),'ChunkedEncodingError'),
    (requests.exceptions.InvalidHeader('secret'),'InvalidHeader'),
    (requests.exceptions.TooManyRedirects('secret'),'TooManyRedirects'),
])
def test_transport_error_diagnostic(monkeypatch,exc,code):
    client=Client()
    def get(*a,**kw): raise exc
    monkeypatch.setattr(client.session,'get',get)
    data,error=client.get('https://api.openalex.org/works',source='OpenAlex')
    assert data is None and code in error and 'secret' not in error
    assert client.session.headers['Accept']=='application/json'
    assert client.session.headers['Accept-Encoding']=='gzip, deflate'

@pytest.mark.parametrize('status,description',[(429,'請求受限'),(503,'服務暫時無法使用')])
def test_retry_exhaustion_preserves_http_status(monkeypatch,status,description):
    # 使用真正的 requests/urllib3 重試流程，以模擬 HTTP 回應取代外部網路。
    from urllib3.response import HTTPResponse
    from urllib3.connectionpool import HTTPConnectionPool
    calls=[]
    def respond(*a,**kw):
        calls.append(1)
        return HTTPResponse(body=io.BytesIO(b'{}'),status=status,
                            headers={'Content-Type':'application/json'},preload_content=False)
    monkeypatch.setattr(HTTPConnectionPool,'_make_request',respond)
    client=Client()
    client.session.trust_env=False
    data,error=client.get('https://api.openalex.org/works',source='OpenAlex')
    assert data is None and f'HTTP {status}' in error and description in error
    assert 'RetryError' not in error and len(calls)==3

@pytest.mark.parametrize('status',[429,503])
def test_wrapped_retry_error_is_unpacked(monkeypatch,status):
    from urllib3.exceptions import MaxRetryError, ResponseError
    exc=requests.exceptions.RetryError(MaxRetryError(None,'https://secret',ResponseError(f'too many {status} error responses')))
    client=Client()
    def get(*a,**kw): raise exc
    monkeypatch.setattr(client.session,'get',get)
    data,error=client.get('https://api.openalex.org/works',source='OpenAlex')
    assert data is None and f'HTTP {status}' in error and '診斷 R3' in error
    assert 'secret' not in error and 'RetryError' not in error

def test_retry_unknown_reason_does_not_guess(monkeypatch):
    client=Client()
    def get(*a,**kw): raise requests.exceptions.RetryError('secret')
    monkeypatch.setattr(client.session,'get',get)
    data,error=client.get('https://api.openalex.org/works',source='OpenAlex')
    assert data is None and '未取得 HTTP 狀態' in error and '診斷 R3' in error
    assert 'secret' not in error

def test_key_registration_saves_without_exposing_secret(monkeypatch,tmp_path,capsys):
    import register_openalex as registration
    import sys
    target=tmp_path/'private'/'openalex-key.json'
    monkeypatch.setattr(registration,'KEY_FILE',target)
    monkeypatch.setattr(sys,'argv',['register_openalex.py','--email','owner@example.org'])
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        return Response(201,{'api_key':'private-key','status':'pending_activation','daily_budget_usd_after_activation':1})
    monkeypatch.setattr(registration.requests,'post',post)
    registration.main()
    assert json.loads(target.read_text())['api_key']=='private-key'
    assert 'private-key' not in capsys.readouterr().out
    assert calls[0][1]['json']['email']=='owner@example.org'
    registration.main()
    assert len(calls)==1

def test_manual_boxes_append_and_preserve_author_order():
    from streamlit.testing.v1 import AppTest
    at=AppTest.from_file(Path('app.py').resolve(),default_timeout=15).run()
    assert [tab.label for tab in at.tabs]==['輸入文字','上傳 CSV']
    at.text_input(key='manual_title').input('First paper')
    at.text_input(key='manual_author_0').input('Alex Chen')
    next(b for b in at.button if b.label=='＋新增作者').click().run()
    assert at.text_input(key='manual_author_0').value=='Alex Chen'
    at.text_input(key='manual_author_1').input('Blair Wang')
    at.text_input(key='manual_year').input('2020')
    next(b for b in at.button if b.label=='加入清單').click().run()
    assert not at.exception
    assert at.session_state['rows'][0]['authors']=='Alex Chen; Blair Wang'
    assert at.text_input(key='manual_title').value==''
    at.text_input(key='manual_title').input('Second paper')
    next(b for b in at.button if b.label=='加入清單').click().run()
    assert len(at.session_state['rows'])==2
    next(b for b in at.button if b.label=='加入清單').click().run()
    assert len(at.session_state['rows'])==2
    assert any('請填寫論文標題' in e.value for e in at.error)

def test_swipe_events_edit_delete_and_ignore_stale_actions(monkeypatch):
    from streamlit.testing.v1 import AppTest
    import swipe_list as swipe
    event = {'value': None}
    monkeypatch.setattr(swipe, '_component', lambda **kwargs: event['value'])
    at=AppTest.from_file(Path('app.py').resolve(),default_timeout=15).run()
    at.session_state['rows']=[vars(Reference(title='Remove me')),vars(Reference(title='Keep me'))]
    at.run()
    fields={'title':'Edited survivor','authors':'Chen, Alex','year':'2020','venue':'Journal','doi':''}
    event['value']={'revision':swipe.revision(at.session_state['rows']),'action':'edit','index':1,'fields':fields}
    at.run()
    assert not at.exception
    assert at.session_state['rows'][1]['title']=='Edited survivor'
    event['value']={'revision':swipe.revision(at.session_state['rows']),'action':'delete','index':0}
    at.run()
    assert [r['title'] for r in at.session_state['rows']]==['Edited survivor']
    # Streamlit 重跑時同一事件不可再次刪除下一篇。
    at.run()
    assert len(at.session_state['rows'])==1
    event['value']={'revision':swipe.revision(at.session_state['rows']),'action':'delete','index':0}
    at.run()
    assert not at.exception and at.session_state['rows']==[]
    assert next(b for b in at.button if b.label=='驗證').disabled
    assert not any(b.label=='刪除選取文獻' for b in at.button)

def test_cloud_settings_uses_env_then_secrets(monkeypatch):
    import cloud_settings
    monkeypatch.setenv('OPENALEX_API_KEY','environment-key')
    monkeypatch.setattr(cloud_settings.st,'secrets',{'OPENALEX_API_KEY':'cloud-key'})
    assert cloud_settings.cloud_setting('OPENALEX_API_KEY')=='environment-key'
    monkeypatch.delenv('OPENALEX_API_KEY')
    assert cloud_settings.cloud_setting('OPENALEX_API_KEY')=='cloud-key'
    assert cloud_settings.cloud_setting('MISSING_SETTING')==''

def test_cloud_settings_without_secret_file(monkeypatch):
    import cloud_settings
    class NoSecrets:
        def get(self,*a): raise FileNotFoundError()
    monkeypatch.delenv('OPENALEX_API_KEY',raising=False)
    monkeypatch.setattr(cloud_settings.st,'secrets',NoSecrets())
    assert cloud_settings.cloud_setting('OPENALEX_API_KEY')==''
