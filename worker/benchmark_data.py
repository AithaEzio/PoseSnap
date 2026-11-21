"""Import published human annotations; never turn predictions into ground truth."""
import hashlib
import math
import random
import re
from pathlib import Path
from urllib.parse import urlparse

from wholebody import BODY, FOOT, HAND

SOURCES = {
    'cmu-foot': {
        'publisher': 'Carnegie Mellon University',
        'homepage': 'https://cmu-perceptual-computing-lab.github.io/foot_keypoint_dataset/',
        'annotationLicense': 'https://creativecommons.org/licenses/by/4.0/',
    },
    'coco-wholebody': {
        'publisher': 'SenseTime Research / COCO-WholeBody authors',
        'homepage': 'https://github.com/jin-s13/COCO-WholeBody',
        'annotationLicense': 'Research and non-commercial use; commercial permission required',
    },
}

def attribution_license(license):
    """Only unambiguous CC BY image records; NC/ND/SA/unknown are excluded."""
    parsed = urlparse(license.get('url', ''))
    return parsed.hostname in ('creativecommons.org', 'www.creativecommons.org') and bool(
        re.fullmatch(r'/licenses/by/(?:2\.0|3\.0|4\.0)/?', parsed.path))

def points(values, names, region):
    if len(values) != len(names) * 3:
        raise ValueError('Unexpected published landmark layout')
    result = []
    for index, name in enumerate(names):
        if name is None:
            continue
        x, y, visibility = values[index * 3:index * 3 + 3]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (x, y, visibility)):
            raise ValueError('Annotation coordinates must be finite')
        if visibility <= 0:
            continue
        # COCO v=1 is labelled but occluded. Do not score it as visible evidence.
        result.append(dict(name=name, region=region, xy=[x, y], visible=visibility >= 2,
                           sourceVisibility=visibility))
    return result

def landmarks(annotation, format):
    if format == 'cmu-foot':
        items = points(annotation['keypoints'], FOOT, 'foot')
    elif format == 'coco-wholebody':
        items = points(annotation['keypoints'], [BODY.get(i) for i in range(17)], 'body')
        if annotation.get('foot_valid'):
            items += points(annotation['foot_kpts'], FOOT, 'foot')
        for side, key in (('l', 'lefthand'), ('r', 'righthand')):
            if annotation.get(key + '_valid'):
                # Body already owns the wrist; avoid counting it twice.
                items += points(annotation[key + '_kpts'], [None] + [side + '_' + n for n in HAND[1:]], side + '_hand')
    else:
        raise ValueError('Unsupported published annotation format')
    for item in items:
        if item['region'] == 'foot':
            item['region'] = item['name'][0] + '_foot'
    return items

def candidates(document, format, limit=40, seed=20261009):
    if format not in SOURCES:
        raise ValueError('Unsupported published annotation format')
    licenses = {p['id']: p for p in document.get('licenses', [])}
    images = {p['id']: p for p in document['images']}
    groups = {}
    for annotation in document['annotations']:
        image = images.get(annotation['image_id'])
        if not image or annotation.get('iscrowd') or not attribution_license(licenses.get(image.get('license'), {})):
            continue
        bbox = annotation.get('bbox', [])
        if len(bbox) != 4 or not all(math.isfinite(v) for v in bbox) or min(bbox[2:]) <= 0:
            raise ValueError('Published person box is invalid')
        if bbox[3] < 120:
            continue
        observed = landmarks(annotation, format)
        if sum(p['visible'] for p in observed) < 3:
            continue
        person = dict(annotationId=annotation['id'], heightPx=bbox[3],
                      box=[bbox[0], bbox[1], bbox[0] + bbox[2], bbox[1] + bbox[3]], landmarks=observed)
        groups.setdefault(image['id'], []).append(person)
    ids = sorted(i for i, people in groups.items() if len(people) <= 4)
    random.Random(seed).shuffle(ids)
    result = []
    for image_id in ids[:limit]:
        image = images[image_id]
        if not re.fullmatch(r'[0-9]{12}\.jpg', image['file_name']):
            raise ValueError('Unexpected COCO image filename')
        people = sorted(groups[image_id], key=lambda p: (p['box'][0], p['annotationId']))
        for i, person in enumerate(people):
            person['personId'] = i + 1
        result.append(dict(id=f'{format}-{image_id:012}', image=image, people=people,
                           imageLicense=licenses[image['license']]))
    return result

def image_url(image):
    url = image.get('coco_url', '')
    parsed = urlparse(url)
    expected = '/val2017/' + image['file_name']
    if parsed.scheme not in ('http', 'https') or parsed.hostname != 'images.cocodataset.org' or parsed.path != expected or parsed.query or parsed.fragment:
        raise ValueError('Only official COCO validation image downloads are supported')
    return url

def case(row, path, annotation_digest, format, source_url):
    return dict(id=row['id'], image=str(Path('images') / path.name),
                imageDigest=hashlib.sha256(path.read_bytes()).hexdigest(),
                category='review-needed', people=row['people'], runs={},
                provenance=dict(**SOURCES[format], annotationSource=source_url,
                                annotationSha256=annotation_digest,
                                imageSource=image_url(row['image']),
                                originalPhoto=row['image'].get('flickr_url'),
                                imageLicense=row['imageLicense'], annotationType='published-human-labels'),
                review=dict(category=False, ownership=False, contact=False,
                            note='Labelled people are not necessarily every person in the image. Review identity/category; no contact or depth truth was supplied.'))
