"""Demo UI profiles: vendor-branded skins for the dashboard.

A profile repaints the dashboard (colour tokens, type, radii live in
static/themes/themes.css under html[data-theme=...]) and swaps the header
partner lockup. The active profile is operator state, not config: it is
persisted to ui_state.json (gitignored) so a booth screen keeps its skin
across service restarts, and config.yaml `ui.profile` only supplies the
first-boot default.
"""

import json
import os
import threading

_STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ui_state.json')
_lock = threading.Lock()

PROFILES = {
    'default': {
        'id': 'default',
        'label': 'Default — NTT DATA',
        'title': 'Project Watch Dog - Factory Patrol Monitoring | NTT DATA',
        'font_href': 'https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap',
        'partner': None,   # no co-brand on the house look
    },
    'azure': {
        'id': 'azure',
        'label': 'Microsoft Azure — Ignite',
        'title': 'Watch Dog · Physical AI on Microsoft Azure | NTT DATA',
        # Segoe UI ships with Windows and cannot be web-served; Fluent's own
        # web fallback chain covers macOS/Linux booth machines.
        'font_href': None,
        'partner': {
            'label': 'Built on',
            # Approved artwork only (static/themes/README.md); until the file is
            # dropped in, the header shows a plain-text reference, which
            # Microsoft's trademark guidance permits without a licence.
            'logo': '/static/themes/azure/logo.svg',
            'alt': 'Microsoft Azure',
            'wordmark': 'Microsoft Azure',
            'tile': False,
        },
    },
    'aws': {
        'id': 'aws',
        'label': 'AWS — re:Invent',
        'title': 'Watch Dog · Physical AI on AWS | NTT DATA',
        'font_href': 'https://fonts.googleapis.com/css2?family=Open+Sans:wght@400;600;700;800&display=swap',
        'partner': {
            'label': 'Built on',
            'logo': '/static/themes/aws/logo.svg',
            'alt': 'AWS',
            'wordmark': 'AWS',
            'tile': False,
        },
    },
}

# Edge hardware shown in the "Powered by NVIDIA" badge, keyed by
# config.yaml telemetry.device_type. Moving to Thor is a config change only.
_NVIDIA_PLATFORMS = {
    'nvidia_agx_orin': 'Jetson AGX Orin',
    'nvidia_orin_nx': 'Jetson Orin NX',
    'nvidia_agx_thor': 'Jetson AGX Thor',
    'nvidia_thor': 'Jetson AGX Thor',
}


_STATIC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
NVIDIA_LOGO = '/static/themes/nvidia/logo.svg'


def asset_exists(url):
    """True if a /static/... URL maps to a real file (approved artwork present)."""
    if not url or not url.startswith('/static/'):
        return False
    rel = url[len('/static/'):]
    path = os.path.normpath(os.path.join(_STATIC_ROOT, rel))
    return path.startswith(_STATIC_ROOT + os.sep) and os.path.isfile(path)


def theme_css_version():
    """Content hash of themes.css so kiosks never keep a stale stylesheet.
    Hashed per page load (the file is ~20 KB) so no metadata cache can go
    stale; any read failure degrades to an unversioned URL, never a 500."""
    import hashlib
    try:
        with open(os.path.join(_STATIC_ROOT, 'themes', 'themes.css'), 'rb') as f:
            return hashlib.sha1(f.read()).hexdigest()[:10]
    except OSError:
        return '0'


def _ui_config():
    try:
        from config import get_config
        return get_config().config.get('ui', {}) or {}
    except Exception:
        return {}


def default_profile_id():
    pid = _ui_config().get('profile', 'default')
    return pid if isinstance(pid, str) and pid in PROFILES else 'default'


def locked_profile_id():
    """config.yaml ui.lock_profile pins the skin for an event and hides the
    picker (e.g. re:Invent sponsor rules forbid showing another cloud)."""
    pid = _ui_config().get('lock_profile')
    return pid if isinstance(pid, str) and pid in PROFILES else None


def get_active_profile_id():
    locked = locked_profile_id()
    if locked:
        return locked
    with _lock:
        try:
            with open(_STATE_PATH) as f:
                state = json.load(f)
            pid = state.get('profile') if isinstance(state, dict) else None
            if isinstance(pid, str) and pid in PROFILES:
                return pid
        except (OSError, ValueError):
            pass
    return default_profile_id()


def set_active_profile_id(pid):
    if not isinstance(pid, str) or pid not in PROFILES:
        raise ValueError('unknown profile: %r' % (pid,))
    with _lock:
        tmp = _STATE_PATH + '.tmp'
        with open(tmp, 'w') as f:
            json.dump({'profile': pid}, f)
        os.replace(tmp, _STATE_PATH)
    return pid


def nvidia_badge():
    """Badge settings: shown on situational-awareness surfaces by default."""
    ui = _ui_config()
    badge = ui.get('nvidia_badge', {}) or {}
    platform = badge.get('platform')
    if not platform:
        try:
            from config import get_config
            device = get_config().config.get('telemetry', {}).get('device_type', '')
        except Exception:
            device = ''
        platform = _NVIDIA_PLATFORMS.get(device, '')
    return {
        'enabled': bool(badge.get('enabled', True)),
        'platform': platform,
        'logo': NVIDIA_LOGO if asset_exists(NVIDIA_LOGO) else None,
    }


def _with_assets(profile):
    p = dict(profile)
    if p.get('partner'):
        partner = dict(p['partner'])
        partner['has_logo'] = asset_exists(partner.get('logo'))
        p['partner'] = partner
    return p


def all_profiles():
    """Profiles offered to the page. A locked event build ships only its own
    profile so no other vendor's name reaches the page at all."""
    locked = locked_profile_id()
    ids = [locked] if locked else list(PROFILES)
    return {pid: _with_assets(PROFILES[pid]) for pid in ids}


def resolve(pid=None):
    """Profile dict for rendering; unknown ids (or a locked event build)
    fall back to the active one."""
    if not isinstance(pid, str) or pid not in PROFILES or locked_profile_id():
        pid = get_active_profile_id()
    return _with_assets(PROFILES[pid])
