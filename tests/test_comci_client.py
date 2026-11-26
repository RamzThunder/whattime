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

# 2026-11 중순 형식: 글자 자료를 QnmsbChange로 감싼다.
TEXT_KEY = [112, 53, 35, 89, 107, 68, 112, 64, 108, 77, 47, 104]
PAGE_JS_V2 = PAGE_JS.replace("p+=자료.자료9[교사]+", "p+=QnmsbChange(자료.자료9[교사])+").replace(
    "'수정일: '+H시간표.자료6", "'수정일: '+QnmsbChange(H시간표.자료6)") + (
    "function QnmsbChange(암호문) { if(암호문==undefined) return ''; var 키=String.fromCharCode("
    + ",".join(map(str, TEXT_KEY)) + "); var 바이트문자열=atob(암호문); }"
)


# 2026-11 말 형식: 함수·자료 이름이 무작위, POST 본문 요청, 암호문 머리말 '3901'.
PAGE_JS_V3 = (
    "window.__HourRequestToken='ABC123';var Q웹보호안내중 = false,Qa='POST';"
    "function sMw3(sc, success) {var s7='15604l'+encodeURIComponent(sc);"
    "    return $.ajax({ url:'./723392', method:Qa, contentType:'text/plain; charset=UTF-8',"
    "        data:encodeURIComponent(btoa(s7+'_3901')),"
    "        headers:{'X-Hour-Token':window.__HourRequestToken || ''}, dataType:'text', success:success });}"
    "function t2d0(sc, sc2, da1, r, success) {    var s7=sc+sc2,s8=s7+'_'+da1;"
    "    return $.ajax({ url:'./723392_T', method:Qa, contentType:'text/plain; charset=UTF-8',"
    "        data:btoa(s8+'_'+r+'_3901'),"
    "        headers:{'X-Hour-Token':window.__HourRequestToken || ''}, dataType:'text', success:success });}"
    "function Zfy3(sc,sc2,r,nw){var da1='0';}"
    "function nal_change(){Zfy3('38583_',sc,r,'0');}"
    "var useBase64=(parts[0]==='3901');"
    "var key=CryptoJS.enc.Hex.parse((function(a){return a[1]+a[0];})(['" + '22' * 16 + "','" + '11' * 16 + "']));"
    "function y2IS(data) { if(data==undefined || data==='') return '';"
    " var a1=String.fromCharCode(" + ",".join(map(str, [112, 53, 35, 89, 107, 68, 112, 64, 108, 77, 47, 104]))
    + "); var a2=atob(data); }"
    "var r=Math.floor(H학교명단.학교검색[i][0]/6347)+2;"
    "function 교사명_설정하기(자료,n){for(var i=1;i<=자료.교사수;i++) {p+=y2IS(자료.CMO684[i]);}}"
    "교사자료=o8WY(자료.BVX152[교사][요일][교시]);과목명=eC0C(자료.TIV461[sb]);"
    "$('#수정일').text('수정일: '+y2IS(o31i.ZWT390));"
)


def wrap_text(text):
    raw = text.encode('euc-kr')
    return base64.b64encode(bytes(b ^ TEXT_KEY[i % len(TEXT_KEY)] for i, b in enumerate(raw))).decode()


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

    def test_reads_wrapped_text_fields(self):
        page = FakePage('<script>' + obfuscate(PAGE_JS_V2) + '</script>')
        self.assertEqual(page.text_key, bytes(TEXT_KEY))
        self.assertEqual(page.fields, {'teachers': '자료9', 'teacher_slots': '자료8',
                                       'subjects': '자료7', 'updated_at': '자료6'})
        self.assertEqual(page.text(wrap_text('조암중학교')), '조암중학교')
        self.assertEqual(page.text(wrap_text('84946')), '84946')
        self.assertEqual(page.text(''), '')
        self.assertEqual(page.text(0), 0)

    def test_reads_randomized_post_page(self):
        page = FakePage('<script>' + obfuscate(PAGE_JS_V3) + '</script>')
        self.assertEqual(page.token, 'ABC123')
        self.assertEqual(page.timetable_path, '723392_T')
        self.assertEqual((page.search_path, page.search_prefix), ('723392', '15604l'))
        self.assertEqual(page.timetable['method'], 'POST')
        self.assertEqual(page.timetable['suffix'], '_3901')
        self.assertFalse(page.timetable['quote'])
        self.assertTrue(page.search['quote'])
        self.assertEqual(page.school_prefix, '38583_')
        self.assertEqual(page.key, bytes.fromhex('11' * 16 + '22' * 16))
        self.assertEqual(page.b64_tags, {'enc5', '3901'})
        self.assertEqual(page.text_key, bytes(TEXT_KEY))
        self.assertEqual(page.code_index, (6347, 2))
        self.assertEqual(page.fields, {'teachers': 'CMO684', 'teacher_slots': 'BVX152',
                                       'subjects': 'TIV461', 'updated_at': 'ZWT390'})

    def test_posts_payload_in_body(self):
        page = FakePage('<script>' + obfuscate(PAGE_JS_V3) + '</script>')
        sent = []
        page._get = lambda url, ajax=True, body=None: sent.append((url, body)) or b'{}'
        page.request(page.timetable, '38583_84946_0_1')
        self.assertEqual(sent, [(c.BASE_URL + '/723392_T',
                                 base64.b64encode(b'38583_84946_0_1_3901').decode())])

    def test_text_passes_through_without_key(self):
        page = FakePage('<script>' + PAGE_JS + '</script>')
        self.assertIsNone(page.text_key)
        self.assertEqual(page.text('국어'), '국어')

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
