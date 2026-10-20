"""Prefer large publisher-supplied originals without downloads or paid requests."""
import math
import re
from urllib.parse import urlsplit, parse_qs

BAD_IMAGE = re.compile(r'logo|placeholder|favicon|avatar|sprite|son-dakikajpg|son_dakika_default', re.I)


def image_candidate(image):
    url = image.get('url') or image.get('href')
    if not isinstance(url, str):
        return None
    parsed = urlsplit(url)
    if (parsed.hostname or '').endswith('.tmgrup.com.tr'):
        original = parse_qs(parsed.query).get('u', [None])[0]
        if original and (urlsplit(original).hostname or '').endswith('.tmgrup.com.tr'):
            url, parsed = original, urlsplit(original)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or BAD_IMAGE.search(parsed.path):
        return None
    def dimension(value):
        try:
            number = float(value)
            return number if math.isfinite(number) and number > 0 else None
        except (ValueError, TypeError):
            return None
    width, height = dimension(image.get('width')), dimension(image.get('height'))
    hint = re.search(r'\b(\d{3,4})x(\d{3,4})\b', parsed.path)
    if hint:
        width, height = width or int(hint[1]), height or int(hint[2])
    if (width and width < 1280) or (height and height < 720):
        return None
    if width and height and not 1.15 <= width/height <= 2.5:
        return None
    # Known HD landscape first; an original with no dimensions is a last resort.
    quality = (2 if width and height else 1 if width or height else 0,
               min(width or 0, (height or 0)*16/9) * min(height or 0, (width or 0)*9/16))
    return quality, url


def preferred_image(images):
    candidates = [candidate for image in images if isinstance(image, dict) and (candidate := image_candidate(image))]
    return max(candidates, key=lambda candidate: candidate[0])[1] if candidates else None


def rss_image(entry):
    images = [image for field in ('media_content', 'media_thumbnail') for image in entry.get(field, [])
              if isinstance(image, dict) and (not image.get('type') or str(image['type']).startswith('image/'))
              and image.get('medium', 'image') == 'image']
    images.extend(image for image in entry.get('enclosures', []) if str(image.get('type', '')).startswith('image/'))
    return preferred_image(images)
