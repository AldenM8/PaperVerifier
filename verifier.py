from __future__ import annotations
import csv
import io
import re
import unicodedata
from pathlib import Path

API_DIAGNOSTIC_VERSION = 3
_LOADED_MTIME = Path(__file__).stat().st_mtime_ns
from dataclasses import dataclass, asdict, field
from difflib import SequenceMatcher
from urllib.parse import quote, urlencode
from datetime import datetime, timezone
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def norm(s):
    s = ''.join(c for c in unicodedata.normalize('NFKD', str(s)).casefold() if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+|[+#=<>/]', s))


def doi_norm(s):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)', '', str(s).strip(), flags=re.I).strip().casefold()


@dataclass
class Reference:
    title: str = ''
    authors: str = ''  # 使用分號分隔，保留順序
    year: str = ''
    venue: str = ''
    doi: str = ''
    raw: str = ''
    parse_note: str = ''


def parse_reference(line):
    """只解析明確的作者 (年份). 標題. 期刊格式；不猜測複雜格式。"""
    d = re.search(r'10\.\d{4,9}/[^\s]+', line, re.I)
    doi = d.group(0).rstrip('.,;') if d else ''
    body = re.sub(r'https?://(?:dx\.)?doi\.org/\S+|doi:\s*10\.\S+|10\.\d{4,9}/\S+', '', line, flags=re.I).strip()
    m = re.match(r'^(.+?)\s*\((\d{4})[a-z]?\)\.?\s+(.+)$', body)
    if not m:
        return Reference(doi=doi, raw=line, parse_note='無法可靠解析；請填入標題、分號分隔的全部作者、年份與刊物。')
    tail = m[3].split('. ', 1)
    # APA 姓氏、名字縮寫可能含逗號；避免以逗號盲目切作者。
    authors = m[1].strip().rstrip('.')
    note = '請確認作者以分號分隔，並核對標題／刊物切分。'
    return Reference(tail[0].strip().rstrip('.'), authors, m[2], tail[1].strip().rstrip('.') if len(tail)>1 else '', doi, line, note)


@dataclass
class Candidate:
    source: str
    title: str
    authors: list[str]
    year: str
    venue: str
    doi: str
    kind: str
    url: str
    record_url: str
    complete_authors: bool = True
    raw: dict = field(default_factory=dict)


def crossref_record(x):
    def first(key):
        return (x.get(key) or [''])[0]
    date = x.get('published') or x.get('published-print') or x.get('published-online') or {}
    parts = date.get('date-parts') or [[]]
    return Candidate('Crossref', first('title'),
        [a.get('name') or ', '.join(filter(None, [a.get('family'), a.get('given')])) for a in x.get('author', [])],
        str(parts[0][0]) if parts[0] else '', first('container-title'), doi_norm(x.get('DOI', '')),
        x.get('type', ''), x.get('resource', {}).get('primary', {}).get('URL') or x.get('URL', ''),
        'https://api.crossref.org/works/' + quote(x.get('DOI', ''), safe=''), raw=x)


def openalex_record(x):
    loc = x.get('primary_location') or {}
    source = loc.get('source') or {}
    authorships = x.get('authorships') or []
    return Candidate('OpenAlex', x.get('display_name') or '',
        [a.get('raw_author_name') or (a.get('author') or {}).get('display_name', '') for a in authorships],
        str(x.get('publication_year') or ''), source.get('display_name') or '', doi_norm(x.get('doi') or ''),
        x.get('type', ''), loc.get('landing_page_url') or '', x.get('id') or '',
        not x.get('is_authors_truncated', False) and (x.get('authors_count') is None or x['authors_count'] == len(authorships)), raw=x)


class Client:
    def __init__(self, email='', api_key=''):
        self.email, self.api_key = email, api_key
        self.session = requests.Session()
        retry = Retry(total=2, backoff_factor=0.5, status_forcelist=[429,500,502,503,504], allowed_methods=['GET'], respect_retry_after_header=False, raise_on_status=False)
        self.session.mount('https://', HTTPAdapter(max_retries=retry))
        self.session.headers.update({'Accept': 'application/json', 'Accept-Encoding': 'gzip, deflate'})
        self.session.headers['User-Agent'] = 'PaperVerifier/0.1' + (f' (mailto:{email})' if email else '')
        self.cache = {}

    def get(self, url, params=None, source=''):
        key = (url, tuple(sorted((params or {}).items())))
        if key in self.cache:
            return self.cache[key]
        headers = {'Authorization': f'Bearer {self.api_key}'} if source == 'OpenAlex' and self.api_key else {}
        try:
            response = self.session.get(url, params=params, headers=headers, timeout=(5,20))
            if response.status_code == 404:
                result = (None, '')
            elif response.status_code != 200:
                hints = {401:'需要有效的存取認證', 403:'存取被拒絕，可能為權限或服務政策限制',
                         429:'請求受限，可能達到速率或額度上限',
                         500:'來源伺服器發生錯誤', 502:'來源閘道暫時異常',
                         503:'來源服務暫時無法使用', 504:'來源閘道逾時'}
                hint = hints.get(response.status_code, '來源未成功回應')
                result = (None, f'{source}: HTTP {response.status_code}，{hint}；來源查詢未完成')
            else:
                try:
                    data = response.json()
                    result = (data, '') if isinstance(data, dict) else (None, f'{source}: JSON 頂層不是物件（代碼：JSONShape），來源查詢未完成')
                except ValueError:
                    content_type = str(getattr(response, 'headers', {}).get('Content-Type', '')).lower()
                    detail = '收到 HTML 網頁，未收到 API JSON 資料' if 'html' in content_type else '回應不是有效 JSON 資料'
                    result = (None, f'{source}: HTTP 200，但{detail}（代碼：InvalidJSON），請稍後重試')
        except requests.exceptions.RetryError as exc:
            # 讀取 requests -> urllib3 包裝原因，只輸出白名單狀態碼，不洩漏 URL 或憑證。
            pending, seen, status = [exc], set(), None
            while pending and len(seen) < 12:
                item = pending.pop()
                if id(item) in seen:
                    continue
                seen.add(id(item))
                match = re.search(r'too many (429|500|502|503|504) error responses', str(item), re.I)
                if match:
                    status = match[1]
                    break
                pending.extend(x for x in getattr(item, 'args', ()) if isinstance(x, BaseException))
                pending.extend(x for x in [getattr(item, 'reason', None), getattr(item, '__cause__', None)] if isinstance(x, BaseException))
            if status:
                hint = '速率或額度受限' if status == '429' else '來源服務暫時異常'
                result = (None, f'{source}: HTTP {status}，{hint}，重試後仍失敗（診斷 R3）')
            else:
                result = (None, f'{source}: 重試已耗盡，但未取得 HTTP 狀態；可能由連線或傳輸層中斷，原因尚未確認（診斷 R3）')
        except requests.exceptions.SSLError:
            result = (None, f'{source}: TLS 憑證驗證失敗，來源查詢未完成')
        except requests.exceptions.Timeout:
            result = (None, f'{source}: 連線或讀取逾時，來源查詢未完成')
        except requests.exceptions.ConnectionError as exc:
            reason = '網路存取被執行環境或安全設定拒絕（WinError 10013）' if '10013' in str(exc) else '無法建立連線（請檢查網路、代理或防火牆）'
            result = (None, f'{source}: {reason}，來源查詢未完成')
        except requests.exceptions.ContentDecodingError:
            result = (None, f'{source}: 回應解壓縮失敗（代碼：ContentDecodingError），請稍後重試')
        except requests.exceptions.ChunkedEncodingError:
            result = (None, f'{source}: 回應傳輸中斷（代碼：ChunkedEncodingError），請稍後重試')
        except requests.exceptions.TooManyRedirects:
            result = (None, f'{source}: 重新導向次數過多（代碼：TooManyRedirects），來源查詢未完成')
        except (requests.RequestException, ValueError) as exc:
            # 僅顯示例外類別，不顯示可能含信箱、金鑰的例外內容或回應內文。
            result = (None, f'{source}: 請求未完成（代碼：{type(exc).__name__}），請重新測試連線')
        self.cache[key] = result
        return result

    def check_connection(self):
        """在相同服務程序內測試兩個 API；失敗不作書目結論。"""
        checks = []
        for source, url, params in [
            ('Crossref', 'https://api.crossref.org/works', {'rows': 1}),
            ('OpenAlex', 'https://api.openalex.org/works', {'per_page': 1}),
        ]:
            data, error = self.get(url, params, source)
            payload = data.get('message') if isinstance(data, dict) else None
            valid = (isinstance(payload, dict) and isinstance(payload.get('items'), list) if source == 'Crossref'
                     else isinstance(data, dict) and isinstance(data.get('results'), list))
            checks.append({'來源': source, '連線成功': bool(valid and not error),
                           '訊息': error or ('API 回應正常' if valid else '測試查詢未取得有效資料')})
        return checks

    def search(self, ref):
        candidates, errors = [], []
        doi = doi_norm(ref.doi)
        for source in ['Crossref', 'OpenAlex']:
            if doi:
                url = ('https://api.crossref.org/works/' + quote(doi, safe='') if source=='Crossref'
                       else 'https://api.openalex.org/works/https://doi.org/' + quote(doi, safe=''))
                data, err = self.get(url, source=source)
                if err: errors.append(err)
                if data:
                    try:
                        candidates.append(crossref_record(data['message']) if source=='Crossref' else openalex_record(data))
                    except (KeyError, TypeError, IndexError, AttributeError, ValueError): errors.append(source + ': 中繼資料格式不完整')
            if ref.title:
                params = ({'query.bibliographic': ref.title + ' ' + ref.authors + ' ' + ref.year, 'rows':5}
                          if source=='Crossref' else {'search':ref.title, 'per_page':5})
                if source=='Crossref' and self.email: params['mailto'] = self.email
                data, err = self.get('https://api.crossref.org/works' if source=='Crossref' else 'https://api.openalex.org/works', params, source)
                if err: errors.append(err)
                if data:
                    try:
                        items = data['message']['items'] if source=='Crossref' else data['results']
                        for item in items:
                            if source=='OpenAlex':
                                # 搜尋列表可能截斷作者，改取完整 work。
                                wid = (item.get('id') or '').rsplit('/',1)[-1]
                                if not re.fullmatch(r'W\d+', wid): continue
                                full, e = self.get('https://api.openalex.org/works/'+wid, source=source)
                                if e: errors.append(e)
                                if not full: continue
                                item = full
                            candidates.append(crossref_record(item) if source=='Crossref' else openalex_record(item))
                    except (KeyError, TypeError, IndexError, AttributeError, ValueError): errors.append(source + ': 中繼資料格式不完整')
        unique = {(c.source, c.record_url):c for c in candidates}
        return list(unique.values()), sorted(set(errors))


def name_parts(name):
    if ',' in name:
        family, given = name.split(',',1)
        return norm(family), norm(given).split()
    words = norm(name).split()
    return (words[-1], words[:-1]) if words else ('', [])


def name_match(a, b):
    if norm(a) == norm(b) and norm(a): return '一致'
    fa, ga = name_parts(a)
    fb, gb = name_parts(b)
    if not fa or fa != fb or not ga or not gb: return '不一致'
    if ga == gb: return '一致'
    if len(ga) != len(gb): return '無法確認'
    compatible = all(x == y or ((len(x)==1 or len(y)==1) and x[0]==y[0]) for x,y in zip(ga,gb))
    return '縮寫相容' if compatible else '不一致'


def author_check(text, c):
    supplied = [a.strip() for a in text.split(';') if a.strip()]
    if not supplied or not c.authors or not c.complete_authors: return '無法確認'
    if re.search(r'\bet\s+al\b|等人|…|\.\.\.', text, re.I): return '作者缺漏'
    if len(supplied) != len(c.authors): return '作者數量不同'
    matches = [name_match(a,b) for a,b in zip(supplied,c.authors)]
    if '不一致' in matches: return '姓名或順序不同'
    if '無法確認' in matches: return '無法確認'
    return '縮寫相容（待確認）' if '縮寫相容' in matches else '一致'


def publication(c):
    if c.kind in ('posted-content', 'preprint'): return '預印本／張貼稿（中繼資料）'
    if c.source == 'Crossref' and c.kind in ('journal-article','proceedings-article') and c.venue and c.doi:
        return '正式發表紀錄（未查證同儕審查）'
    return '無法確認'


def compare(ref, c):
    title = '一致' if norm(ref.title) and norm(ref.title)==norm(c.title) else ('缺少資料' if not ref.title or not c.title else '不同')
    authors = author_check(ref.authors, c)
    year = '一致' if ref.year and ref.year==c.year else ('缺少資料' if not ref.year or not c.year else '不同（可能線上／印刷年份差異）')
    venue = '一致' if norm(ref.venue) and norm(ref.venue)==norm(c.venue) else ('缺少資料' if not ref.venue or not c.venue else '不同（縮寫請人工確認）')
    doi = '一致' if ref.doi and doi_norm(ref.doi)==c.doi else ('未提供／來源缺漏' if not ref.doi or not c.doi else '不同')
    fields = {'標題':title, '全部作者與順序':authors, '年份':year, '期刊／會議':venue, 'DOI':doi}
    match = all(v=='一致' for k,v in fields.items() if k!='DOI') and (not ref.doi or doi=='一致')
    return fields, match


def verify(ref, candidates, errors=()):
    ranked = sorted(candidates, key=lambda c: (norm(c.title)==norm(ref.title) and bool(ref.title),
        bool(ref.doi) and c.doi==doi_norm(ref.doi), SequenceMatcher(None,norm(ref.title),norm(c.title)).ratio()), reverse=True)
    plausible = [c for c in ranked if (ref.doi and c.doi==doi_norm(ref.doi)) or (ref.title and SequenceMatcher(None,norm(ref.title),norm(c.title)).ratio()>=0.75)]
    result = {'輸入':asdict(ref), '判定':'無法確認', '發表類型':'無法確認', '說明':[], '來源錯誤':list(errors),
              '查詢時間UTC':datetime.now(timezone.utc).isoformat(), 'Google Scholar':'https://scholar.google.com/scholar?'+urlencode({'q':ref.title or ref.raw or ref.doi}), '候選':[]}
    for c in ranked:
        fields, match = compare(ref,c)
        result['候選'].append({'來源':c.source, '標題':c.title, '作者':c.authors, '年份':c.year, '期刊／會議':c.venue,
            'DOI':c.doi, 'DOI連結':'https://doi.org/'+quote(c.doi,safe='/') if c.doi else '', '出版社／原始頁':safe_url(c.url),
            '來源紀錄':safe_url(c.record_url), '發表類型':publication(c), '欄位比對':fields, '完整比對一致':match})
    if not plausible:
        if errors:
            result['判定'] = '查詢失敗／未完成'
            result['說明'].append('來源查詢未完成，尚無足夠資料判斷這筆文獻。請先排除連線或 API 錯誤後重試。')
        else:
            result['說明'].append('未找到足夠相近的候選；不代表文獻不存在。')
        return result
    best = plausible[0]
    fields, match = compare(ref,best)
    same_work = [c for c in plausible if (best.doi and c.doi==best.doi) or (not best.doi and norm(c.title)==norm(best.title))]
    ambiguity = any(c.doi != best.doi for c in plausible[1:] if norm(c.title)==norm(best.title) and author_check(ref.authors,c) not in ('姓名或順序不同','作者數量不同'))
    conflict_notes = []
    baseline = Reference(best.title, '; '.join(best.authors), best.year, best.venue, best.doi)
    attributes = {'標題':'title', '全部作者與順序':'authors', '年份':'year', '期刊／會議':'venue', 'DOI':'doi'}
    for other in same_work[1:]:
        comparison, _ = compare(baseline, other)
        for name, state in comparison.items():
            if state in ('一致', '未提供／來源缺漏'):
                continue
            if name == '全部作者與順序' and not other.complete_authors:
                conflict_notes.append(f'{other.source} 的作者清單不完整，無法交叉確認全部作者與順序。')
                continue
            def display(candidate):
                value = getattr(candidate, attributes[name])
                return '；'.join(value) if isinstance(value,list) else str(value or '未提供')
            conflict_notes.append(f'來源差異｜{name}：{best.source}「{display(best)}」；{other.source}「{display(other)}」。')
    conflicts = bool(conflict_notes)
    if match and not ambiguity and not conflicts and not errors and not ref.parse_note:
        result['判定'] = '書目一致'
    else:
        result['判定'] = '需人工確認'
    result['發表類型'] = publication(best) if not ambiguity else '無法確認'
    if ambiguity: result['說明'].append('同名候選有不同 DOI，可能為不同版本，請選擇原始紀錄核對。')
    result['說明'].extend(conflict_notes)
    if errors: result['說明'].append('部分來源未完成，無法完成交叉驗證。')
    if ref.parse_note: result['說明'].append(ref.parse_note)
    result['說明'].extend(f'{k}：{v}' for k,v in fields.items() if v!='一致')
    result['說明'].append('僅核對登錄中繼資料；出版社頁面與同儕審查狀態需人工查核。')
    return result


def safe_url(url):
    return url if isinstance(url,str) and url.startswith(('https://','http://')) else ''


def csv_export(results):
    buf = io.StringIO(newline='')
    columns = ['輸入標題','輸入資料JSON','判定','發表類型','說明','來源錯誤','查詢時間UTC','Google Scholar','候選資料JSON']
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    import json
    def safe(value):
        text = str(value)
        return "'"+text if text.lstrip().startswith(('=','+','-','@')) else text
    for r in results:
        values = [r['輸入']['title'],json.dumps(r['輸入'],ensure_ascii=False),r['判定'],r['發表類型'],'；'.join(r['說明']),'；'.join(r['來源錯誤']),r['查詢時間UTC'],r['Google Scholar'],json.dumps(r['候選'],ensure_ascii=False)]
        writer.writerow(dict(zip(columns,map(safe,values))))
    return buf.getvalue().encode('utf-8-sig')


