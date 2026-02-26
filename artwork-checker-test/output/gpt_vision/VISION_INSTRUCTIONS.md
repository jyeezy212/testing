# GPT Vision Verification Required

This run produced items requiring visual verification.

## Workflow

1. Open `vision_tasks.json`
2. For each item:
   - Open `page_image` first — this is the full artwork render. Use it to orient yourself.
   - Then open each `tile` listed for that item to read fine-detail text without distortion.
   - `NOT FOUND` items have ALL tiles listed — the text may appear anywhere on the page. Search all tiles.
   - Retype the ACTUAL visible artwork text character-by-character.
3. Write `output/vision_overrides.json`:

```json
{"overrides":[
  {"finding_id":"<id>","visual_artwork_value":"<text>","found":true,"notes":"Visually verified on page X, [panel], [lang]"}
]}
```

Sentinel block is printed to stdout between:
`<<<GPT_VISION_REQUIRED>>>` and `<<<END_GPT_VISION_REQUIRED>>>`
