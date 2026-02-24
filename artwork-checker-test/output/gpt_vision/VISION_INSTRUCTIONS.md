# GPT Vision Verification Required

This run produced Tier 1 items requiring visual verification.

- Open `vision_tasks.json`
- For each item:
  - Open the listed crop(s) (or full `page_image`)
  - Retype the visible artwork text character-by-character
  - Update the final report: Artwork Value + Match + Notes

Sentinel block is printed to stdout between:
`<<<GPT_VISION_REQUIRED>>>` and `<<<END_GPT_VISION_REQUIRED>>>`
