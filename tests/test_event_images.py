import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from PIL import Image
from event_images import image_info, public_url


class ImageSelectionTests(unittest.TestCase):
    def image(self, size):
        image = Image.linear_gradient('L').resize(size).convert('RGB')
        output = io.BytesIO(); image.save(output, format='JPEG')
        return output.getvalue()

    def test_decoded_resolution_beats_filename_claims(self):
        with self.assertRaises(ValueError): image_info(self.image((320, 180)))
        wide = image_info(self.image((1920, 1080)))
        small = image_info(self.image((800, 450)))
        self.assertEqual((wide['width'], wide['height']), (1920, 1080))
        self.assertGreater(wide['quality'], small['quality'])
        self.assertTrue(wide['preview'].startswith('data:image/jpeg;base64,'))

    def test_solid_and_portrait_candidates_do_not_qualify(self):
        output = io.BytesIO(); Image.new('RGB', (1600, 900), 'black').save(output, format='JPEG')
        with self.assertRaises(ValueError): image_info(output.getvalue())
        with self.assertRaises(ValueError): image_info(self.image((800, 1200)))

    def test_private_destinations_and_embedded_credentials_are_rejected(self):
        with patch('event_images.socket.getaddrinfo', return_value=[(2, 1, 6, '', ('127.0.0.1', 443))]):
            with self.assertRaises(ValueError): public_url('https://publisher.invalid/image.jpg')
        with self.assertRaises(ValueError): public_url('https://user:password@example.org/image.jpg')


if __name__ == '__main__': unittest.main()
