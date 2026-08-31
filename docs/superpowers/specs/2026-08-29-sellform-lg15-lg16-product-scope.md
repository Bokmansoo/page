# Sellform LG-15 / LG-16 Product Scope Refinement

**Date:** 2026-08-29

**Status:** Canonical refinement for LG-15 and LG-16

**Refines:** `SOCIAL-01`~`SOCIAL-06`, `VIDEO-01`~`VIDEO-06`, `MASTER-04`, `MASTER-06`, `UX-03`, `UX-04`, `UX-06`, `UX-07`

This document refines the product scope of LG-15 and LG-16 without replacing or weakening the existing final-design requirements. Security, authorization, immutable lineage, fact provenance, rights, idempotency, checkpoint/recovery, cost approval, and export parity contracts remain authoritative.

## 1. Shared authority boundary

LG-14, LG-15, and LG-16 are sibling outputs derived directly from the same current `CommerceCreativeMasterVersion` lineage.

```text
CommerceCreativeMasterVersion
  |-- LG-14 DetailPageVersion
  |-- LG-15 SocialKitVersion
  `-- LG-16 VideoProjectVersion
```

All three outputs reuse the Master-pinned Product Truth, Seller Confirmation, approved facts, Creative Brief, Brand Kit, evidence, and rights-confirmed assets.

The following are prohibited:

- re-analysing an LG-14 rendered PNG/JPG with OCR or vision to create LG-15 or LG-16 product facts;
- using an LG-15 card image as the fact authority for LG-16;
- introducing unsupported product claims from downstream rendered content;
- treating a downstream output as a replacement for the current Master lineage.

## 2. LG-15 product contract

LG-15 produces an immutable product-advertising **Social Card Set**. `SocialKitVersion` is the version authority for the complete set, not a generic all-platform conversion object and not an Instagram-only model.

Instagram is the first publishing target for the LG-15 Beta. Card semantics remain reusable, while each frozen SocialKitVersion continues to pin the target channel, format, channel contract reference, source Master identity, and output identity required by `SOCIAL-01`.

### 2.1 Card roles and usable set

The initial semantic roles are:

| Role | Contract |
|---|---|
| `hero` | required |
| `benefit` | required |
| `cta` | required |
| `feature` / `evidence` | optional |
| `usage` | optional |

Five cards are the recommended default presentation when sufficient approved facts and rights-confirmed assets exist. Five is not a hard schema invariant. A usable set contains at least the three required roles; optional roles must not be fabricated when the Master lacks supporting facts or assets.

### 2.2 Ordered card manifest

The SocialKit manifest is an ordered list. Seller-visible order must be stored explicitly and must not be inferred by sorting `logical_target` or another identifier.

Each future card entry must freeze bounded semantic references for:

- stable card identity (`card_id` or existing compatible `logical_target`);
- role and explicit order;
- selected active variant reference;
- copy reference and hash;
- rights-confirmed asset reference and hash;
- rendered output reference and hash when available;
- fact/evidence provenance references;
- bounded status;
- card output hash.

Full copy bodies, prompts, raw provider payloads, image bytes, and raw errors do not belong in the reference-only manifest, checkpoint, or AgentRunEvent payload.

### 2.3 Edit, regeneration, and variants

Initial generation creates one active card set. It must not pre-generate alternatives for every card.

A seller edit, card regeneration, alternative request, reorder, or deletion produces a successor `SocialKitVersion` that pins its parent version identity. Unaffected cards retain their immutable references. The selected variant is part of the successor manifest and canonical hash.

This on-demand strategy is required to avoid unnecessary provider cost, confusing selection UX, and duplicate lineage.

### 2.4 Content and platform responsibilities

LG-15 separates card content semantics from platform rendering.

The content layer owns:

- card roles and order;
- message hierarchy and copy intent;
- approved fact/evidence provenance;
- rights-confirmed asset selection;
- Brand Kit and visual intent;
- content completeness and duplicate-content checks.

The rendering layer owns:

- dimensions and aspect ratio;
- visual render integrity and asset identity;
- safe-area application;
- output file type and output reference/hash.

The platform-validation layer owns:

- platform dimensions and aspect-ratio contract;
- safe area;
- platform copy limits;
- file-type acceptance;
- preview/export manifest parity.

`SOCIAL-05` is therefore a mandatory render/export gate, not a blocker for deterministic card-role and content planning. Numeric platform rules remain a separate product decision and must be fixed in a versioned channel/format contract before platform rendering or export is accepted.

### 2.5 LG-15 quality layers

`CONTENT_QUALITY` covers fact fidelity, rights, role coverage, hierarchy, copy coherence, Brand Kit consistency, duplicate content, explicit order, and set completeness.

`RENDERING_QUALITY` covers output completeness, visual render integrity, and frozen asset/output identity.

`PLATFORM_VALIDATION` covers dimensions, aspect ratio, safe area, platform copy limits, file type, and preview/export parity.

These dimensions should extend the existing quality ownership when implemented. LG-15 must not introduce a parallel Quality Bar architecture.

### 2.6 Intended outputs

LG-15 intends to provide individual card PNG/JPG outputs and a kit ZIP. Exact numeric platform presets and export packaging details are deferred to the versioned rendering/export contract.

## 3. LG-16 product contract

LG-16 remains the **Short-form Video Studio**. It produces a short shopping video focused on the product being used, derived directly from the current CommerceCreativeMasterVersion rather than from LG-14 or LG-15 rendered outputs.

`VideoProjectVersion` is the immutable authority for:

- source Master ID/version/hash;
- common short-form creative plan;
- storyboard and ordered shot/scene identities;
- product and usage asset references;
- editable caption references;
- audio references;
- thumbnail identity;
- frozen preview/final output references and hashes.

Schema and production implementation belong to LG-16.

### 3.1 Common-video strategy

The default flow is:

```text
CommerceCreativeMasterVersion
  -> common short-form creative plan
  -> storyboard and scenes
  -> common rendered short-form video
  -> platform metadata adaptation
```

The first publishing targets are Instagram Reels, TikTok, and YouTube Shorts. The system must not generate three equivalent videos by default. It should adapt caption, title, description, hashtags, or CTA metadata only when supported by approved facts and the platform contract.

A platform-specific render is added only when an actual platform requirement cannot be satisfied by the frozen common video asset. Numeric video specifications are not fixed by this refinement.

### 3.2 LG-16 quality direction

LG-16 quality must preserve the existing `VIDEO-01`~`VIDEO-06` contracts, including fact fidelity, rights, product identity, storyboard/scene continuity, usage realism, unsupported-claim rejection, duration/format validation, editable caption accuracy, and preview/final parity. Scene-level generation and regeneration remain subject to the existing cost-approval, durable outbox, retry, and idempotency contracts.

### 3.3 Intended outputs

LG-16 intends to provide a frozen MP4 plus an optional caption/metadata bundle. Exact platform metadata and render presets are deferred to the LG-16 implementation contract.

## 4. Shared planning rule

LG-15 and LG-16 may use related concepts such as hook, benefit, feature, usage, and CTA. This vocabulary does not authorize a new shared planning service. A shared downstream abstraction may be extracted only after duplicated production logic and a stable common contract are demonstrated.

## 5. Existing LG-15 foundation compatibility

The completed LG-15 A1/A2 foundation remains valid and is not rolled back:

- immutable `SocialKitVersion` and parent lineage;
- reference-only card manifest;
- canonical hash and semantic idempotency;
- current Master authority and stale/cross-scope rejection;
- approved fact, Brand Kit, and rights validation;
- `social_source_guard` and `social_card_planner`;
- PostgreSQL checkpoint and bounded AgentRunEvent lifecycle;
- replay, recovery, and concurrency behavior;
- deterministic fake planning;
- prohibition on DetailPage image re-analysis.

Follow-up LG-15 work extends the manifest with explicit order, roles, selected on-demand variants, provenance, bounded status, and publishing-profile semantics. This refinement requires no database migration. Existing JSON contract version evolution is preferred; a new table is not justified by the current scope.

## 6. Implementation order

LG-15 proceeds in this order:

1. card semantic manifest contract;
2. deterministic role/order planning;
3. content Quality;
4. card rendering contract;
5. card image generation;
6. edit, reorder, delete, and on-demand card variants;
7. platform validation;
8. export;
9. seller UI;
10. headed-browser acceptance and LG-15 closure.

LG-16 implementation starts after LG-15 closure unless a later canonical plan explicitly authorizes independent parallel work.

## 7. Deferred product decisions

This refinement does not define:

- hard enforcement of exactly five cards;
- mandatory inclusion of optional `feature`/`evidence` or `usage` roles;
- Instagram numeric dimensions, aspect ratio, or safe-area values;
- platform copy limits;
- exact PNG/JPG/ZIP packaging details;
- Reels, TikTok, or YouTube Shorts numeric video presets;
- circumstances requiring a platform-specific video render.

Those decisions must be documented in the appropriate versioned render/export contract before the corresponding acceptance gate is implemented.
