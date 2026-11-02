import hashlib
import json
from pathlib import Path
import streamlit.components.v1 as components

_component = components.declare_component('reference_swipe_list', path=str(Path(__file__).with_name('swipe_component')))
FIELDS = ('title','authors','year','venue','doi','raw','parse_note')

def revision(rows):
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False,sort_keys=True).encode()).hexdigest()

def apply_event(rows,event):
    if not isinstance(event,dict) or event.get('revision') != revision(rows):
        return rows
    index = event.get('index')
    if type(index) is not int or not 0 <= index < len(rows):
        return rows
    if event.get('action') == 'delete':
        return rows[:index]+rows[index+1:]
    if event.get('action') == 'edit' and isinstance(event.get('fields'),dict):
        patch=event['fields']
        editable=('title','authors','year','venue','doi')
        if any(not isinstance(patch.get(k),str) for k in editable) or not patch['title'].strip():
            return rows
        updated = dict(rows[index])
        updated.update({k:patch[k].strip() for k in editable})
        return rows[:index]+[updated]+rows[index+1:]
    return rows

def swipe_list(rows):
    event=_component(rows=rows, revision=revision(rows), key='reference_swipe_list', default=None)
    return apply_event(rows,event)
