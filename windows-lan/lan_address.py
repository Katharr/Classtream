"""Shared, dependency-free student URL rules for launcher and web adapter."""
import json
import re


def validate_mdns(cfg):
    enabled = cfg.get('mdns_enabled', True)
    name = cfg.get('mdns_hostname', 'live')
    if type(enabled) is not bool:
        raise ValueError('mdns_enabled must be true or false.')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', name):
        raise ValueError('mdns_hostname must be a lowercase DNS label (1-63 characters).')
    return enabled and cfg.get('mode', 'http') == 'http', name


def http_origin(host, port):
    return f'http://{host}' + (f':{port}' if port != 80 else '')


def student_addresses(cfg, publication=None):
    """Only promote a hostname after this launcher successfully published it."""
    if cfg.get('mode', 'http') != 'http':
        url = f"https://{cfg['teacher_ip']}:{cfg['https_port']}/class"
        return dict(student_url=url, fallback_url=url, mdns_status='disabled')
    enabled, name = validate_mdns(cfg)
    fallback = http_origin(cfg['teacher_ip'], cfg.get('http_port', 80))
    state = publication or {}
    matching = (enabled and state.get('teacher_ip') == cfg['teacher_ip']
                and state.get('http_port') == cfg.get('http_port', 80)
                and state.get('mdns_hostname') == name)
    status = state.get('mdns_status', 'unavailable') if matching else ('unavailable' if enabled else 'disabled')
    return dict(student_url=http_origin(name + '.local', cfg.get('http_port', 80))
                if status == 'published' else fallback,
                fallback_url=fallback, mdns_status=status)


def read_publication(home):
    try:
        return json.loads((home / 'runtime' / 'ready.json').read_text('utf-8'))
    except (OSError, ValueError):
        return {}
