---
> ⚠️ **DRAFT REPORT — VISUAL VERIFICATION PENDING**
>
> This report was produced by **automated text extraction only**.
> It is **NOT final**. A `<<<GPT_VISION_REQUIRED>>>` sentinel block was printed to stdout.
> Before presenting results to the user, the GPT must:
> 1. Read the sentinel JSON and open `gpt_vision/vision_tasks.json`.
> 2. For **every item**, open the listed crop (or `page_image`) and retype visible text character by character.
> 3. Any `NOT FOUND` result must be re-checked visually — visual value overrides the script value.
> 4. Each Section D row Notes column must begin with `Visually verified on page X, [panel], [language]`.
> 5. If visual verification cannot be performed, output a `⛔ VISUAL VERIFICATION NOT EXECUTED` block listing all unverified fields.
>
> **Do not remove this banner or present the report as final until all items in `vision_tasks.json` are verified.**
---

# Artwork Verification Report

*Generated: 2026-02-24 13:43:04*

*Checker Version: 2.1.0*

*Vision verification: 🔍 REQUIRED — run Custom GPT visual pass on `gpt_vision/vision_tasks.json`*


## 1️⃣ Project Header

| Field | Value |
|-------|-------|
| Project Name | amika big embrace smoothing whipped body butter 250 ml |
| Component Type | Carton |


## 2️⃣ Files

| Type | Filename | Version | Note |
|------|----------|---------|------|
| Copy Document | 5_Body_Butter_250ml_-_Carton.xlsx | — | 37 fields, 2 instructional notes |
| Artwork | 5__Amika_Body_BodyButter_Carton_AW_090225_VC_22640.pdf | — | 79 text elements extracted |


## 3️⃣ Core Verification Tables


### A. Copy Quality

| Language | Field | Issue Type | Recommendation | Status |
|----------|-------|------------|----------------|--------|
| French | Marketing + Usage Copy 1 | Capitalization | 'Ce' should be lowercase 'ce' | ⚠️ |
| English | PAO Jar, Recycling Icon,... | Instructional note | Remove internal instruction (matched:... | ⚠️ |
| English | Vegan Icon | Instructional note | Remove internal instruction (matched: \bPO\b) | ⚠️ |

### B. Claim Risk

| Language | Claim | Risk Level | Rationale | Regions | Action | Status |
|----------|-------|------------|-----------|---------|--------|--------|
| English | friend to skin | Low | Cosmetic/descriptive claim - acceptable | All | Keep | ✅ |
| English | clinically proven | High | Contains high-risk term: 'clinically... | USA, EU, UK | Escalate | ⚠️ |
| English | for all skin tones | Low | Cosmetic/descriptive claim - acceptable | All | Keep | ✅ |

### C. Label-Claim Conversion

| Source | Declared (mL) | Calculated (fl oz) | Declared (fl oz) | Within ±0.10 | Status | Notes |
|--------|---------------|-------------------|------------------|--------------|--------|-------|
| Fill Weight | 250.0 | 8.45 | 8.5 | Yes | ✅ | Declared: 8.5 fl oz, Calculated: 8.45 fl oz, Diff: 0.05 |

### D. Artwork Match

*2 fields marked as instructional notes (excluded from matching)*


**Front Panel — English**

| Field | Copy Doc Value | Artwork Value | Match | Notes |
|-------|----------------|---------------|-------|-------|
| Product Name | big embrace | NOT FOUND | ❌ | [D-001] NOT FOUND in artwork — requires visual confirmation |
| Secondary Name | smoothing whipped body butter | NOT FOUND | ❌ | [D-002] NOT FOUND in artwork — requires visual confirmation |
| Fill Weight | 250 ML / 8.5 US FL. OZ. | 250 ML / 8.5 US FL. OZ. | ✅ | [D-004] Exact match |
| Scent | amika:aura | amika:aura | ✅ | Exact match |

**Front Panel — French**

| Field | Copy Doc Value | Artwork Value | Match | Notes |
|-------|----------------|---------------|-------|-------|
| Secondary Name | beurre corporel fouetté apaisant | NOT FOUND | ❌ | [D-003] NOT FOUND in artwork — requires visual confirmation |

**Back Panel — English**

| Field | Copy Doc Value | Artwork Value | Match | Notes |
|-------|----------------|---------------|-------|-------|
| Marketing + Usage Copy 1 | like a big embrace, this nourishing... | like a big embrace, this nourishing... | ✅ | Exact match |
| Marketing + Usage Copy 2 | scented with juicy, uplifting amika:aura | scented with juicy, uplifting amika:aura | ✅ | Exact match |
| Marketing + Usage Copy 3 | use it: apply onto body, massaging... | use it: apply onto body, massaging... | ✅ | Exact match |
| Pack Claim 1 | friend to skin | friend to skin | ✅ | Exact match |
| Pack Claim 2 | clinically proven | clinically proven | ✅ | Exact match |
| Pack Claim 3 | for all skin tones | NOT FOUND | ❌ | [D-006] NOT FOUND in artwork — requires visual confirmation |
| Hero Ingredients Header | key ingredients | key ingredients | ✅ | Exact match |
| Hero Ingredient Call-outs 2 | ceramide NP: deeply moisturizes +... | ceramide NP: deeply moisturizes +... | ✅ | Exact match |
| Hero Ingredient Call-outs 3 | lipohydroxy acid: gently exfoliates... | lipohydroxy acid: gently exfoliates... | ✅ | Exact match |
| Hero Ingredient Call-outs 4 | regenerative shea butter: enriches... | regenerative shea butter: enriches... | ✅ | Exact match |
| Hero Ingredient Call-outs 5 | sea buckthorn: nourishes + seals in... | sea buckthorn: nourishes + seals in... | ✅ | Exact match |
| Warning | avoid contact with eyes. | avoid contact with eyes. | ✅ | Exact match |
| PCR Callout (if needed) | this jar is made with 50% post... | this jar is made with 50%... | ⚠️ | [D-012] Near match (98.1%) — verify differences |
| Address Block | amika Brooklyn, NY 11249 USA | amika Brooklyn, NY 11249 USA | ✅ | [D-014] Exact match; Text is underlined in artwork but... |
| Biorius Address | BIORIUS / EU: Wavre, BE, UK: London,... | NOT FOUND | ❌ | [D-015] NOT FOUND in artwork — requires visual confirmation |
| Formula Country of Origin | made in USA with global materials | made in USA with global materials | ✅ | [D-016] Exact match; Text is underlined in artwork but... |
| Ingredient List (Formula #) | (22640) | (22640) | ✅ | Formula number match |
| Ingredient List | Water/Aqua/Eau, Cocos Nucifera... | NOT FOUND | ❌ | [D-019] NOT FOUND in artwork — requires visual confirmation |
| Social Handles | loveamika.com/recycle | loveamika.com/recycle | ✅ | [D-019] Exact match; Text is underlined in artwork but... |

**Back Panel — French**

| Field | Copy Doc Value | Artwork Value | Match | Notes |
|-------|----------------|---------------|-------|-------|
| Marketing + Usage Copy 1 | Ce beurre corporel nourrissant... | NOT FOUND | ❌ | [D-005] NOT FOUND in artwork — requires visual... |
| Marketing + Usage Copy 2 | fragrance fruitée et enivrante... | fragrance fruitée et enivrante... | ✅ | Exact match |
| Marketing + Usage Copy 3 | utilisation : appliquez sur le corps... | utilisation : appliquez sur le corps... | ✅ | Exact match |
| Pack Claim 1 | l'ami de votre peau | l'ami de votre peau | ✅ | Exact match |
| Pack Claim 2 | cliniquement prouvé | cliniquement prouvé | ✅ | Exact match |
| Pack Claim 3 | idéal pour toutes les carnations | NOT FOUND | ❌ | [D-007] NOT FOUND in artwork — requires visual confirmation |
| Hero Ingredients Header | ingrédients clés | ingrédients clés | ✅ | Exact match |
| Hero Ingredient Call-outs 2 | complexe céramides : hydrate... | complexe céramides hydrate... | ⚠️ | [D-008] Near match (98.7%) — verify differences |
| Hero Ingredient Call-outs 3 | acide lipo-hydroxy (LHA) : exfolie... | acide lipo-hydroxy (LHA) exfolie en... | ⚠️ | [D-009] Near match (98.6%) — verify differences |
| Hero Ingredient Call-outs 4 | beurre de karité régénérant : ses... | beurre de karité régénérant ses... | ⚠️ | [D-010] Near match (98.9%) — verify differences |
| Hero Ingredient Call-outs 5 | l'argousier : nourrit + préserve... | l'argousier nourrit + préserve... | ⚠️ | [D-011] Near match (99.3%) — verify differences |
| Warning | éviter tout contact avec les yeux. | éviter tout contact avec les yeux. | ✅ | Exact match |
| PCR Callout (if needed) | ce pot contient 50% de matériaux... | ce pot contient 50% de matériaux... | ✅ | [D-013] Exact match |
| Formula Country of Origin | fabriqué aux États-Unis avec des... | fabriqué aux États-Unis avec des... | ✅ | [D-017] Exact match; Text is underlined in artwork but... |

### E. Font Size

| Text String / Field | Jurisdiction | Required Min (pt) | Measured Min (pt) | Method | Status | Screenshot ID |
|---------------------|--------------|-------------------|-------------------|--------|--------|---------------|
| 12M | USA | 4.5 | 3.72 | Vector | ❌ | FS-001 |
| 12M | EU | 6.0 | 3.72 | Vector | ❌ | FS-001 |

### F. Barcode

| Symbology | Encoded Digits | Check Digit Valid | X-Dim (mm) | Quiet Zone (mm) | Module Count | Print Contrast | Scan Test |
|-----------|----------------|-------------------|------------|-----------------|--------------|----------------|-----------|
| Unknown | — | — | Manual check required | Manual check required | Manual check required | Manual check required | Manual check required |

### G. Visual Snapshots

| ID | What | Where | Fix | Linked Rows | Status After Fix |
|----|------|-------|-----|-------------|------------------|
| D-001 | Missing text | Front Panel — English | NOT FOUND in artwork —... | D | TBD |
| D-002 | Missing text | Front Panel — English | NOT FOUND in artwork —... | D | TBD |
| D-003 | Missing text | Front Panel — French | NOT FOUND in artwork —... | D | TBD |
| D-004 | exact | Front Panel — English | Exact match | D | TBD |
| D-005 | Missing text | Back Panel — French | NOT FOUND in artwork —... | A, D | TBD |
| D-006 | Missing text | Back Panel — English | NOT FOUND in artwork —... | D | TBD |
| D-007 | Missing text | Back Panel — French | NOT FOUND in artwork —... | D | TBD |
| D-008 | Near match | Back Panel — French | Near match (98.7%) —... | D | TBD |
| D-009 | Near match | Back Panel — French | Near match (98.6%) —... | D | TBD |
| D-010 | Near match | Back Panel — French | Near match (98.9%) —... | D | TBD |
| D-011 | Near match | Back Panel — French | Near match (99.3%) —... | D | TBD |
| D-012 | Near match | Back Panel — English | Near match (98.1%) —... | D | TBD |
| D-013 | exact | Back Panel — French | Exact match | D | TBD |
| D-014 | exact | Back Panel — English | Exact match | D | TBD |
| D-015 | Missing text | Back Panel — English | NOT FOUND in artwork —... | D | TBD |
| D-016 | exact | Back Panel — English | Exact match | D | TBD |
| D-017 | exact | Back Panel — French | Exact match | D | TBD |
| D-019 | Missing text | Back Panel — English | NOT FOUND in artwork —... | D | TBD |
| D-019 | exact | Back Panel — English | Exact match | D | TBD |

*1 annotated snapshot(s) generated.*
- `snapshot_page_1.png`

### H. Score & Summary

| Area | Checks | Matches | Score % | Notes |
|------|--------|---------|---------|-------|
| Copy accuracy | 38 | 25 | 66 | — |
| Claims & risk | 3 | 2 | 67 | 1 high-risk claim(s) pending |
| Regulatory (EU font) | 2 | 0 | 0 | Smallest: 3.72pt |
| **Overall** | — | — | **44.2** | — |

**Top Fixes (❌)**

| Item |
|------|
| [D-001] Product Name: NOT FOUND in artwork — requires visual... |
| [D-002] Secondary Name: NOT FOUND in artwork — requires visual... |
| [D-003] Secondary Name: NOT FOUND in artwork — requires visual... |
| [D-005] Marketing + Usage Copy 1: NOT FOUND in artwork — requires visual... |
| [D-006] Pack Claim 3: NOT FOUND in artwork — requires visual... |

**Attention (⚠️)**

| Item |
|------|
| Hero Ingredient Call-outs 2: Near match (98.7%) — verify differences |
| Hero Ingredient Call-outs 3: Near match (98.6%) — verify differences |
| Hero Ingredient Call-outs 4: Near match (98.9%) — verify differences |
| Hero Ingredient Call-outs 5: Near match (99.3%) — verify differences |
| PCR Callout (if needed): Near match (98.1%) — verify differences |

## 4️⃣ Optional Fields

| Field | Content |
|-------|---------|
| Version Change Log | Not provided |
| Creative Brand-Voice Check | Not requested |
| One-Page PDF Summary Export | Available on request |


## 5️⃣ Special Notes / Constraints

| Constraint | Source | Applies To | Notes |
|------------|--------|------------|-------|
| Text must match character-for-character | Brand | All panels | Including punctuation, case, diacritics |
| 7 fields require visual verification | Zoom Triggers | See flagged items | Numbers, units, or low confidence |
| 2 instructional notes detected | Copy Document | See Section A | Excluded from artwork matching |