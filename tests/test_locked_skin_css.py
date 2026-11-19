"""A locked event skin's stylesheet must not show that another vendor's skin exists.

  python3 tests/test_locked_skin_css.py"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import ui_profiles  # noqa: E402

VENDOR_WORDS = {
    'azure': r'azure|microsoft|fluent|ignite|segoe',
    'aws': r'aws|amazon|cloudscape|re:invent|squid ink|ember',
}


def served(locked):
    ui_profiles.locked_profile_id = lambda: locked
    return ui_profiles.theme_css()


def test_each_lock_hides_the_other_vendor():
    for locked, other in (('azure', 'aws'), ('aws', 'azure')):
        css = served(locked)
        hits = re.findall(VENDOR_WORDS[other], css, flags=re.I)
        assert not hits, '%s lock leaks %s: %s' % (locked, other, sorted(set(hits)))
        assert 'html[data-theme="%s"]' % locked in css, '%s lock lost its own rules' % locked
        assert css.count('{') == css.count('}'), '%s lock unbalanced braces' % locked
        assert '/*' not in css


def test_shared_rules_survive_the_filter():
    css = served('azure')
    assert ':focus-visible' in css and '@media' in css
    # a mixed selector list keeps only the locked theme's half
    assert re.search(r'html\[data-theme="azure"\] \.log-header h2\s*\{', css)


def test_unlocked_serves_the_file_whole():
    with open(os.path.join(ui_profiles._STATIC_ROOT, 'themes', 'themes.css'), encoding='utf-8') as f:
        assert served(None) == f.read()


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
