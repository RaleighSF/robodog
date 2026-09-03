# Detection Modes Guide

Watch Dog supports **four detection modes** with a priority-based system. Understanding this priority is crucial for switching between modes.

## Detection Mode Priority (Highest to Lowest)

```
1. NLP Mode          ← Highest Priority (overrides all others)
2. Visual Mode       ← Second Priority
3. Text Mode         ← Third Priority
4. Open Detection    ← Default (detects all 80 COCO classes)
```

**Important**: When a higher-priority mode is enabled, lower-priority modes are ignored!

---

## 1. NLP Mode (AI Natural Language)

**Priority**: 🔴 HIGHEST
**Trigger**: `nlp_enabled: true` in config

### What It Does
Uses OpenAI GPT to map natural language descriptions to YOLO classes.

### Examples
- "Find things you can drink from" → `[cup, bottle, wine glass]`
- "Find people" → `[person]`
- "Find electronics" → `[tv, laptop, cell phone, remote, keyboard, mouse]`

### How to Enable
1. Open Configuration (⚙️)
2. Go to "NLP Mode" tab
3. **Check** "Enable NLP Mode"
4. Enter your natural language prompt
5. Click "Test NLP" to preview mapping
6. Click "Save NLP Config"
7. Restart detection

### How to DISABLE (to use other modes)
1. Open Configuration (⚙️)
2. Go to "NLP Mode" tab
3. **Uncheck** "Enable NLP Mode"
4. Click "Save NLP Config"
5. Restart detection

**⚠️ Common Mistake**: Forgetting to uncheck "Enable NLP Mode" when trying to use Visual or Text modes!

---

## 2. Visual Mode (Image-Based Detection)

**Priority**: 🟡 SECOND
**Trigger**: Visual prompt images uploaded + NLP disabled

### What It Does
Detects objects similar to uploaded reference images using YOLO-E's visual prompting.

### Example
Upload a photo of your UPS battery backup → System detects similar UPS devices in the camera feed.

### How to Enable
1. **FIRST**: Disable NLP Mode (see above)
2. Open Configuration (⚙️)
3. Go to "Visual Prompts" tab
4. Click "Click to upload images"
5. Select one or more reference images
6. Assign class names to each image
7. Click "Upload Visual Prompts"
8. Restart detection

### Requirements
- ✅ NLP Mode must be **disabled**
- ✅ At least one visual prompt image uploaded
- ✅ Images should be clear, well-lit, 256-640px

---

## 3. Text Mode (Manual Class Names)

**Priority**: 🟢 THIRD
**Trigger**: Text prompts configured + NLP disabled + No visual prompts

### What It Does
Detects specific YOLO class names you manually specify.

### Available Classes
80 standard COCO classes:
- People: `person`
- Vehicles: `car`, `truck`, `bus`, `motorcycle`, `bicycle`, `airplane`, `boat`, `train`
- Animals: `cat`, `dog`, `bird`, `horse`, `sheep`, `cow`, `bear`, `elephant`, `zebra`, `giraffe`
- Objects: `cup`, `bottle`, `wine glass`, `fork`, `knife`, `spoon`, `bowl`, `laptop`, `cell phone`, `tv`, `mouse`, `keyboard`, `remote`, `book`, `clock`, `vase`, `scissors`
- Furniture: `chair`, `couch`, `bed`, `dining table`, `toilet`
- Food: `banana`, `apple`, `sandwich`, `orange`, `broccoli`, `carrot`, `hot dog`, `pizza`, `donut`, `cake`
- And more... [Full list](https://github.com/ultralytics/ultralytics/blob/main/ultralytics/cfg/datasets/coco.yaml)

### How to Enable
1. **FIRST**: Disable NLP Mode
2. **SECOND**: Remove all Visual Prompts (if any)
3. Open Configuration (⚙️)
4. Go to "Text Prompts" tab
5. Enter class names separated by commas: `person, car, cup, laptop`
6. Click "Save Text Prompts"
7. Restart detection

### Requirements
- ✅ NLP Mode must be **disabled**
- ✅ No visual prompts uploaded
- ✅ At least one text prompt configured

---

## 4. Open Detection (Detect Everything)

**Priority**: ⚪ LOWEST (Default)
**Trigger**: All modes disabled/empty

### What It Does
Detects all 80 COCO classes simultaneously.

### How to Enable
1. Disable NLP Mode
2. Remove all Visual Prompts
3. Clear all Text Prompts
4. Save configuration
5. Restart detection

This is the default fallback mode.

---

## Quick Reference: Mode Switching Checklist

### Want to use NLP Mode?
- [x] Enable "NLP Mode" checkbox
- [x] Enter natural language prompt
- [x] Save NLP Config

### Want to use Visual Mode?
- [x] **Uncheck** "Enable NLP Mode"
- [x] Save NLP Config
- [x] Upload visual prompt images
- [x] Restart detection

### Want to use Text Mode?
- [x] **Uncheck** "Enable NLP Mode"
- [x] Save NLP Config
- [x] Remove all visual prompts
- [x] Enter text class names
- [x] Save Text Prompts
- [x] Restart detection

### Want to detect everything?
- [x] **Uncheck** "Enable NLP Mode"
- [x] Remove all visual prompts
- [x] Clear text prompts
- [x] Save All Configuration

---

## Common Issues

### "I can't switch to Visual Mode!"
**Problem**: NLP Mode is still enabled
**Solution**: Go to NLP tab → Uncheck "Enable NLP Mode" → Save

### "I can't switch to Text Mode!"
**Problem**: NLP Mode enabled OR visual prompts uploaded
**Solution**:
1. Disable NLP Mode
2. Remove all visual prompts
3. Then configure text prompts

### "The mode badge shows NLP but I disabled it!"
**Problem**: Configuration saved but detection not restarted
**Solution**: Stop detection → Start detection (reload required)

---

## Technical Details

Detection mode is determined by this logic in `config.py`:

```python
def get_detection_mode(self) -> str:
    if self.is_nlp_enabled():
        return "nlp"     # Highest priority
    elif self.has_visual_prompts():
        return "visual"  # Second priority
    elif self.has_text_prompts():
        return "text"    # Third priority
    else:
        return "open"    # Default fallback
```

The mode is evaluated **in order**, so the first match wins!
