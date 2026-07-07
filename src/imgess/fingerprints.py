from PIL import Image, ImageOps


def bitstring_from_image(image, size, flags=""):
    prepared = prepare_image(image, size)
    values = list(prepared.getdata())
    mask = make_mask(size, flags)
    active = [value for value, keep in zip(values, mask) if keep]
    median = sorted(active)[len(active) // 2]
    bits = []
    for value, keep in zip(values, mask):
        if keep:
            bits.append("1" if value >= median else "0")
        else:
            bits.append("x")
    return "".join(bits)


def prepare_image(image, size):
    image = ImageOps.exif_transpose(image)
    image = image.convert("L")
    image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
    return image


def make_mask(size, flags=""):
    width, height = size
    mask = []
    for y in range(height):
        for x in range(width):
            keep = True
            if "c" in flags:
                keep = keep and not is_corner_pixel(x, y, width, height)
            if "m" in flags:
                keep = keep and is_center_pixel(x, y, width, height)
            mask.append(keep)
    return mask


def is_corner_pixel(x, y, width, height):
    corner_w = max(2, width // 4)
    corner_h = max(4, height // 8)
    left = x < corner_w
    right = x >= width - corner_w
    top = y < corner_h
    bottom = y >= height - corner_h
    return (left or right) and (top or bottom)


def is_center_pixel(x, y, width, height):
    min_x = width // 4
    max_x = width - min_x
    min_y = height // 5
    max_y = height - min_y
    return min_x <= x < max_x and min_y <= y < max_y


def dhash_from_image(image, size=(9, 32)):
    prepared = prepare_image(image, size)
    width, height = size
    pixels = list(prepared.getdata())
    bits = []
    for y in range(height):
        offset = y * width
        for x in range(width - 1):
            bits.append("1" if pixels[offset + x] > pixels[offset + x + 1] else "0")
    return "".join(bits)


def compute_fingerprints(image):
    return {
        "gray_16x32": bitstring_from_image(image, (16, 32)),
        "gray_16x32_corner_masked": bitstring_from_image(image, (16, 32), "c"),
        "gray_32x64": bitstring_from_image(image, (32, 64)),
        "gray_32x64_corner_masked": bitstring_from_image(image, (32, 64), "c"),
        "gray_32x64_center": bitstring_from_image(image, (32, 64), "m"),
        "dhash_8x32": dhash_from_image(image),
    }


def hamming_fraction(a, b):
    checked = 0
    distance = 0
    for left, right in zip(a, b):
        if left == "x" or right == "x":
            continue
        checked += 1
        if left != right:
            distance += 1
    if checked == 0:
        return 1.0
    return distance / checked


def compare_fingerprints(left, right):
    distances = {}
    for key in left:
        if key in right:
            distances[key] = hamming_fraction(left[key], right[key])
    weighted = 0.0
    total = 0.0
    weights = {
        "gray_16x32": 1.0,
        "gray_16x32_corner_masked": 1.5,
        "gray_32x64": 1.0,
        "gray_32x64_corner_masked": 1.5,
        "gray_32x64_center": 1.2,
        "dhash_8x32": 0.8,
    }
    for key, distance in distances.items():
        weight = weights[key]
        weighted += distance * weight
        total += weight
    if total == 0:
        score = 0.0
        distance = 1.0
    else:
        distance = weighted / total
        score = max(0.0, 1.0 - distance)
    return {
        "score": round(score, 4),
        "distance": round(distance, 4),
        "distances": {key: round(value, 4) for key, value in distances.items()},
    }
