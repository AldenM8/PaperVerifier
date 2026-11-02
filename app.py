import csv
import io
import json
import os
from html import escape
from pathlib import Path
import streamlit as st
import importlib
import verifier
from swipe_list import swipe_list
from cloud_settings import cloud_setting

# Streamlit 重跑頁面時也檢查相依模組，避免只更新 UI 卻繼續使用舊 Client。
if getattr(verifier, '_LOADED_MTIME', None) != Path(verifier.__file__).stat().st_mtime_ns:
    importlib.reload(verifier)
from verifier import Client, Reference, verify, safe_url, API_DIAGNOSTIC_VERSION

st.set_page_config(page_title='PaperVerifier', page_icon='📚', layout='wide', initial_sidebar_state='auto')
if st.session_state.get('diagnostic_version') != API_DIAGNOSTIC_VERSION:
    st.session_state.pop('connection_checks', None)
    st.session_state['diagnostic_version'] = API_DIAGNOSTIC_VERSION
st.markdown('<style>'+Path(__file__).with_name('style.css').read_text(encoding='utf-8')+'</style>', unsafe_allow_html=True)
st.title('PaperVerifier')
st.caption('學術文獻驗證')
def configured_client():
    key = cloud_setting('OPENALEX_API_KEY')
    if not key:
        key_file = Path(__file__).resolve().parent / '.streamlit' / 'openalex-key.json'
        if key_file.exists():
            try:
                saved = json.loads(key_file.read_text(encoding='utf-8'))
                value = saved.get('api_key', '') if isinstance(saved, dict) else ''
                key = value if isinstance(value, str) else ''
            except (OSError, ValueError):
                st.sidebar.error('本機金鑰設定無法讀取，請檢查申請設定。')
    return Client(cloud_setting('CROSSREF_MAILTO'), key)


with st.sidebar:
    st.header('連線狀態')
    if st.button('測試 API 連線'):
        with st.spinner('測試此網頁服務是否能連線…'):
            st.session_state['connection_checks'] = configured_client().check_connection()
    connection_output = st.empty()


def show_connection_results():
    with connection_output.container():
        checks = st.session_state.get('connection_checks', [])
        if not checks:
            st.caption('尚未測試連線')
        for check in checks:
            if check['連線成功']:
                st.markdown(f"<div class='connection-ok'>● {escape(check['來源'])}<span>已連線</span></div>", unsafe_allow_html=True)
            else:
                st.error(check['來源'] + '：' + check['訊息'].removeprefix(check['來源'] + ': '))
        if checks and not any(c['連線成功'] for c in checks):
            st.error('兩個來源均無法使用，請先修復連線；此狀態無法驗證文獻。')


show_connection_results()

def add_author_box():
    st.session_state['manual_author_count'] = st.session_state.get('manual_author_count', 1) + 1


def add_manual_reference():
    count = st.session_state.get('manual_author_count', 1)
    title = st.session_state.get('manual_title', '').strip()
    year = st.session_state.get('manual_year', '').strip()
    if not title:
        st.session_state['manual_error'] = '請填寫論文標題。'
        return
    if year and (len(year) != 4 or not year.isascii() or not year.isdigit()):
        st.session_state['manual_error'] = '年份請填四位數，或留白。'
        return
    rows = st.session_state.get('rows', [])
    if len(rows) >= 30:
        st.session_state['manual_error'] = '每批最多 30 篇。'
        return
    authors = [st.session_state.get(f'manual_author_{j}', '').strip() for j in range(count)]
    ref = Reference(title=title, authors='; '.join(a for a in authors if a), year=year,
                    venue=st.session_state.get('manual_venue', '').strip(),
                    doi=st.session_state.get('manual_doi', '').strip())
    st.session_state['rows'] = rows + [vars(ref)]
    st.session_state.pop('results', None)
    st.session_state.pop('reference_editor', None)
    st.session_state.pop('manual_error', None)
    for key in ['manual_title','manual_year','manual_venue','manual_doi'] + [f'manual_author_{j}' for j in range(count)]:
        st.session_state.pop(key, None)
    st.session_state['manual_author_count'] = 1
    st.session_state['manual_added'] = True


def input_row(label, key, placeholder='', **kwargs):
    with st.container(key=f'fieldrow_{key}'):
        label_col, input_col = st.columns([1.4, 6], vertical_alignment='center')
        label_col.markdown(f'<span class="form-label">{escape(label)}</span>', unsafe_allow_html=True)
        input_col.text_input(label, key=key, placeholder=placeholder, label_visibility='collapsed', **kwargs)


def form_divider():
    st.markdown('<div class="form-divider"></div>', unsafe_allow_html=True)


with st.expander('輸入搜尋資料', expanded='results' not in st.session_state):
    text_tab, csv_tab = st.tabs(['輸入文字', '上傳 CSV'])
    with text_tab:
        input_row('論文標題', 'manual_title', '輸入或貼上標題')
        form_divider()
        count = st.session_state.get('manual_author_count', 1)
        for j in range(count):
            input_row(f'作者 {j+1}', f'manual_author_{j}', '完整姓名',
                      help='依論文原始順序，每格一位作者。')
        _, author_action = st.columns([1.4, 6])
        author_action.button('＋新增作者', on_click=add_author_box)
        form_divider()
        input_row('年份', 'manual_year', '2020', max_chars=4)
        form_divider()
        input_row('期刊／會議', 'manual_venue', '刊物或會議名稱')
        form_divider()
        input_row('DOI（選填）', 'manual_doi', '10.xxxx/xxxx 或 DOI 連結')
        form_divider()
        _, add_action = st.columns([1.4, 6])
        add_action.button('加入清單', on_click=add_manual_reference)
        if st.session_state.get('manual_error'):
            st.error(st.session_state['manual_error'])
        if st.session_state.pop('manual_added', False):
            st.caption(f"已加入 · 清單共 {len(st.session_state['rows'])} 篇")
    with csv_tab:
        upload = st.file_uploader('選擇文獻 CSV', type=['csv'], help='欄位：title、authors、year、venue、doi；作者以分號分隔。')
        if st.button('匯入 CSV', help='匯入後取代目前清單。'):
            try:
                if upload is None:
                    raise ValueError('請先選擇 CSV 檔案。')
                reader = csv.DictReader(io.StringIO(upload.getvalue().decode('utf-8-sig')))
                if not reader.fieldnames or 'title' not in reader.fieldnames:
                    raise ValueError('CSV 必須包含 title 欄位。')
                rows = [{k:str(row.get(k) or '') for k in Reference.__dataclass_fields__} for row in reader]
                if not 1 <= len(rows) <= 30:
                    raise ValueError('請提供 1–30 筆文獻。')
                st.session_state['rows'] = rows
                st.session_state.pop('results',None)
                st.session_state.pop('reference_editor',None)
            except (ValueError, UnicodeDecodeError, csv.Error) as exc:
                st.error(str(exc))

    if 'rows' in st.session_state:
        st.caption(f"待驗證清單 · {len(st.session_state['rows'])} 篇")
        edited = swipe_list(st.session_state['rows'])
        if edited != st.session_state['rows']:
            st.session_state['rows'] = edited
            st.session_state.pop('results', None)
            st.rerun()
        if st.button('驗證', type='primary', disabled=not edited):
            refs = [Reference(**{key:row.get(key, '') for key in Reference.__dataclass_fields__}) for row in edited]
            if any(not r.title.strip() for r in refs):
                st.error('請先補齊每筆標題，才能可靠比對。')
            else:
                client = configured_client()
                st.session_state.pop('results', None)
                with st.spinner('批次開始前先測試 API 連線…'):
                    checks = client.check_connection()
                    st.session_state['connection_checks'] = checks
                show_connection_results()
                if not any(c['連線成功'] for c in checks):
                    st.error('批次未開始：兩個 API 都無法連線或取得有效回應。這是查詢服務問題，尚未驗證任何文獻。')
                    for check in checks:
                        st.error(check['來源'] + '：' + check['訊息'].removeprefix(check['來源'] + ': '))
                    st.info('若出現 WinError 10013，可在自己的 Windows 終端機啟動本專案的 start.cmd，再使用新開啟的頁面。')
                    st.stop()
                for check in checks:
                    if not check['連線成功']:
                        st.warning(check['來源'] + ' 暫時無法使用；結果會保留來源錯誤供人工確認。')
                results = []
                progress = st.progress(0)
                status = st.empty()
                for i,ref in enumerate(refs):
                    status.write(f'處理 {i+1}/{len(refs)}：{ref.title}')
                    candidates, errors = client.search(ref)
                    result = verify(ref,candidates,errors)
                    result['模式'] = '即時API'
                    results.append(result)
                    progress.progress((i+1)/len(refs))
                    st.session_state['results'] = results
                if any(r['來源錯誤'] for r in results):
                    status.warning('批次已結束，但有來源查詢未完成；請先查看連線錯誤，勿視為文獻查無紀錄。')
                else:
                    status.empty()

def original_url(result):
    if result['判定'] != '書目一致':
        return ''
    for candidate in result['候選']:
        if candidate.get('完整比對一致'):
            for key in ('DOI連結', '出版社／原始頁'):
                url = safe_url(candidate.get(key, ''))
                if url:
                    return url
    return ''


def comparison_table(rows):
    header = '<tr><th>欄位</th><th>你的資料</th><th>來源資料</th><th>比對</th></tr>'
    labels = ['欄位','你的資料','來源資料','比對']
    body = ''.join('<tr>'+''.join('<td data-label="'+labels[j]+'">'+escape(str(value))+'</td>' for j,value in enumerate(row))+'</tr>' for row in rows)
    st.markdown('<div class="comparison-wrap"><table class="comparison">'+header+body+'</table></div>', unsafe_allow_html=True)


def render_candidate(result, index):
    candidates = result['候選']
    if not candidates:
        st.caption('尚無可比對紀錄')
        return
    def label(j):
        c = candidates[j]
        matched = sum(value == '一致' for value in c['欄位比對'].values())
        return f"{j+1} · {c['來源']} · {c['年份'] or '年份未提供'} · {matched}/5 一致"
    st.caption('候選來源')
    with st.container(border=True, key=f'candidate_selector_{index}'):
        selected = st.selectbox('候選來源', range(len(candidates)), format_func=label,
                               key=f'candidate_{index}', label_visibility='collapsed')
    c = candidates[selected]
    st.write(c['標題'])
    fields, supplied = c['欄位比對'], result['輸入']
    source_values = {'標題':c['標題'], '年份':c['年份'], '期刊／會議':c['期刊／會議'], 'DOI':c['DOI']}
    input_keys = {'標題':'title', '年份':'year', '期刊／會議':'venue', 'DOI':'doi'}
    rows = [(key, supplied[input_keys[key]] or '未提供', value or '未提供', fields[key])
            for key,value in source_values.items()]
    differences = [row for row in rows if row[-1] != '一致']
    author_difference = fields['全部作者與順序'] != '一致'
    if differences:
        comparison_table(differences)
    if author_difference:
        st.markdown(':orange[作者：'+fields['全部作者與順序']+']')
    if not differences and not author_difference:
        st.markdown('<div class="match-note">✓ 此來源的書目欄位一致</div>',unsafe_allow_html=True)
    with st.expander('完整欄位與作者'):
        comparison_table(rows)
        input_authors = [a.strip() for a in supplied['authors'].split(';') if a.strip()]
        st.caption(f"作者順序 · 輸入 {len(input_authors)} 位 / 來源 {len(c['作者'])} 位 · {fields['全部作者與順序']}")
        author_rows = [{'順序':j+1,
                        '你的作者':input_authors[j] if j<len(input_authors) else '缺漏',
                        '來源作者':c['作者'][j] if j<len(c['作者']) else '缺漏'}
                       for j in range(max(len(input_authors),len(c['作者'])))]
        st.dataframe(author_rows, hide_index=True, use_container_width=True)
        st.caption(c['發表類型'])
        st.caption('查詢 UTC：'+result['查詢時間UTC'])
    links = st.columns(2)
    url = safe_url(c.get('DOI連結','')) or safe_url(c.get('出版社／原始頁',''))
    if url:
        links[0].link_button('原文 ↗',url)
    links[1].link_button('Google Scholar ↗',result['Google Scholar'])


if 'results' in st.session_state:
    results = st.session_state['results']
    for r in results:
        if r['來源錯誤'] and not r['候選']:
            r['判定'] = '查詢失敗／未完成'
            r['說明'] = ['來源查詢失敗，這筆尚未完成驗證；不能據此判斷文獻是否存在。']
    st.subheader('驗證結果')
    with st.container(key='summary_metrics'):
        counts = st.columns(3)
    for col,title,value,tone in [
        (counts[0],'書目一致',sum(r['判定']=='書目一致' for r in results),'green'),
        (counts[1],'待核對',sum(r['判定']=='需人工確認' for r in results),'amber'),
        (counts[2],'無法確認',sum(r['判定'] not in ('書目一致','需人工確認') for r in results),'blue')]:
        col.markdown(f'<div class="stat {tone}"><span>{title}</span><strong>{value}</strong></div>',unsafe_allow_html=True)
    st.markdown("""<div class="result-guide">
<div class="guide-green"><b>書目一致</b><span>資料吻合，不代表同儕審查認證。</span></div>
<div class="guide-amber"><b>無法確認</b><span>查不到，不代表文獻不存在。</span></div>
<div class="guide-blue"><b>Google Scholar</b><span>提供人工輔助搜尋。</span></div>
</div>""", unsafe_allow_html=True)
    if any(r['判定']=='查詢失敗／未完成' for r in results):
        st.error('有文獻因來源查詢失敗而未完成驗證，請先測試 API 連線。')
    with st.container(key='result_table_header'):
        header = st.columns([6,2,2])
    for col,text in zip(header,['文獻標題','判定／原文','發表類型']):
        col.markdown(f'**{text}**')
    for i,r in enumerate(results):
        with st.container(border=True, key=f'result_card_{i}'):
            with st.container(key=f'result_heading_{i}'):
                title_col,status_col,type_col = st.columns([6,2,2],vertical_alignment='center')
            title_col.write(f"{i+1}. {r['輸入']['title']}")
            url = original_url(r)
            if url:
                status_col.markdown(f'<a class="pill green result-link" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">一致 · 開啟原文 ↗</a>', unsafe_allow_html=True)
            elif r['判定']=='書目一致':
                status_col.success('書目一致')
                status_col.caption('來源未提供原文連結')
            else:
                tone = 'amber' if r['判定']=='需人工確認' else 'blue'
                status_col.markdown(f'<span class="pill {tone}">{escape(r["判定"])}</span>',unsafe_allow_html=True)
            type_col.caption(r['發表類型'].replace('（未查證同儕審查）','').replace('（中繼資料）',''))
            with st.expander("查看差異與來源"):
                for error in r['來源錯誤']:
                    st.error(error)
                notes = [note for note in r['說明'] if not note.startswith('僅核對登錄中繼資料')]
                if notes:
                    explanation_label, explanation_text = st.columns([1,5], vertical_alignment='top')
                    explanation_label.markdown('**結果說明**')
                    with explanation_text:
                        for note in notes:
                            st.caption(note)
                render_candidate(r,i)

