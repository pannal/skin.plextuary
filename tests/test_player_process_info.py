"""Offline PPI contracts. Run: python3 -m unittest discover -s tests.

The label helper exercises the small condition/$INFO/$VAR subset used by these
variables. These checks do not replace Kodi's parser or native GUI rendering.
"""
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
VARIABLES = {v.attrib['name']: v for v in ET.parse(ROOT / 'xml/Variables.xml').getroot()}
DIALOG = ET.parse(ROOT / 'xml/DialogPlayerProcessInfo.xml').getroot()


def resolve(key, state):
    return str(state.get(key.lower(), ''))


def condition(expression, state):
    if not expression:
        return True
    for term in expression.split(' + '):
        negate = term.startswith('!')
        term = term.lstrip('!')
        match = re.fullmatch(r'(String|Integer)\.(IsEmpty|IsEqual|StartsWith|Contains)\((.*)\)', term)
        if match:
            kind, op, args = match.groups()
            left, _, right = args.partition(',')
            left = resolve(left, state)
            if right.lower().startswith(('player.process(', 'videoplayer.')):
                right = resolve(right, state)
            if kind == 'Integer':
                # Kodi initializes failed/missing integer conversions to zero.
                def integer(value):
                    match = re.match(r'-?\d+', value)
                    return int(match[0]) if match else 0
                result = integer(left) == integer(right)
            else:
                left, right = left.lower(), right.lower()
                result = {'IsEmpty': lambda: not left,
                          'IsEqual': lambda: left == right,
                          'StartsWith': lambda: left.startswith(right),
                          'Contains': lambda: right in left}[op]()
        elif term.lower() == 'player.passthrough':
            result = bool(state.get(term.lower(), False))
        else:
            raise AssertionError('Unsupported test condition: ' + term)
        if result == negate:
            return False
    return True


def expand(text, state):
    """Evaluate optional label prefixes/suffixes, preserving Kodi color markup."""
    while True:
        match = re.search(r'\$(INFO|VAR)\[', text)
        if not match:
            return text
        depth, end = 1, match.end()
        while depth:
            char = text[end]
            depth += (char == '[') - (char == ']')
            end += 1
        args = text[match.end():end - 1].split(',', 2)
        value = variable(args[0], state) if match[1] == 'VAR' else resolve(args[0], state)
        if value:
            value = (args[1] if len(args) > 1 else '') + value + (args[2] if len(args) > 2 else '')
        text = text[:match.start()] + value + text[end:]


def variable(name, state):
    for value in VARIABLES[name]:
        if condition(value.get('condition', ''), state):
            return expand(value.text or '', state)
    return ''


def plain(text):
    return re.sub(r'\[/?(?:COLOR[^\]]*|UPPERCASE)\]', '', text)


def process(**values):
    return {'player.process(' + key + ')': str(value) for key, value in values.items()}


class PlayerProcessInfoTests(unittest.TestCase):
    def test_omniphony_optional_details(self):
        for sofa, config, expected in (
                ('', '', 'Omniphony'),
                ('Built-in HRIR', '', 'Omniphony (Built-in HRIR)'),
                ('', 'config', 'Omniphony - config'),
                ('Custom BRIR', 'config', 'Omniphony (Custom BRIR) - config')):
            with self.subTest(sofa=sofa, config=config):
                state = process(audiodecoder='om-test', **{'omniphony.sofa': sofa, 'omniphony.config': config})
                self.assertEqual(plain(variable('AudioOutputVar', state)), expected)

    def test_new_and_legacy_audio_output(self):
        for state, expected in (
                (process(audiodecoder='pt-truehd'), 'Passthrough Bitstream'),
                (process(audiodecoder='ff-aac'), 'Decoded PCM'),
                ({'player.passthrough': True}, 'Passthrough'),
                (process(audiochannelssink='PCM 7.1'), 'PCM 7.1'),
                (process(audiodecoder='custom'), 'Decoding | custom')):
            with self.subTest(state=state):
                self.assertEqual(plain(variable('AudioOutputVar', state)), expected)

    def test_audio_layout_priorities(self):
        state = {'videoplayer.audiochannels': '6'}
        self.assertEqual(variable('AudioLayoutVar', state), 'FL, FR, FC, LFE, SL, SR')
        state.update(process(**{'audio.object.layout': '7.1.4'}))
        self.assertEqual(variable('AudioLayoutVar', state), 'FL, FR, FC, LFE, SL, SR')
        state['player.passthrough'] = True
        self.assertEqual(variable('AudioLayoutVar', state), '7.1.4')
        state.update(process(**{'omniphony.input': '7.1.4 + 5 Objects', 'omniphony.render': 'Direct'}))
        self.assertEqual(plain(variable('AudioLayoutVar', state)), '7.1.4 + 5 Objects (Direct)')

    def test_dv_layout_distinguishes_missing_from_absent_el(self):
        for values, expected in (({}, 'Unknown'), ({'video.dovi.el.present': '0'}, 'Single-layer'),
                                 ({'video.dovi.el.present': '1'}, 'Unknown'),
                                 ({'video.dovi.dual.track': 'DT-DL', 'video.dovi.el.present': '1'}, 'DT-DL')):
            with self.subTest(values=values):
                self.assertEqual(plain(variable('DVLayoutVar', process(**values))), expected)

    def test_source_el_only_when_different(self):
        state = process(**{'video.source.dovi.profile': '7', 'video.source.dovi.el.type': 'full',
                           'video.dovi.el.type': 'full', 'video.source.dovi.el.present': '0',
                           'video.dovi.el.present': '0'})
        self.assertEqual(variable('DVSourceELVar', state), '')
        self.assertEqual(variable('ELSourcePresentVar', state), '')
        state.update(process(**{'video.dovi.el.type': 'minimum', 'video.dovi.el.present': '1'}))
        self.assertEqual(plain(variable('DVSourceELVar', state)), 'FEL')
        self.assertIn('■', variable('ELSourcePresentVar', state))
        state.update(process(**{'video.source.dovi.profile': '0'}))
        self.assertEqual(variable('DVSourceELVar', state), '')
        self.assertEqual(variable('ELSourcePresentVar', state), '')
        state.pop('player.process(video.source.dovi.profile)')
        self.assertEqual(variable('DVSourceELVar', state), '')
        self.assertEqual(variable('ELSourcePresentVar', state), '')

    def test_borders_fallback_and_offsets(self):
        self.assertEqual(variable('ActiveBordersVar', {}), 'Unavailable')
        self.assertEqual(variable('ActiveBordersVar', process(**{'video.borders.detected': '0'})), 'Unavailable')
        state = process(**{'video.borders.detected': '1', 'video.borders.left.offset': '0',
                           'video.borders.right.offset': '0', 'video.borders.top.offset': '132',
                           'video.borders.bottom.offset': '132'})
        self.assertEqual(plain(variable('ActiveBordersVar', state)), '0 L | 0 R | 132 T | 132 B')

    def test_optional_luminance_and_lowest_fps(self):
        state = process(**{'amlogic.vs10.mode.raw': '0', 'amlogic.eoft_gamut': 'DV-LL'})
        self.assertEqual(variable('DVSignalTypeVar', state), 'LLDV')
        state.update(process(**{'video.dovi.vsvdb.max.lum': '1000'}))
        self.assertEqual(plain(variable('DVSignalTypeVar', state)), 'LLDV|1000 nits')
        label = next(e.text for e in DIALOG.iter('label') if 'amlogic.video.fps.drop' in (e.text or ''))
        self.assertEqual(expand(label, {}), '')
        self.assertEqual(expand(label, process(**{'amlogic.video.fps.drop': '23.976'})), '> 23.976 fps')

    def test_panel_geometry_and_plextuary_controls(self):
        controls = DIALOG.find('controls')
        self.assertEqual([e.text for e in controls.findall('include')],
                         ['CodecLogosLeftOSD', 'CodecLogosCenterOSD', 'CodecLogosRightOSD'])
        panel = controls.find('control')
        self.assertEqual(panel.findtext('height'), '340')
        self.assertEqual(panel.find('control').findtext('height'), '460')
        self.assertEqual({e.text for e in DIALOG.iter('font')}, {'font10', 'font40'})
        tabs = {e.get('id'): e for e in DIALOG.iter('control') if e.get('id') in ('5551', '5552', '5553')}
        self.assertEqual(set(tabs), {'5551', '5552', '5553'})
        self.assertNotIn('amlogic.vs10.mode', ''.join(e.text or '' for e in tabs['5552'].findall('visible')))
        background = panel.find('control')
        background_bottom = int(background.findtext('top')) + int(background.findtext('height'))
        for group in panel.findall("control[@type='grouplist']"):
            if group.get('id') == '5550':
                continue
            for av1 in (False, True):
                height = 0
                for row in group.findall('control'):
                    visible = ' '.join(e.text or '' for e in row.findall('visible'))
                    # AV1/non-AV1 type rows are mutually exclusive in Kodi.
                    if 'String.IsEqual(VideoPlayer.VideoCodec,av1)' in visible:
                        if av1 == ('!String.IsEqual(VideoPlayer.VideoCodec,av1)' in visible):
                            continue
                    height += int(row.findtext('height', '0'))
                self.assertLessEqual(int(group.findtext('top')) + height, background_bottom)

    def test_rearranged_rows_and_readable_vp_state(self):
        labels = [e.text for e in DIALOG.iter('label')]
        for label in ('- decoder:', '- deint:', '- borders:', 'VS10 mode:', 'VP mode:', 'Module:', 'Layout:'):
            self.assertIn('[COLOR button_focus]' + label + '[/COLOR]', labels)
        self.assertEqual(variable('VPModeVar', process(**{'video.vpmode': '1'})), 'Enabled')
        self.assertEqual(variable('VPModeVar', process(**{'video.vpmode': '0'})), 'Disabled')
        self.assertEqual(plain(variable('L5StateVar', process(**{'video.dovi.l5.auto': '1'}))), 'Auto (letterbox)')
        self.assertEqual(plain(variable('L5StateVar', process(**{'video.dovi.l5.detect.state': '2'}))), 'Skipped (VAR)')

    def test_xml_and_ppi_dependencies(self):
        for path in (ROOT / 'xml').glob('*.xml'):
            with self.subTest(path=path.name):
                ET.parse(path)
        for control in DIALOG.iter('control'):
            self.assertFalse((control.text or '').strip(), 'Unexpected literal text inside a control')
        text = ET.tostring(DIALOG, encoding='unicode')
        for name in re.findall(r'\$VAR\[([^],]+)', text):
            self.assertIn(name, VARIABLES)
        self.assertEqual(len(VARIABLES), len(ET.parse(ROOT / 'xml/Variables.xml').getroot()))
        for name in ('AudioOutputVar', 'AudioLayoutVar', 'DVSourceELVar', 'ELSourcePresentVar',
                     'DVLayoutVar', 'ActiveBordersVar', 'VPModeVar', 'DVSignalTypeVar'):
            for value in VARIABLES[name]:
                expression = value.get('condition', '')
                self.assertEqual(expression.count('('), expression.count(')'), (name, expression))


if __name__ == '__main__':
    unittest.main()
