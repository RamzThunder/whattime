import base64
import hashlib
import hmac
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import comci_client as c


def obfuscate(js, key=83):
    chunk = ''.join(f'{ord(ch) ^ ((key + i * 13) & 255):04X}' for i, ch in enumerate(js))
    return ("/* hour-obfuscated-v2 */(function(a,k){var s='',i,j,b;(0,eval)(s);})("
            + json.dumps([[0, chunk]]) + f",{key});")


PAGE_JS = (
    "window.__HourRequestToken='ABC123';"
    "function QAjaxSchool(sc, success) { return $.ajax({ url:'./111?'+encodeURIComponent(btoa('222l'+encodeURIComponent(sc)+'_enc5')) }); }"
    "function QAjaxTimetable(sc, sc2, da1, r, success) { return $.ajax({ url:'./111_T?'+btoa(sc+sc2) }); }"
    "sc_data('333_',storage.Tsc,1,'1');"
    "var key=CryptoJS.enc.Hex.parse((function(a){return a[1]+a[0];})(['" + '22' * 16 + "','" + '11' * 16 + "']));"
    "var r=Math.floor(학교명단[i][0]/100)+2;"
    "p+=자료.자료9[교사]+\" 시간표\"; 교사자료=Q자료(자료.자료8[교사][요일][교시]);"
    "과목명=Q과목명(자료.자료7[sb]); $('#수정일').text('수정일: '+H시간표.자료6);"
)


class FakePage(c._Page):
    def __init__(self, html):
        self._html = html
        super().__init__(opener=None, path='th', timeout=1)

    def _get(self, url, ajax=True):
        return self._html.encode('euc-kr')


class AesTest(unittest.TestCase):
    def test_fips197_vectors(self):
        plain = bytes.fromhex('00112233445566778899aabbccddeeff')
        cases = [(16, '69c4e0d86a7b0430d8cdb78070b4c55a'), (32, '8ea2b7ca516745bfeafc49904b496089')]
        for size, ct in cases:
            keys = c._expand_key(bytes(range(size)))
            self.assertEqual(c._decrypt_block(keys, bytes.fromhex(ct)), plain)

    def test_rejects_bad_padding(self):
        with self.assertRaises(c.ComciError):
            c._aes_cbc_decrypt(bytes(32), bytes(16), bytes(16))


class PageTest(unittest.TestCase):
    def test_reads_values_from_nested_obfuscated_page(self):
        page = FakePage('<script>' + obfuscate(obfuscate(PAGE_JS), key=100) + '</script>')
        self.assertEqual(page.token, 'ABC123')
        self.assertEqual(page.timetable_path, '111_T')
        self.assertEqual((page.search_path, page.search_prefix), ('111', '222l'))
        self.assertEqual(page.school_prefix, '333_')
        self.assertEqual(page.key, bytes.fromhex('11' * 16 + '22' * 16))
        self.assertEqual(page.code_index, (100, 2))
        self.assertEqual(page.fields, {'teachers': '자료9', 'teacher_slots': '자료8',
                                       'subjects': '자료7', 'updated_at': '자료6'})

    def test_decrypt_checks_hmac(self):
        page = FakePage('<script>' + PAGE_JS + '</script>')
        iv, ct = base64.b64encode(bytes(16)).decode(), base64.b64encode(bytes(16)).decode()
        head = f'enc5:{iv}:{ct}'
        tag = base64.b64encode(hmac.new(hashlib.sha256(page.key).digest(), head.encode(),
                                        hashlib.sha256).digest()).decode()
        with self.assertRaises(c.ComciError):
            page.decrypt(head + ':' + 'A' * len(tag))
        with self.assertRaises(c.ComciError):  # HMAC 통과 후 패딩 검사에서 막힌다.
            page.decrypt(head + ':' + tag)

    def test_plain_text_passes_through(self):
        page = FakePage('<script>' + PAGE_JS + '</script>')
        self.assertEqual(page.decrypt('{}'), '{}')

    def test_decode_json_ignores_trailing_bytes(self):
        self.assertEqual(c._decode_json('{"a": 1}\x00\x00junk'), {'a': 1})


if __name__ == '__main__':
    unittest.main()
