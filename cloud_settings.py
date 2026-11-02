"""本機與雲端的憑證載入；不將憑證回傳至瀏覽器。"""
import os
import streamlit as st


def cloud_setting(name):
    value = os.getenv(name, '')
    if value:
        return value
    try:
        value = st.secrets.get(name, '')
    except FileNotFoundError:
        return ''
    return value if isinstance(value, str) else ''
