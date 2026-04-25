import requests

TOKEN = "FlwBUHNad_yhHrjzDGXEp9v9sHxw-faIo9JvWa4ISfYeEVoUneWkLL28rCKXZ_EDKP3eDipHVNhi0OoKR2UKpU6OXYgmVf_TEJTIJQ2ngWFeR6j6QykLUopKiT3ujk-h6SWV2ArPssdbjnuH770LsPPA-gyuGh-QWERUTXQxsrucHVVoMpbjgSLQokGoBD5m249mM_TnuPB_FtnWEfMuf5feZ9dQQmte1FgM2i7Cau-nvGzjqoVshUKaQY2K6ReJaeQh2Ixoe_baVbUV5fkC1OSEQdKlGb8gZarj4aVjGy2Veweb"

url = "https://api.psacard.com/publicapi/cert/GetByCertNumber/139075607"
headers = {
    "Authorization": f"bearer {TOKEN}",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Referer": "https://www.psacard.com/",
}

try:
    response = requests.get(url, headers=headers, timeout=10)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.text[:500]}")
except Exception as e:
    print(f"Exception: {e}")

input("Enterで終了...")
