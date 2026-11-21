# Optional production asset library

The default source checkout contains this manifest rather than the original large media library. Every original byte remains in the preservation branch and earlier history.

For a lightweight checkout, use `git clone --filter=blob:none` and work with the authored offline examples. A normal full clone still includes historical media; this change intentionally does not rewrite history.

Restore optional media only when a production run needs it:

```bash
python tools/restore_asset_library.py --fetch
```

The helper pins the preservation commit, checks every SHA-256 digest, and refuses to overwrite modified local files. It copies original bytes without image or audio processing. Restored files are ignored locally. The production mode can also use an existing authorized library through `LONGFORM_ASSET_LIBRARY`.
