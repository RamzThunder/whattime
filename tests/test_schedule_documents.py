import struct
import tempfile
import unittest
import zipfile
import zlib
from pathlib import Path
from schedule_documents import (parse_schedule_document, _hwp_rows, _hwp_body,
                                _hwp_records, _hwp_text, _schedule_from_hwpx_rows)


def record(tag, level, payload):
    return struct.pack('<I', tag | level << 10 | len(payload) << 20) + payload


def table_body():
    body = record(71, 1, b' lbt') + record(77, 2, b'\0' * 20)
    for row, cells in enumerate([['1교시', '09:00', '09:40'], ['2교시', '09:50', '10:30']]):
        for col, cell in enumerate(cells):
            geometry = b'\0' * 8 + struct.pack('<HHHH', col, row, 1, 1) + b'\0' * 18
            body += record(72, 2, geometry) + record(66, 3, b'')
            body += record(67, 4, (cell + '\r').encode('utf-16le'))
    return body


def write_hwp_fixture(path, header, body):
    # Minimal Compound File with two regular streams; no mini-stream needed.
    end, free = 0xfffffffe, 0xffffffff
    ole_header = bytearray(512)
    ole_header[:8] = bytes.fromhex('d0cf11e0a1b11ae1')
    struct.pack_into('<HHHHH', ole_header, 24, 62, 3, 0xfffe, 9, 6)
    struct.pack_into('<IIIIIIIII', ole_header, 40, 0, 1, 0, 0, 4096, end, 0, end, 0)
    struct.pack_into('<109I', ole_header, 76, 17, *([free] * 108))
    def directory(name, kind, child=free, right=free, sector=end, size=0):
        item = bytearray(128)
        encoded = (name + '\0').encode('utf-16le')
        item[:len(encoded)] = encoded
        struct.pack_into('<HBBIII', item, 64, len(encoded), kind, 1, free, right, child)
        struct.pack_into('<IQ', item, 116, sector, size)
        return item
    dirs = (directory('Root Entry', 5, child=1) +
            directory('FileHeader', 2, right=2, sector=1, size=4096) +
            directory('BodyText', 1, child=3) +
            directory('Section0', 2, sector=9, size=4096))
    fat = [end] + list(range(2, 9)) + [end] + list(range(10, 17)) + [end, 0xfffffffd]
    fat += [free] * (128 - len(fat))
    Path(path).write_bytes(ole_header + dirs + header.ljust(4096, b'\0') +
                           body.ljust(4096, b'\0') + struct.pack('<128I', *fat))


class DocumentTests(unittest.TestCase):
    def test_hwpx_table_and_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'test.hwpx'
            rows = [['1교시','09:00','09:40'], ['2교시','09:50','10:30']]
            xml = '<section><tbl>' + ''.join('<tr>' + ''.join('<tc><p><t>'+c+'</t></p></tc>' for c in row) + '</tr>' for row in rows) + '</tbl></section>'
            with zipfile.ZipFile(path, 'w') as f: f.writestr('Contents/section0.xml', xml)
            result = parse_schedule_document(path)
            self.assertEqual(result[0], {'name':'1교시','start':'09:00','end':'09:40'})
            self.assertEqual(len(result), 2)
            with self.assertRaises(ValueError): parse_schedule_document(Path(tmp) / 'test.pdf')

    def test_hwp_table_cells_and_unrelated_paragraph(self):
        body = table_body() + record(66, 0, b'') + record(67, 1, '안내'.encode('utf-16le'))
        tables, paragraphs = _hwp_rows(body)
        self.assertEqual(_schedule_from_hwpx_rows(tables[0])[1]['start'], '09:50')
        self.assertEqual(paragraphs, [['안내']])

    def test_hwp_compressed_and_plain_file_routing(self):
        for compressed in [False, True]:
            header = bytearray(256); header[:17] = b'HWP Document File'; header[35] = 5
            struct.pack_into('<I', header, 36, int(compressed))
            body = table_body()
            if compressed:
                encoder = zlib.compressobj(wbits=-15)
                body = encoder.compress(body) + encoder.flush()
            with tempfile.NamedTemporaryFile(suffix='.hwp') as f:
                write_hwp_fixture(f.name, bytes(header), body)
                result = parse_schedule_document(f.name)
                self.assertEqual(len(result), 2)
                self.assertEqual(result[0]['start'], '09:00')
                struct.pack_into('<I', header, 36, 2)
                write_hwp_fixture(f.name, bytes(header), body)
                with self.assertRaisesRegex(ValueError, '암호'): parse_schedule_document(f.name)

    def test_corrupt_records_and_decompression_limits(self):
        with self.assertRaises(ValueError): list(_hwp_records(b'\0'))
        with self.assertRaises(ValueError): list(_hwp_records(struct.pack('<I', 67 | 100 << 20)))
        encoder = zlib.compressobj(wbits=-15)
        compressed = encoder.compress(b'x' * 1000) + encoder.flush()
        with self.assertRaises(ValueError): _hwp_body(compressed, True, 20)
        with self.assertRaises(ValueError): _hwp_body(compressed[:-1], True, 2000)
        text = '조회'.encode('utf-16le') + b'\x09\x00' + b'X' * 14 + '09:00'.encode('utf-16le')
        self.assertEqual(_hwp_text(text), '조회 09:00')
