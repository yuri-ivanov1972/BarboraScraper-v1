# Recovered minced-poultry scoring — 2026-10-13

## Status: approved, applied and verified

The user explicitly approved the presented mapping, estimated fiber, scores and
turkey ingredient-link correction. The still-fresh approved manifest was applied
to production in one transaction on 2026-10-13, then checked using server-enforced
read-only connections. No approval expiry bypass or fresh-preview substitution
was needed.

The approval manifest and verification report are ignored in
`generated-artifacts/poultry-scoring-preview.json` and
`generated-artifacts/poultry-scoring-verification.json`.

| Barbora SKU | Saved Rimi category | Estimated fiber / 100 g | Nutri-Score | NOVA |
| --- | --- | --- | --- | --- |
| `000000000001315297` | 78 / SH-6-11 | 0 g, estimated | C, 4 points | 4, additive override |
| `000000000001286881` | 78 / SH-6-11 | 0 g, estimated | C, 3 points | 4, additive override |

The poultry category remains **352**, UUID
`8a626638-f481-4299-a438-eb24495c3fb1`. The numeric Rimi reference ID is
**78**, not Barbora category 352. Neither raw chicken category 366 nor raw
turkey category 367 nor marinated poultry category 369 is used.

## Source evidence

Read-only Rimi database checks confirmed:

- Category 78 is **Dažādu veidu maltā gaļa**, code SH-6-11, under fresh meat.
  Its NOVA 1 is inherited, not an explicit preparation-specific classification.
- Rimi SKU **987816**, **Malta masa cāļa filejas Ķekava 450g**, is in category 78.
  Its ingredients and all core nutrition match the recovered Barbora chicken.
  Rimi already stores NOVA 4 / additive_override for this product.
- Rimi SKU **813665**, **Tītara gaļa kotletēm, atdzesēta Rimi 500g**, is also in
  category 78. Its 98% turkey, added salt, sodium acetates (E262), flavourings and
  spice extracts verify the comparable minced-preparation form, not an exact
  product match. Its package size, brand, origin, protein, and ingredients differ
  from WELL DONE; none of these values is copied to Barbora. Its inherited NOVA 1
  is **not** used as evidence of a valid preparation score.
- Both references have stored fiber 0 with `is_fiber_correct=false`.
  The existing fiber configuration already has category **78: 0.0**.
  No new default or mapping is invented.

Live website reads corroborated category membership and preparation ingredients:

- [Rimi mixed minced meat category](https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/svaiga-gala/dazadu-veidu-malta-gala/c/SH-6-11)
- [Identical Ķekava chicken preparation](https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/svaiga-gala/dazadu-veidu-malta-gala/malta-masa-cala-filejas-kekava-450g/p/987816)
- [Comparable Rimi turkey preparation](https://www.rimi.lv/e-veikals/lv/produkti/gala-zivis-un-gatava-kulinarija/svaiga-gala/dazadu-veidu-malta-gala/titara-gala-kotletem-atdzeseta-rimi-500g/p/813665)

Fresh Barbora page reads match the accepted ingredients and all core nutrition.
Neither website supplies fiber. The proposed **0 is a category estimate**, never
an inference that absent website fiber is zero. Existing positive/verified fiber
and manual nutrition retain their established protections.

## Supported automatic NOVA rule

[Monteiro et al., 2019, “Ultra-processed foods: what they are and how to identify
them”](https://pubmed.ncbi.nlm.nih.gov/30744710/) identifies flavourings among
the additive classes characteristic of NOVA 4.

Both products explicitly list **aromatizētāji**. Its existing shared analysis is
processed, `is_processed=true`, `suspicion_level=caution`,
`suspicion_category=flavor_enhancer`. The new narrow rule recognizes this explicit
flavouring marker even when its health concern is only “caution.” Processing
classification is not a synonym for a high harm rating. Other caution ingredients,
salt alone, and unknown analysis do not become NOVA 4.

The inherited category-1 default cannot turn a salted/flavoured preparation into
raw meat. An unsupported result stays unknown. A supported group-4 marker is
sufficient even when other analysis is pending, consistent with the existing
additive-override path. Manual NOVA overrides are untouched.

This is shared automatic scoring logic; after merge it can affect future
completion/refresh events with the same explicit flavouring evidence. There is
no broad production backfill, no category NOVA edit, and no manual override UI.

## Accepted ingredient analysis

The only initially pending link was the turkey token
`garšvielas var saturēt lipekli saturošus graudaugus`.
The existing parser had merged a separate “Var saturēt…” precautionary allergen
sentence with spices, then mapped possible trace allergens as ingredients.

The narrow parser correction stops at that explicit sentence boundary.
The accepted label text, including its allergen warning, is **not changed**.
Only this product's ingredient links are corrected: actual **garšvielas** replaces
the malformed token, and precautionary soju/pienu/selerijas/sinepes links are
removed. Existing shared analyses are retained, not deleted or overwritten.
The actual spice ingredient already has usable natural analysis in production.
After this correction all actual ingredients of both products have usable
existing analysis: **no AI request, invented classification, or global analysis
run is needed**.

The same accepted-analysis and atomic NOVA pipeline is used. Incomplete or
contradictory AI responses now stay uncategorized instead of gaining a silently
assumed “clean” assessment.

## Apply safeguards

`poultry_scoring.py` has two explicit modes:

```sh
python poultry_scoring.py --preview generated-artifacts/poultry-scoring-preview.json
python poultry_scoring.py --preview generated-artifacts/poultry-scoring-preview.json \
  --apply-approved-sha256 <exact-reviewed-checksum>
```

Only run the second command after user approval of the supported changes.

The manifest expires in 30 minutes. Apply checks its integrity, database target,
policy, Rimi evidence, both complete locked product snapshots, shared ingredient
analysis and recalculated plans. Changed/manual-edited/stale data rejects Apply.
Mapping, estimated fiber, Nutri-Score, accepted ingredient links and NOVA commit
in one serializable transaction. A completion failure rolls back the entire unit.
No core nutrition, product name, description, brand, producer, price, photos,
availability, manual nutrition, or unrelated product is updated.

If approval arrives after expiry, obtain a genuine fresh preview and compare all
supported changes and evidence to the approved proposal. Never extend a timestamp
or bypass the expiry gate.

## Completed verification

- All saved product and nutrition fields equal the exact approved before/after
  values. No other product or nutrition field changed, including core nutrition,
  accepted label text and manual flags.
- Both products retain `is_fiber_correct=false`: zero fiber remains explicitly
  estimated. Nutri-Score is C / 4 points for chicken and C / 3 points for turkey.
- Both products store NOVA 4 / `additive_override`, verified again using the
  actual accepted ingredient analysis and shared scoring function.
- Chicken has **6** actual ingredient links; turkey has **7**. All actual
  ingredients have usable existing analysis. Shared classifications were
  preserved; only affected usage frequencies were recalculated.
- Photos, latest market records, validation records, brands, producers and
  category path match their complete approval snapshots.
- The actual Product Browser listing reader returns exactly these two products
  with C / NOVA 4; its detail reader returns both stored scores and fiber 0.
  This checks the UI's data-reading path, not a clicked product-card screenshot.
- **86** scoped tests pass across poultry scoring, atomic NOVA completion,
  product refresh, nutrition reload and category recovery. These use disposable
  PostgreSQL fixtures, never production databases.
- Streamlit restarted cleanly and its landing-page screenshot showed no error.
- No deployment, broad worker run, global analysis job or production backfill
  was performed.
