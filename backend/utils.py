# utils.py
import requests
from django.conf import settings

def send_to_hosted(payload, endpoint):
    url = f'{settings.HOSTED_BASE_URL}/{endpoint}'
    headers = {
        'Authorization': f'Bearer {settings.HOSTED_API_TOKEN}',
        'Content-Type': 'application/json',
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        return True, response.json()
    except requests.exceptions.Timeout:
        return False, 'Request timed out'
    except requests.exceptions.ConnectionError:
        return False, 'Could not connect to server'
    except requests.exceptions.HTTPError as e:
        return False, f'Server returned error: {e.response.status_code}'
    except Exception as e:
        return False, str(e)