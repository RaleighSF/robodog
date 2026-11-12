"""The Settings show switch locks a skin (and so its cloud path) and the choice
survives a restart, because it is saved to config.yaml ui.lock_profile.

  python3 tests/test_show_switch.py"""
import os
import sys
import tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
tmp = tempfile.mkdtemp()
os.environ['WATCHDOG_CONFIG'] = os.path.join(tmp, 'config.yaml')
os.environ.pop('WATCHDOG_CONFIG_OVERLAY', None)
with open(os.environ['WATCHDOG_CONFIG'], 'w') as f:
    f.write("ui:\n  lock_profile: ''\n  profile: default\n")
sys.path.insert(0, ROOT)
import config  # noqa: E402
import ui_profiles  # noqa: E402

ui_profiles._STATE_PATH = os.path.join(tmp, 'ui_state.json')


def restart():
    """A fresh process: reload the config from disk."""
    config.config = config.VisionConfig()


def test_lock_to_each_cloud_survives_restart():
    for pid in ('azure', 'aws'):
        ui_profiles.set_show_cloud(pid)
        assert ui_profiles.get_active_profile_id() == pid
        assert ui_profiles.active_clouds() == [pid]
        restart()
        assert ui_profiles.locked_profile_id() == pid, 'lost after restart'
        assert ui_profiles.active_clouds() == [pid]
        assert [p['id'] for p in ui_profiles.all_profiles().values()] == [pid]


def test_default_unlocks_and_sends_to_both():
    ui_profiles.set_show_cloud('azure')
    ui_profiles.set_show_cloud('default')
    restart()
    assert ui_profiles.locked_profile_id() is None
    assert ui_profiles.get_active_profile_id() == 'default'
    assert ui_profiles.active_clouds() == ['azure', 'aws']


def test_unknown_profile_is_refused():
    for bad in ('gcp', None, ''):
        try:
            ui_profiles.set_show_cloud(bad)
        except ValueError:
            continue
        raise AssertionError('accepted %r' % (bad,))


if __name__ == '__main__':
    failed = 0
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            try:
                fn()
                print('  PASS ', name)
            except AssertionError as e:
                failed += 1
                print('  FAIL ', name, '-', e)
    print('%d failed' % failed)
    sys.exit(1 if failed else 0)
