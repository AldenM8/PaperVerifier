"""向 OpenAlex 申請免費金鑰，僅儲存於本機私有設定，不顯示金鑰。"""
import argparse
import json
import sys
from pathlib import Path
import requests

BASE = Path(__file__).resolve().parent
KEY_FILE = BASE / '.streamlit' / 'openalex-key.json'

def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--email', required=True)
    args = parser.parse_args()
    if KEY_FILE.exists():
        print('本機已有金鑰，未重複申請。請確認啟用信後，回網頁測試 API 連線。')
        return
    try:
        response = requests.post('https://api.openalex.org/api-keys',
                                 json={'email':args.email, 'agent':'PaperVerifier'},timeout=(5,20))
        try:
            data = response.json()
        except ValueError:
            print(f'申請未完成：HTTP {response.status_code}，回應格式不正確。')
            return
        if not isinstance(data,dict):
            print('申請未完成：回應格式不正確。')
            return
        if response.status_code == 201 and isinstance(data.get('api_key'),str) and data['api_key']:
            KEY_FILE.parent.mkdir(exist_ok=True)
            KEY_FILE.write_text(json.dumps({'api_key':data['api_key']},ensure_ascii=True),encoding='utf-8')
            print('免費金鑰已取得並儲存於本機，沒有顯示或匯出金鑰。')
            print('請到信箱開啟 OpenAlex 的「Activate your OpenAlex API key」信件，點擊啟用連結。')
            print('啟用後回 PaperVerifier 按「測試 API 連線」，程式會自動讀取金鑰。')
            if data.get('daily_budget_usd_after_activation') is not None:
                print('官方回傳的啟用後每日免費額度：US$'+str(data['daily_budget_usd_after_activation']))
        elif response.status_code == 409:
            print('官方回覆 HTTP 409：可能已有帳號或正在等待啟用。')
            print('請先檢查啟用信；若已有帳號，請至 https://openalex.org/settings/api 取得金鑰。')
        elif response.status_code == 429:
            print('申請未完成：HTTP 429，官方限制目前網路或信箱網域的申請數量。請稍後再試。')
        else:
            print(f'申請未完成：HTTP {response.status_code}。未儲存金鑰。')
    except requests.RequestException as exc:
        if '10013' in str(exc):
            print('申請未完成：Windows 拒絕對外連線（10013）。')
        else:
            print('申請未完成：網路連線或讀取錯誤（'+type(exc).__name__+'）。')

if __name__ == '__main__':
    main()
