"""The diagnostic must reveal failures without reading any user documents."""
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_ocr
import rasam_ocr


HAVE_PIL = importlib.util.find_spec('PIL') is not None


class OCRDiagnosticTests(unittest.TestCase):
    def run_check(self):
        output = io.StringIO()
        with redirect_stdout(output), \
                patch.object(rasam_ocr, 'local_ocr_status', return_value={'engine': 'paddleocr'}):
            code = check_ocr.main([])
        return code, output.getvalue()

    def test_load_failure_prints_traceback_and_skips_prediction(self):
        with patch.object(rasam_ocr, '_load_paddle', side_effect=RuntimeError('model download failed')), \
                patch.object(rasam_ocr, '_paddle_text') as predict, \
                patch.object(check_ocr, '_sample_image') as sample:
            code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn('FAILED at stage: Load PaddleOCR model', output)
        self.assertIn('Traceback (most recent call last)', output)
        self.assertIn('RuntimeError: model download failed', output)
        self.assertIn('Python executable:', output)
        predict.assert_not_called()
        sample.assert_not_called()

    @unittest.skipUnless(HAVE_PIL, 'Pillow is optional')
    def test_predict_failure_has_stage_and_cleans_sample(self):
        paths = []

        def fail(path):
            paths.append(path)
            self.assertTrue(path.is_file())
            raise RuntimeError('unsupported CPU operation')

        with patch.object(rasam_ocr, '_load_paddle'), \
                patch.object(rasam_ocr, '_paddle_text', side_effect=fail):
            code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn('FAILED at stage: Read generated sample', output)
        self.assertIn('RuntimeError: unsupported CPU operation', output)
        self.assertFalse(paths[0].parent.exists())

    @unittest.skipUnless(HAVE_PIL, 'Pillow is optional')
    def test_success_predicts_generated_image_parses_output_and_cleans_sample(self):
        from PIL import Image
        paths = []

        def predict(path):
            path = Path(path)
            paths.append(path)
            self.assertEqual(path.name, 'fictional-invoice.png')
            self.assertTrue(path.parent.name.startswith('rasam-ocr-check-'))
            with Image.open(path) as sample:
                self.assertEqual(sample.size, (1400, 1000))
                self.assertEqual(sample.mode, 'RGB')
                self.assertEqual(sample.getextrema(), ((0, 255),) * 3)
            return [{'rec_texts': ['TEST-0042'], 'rec_scores': [0.99]}]

        model = Mock()
        model.predict.side_effect = predict
        with patch.object(rasam_ocr, '_load_paddle', return_value=model):
            code, output = self.run_check()
        self.assertEqual(code, 0)
        self.assertIn('Recognized characters: 9', output)
        self.assertIn('SUCCESS:', output)
        self.assertIn('not an accuracy benchmark', output)
        self.assertNotIn('TEST-0042', output)
        self.assertFalse(paths[0].parent.exists())
        model.predict.assert_called_once()

    @unittest.skipUnless(HAVE_PIL, 'Pillow is optional')
    def test_empty_result_fails_and_cleans_sample(self):
        paths = []

        def empty(path):
            paths.append(path)
            return ' \n\t ', []

        with patch.object(rasam_ocr, '_load_paddle'), \
                patch.object(rasam_ocr, '_paddle_text', side_effect=empty):
            code, output = self.run_check()
        self.assertEqual(code, 1)
        self.assertIn('Recognized characters: 0', output)
        self.assertIn('PaddleOCR returned no text', output)
        self.assertNotIn('SUCCESS:', output)
        self.assertFalse(paths[0].parent.exists())

    def test_rejects_user_document_arguments_before_loading(self):
        with redirect_stderr(io.StringIO()), \
                patch.object(rasam_ocr, '_load_paddle') as load:
            with self.assertRaises(SystemExit) as caught:
                check_ocr.main(['private-invoice.png'])
        self.assertEqual(caught.exception.code, 2)
        load.assert_not_called()


if __name__ == '__main__':
    unittest.main()
