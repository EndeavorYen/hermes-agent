# Accessible Explanation Contract

## Project Profile

`explanation_profile.json` uses schema
`story_video_accessible_explanation_v1` and records:

```json
{
  "schema": "story_video_accessible_explanation_v1",
  "profile_id": "story-video-accessible-explainer-v1",
  "mode": "accessible",
  "activation": "default",
  "scope": "explanatory_beats_only",
  "audience_target": "curious_newcomer_5_plus",
  "explanation_order": [
    "concrete_intuition",
    "causal_chain",
    "formal_term",
    "precision_boundary"
  ],
  "baby_talk_forbidden": true,
  "precision_loss_forbidden": true
}
```

Explicit `advanced` and `professional` requests use
`activation=operator_override`. The file is created and locked by runtime.

## Review Evidence

For `accessible` explanatory work, `script_review_report.json` includes one
`newcomer_comprehension_editor` with score 85 or higher and:

```json
{
  "accessibility_metrics": {
    "schema": "story_video_accessibility_metrics_v1",
    "status": "PASS",
    "unexplained_jargon": [],
    "baby_talk_detected": false,
    "precision_loss_detected": false,
    "concept_bridges": [
      {
        "term": "總需求",
        "segment_id": "S02",
        "concrete_anchor": "街上的店家同時少了客人",
        "plain_explanation": "大家少花錢，店家就更難賣出商品",
        "precision_boundary": "這是理解景氣循環的入口，不是完整模型"
      }
    ]
  }
}
```

Every `segment_id` must name a real `### Sxx` section. A concept bridge is
evidence, not a score justification: it must show the concrete intuition,
plain causal meaning, and the precision boundary used in the final script.
