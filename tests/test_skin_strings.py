"""Offline skin localization checks: python3 -m unittest discover -s tests.

These validate string catalogs/references, not native CE22 GUI rendering.
"""
import ast
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = {
    31302: 'Open Sans (needs McFontFace)',
    31303: 'Hind (needs McFontFace)',
    31304: 'PT Sans (needs McFontFace)',
    31305: 'Inter (needs McFontFace)',
    31306: 'Lato (needs McFontFace)',
    31307: 'DejaVu Sans (needs McFontFace)',
    31308: 'Source Sans 3 (needs McFontFace)',
    31309: 'Noto Sans (old default, bundled)',
    31310: 'Inter UI (default, bundled)',
    31311: 'Exit Menu customization',
    31312: 'Show backdrop on pause',
    31313: 'Show Restart Kodi option in exit menu',
}


def catalog(text):
    """Read active entries and join PO continuations; ignore obsolete entries."""
    result, entry, field = {}, None, None
    for line in text.splitlines():
        match = re.fullmatch(r'msgctxt "#(\d+)"', line)
        if match:
            ident = int(match[1])
            if ident in result:
                raise AssertionError('Duplicate active string ID: %d' % ident)
            entry = result[ident] = {}
            field = None
        elif entry is not None:
            match = re.fullmatch(r'(msgid|msgstr) (".*")', line)
            if match:
                field = match[1]
                entry[field] = ast.literal_eval(match[2])
            elif line.startswith('"') and field:
                entry[field] += ast.literal_eval(line)
    return result


class SkinStringTests(unittest.TestCase):
    def test_catalogs_use_skin_range_and_unique_ids(self):
        for path in ROOT.glob('language/*/strings.po'):
            with self.subTest(language=path.parent.name):
                entries = catalog(path.read_text())
                self.assertTrue(entries)
                self.assertTrue(all(31000 <= ident <= 31999 for ident in entries))
                for entry in entries.values():
                    self.assertIn('msgid', entry)
                    self.assertIn('msgstr', entry)

    def test_fork_labels_keep_ce_custom_builds_meanings(self):
        english = catalog((ROOT / 'language/resource.language.en_gb/strings.po').read_text())
        german = catalog((ROOT / 'language/resource.language.de_de/strings.po').read_text())
        for ident, text in EXPECTED.items():
            with self.subTest(ident=ident):
                self.assertEqual(english[ident]['msgid'], text)
                self.assertEqual(german[ident]['msgid'], text)
                self.assertTrue(german[ident]['msgstr'])

    def test_font_names_use_matching_label_ids(self):
        fonts = ET.parse(ROOT / 'xml/Font.xml').getroot()
        expected = {'Default': '31310', 'OpenSans': '31302', 'Hind-Regular': '31303',
                    'PTSans-Regular': '31304', 'Inter': '31305', 'NotoSans': '31309',
                    'Lato': '31306', 'DejaVuSans': '31307', 'SourceSans3': '31308', 'Arial': '31053'}
        self.assertEqual({font.get('id'): font.get('idloc') for font in fonts}, expected)

    def test_xml_localizations_resolve_and_control_ids_stay_separate(self):
        english = catalog((ROOT / 'language/resource.language.en_gb/strings.po').read_text())
        for path in ROOT.glob('xml/*.xml'):
            with self.subTest(path=path.name):
                tree = ET.parse(path)
                text = path.read_text()
                ids = [int(ident) for ident in re.findall(r'\$LOCALIZE\[(\d+)\]', text)]
                for node in tree.iter():
                    if node.get('idloc', '').isdigit():
                        ids.append(int(node.get('idloc')))
                    if node.tag == 'label' and (node.text or '').strip().isdigit():
                        ids.append(int(node.text))
                for ident in ids:
                    if 31000 <= ident <= 32999:
                        self.assertLessEqual(ident, 31999)
                        self.assertIn(ident, english)
        settings = (ROOT / 'xml/SkinSettings.xml').read_text()
        for ident in (31311, 31312, 31313):
            self.assertIn('$LOCALIZE[%d]' % ident, settings)
        includes = (ROOT / 'xml/Includes.xml').read_text()
        self.assertIn('<control type="image" id="32111">', includes)
        self.assertIn('Control.IsVisible(32111)', includes)

    def test_parser_joins_continuations_and_ignores_obsolete_entries(self):
        text = 'msgctxt "#31312"\nmsgid "Show backdrop "\n"on pause"\nmsgstr "Hintergrund "\n"anzeigen"\n\n#~ msgctxt "#31312"\n#~ msgid "old"\n'
        self.assertEqual(catalog(text), {31312: {'msgid': 'Show backdrop on pause', 'msgstr': 'Hintergrund anzeigen'}})


if __name__ == '__main__':
    unittest.main()
