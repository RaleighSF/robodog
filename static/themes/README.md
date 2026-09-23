# Demo profiles (Default / Microsoft Azure / AWS)

Pick a profile in the dashboard under **Configure → Demo profile**. The switch is
live and is remembered on the edge in `ui_state.json`. `config.yaml` has three
related settings:

```yaml
ui:
  profile: default        # first-boot default
  lock_profile: ''        # e.g. aws at re:Invent: pins the skin, hides the picker,
                          # and keeps other vendors' names out of the page entirely
  nvidia_badge:
    enabled: true
    platform: ''          # blank = derived from telemetry.device_type
```

Add `?profile=aws` (or `azure`/`default`) to the URL to preview a profile
without saving it. This is disabled while a lock is set.

## Vendor artwork: approved files only

Every vendor needs written approval before its logo can appear in a product UI:

| Vendor | Rule | Where approved artwork comes from |
|---|---|---|
| NVIDIA | Any NVIDIA logo, and any logo placed next to NVIDIA's, needs NVIDIA marketing approval. | NVIDIA Partner Network portal |
| Microsoft | Logos need an express license. Text references ("Built on Microsoft Azure") are fine. Azure architecture icons are licensed for diagrams only, not UI. | trademarks@microsoft.com / partner marketing |
| AWS | Single colour only (white on dark), must be smaller than your own logo, must not imply endorsement. "Powered by AWS" only if the app really runs on AWS. | AWS Partner Central |

So the header shows **plain-text wordmarks** until a file exists. Once approved
artwork arrives, drop it at these paths and it is picked up on the next page load,
with no code change:

- `static/themes/azure/logo.svg`: Microsoft Azure lockup, for dark backgrounds
- `static/themes/aws/logo.svg`: AWS logo, white single-colour
- `static/themes/nvidia/logo.svg`: NVIDIA logo, for dark backgrounds (used in the "Powered by" badges)

**re:Invent:** the 2025 sponsor toolkit says competitor clouds' names and logos
can't be shown. Set `lock_profile: aws` on the re:Invent box.

## Where the design tokens come from

- Azure: Fluent 2 `webDarkTheme`, from `@fluentui/tokens@1.0.0-alpha.24`. Brand
  is #115EA3 / #0F6CBD. The older #0078D4 is not in the Fluent 2 ramp. Segoe UI
  is licensed and never web-served, so the stack falls back to the system font.
- AWS: Cloudscape dark visual refresh, from `@cloudscape-design/design-tokens@3.0.113`.
  Font is Open Sans (Google Fonts). The chrome uses Cloudscape blue, not AWS orange.
- NVIDIA green is #76B900.

The token values and component overrides are in `themes.css`, with the source
token named next to each value.
