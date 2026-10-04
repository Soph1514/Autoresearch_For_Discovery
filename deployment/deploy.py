"""Drain, checkpoint, recreate, and verify the hosted lab. Requires Modal auth."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

import modal

ROOT = Path(__file__).resolve().parents[1]
APP = 'autoresearch-lab'


def request(url, access, path, method='GET'):
    headers = {'X-Deploy-Token': access.get('RESEARCH_DEPLOY_TOKEN', '')}
    if access.get('RESEARCH_API_PASSWORD'):
        pair = access.get('RESEARCH_API_USER', 'research') + ':' + access['RESEARCH_API_PASSWORD']
        headers['Authorization'] = 'Basic ' + base64.b64encode(pair.encode()).decode()
    req = urllib.request.Request(url.rstrip('/') + path, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=90) as response:
        body = response.read()
        return json.loads(body) if response.headers.get_content_type() == 'application/json' else body


def main():
    os.chdir(ROOT)
    url, access, drained = None, None, False
    try:
        url = modal.Function.from_name(APP, 'web').get_web_url()
        access = modal.Function.from_name(APP, 'deployment_access').remote()
    except modal.exception.NotFoundError:
        print('First deployment.', flush=True)
    try:
        if url:
            request(url, access, '/api/deployment/drain', 'POST')
            drained = True
            deadline = time.monotonic() + 1800
            while True:
                state = request(url, access, '/api/deployment')
                if not state['active_runs'] and not state['requests']:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError('Active work did not finish within 30 minutes; update cancelled.')
                print(f"Waiting: {state['active_runs']} active runs, {state['requests']} submissions.", flush=True)
                time.sleep(15)
            request(url, access, '/api/deployment/checkpoint', 'POST')
        env = dict(os.environ)
        env['RESEARCH_REVISION'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
        subprocess.run([sys.executable, '-m', 'modal', 'deploy', '--strategy', 'recreate',
                        'deployment/modal_app.py'], env=env, check=True)
        url = modal.Function.from_name(APP, 'web').get_web_url()
        access = modal.Function.from_name(APP, 'deployment_access').remote()
        for attempt in range(12):
            try:
                health = request(url, access, '/api/health')
                assert health['custom_evaluator_configured']
                capabilities = request(url, access, '/api/capabilities')
                assert capabilities['evaluator_ready'], capabilities.get('evaluator_error')
                assert b'<html' in request(url, access, '/')
                assert b'<html' in request(url, access, '/engine.html')
                break
            except Exception:
                if attempt == 11:
                    raise
                time.sleep(5)
        result = modal.Function.from_name(APP, 'smoke_candidate').remote()
        assert result['ok'] and result['output'] == 42, result
        compiled = modal.Function.from_name(APP, 'smoke_compiler').remote()
        assert compiled['valid'] and compiled['objective'] == 7, compiled
        print(f'Deployed and verified: {url}', flush=True)
    finally:
        if drained and url and access:
            try:
                request(url, access, '/api/deployment/resume', 'POST')
            except Exception:
                print('Could not clear deployment drain; check the Modal app status.', file=sys.stderr)


if __name__ == '__main__':
    main()
