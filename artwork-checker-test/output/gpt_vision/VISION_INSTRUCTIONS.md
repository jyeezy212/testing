# GPT Vision Verification Required

This run produced items requiring visual verification.

## Workflow

1. Open `vision_tasks.json`
2. For each item:
   - Open `page_image` first — this is the full artwork rendered at 300 DPI. Read it holistically, just like a human reads a physical label: scan the whole artwork to orient yourself.
   - If `focus_crop` is provided (non-null), open it next — this is a zoomed-in crop centered on the matched text region. Use it to read fine-detail text character-by-character.
   - `NOT FOUND` items have no `focus_crop` — search the entire `page_image` carefully.
   - Retype the ACTUAL visible artwork text character-by-character.
3. Write `output/vision_overrides.json`:

```json
{"vision_audit":{"source":"manual_image_read","task_hash":"<task_hash from vision_tasks.json>"},
"overrides":[
  {"finding_id":"<id>","visual_artwork_value":"<text>","found":true,"notes":"Visually verified on page X, [panel], [lang]","evidence":"focus_crop|page_image","evidence_path":"<path>"}
]}
```

Sentinel block is printed to stdout between:
`<<<GPT_VISION_REQUIRED>>>` and `<<<END_GPT_VISION_REQUIRED>>>`
