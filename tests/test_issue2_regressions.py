"""Offline regressions for Issue #2 observations 2-6 (no AutoCAD required)."""
import argparse
import copy
import random
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dxf-batch-pdf-export' / 'scripts'))
from dxf_scan_utils import parse_sections, entity_bbox, get_text_value, bbox_union, boxes_touch
import detect_dxf_frames as detection
from page_ordering import apply_page_number_sort
from verify_pdf_pages import image_stats, find_pdftoppm
from PIL import Image
from test_frame_detection import pair, make_dxf


def args(**changes):
    defaults = dict(frame_block='', min_count=1, frame_width=841, frame_height=594,
                    tolerance=5, padding=.01, frame_color='6', frame_layer='',
                    frame_layer_token='\u56fe\u6846', color_cluster_gap=2, cluster_gap=30,
                    min_entity_size=0, min_cluster_entities=1, min_cluster_width=0,
                    min_cluster_height=0, strategy='auto', allow_suspicious_cluster=False,
                    sort='top-left')
    return argparse.Namespace(**(defaults | changes))


class Regressions(unittest.TestCase):
    def test_classic_polyline_model_and_block(self):
        poly = pair(0, 'POLYLINE') + pair(8, '\u56fe\u6846') + pair(10, 0) + pair(20, 0) + pair(70, 1)
        for x, y in ((100, 200), (941, 200), (941, 794), (100, 794)):
            poly += pair(0, 'VERTEX') + pair(10, x) + pair(20, y)
        poly += pair(0, 'SEQEND')
        for section in ('ENTITIES', 'BLOCKS'):
            content = pair(0, 'SECTION') + pair(2, section)
            if section == 'BLOCKS':
                content += pair(0, 'BLOCK') + pair(2, 'A1')
            content += poly
            if section == 'BLOCKS':
                content += pair(0, 'ENDBLK')
            content += pair(0, 'ENDSEC') + pair(0, 'EOF')
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'classic.dxf'
                path.write_text('\n'.join(content) + '\n', encoding='utf-8')
                entities, blocks, _, _ = parse_sections(path)
            records = entities if section == 'ENTITIES' else blocks['A1']
            self.assertEqual(len(records), 1)
            self.assertEqual(entity_bbox(*records[0]), (100, 200, 941, 794))
            if section == 'ENTITIES':
                frames, strategy, *_ = detection.choose_frames(args(), entities, blocks)
                self.assertEqual((strategy, len(frames)), ('layer', 1))

    def test_single_cluster_unknown_layer_requires_confirmation(self):
        entities = [('LWPOLYLINE', [('8', 'FRAME'), ('10', '0'), ('20', '0'), ('10', '1800'), ('20', '594')])]
        with self.assertRaisesRegex(RuntimeError, 'single unverified'):
            detection.choose_frames(args(), entities, {})
        result = detection.choose_frames(args(allow_suspicious_cluster=True), entities, {})
        self.assertEqual(result[1], 'cluster')
        self.assertTrue(result[4])

    def test_eight_frames_unknown_layer_can_be_selected_explicitly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'eight.dxf'
            make_dxf(path)
            path.write_text(path.read_text(encoding='utf-8').replace('\u56fe\u6846-A1', 'BORDER'), encoding='utf-8')
            entities, blocks, _, _ = parse_sections(path)
        result = detection.choose_frames(args(frame_layer='BORDER'), entities, blocks)
        self.assertEqual(result[1], 'color')
        self.assertEqual(len(result[0]), 8)

    def test_punctuation_pages_and_conflict(self):
        frames = [dict(rawWindow=[i * 10, 0, i * 10 + 9, 9], insert=[i * 10, 0]) for i in range(8)]
        separators = [' ', ',', '\uFF0C', '/', ' / ', '\uFF0F', ';', '\\P']
        entities = [('TEXT', [('10', str(i * 10 + 1)), ('20', '1'), ('1', f'\u7b2c {8-i} \u5f20{sep}\u5171 8 \u5f20')]) for i, sep in enumerate(separators)]
        ordered, info, warnings = apply_page_number_sort(copy.deepcopy(frames), entities)
        self.assertEqual(info['method'], 'title-block-page-number')
        self.assertEqual([f['pageNumberEvidence']['page'] for f in ordered], list(range(1, 9)))
        self.assertFalse(warnings)
        entities[0][1][-1] = ('1', '\u7b2c8\u5f20,\u51718\u5f20 \u7b2c7\u5f20/\u51718\u5f20')
        _, info, warnings = apply_page_number_sort(copy.deepcopy(frames), entities)
        self.assertEqual(info['method'], 'geometry')
        self.assertTrue(warnings)

    def test_missing_page_evidence_warns(self):
        frames = [dict(rawWindow=[0, 0, 9, 9], insert=[0, 0])]
        _, info, warnings = apply_page_number_sort(frames, [])
        self.assertEqual(info['method'], 'geometry')
        self.assertTrue(warnings)

    def test_mtext_chunk_order(self):
        self.assertEqual(get_text_value([('3', 'first'), ('3', ' second'), ('1', ' last')]), 'first second last')

    def test_cluster_cache_preserves_old_semantics(self):
        rng = random.Random(42)
        for _ in range(20):
            records = [dict(bbox=(x, y, x + 5, y + 5)) for x, y in [(rng.randrange(100), rng.randrange(100)) for _ in range(80)]]
            old = []
            for record in records:
                attached = [i for i, component in enumerate(old) if boxes_touch(bbox_union([v['bbox'] for v in component]), record['bbox'], 1)]
                if not attached:
                    old.append([record])
                else:
                    old[attached[0]].append(record)
                    for i in reversed(attached[1:]):
                        old[attached[0]].extend(old.pop(i))
            self.assertEqual(detection.connected_components(records, 1), old)

    def test_cluster_cache_does_not_rescan_component(self):
        records = [dict(bbox=(0, 0, 841, 594)) for _ in range(1000)]
        with patch.object(detection, 'bbox_union', wraps=bbox_union) as union:
            self.assertEqual(len(detection.connected_components(records, 0)), 1)
            self.assertTrue(all(len(call.args[0]) <= 2 for call in union.call_args_list))

    def test_image_stats_matches_reference(self):
        rng = random.Random(91)
        cases = [[(255, 255, 255)] * 400, [(245, 245, 245), (244, 254, 254), (244, 255, 255)] * 133 + [(0, 0, 0)], [tuple(rng.randrange(256) for _ in range(3)) for _ in range(400)]]
        for pixels in cases:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'sample.png'
                image = Image.new('RGB', (20, 20))
                image.putdata(pixels)
                image.save(path)
                stats = image_stats(path)
            ink = [(i % 20, i // 20) for i, p in enumerate(pixels) if min(p) < 245]
            self.assertEqual(stats['nonwhitePixels'], len(ink))
            self.assertEqual(stats['colorPixels'], sum(min(p) < 245 and max(p)-min(p) > 10 for p in pixels))
            expected = [min(x for x,y in ink), min(y for x,y in ink), max(x for x,y in ink), max(y for x,y in ink)] if ink else None
            self.assertEqual(stats['contentBBoxPx'], expected)

    def test_poppler_explicit_path_and_invalid_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 'pdftoppm.exe'
            exe.touch()
            self.assertEqual(find_pdftoppm(str(exe)), str(exe))
            with self.assertRaisesRegex(SystemExit, 'Explicit pdftoppm'):
                find_pdftoppm(str(exe.parent / 'missing.exe'))

    def test_poppler_never_recursively_searches(self):
        with patch.object(Path, 'glob', side_effect=AssertionError('recursive scan')), patch('verify_pdf_pages.shutil.which', return_value=None), patch.object(Path, 'exists', return_value=False):
            self.assertIsNone(find_pdftoppm(None))
        with patch('verify_pdf_pages.shutil.which', return_value='PATH/pdftoppm'), patch.object(Path, 'resolve', side_effect=AssertionError('PATH must win')):
            self.assertEqual(find_pdftoppm(None), 'PATH/pdftoppm')


if __name__ == '__main__':
    unittest.main(verbosity=2)
