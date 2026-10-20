import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from source_images import rss_image


class SourceImageTests(unittest.TestCase):
    def test_large_original_beats_first_thumbnail_without_fabricating_a_url(self):
        small = {'url': 'https://example.org/800.jpg', 'width': '800', 'height': '450'}
        large = {'url': 'https://example.org/original.jpg', 'width': '1920', 'height': '1080'}
        entry = {'media_content': [small, {'url': 'https://example.org/unknown.jpg'}, large]}
        self.assertEqual(rss_image(entry), large['url'])

    def test_tiny_logos_portraits_and_video_are_not_covers(self):
        self.assertIsNone(rss_image({'media_content': [
            {'url': 'https://example.org/tiny.jpg', 'width': '320', 'height': '180'},
            {'url': 'https://example.org/logo.jpg', 'width': '1920', 'height': '1080'},
            {'url': 'https://example.org/portrait.jpg', 'width': '1200', 'height': '1800'},
            {'url': 'https://example.org/movie.mp4', 'medium': 'video'},
        ]}))

    def test_unknown_dimensions_preserve_a_real_source_fallback(self):
        self.assertEqual(rss_image({'enclosures': [{'href': 'https://example.org/photo.jpg', 'type': 'image/jpeg'}]}), 'https://example.org/photo.jpg')
        self.assertIsNone(rss_image({'media_content': [{'url': 'javascript:alert(1)'}]}))

    def test_url_sizes_prefer_hd_and_reject_generic_breaking_news_art(self):
        entry={'media_content': [
            {'url':'https://example.org/son-dakikajpg-banner.jpg'},
            {'url':'https://example.org/900x506.jpg'},
            {'url':'https://example.org/unknown.jpg'},
            {'url':'https://example.org/1920x1080.jpg'}]}
        self.assertEqual(rss_image(entry),'https://example.org/1920x1080.jpg')
        self.assertEqual(rss_image({'media_content':[{'url':'https://iaahbr.tmgrup.com.tr/resize?u=https%3A%2F%2Fiahbr.tmgrup.com.tr%2Foriginal.jpg'}]}),'https://iahbr.tmgrup.com.tr/original.jpg')


if __name__ == '__main__': unittest.main()
