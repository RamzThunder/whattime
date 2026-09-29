"""Read school bell schedules from local HWPX and HWP 5 documents."""
import os
import re
import struct
import zlib

def _xml_local_name(tag):
    return str(tag).rsplit('}', 1)[-1]

def _hwpx_element_text(element):
    pieces = []
    for node in element.iter():
        if _xml_local_name(node.tag) == 't' and node.text:
            text = ' '.join(node.text.split())
            if text:
                pieces.append(text)
    return ' '.join(pieces).strip()

def _hwpx_table_rows(root):
    tables = []
    for table in root.iter():
        if _xml_local_name(table.tag) != 'tbl':
            continue
        rows = []
        for row in table.iter():
            if _xml_local_name(row.tag) != 'tr':
                continue
            cells = [
                _hwpx_element_text(cell)
                for cell in row.iter()
                if _xml_local_name(cell.tag) == 'tc'
            ]
            cells = [cell for cell in cells if cell]
            if cells:
                rows.append(cells)
        if rows:
            tables.append(rows)
    return tables

def _schedule_entry_from_hwpx_row(cells, fallback_period):
    import re
    time_pattern = re.compile(r'(?<!\d)([01]?\d|2[0-3])\s*[:：]\s*([0-5]\d)(?!\d)')
    joined = ' | '.join(cells)
    matches = list(time_pattern.finditer(joined))
    if len(matches) < 2:
        return None

    start_hour, start_minute = map(int, matches[0].groups())
    end_hour, end_minute = map(int, matches[1].groups())
    start_total = start_hour * 60 + start_minute
    end_total = end_hour * 60 + end_minute
    if end_total <= start_total or end_total - start_total > 180:
        return None

    label_candidates = []
    for cell in cells:
        without_times = time_pattern.sub(' ', cell)
        without_times = re.sub(r'\b\d+\s*분\b', ' ', without_times)
        cleaned = re.sub(r'[~∼〜～\-–—:：|()\[\]]+', ' ', without_times)
        cleaned = ' '.join(cleaned.split()).strip()
        if cleaned:
            label_candidates.append(cleaned)

    label = ''
    for candidate in label_candidates:
        if re.search(r'\d+\s*교시|점심|조회|종례|청소|수업|행사|활동', candidate):
            label = candidate
            break
    if not label and label_candidates:
        label = label_candidates[0]
    if re.fullmatch(r'\d+', label):
        label += '교시'
    if not label or label in ('구분', '시간', '시정', '일정'):
        label = f'{fallback_period}교시'

    return {
        'name': label,
        'start': f'{start_hour:02d}:{start_minute:02d}',
        'end': f'{end_hour:02d}:{end_minute:02d}',
    }

def _schedule_from_hwpx_rows(rows):
    schedule = []
    seen = set()
    for cells in rows:
        entry = _schedule_entry_from_hwpx_row(cells, len(schedule) + 1)
        if not entry:
            continue
        key = (entry['name'], entry['start'], entry['end'])
        if key in seen:
            continue
        seen.add(key)
        schedule.append(entry)
    return schedule

def parse_hwpx_schedule(path):
    import zipfile
    import xml.etree.ElementTree as ET

    if not str(path).lower().endswith('.hwpx'):
        raise ValueError('HWPX 파일을 선택해 주세요.')
    if os.path.getsize(path) > 50 * 1024 * 1024:
        raise ValueError('HWPX 파일이 너무 큽니다. 50MB 이하 파일을 선택해 주세요.')

    tables = []
    paragraph_rows = []
    total_xml_size = 0
    try:
        with zipfile.ZipFile(path, 'r') as archive:
            section_names = sorted(
                name for name in archive.namelist()
                if name.startswith('Contents/section') and name.lower().endswith('.xml')
            )
            if not section_names:
                raise ValueError('HWPX 본문을 찾을 수 없습니다.')
            for name in section_names:
                info = archive.getinfo(name)
                total_xml_size += info.file_size
                if total_xml_size > 20 * 1024 * 1024:
                    raise ValueError('HWPX 본문이 너무 큽니다.')
                root = ET.fromstring(archive.read(name))
                tables.extend(_hwpx_table_rows(root))
                for paragraph in root.iter():
                    if _xml_local_name(paragraph.tag) == 'p':
                        text = _hwpx_element_text(paragraph)
                        if text:
                            paragraph_rows.append([text])
    except zipfile.BadZipFile:
        raise ValueError('올바른 HWPX 파일이 아닙니다.')
    except ET.ParseError:
        raise ValueError('HWPX 본문 XML을 읽을 수 없습니다.')

    candidates = [_schedule_from_hwpx_rows(rows) for rows in tables]
    candidates = [schedule for schedule in candidates if schedule]
    schedule = max(candidates, key=len) if candidates else _schedule_from_hwpx_rows(paragraph_rows)
    if len(schedule) < 2:
        raise ValueError('교시명과 시작·종료 시각이 있는 시정표를 찾지 못했습니다.')
    return schedule


# HWP 5 record structure: Hancom's public file-format specification.
MAX_BODY = 20 * 1024 * 1024


def _hwp_records(data):
    offset = 0
    while offset < len(data):
        if offset + 4 > len(data):
            raise ValueError('HWP 본문 레코드가 손상되었어요.')
        header, = struct.unpack_from('<I', data, offset)
        offset += 4
        tag, level, size = header & 1023, (header >> 10) & 1023, header >> 20
        if size == 4095:
            if offset + 4 > len(data):
                raise ValueError('HWP 본문 레코드가 손상되었어요.')
            size, = struct.unpack_from('<I', data, offset)
            offset += 4
        if offset + size > len(data):
            raise ValueError('HWP 본문 레코드가 손상되었어요.')
        yield tag, level, data[offset:offset + size]
        offset += size


def _hwp_text(data):
    # Inline/extended controls occupy eight UTF-16 code units, not visible text.
    output = bytearray()
    offset = 0
    while offset + 2 <= len(data):
        code, = struct.unpack_from('<H', data, offset)
        if 1 <= code <= 23 and code not in (10, 13):
            output.extend(b' \x00')
            offset += 16
        else:
            output.extend(data[offset:offset + 2] if code >= 32 else b' \x00')
            offset += 2
    return ' '.join(output.decode('utf-16le', errors='replace').split())


def _hwp_rows(data):
    tables, stack, paragraphs = [], [], []
    for tag, level, payload in _hwp_records(data):
        while stack and level <= stack[-1]['level']:
            stack.pop()
        if tag == 71 and payload[:4] == b' lbt':
            table = {'level': level, 'rows': {}, 'cell': None, 'body': False}
            stack.append(table)
            tables.append(table)
        elif stack and tag == 77 and level == stack[-1]['level'] + 1:
            stack[-1]['body'] = True
        elif stack and tag == 72 and level == stack[-1]['level'] + 1:
            table = stack[-1]
            table['cell'] = None
            # Modern HWP list header is 8 bytes, followed by cell geometry.
            if table['body'] and len(payload) >= 34:
                col, row, colspan, rowspan = struct.unpack_from('<HHHH', payload, 8)
                if colspan and rowspan:
                    table['cell'] = table['rows'].setdefault(row, {}).setdefault(col, [])
        elif tag == 67:
            text = _hwp_text(payload)
            if text:
                if stack and stack[-1]['cell'] is not None:
                    stack[-1]['cell'].append(text)
                elif not stack:
                    paragraphs.append([text])
    rows = [[[ ' '.join(cells[col]) for col in sorted(cells)]
             for _, cells in sorted(table['rows'].items())] for table in tables]
    return rows, paragraphs


def _hwp_body(raw, compressed, limit):
    if not compressed:
        if len(raw) > limit:
            raise ValueError('HWP 본문이 너무 큽니다.')
        return raw
    decoder = zlib.decompressobj(-15)
    try:
        body = decoder.decompress(raw, limit + 1)
    except zlib.error:
        raise ValueError('HWP 본문 압축을 읽지 못했어요.') from None
    if len(body) > limit or decoder.unconsumed_tail:
        raise ValueError('HWP 본문이 너무 큽니다.')
    if not decoder.eof:
        raise ValueError('HWP 본문 압축이 손상되었어요.')
    return body


def parse_hwp_schedule(path):
    import olefile
    if os.path.getsize(path) > 50 * 1024 * 1024:
        raise ValueError('50MB 이하 파일을 선택해 주세요.')
    if not olefile.isOleFile(path):
        raise ValueError('HWP 5 형식이 아니에요. 한글에서 HWPX로 저장한 뒤 불러오세요.')
    try:
        with olefile.OleFileIO(path) as document:
            header = document.openstream('FileHeader').read(256)
            if len(header) < 40 or not header.startswith(b'HWP Document File') or header[35] != 5:
                raise ValueError('지원하지 않는 HWP 형식이에요. HWPX로 저장한 뒤 불러오세요.')
            flags, = struct.unpack_from('<I', header, 36)
            if flags & (2 | 4):
                raise ValueError('암호 또는 배포용 HWP 문서는 읽을 수 없어요. 편집 가능한 HWPX로 저장해 주세요.')
            sections = sorted((p for p in document.listdir() if len(p) == 2 and p[0] == 'BodyText'
                               and re.fullmatch(r'Section\d+', p[1])), key=lambda p: int(p[1][7:]))
            candidates, paragraphs, total = [], [], 0
            for section in sections:
                if document.get_size(section) > MAX_BODY:
                    raise ValueError('HWP 본문이 너무 큽니다.')
                raw = document.openstream(section).read()
                body = _hwp_body(raw, bool(flags & 1), MAX_BODY - total)
                total += len(body)
                tables, text = _hwp_rows(body)
                candidates.extend(_schedule_from_hwpx_rows(rows) for rows in tables)
                paragraphs.extend(text)
    except (OSError, IOError, struct.error):
        raise ValueError('HWP 파일을 읽지 못했어요. HWPX로 저장한 뒤 다시 불러오세요.') from None
    candidates = [s for s in candidates if s]
    result = max(candidates, key=len) if candidates else _schedule_from_hwpx_rows(paragraphs)
    if len(result) < 2:
        raise ValueError('시정표를 찾지 못했어요. 교시명과 시작·종료 시각이 있는 표인지 확인하거나 HWPX로 저장해 주세요.')
    return result


def parse_schedule_document(path):
    suffix = os.path.splitext(str(path))[1].lower()
    if suffix == '.hwpx':
        return parse_hwpx_schedule(path)
    if suffix == '.hwp':
        return parse_hwp_schedule(path)
    raise ValueError('HWP 또는 HWPX 파일을 선택해 주세요.')
