"""컴시간알리미 서버와 통신한다.

컴시간은 2026-11부터 요청마다 페이지에서 받은 토큰(X-Hour-Token)을 요구하고,
응답을 AES-256-CBC + HMAC-SHA256으로 암호화해서 보낸다. 요청 주소 번호와 키는
난독화된 페이지 스크립트 안에 들어 있고 바뀔 수 있어서, 매번 페이지에서 읽어 온다.
"""
import base64
import hashlib
import hmac
import http.cookiejar
import urllib.error
import json
import re
import urllib.parse
import urllib.request

BASE_URL = 'http://comci.net:4082'
USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
              '(KHTML, like Gecko) Version/17.0 Safari/605.1.15')

_OBFUSCATED = re.compile(
    r"/\* hour-[a-z-]*obfuscated-v\d+ \*/\(function\(a,k\)\{.*?\(0,eval\)\(s\);\}\)\((\[\[.*?\]\]),(\d+)\);",
    re.S,
)


class ComciError(Exception):
    pass


def _deobfuscate(html):
    def decode(match):
        parts, key = json.loads(match.group(1)), int(match.group(2))
        out = []
        for plain, chunk in parts:
            if plain:
                out.append(chunk)
                continue
            for j in range(0, len(chunk), 4):
                out.append(chr(int(chunk[j:j + 4], 16) ^ ((key + (j // 4) * 13) & 255)))
        return ''.join(out)

    for _ in range(10):  # 스크립트가 여러 겹으로 감싸져 있다.
        decoded = _OBFUSCATED.sub(decode, html)
        if decoded == html:
            break
        html = decoded
    return html


def _search(pattern, text, what):
    match = re.search(pattern, text, re.S)
    if not match:
        raise ComciError(f'컴시간 페이지 구조가 바뀌어 {what}을(를) 찾지 못했습니다.')
    return match


class _Page:
    """컴시간 페이지 하나에서 읽어 낸 토큰·주소·키."""

    def __init__(self, opener, path, timeout):
        self.opener = opener
        self.timeout = timeout
        self.referer = f'{BASE_URL}/{path}'
        raw = self._get(self.referer, ajax=False)
        html = _deobfuscate(raw.decode('euc-kr', errors='replace'))

        self.token = _search(r"__HourRequestToken\s*=\s*'([^']+)'", html, '접속 토큰').group(1)
        self.timetable_path = _search(
            r"function QAjaxTimetable\(.*?url:'\./([^'?]+)\?", html, '시간표 주소').group(1)
        self.school_prefix = _search(r"sc_data\('(\d+_)'", html, '학교 코드 앞자리').group(1)
        search = re.search(r"function QAjaxSchool\(.*?url:'\./([^'?]+)\?.*?btoa\('([^']+)'", html, re.S)
        self.search_path, self.search_prefix = search.groups() if search else (None, None)

        key = _search(
            r"var key=CryptoJS\.enc\.Hex\.parse\(\(function\(a\)\{return ([a\[\]\d+]+);\}\)\((\[[^\]]+\])\)\)",
            html, '복호화 키')
        pieces = json.loads(key.group(2).replace("'", '"'))
        order = [int(i) for i in re.findall(r'a\[(\d+)\]', key.group(1))]
        self.key = bytes.fromhex(''.join(pieces[i] for i in order))

        # 검색 결과의 숫자 중 진짜 학교코드 위치: floor(항목[0] / 나눗수) + 더할수
        code_at = re.search(r"Math\.floor\(학교명단\[i\]\[0\]/(\d+)\)\+(\d+)", html)
        self.code_index = (int(code_at.group(1)), int(code_at.group(2))) if code_at else None

        # 응답 속 자료 이름(자료NNN)은 페이지 버전마다 바뀐다.
        def field(pattern, default):
            match = re.search(pattern, html)
            return match.group(1) if match else default
        self.fields = {
            'teachers': field(r"자료\.(자료\d+)\[교사\]\+\" 시간표", '자료148'),
            'teacher_slots': field(r"교사자료=Q자료\(자료\.(자료\d+)\[교사\]", '자료171'),
            'subjects': field(r"과목명=Q과목명\(자료\.(자료\d+)\[sb\]\)", '자료175'),
            'updated_at': field(r"'수정일: '\+H시간표\.(자료\d+)", '자료158'),
        }

    def _get(self, url, ajax=True):
        headers = {'User-Agent': USER_AGENT, 'Accept': '*/*'}
        if ajax:
            headers.update({
                'Referer': self.referer,
                'X-Requested-With': 'XMLHttpRequest',
                'X-Hour-Token': self.token,
            })
        req = urllib.request.Request(url, headers=headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            body = error.read().decode('utf-8', errors='replace').strip()
            if error.code == 429 or body == 'HOUR_RATE_LIMIT':
                raise ComciError('컴시간 요청이 많습니다. 1분 후 다시 시도해 주세요.') from error
            if error.code == 503 or body == 'HOUR_SERVICE_BUSY':
                raise ComciError('컴시간 서버가 혼잡합니다. 잠시 후 다시 시도해 주세요.') from error
            if body == 'HOUR_TOKEN_REQUIRED':
                raise ComciError('컴시간 접속 확인에 실패했습니다. 잠시 후 다시 시도해 주세요.') from error
            raise

    def request(self, path, query):
        raw = self._get(f'{BASE_URL}/{path}?{query}')
        return self.decrypt(raw.decode('utf-8', errors='replace').rstrip('\x00 \t\r\n'))

    def decrypt(self, text):
        if not (text.startswith('enc5:') or text.startswith('enc1:')):
            return text
        parts = text.split(':')
        if len(parts) != 4:
            raise ComciError('컴시간 응답 형식이 올바르지 않습니다.')
        decode = base64.b64decode if parts[0] == 'enc5' else bytes.fromhex
        iv, ciphertext = decode(parts[1]), decode(parts[2])
        tag = hmac.new(hashlib.sha256(self.key).digest(), ':'.join(parts[:3]).encode('ascii'),
                       hashlib.sha256).digest()
        expected = base64.b64encode(tag).decode() if parts[0] == 'enc5' else tag.hex()
        if not hmac.compare_digest(expected, parts[3]):
            raise ComciError('컴시간 응답 검증에 실패했습니다.')
        plain = _aes_cbc_decrypt(self.key, iv, ciphertext)
        return plain.decode('utf-8', errors='replace').rstrip('\x00')


def _opener():
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def _decode_json(text):
    """응답 끝에 쓰레기 값이 붙어 오기도 해서 마지막 '}'까지만 읽는다."""
    text = text.strip('\x00 \t\r\n')
    end = text.rfind('}')
    if end < 0:
        raise ComciError('컴시간 응답을 읽을 수 없습니다.')
    return json.loads(text[:end + 1])


def fetch_teacher_data(school_code, timeout=10):
    """이번 주 교사용 시간표를 받아 필요한 자료만 이름을 붙여 돌려준다.

    첫 응답의 '오늘r'이 1이 아니면 같은 토큰으로 그 주를 다시 받는다.
    """
    page = _Page(_opener(), 'th', timeout)

    def get(index):
        payload = f'{page.school_prefix}{int(school_code)}_0_{int(index)}_enc5'
        query = base64.b64encode(payload.encode('ascii')).decode('ascii')
        return _decode_json(page.request(page.timetable_path, query))

    data = get(1)
    if not isinstance(data, dict) or not data:
        raise ComciError('학교코드를 확인할 수 없거나 시간표 자료가 없습니다.')
    today_index = int(data.get('오늘r') or 1)
    if today_index != 1:
        data = get(today_index)

    f = page.fields
    if f['teacher_slots'] not in data or f['teachers'] not in data:
        raise ComciError('컴시간 자료 형식이 바뀌어 교사 시간표를 찾지 못했습니다.')
    return {
        'school_name': str(data.get('학교명') or ''),
        'teachers': data.get(f['teachers']) or [],
        'teacher_slots': data.get(f['teacher_slots']) or [],
        'subjects': data.get(f['subjects']) or [],
        'updated_at': str(data.get(f['updated_at']) or ''),
    }


def search_schools(query, timeout=10):
    """[{'region', 'school_name', 'school_code'}] 목록."""
    page = _Page(_opener(), 'st', timeout)
    if not page.search_path:
        raise ComciError('컴시간 페이지 구조가 바뀌어 학교 검색 주소를 찾지 못했습니다.')
    payload = page.search_prefix + urllib.parse.quote(query, safe="-_.!~*'()") + '_enc5'
    encoded = urllib.parse.quote(base64.b64encode(payload.encode('ascii')).decode('ascii'), safe='')
    data = _decode_json(page.request(page.search_path, encoded))

    results = []
    for item in (data or {}).get('학교검색', []):
        if len(item) < 4 or item[1] == '알림':
            continue
        if page.code_index:
            divisor, offset = page.code_index
            index = int(item[0]) // divisor + offset
        else:
            index = 3
        if index < len(item) and item[index]:
            results.append({'region': str(item[1]), 'school_name': str(item[2]),
                            'school_code': int(item[index])})
    return results


# ---- AES-256 복호화 (외부 라이브러리 없이) ----

def _xtime(a):
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _build_tables():
    sbox = [0] * 256
    p = q = 1
    while True:  # GF(2^8)에서 역원과 아핀 변환으로 S-box를 만든다.
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ ((q << 1 | q >> 7) & 0xFF) ^ ((q << 2 | q >> 6) & 0xFF) \
            ^ ((q << 3 | q >> 5) & 0xFF) ^ ((q << 4 | q >> 4) & 0xFF)
        sbox[p] = x ^ 0x63
        if p == 1:
            break
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, inv


_SBOX, _INV_SBOX = _build_tables()


def _mul(a, b):
    result = 0
    while b:
        if b & 1:
            result ^= a
        a = _xtime(a)
        b >>= 1
    return result


_MUL = {n: [_mul(i, n) for i in range(256)] for n in (9, 11, 13, 14)}


def _expand_key(key):
    nk = len(key) // 4
    rounds = nk + 6
    words = [list(key[i:i + 4]) for i in range(0, len(key), 4)]
    rcon = 1
    for i in range(nk, 4 * (rounds + 1)):
        t = list(words[i - 1])
        if i % nk == 0:
            t = [_SBOX[b] for b in t[1:] + t[:1]]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        words.append([a ^ b for a, b in zip(words[i - nk], t)])
    return [sum(words[r * 4:r * 4 + 4], []) for r in range(rounds + 1)]


def _decrypt_block(round_keys, block):
    s = [b ^ k for b, k in zip(block, round_keys[-1])]
    m9, m11, m13, m14 = _MUL[9], _MUL[11], _MUL[13], _MUL[14]
    for r in range(len(round_keys) - 2, -1, -1):
        # InvShiftRows + InvSubBytes (상태는 열 우선 순서)
        s = [_INV_SBOX[s[(i + 4 * (i % 4) * 3) % 16]] for i in range(16)]
        s = [b ^ k for b, k in zip(s, round_keys[r])]
        if r == 0:
            break
        out = []
        for c in range(4):
            a0, a1, a2, a3 = s[4 * c:4 * c + 4]
            out += [
                m14[a0] ^ m11[a1] ^ m13[a2] ^ m9[a3],
                m9[a0] ^ m14[a1] ^ m11[a2] ^ m13[a3],
                m13[a0] ^ m9[a1] ^ m14[a2] ^ m11[a3],
                m11[a0] ^ m13[a1] ^ m9[a2] ^ m14[a3],
            ]
        s = out
    return bytes(s)


def _aes_cbc_decrypt(key, iv, data):
    if len(key) not in (16, 24, 32) or len(iv) != 16 or not data or len(data) % 16:
        raise ComciError('컴시간 응답 크기가 올바르지 않습니다.')
    round_keys = _expand_key(key)
    out = bytearray()
    prev = iv
    for i in range(0, len(data), 16):
        block = data[i:i + 16]
        out += bytes(a ^ b for a, b in zip(_decrypt_block(round_keys, block), prev))
        prev = block
    pad = out[-1]
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ComciError('컴시간 응답 복호화에 실패했습니다.')
    return bytes(out[:-pad])
