# NLP Mode Usage Guide

## How NLP Detection Works

The NLP (Natural Language Processing) mode allows you to describe what you want to detect using natural language instead of manually selecting YOLO class names.

### Examples of NLP Prompts

| Natural Language Prompt | Mapped YOLO Classes |
|------------------------|-------------------|
| "Find things you can drink from" | cup, bottle, wine glass |
| "Find people" | person |
| "Find electronics" | tv, laptop, cell phone, remote, keyboard, mouse, hair drier |
| "Find all furniture" | chair, couch, bed, dining table |
| "Find sharp objects" | knife, scissors |
| "Find kitchen appliances" | microwave, oven, toaster, refrigerator |

### How to Use NLP Mode

1. **Open Configuration**
   - Click the gear icon (⚙️) in the top right corner

2. **Go to NLP Tab**
   - Click on the "NLP" tab in the configuration modal

3. **Enable NLP Mode**
   - Check the "Enable NLP Mode" checkbox

4. **Enter Your Prompt**
   - Type your natural language description in the text area
   - Example: "Find things you can drink from"

5. **Test Your Prompt** ⚠️ IMPORTANT
   - Click the **"Test NLP"** button
   - This will show you which YOLO classes your prompt maps to
   - Review the mapped classes to ensure they match your intent

6. **Save Configuration** ⚠️ CRITICAL STEP
   - Click **"Save NLP Config"** or **"Save All Configuration"**
   - **The detection will NOT update until you save!**

7. **Restart Detection (if running)**
   - If detection is already running, stop and restart it
   - The new NLP mapping will be applied

### Common Issues

#### Issue: "NLP doesn't detect the classes I want"

**Solution**: You probably didn't click the Save button!

1. Update your NLP prompt
2. Click "Test NLP" to verify the mapping
3. **Click "Save NLP Config"** to apply the changes
4. If detection is running, stop and restart it

#### Issue: "Test NLP works but detection doesn't use the new classes"

**Solution**: The detector needs to be reloaded after saving.

1. After saving, **stop the current detection**
2. **Start detection again**
3. The new NLP mapping should now be active

### Technical Details

- **NLP Engine**: Uses OpenAI GPT-4o-mini for intelligent class mapping
- **Available Classes**: 80 COCO classes (person, car, cup, etc.)
- **API Requirements**: Requires valid OpenAI API key
- **Mapping Logic**:
  - Analyzes your natural language prompt
  - Identifies relevant YOLO classes from the 80 available classes
  - Returns only classes that genuinely match your intent
  - Excludes unrelated classes (e.g., "electronics" won't include "sink")

### Test Results (Verified Working)

Tested on 2025-10-19:

```
✅ "Find things you can drink from" → ["cup", "bottle", "wine glass"]
✅ "Find people" → ["person"]
✅ "Find electronics" → ["tv", "laptop", "cell phone", "remote", "keyboard", "mouse", "hair drier"]
```

All mappings are accurate and working correctly!
