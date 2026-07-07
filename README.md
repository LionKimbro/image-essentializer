# image-essentializer

Reconstruct likely matching image sets from recovered folders.

The first slice keeps originals in place, builds a SHA-centered JSON index,
emits an M1 transport file, and provides a Tkinter cluster review GUI.

## Commands

```powershell
imgess --source.paths "D:\recovered;E:\more-images" scan
imgess --source.paths "D:\recovered;E:\more-images" survey
imgess gui
imgess --execpath.query "D:\some-image.png" lookup
imgess clean
```

Important outputs:

- `imgess-index.json`: persistent scan/fingerprint/cluster index
- `imgess-index.m1`: M1 transport export

Useful options:

- `--filter.min_width 400`
- `--filter.max_width 6000`
- `--filter.min_height 800`
- `--filter.max_height 8000`
- `--filter.target_ratio 0.6667`
- `--filter.ratio_tolerance 0.08`
- `--match.cluster_threshold 0.90`
- `--match.coarse_threshold 0.72`
- `--scan.progress_every 250`
- `--scan.checkpoint_every 250`
- `--cluster.progress_seconds 10`
- `--cluster.bucket_band_size 32`
- `--cluster.max_bucket_size 250`

`scan` writes resumable recovery files named `eraseme-after-YYYY-MM-DD...`.
They are ignored by git, automatically removed after their date has passed,
and can be deleted manually with `imgess clean`.
