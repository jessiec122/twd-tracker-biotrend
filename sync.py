import os

with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace specific variables to match production settings
content = content.replace('PAGE_TITLE = "TWD 問題追蹤系統"', 'PAGE_TITLE = "TWD 問題追蹤系統(正式區)"')
content = content.replace('請檢查 UAT App Secrets', '請檢查正式區 Secrets')

# The rest is identical because app.py relies on st.secrets with fallbacks to prod table strings
with open('app_prod.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully synced app.py to app_prod.py")
