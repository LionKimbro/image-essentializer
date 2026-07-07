# Generalization Evaluation

The image reconstruction tool is feasible to generalize beyond the current
sticker-design use case.

The core engine is already broadly applicable:

- scan folders in place
- identify image files by SHA-256
- record every filesystem location where an image is found
- compute visual fingerprints
- compare images by near-match similarity
- cluster likely related images
- support human review of proposed clusters
- look up an image from a file or clipboard against the indexed dataset
- export semantic data, including M1 transport data

The current domain-specific assumptions are mostly configuration and language:

- the default intake filter assumes a `2:3` image profile
- dimension limits are tuned for recovered sticker-design images
- fingerprinting includes corner-masked and center-emphasis variants
- the GUI uses terms such as "design", "variant", and "cluster"
- M1 type hints and custom aspects are oriented around image/design reconstruction

A clean generalization path is to introduce named profiles. Each profile would
describe the image domain being reconstructed.

Example profile responsibilities:

- accepted aspect ratio or ratio family
- minimum and maximum dimensions
- fingerprint sizes and strategies
- mask strategy, such as no mask, corner mask, border ignore, or center emphasis
- clustering thresholds
- GUI decision vocabulary
- export vocabulary and M1 type hints

Example profile names:

- `stickers-2x3`
- `square-icons`
- `tarot-cards`
- `screenshots`
- `product-photos`
- `portraits`
- `arbitrary-images`

The most important design issue is not the matching engine. It is vocabulary.
Different image domains require different decision language. For sticker
reconstruction, "Same Design" is clear. For other domains, the correct phrase
might be "Same Subject", "Same Screenshot", "Same Product", "Same Artwork", or
"Same Document Image".

The recommended architecture is:

```text
one matching/reconstruction engine
many domain profiles
```

The existing tool can continue as a specialized application while the stable
engine concepts are gradually extracted into a more general image-reconstruction
framework.
