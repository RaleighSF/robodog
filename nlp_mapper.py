#!/usr/bin/env python3
"""
NLP-based Class Mapper for YOLO Detection
Uses OpenAI to intelligently map natural language prompts to YOLO class names
"""
import os
import json
from typing import List, Dict, Optional
import requests

class NLPClassMapper:
    """Maps natural language prompts to YOLO classes using OpenAI"""

    # Standard COCO 80 classes that YOLO11 supports
    YOLO_CLASSES = [
        'person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat',
        'traffic light', 'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat',
        'dog', 'horse', 'sheep', 'cow', 'elephant', 'bear', 'zebra', 'giraffe', 'backpack',
        'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee', 'skis', 'snowboard', 'sports ball',
        'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard', 'tennis racket',
        'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
        'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair',
        'couch', 'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse',
        'remote', 'keyboard', 'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator',
        'book', 'clock', 'vase', 'scissors', 'teddy bear', 'hair drier', 'toothbrush'
    ]

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize NLP mapper

        Args:
            api_key: OpenAI API key. If None, will try to read from OPENAI_API_KEY env var
        """
        self.api_key = api_key or os.getenv('OPENAI_API_KEY')
        if not self.api_key:
            print("⚠️ No OpenAI API key provided. NLP prompting will not work.")
            print("💡 Set OPENAI_API_KEY environment variable or pass api_key parameter")

        self.api_url = "https://api.openai.com/v1/chat/completions"

    def map_prompt_to_classes(self, natural_prompt: str) -> List[str]:
        """
        Map a natural language prompt to YOLO class names

        Args:
            natural_prompt: Natural language description like "Find all sharp objects"

        Returns:
            List of YOLO class names that match the prompt

        Examples:
            "Find all sharp objects" -> ["knife", "scissors", "fork"]
            "Detect dangerous items" -> ["knife", "scissors", "bottle"]
            "Find furniture" -> ["chair", "couch", "bed", "dining table"]
        """
        if not self.api_key:
            print("❌ Cannot map prompt: No OpenAI API key configured")
            return []

        try:
            # Build the prompt for OpenAI
            system_prompt = f"""You are an AI assistant that maps natural language object detection requests to specific object classes.

Given a natural language prompt and a list of available object classes, your task is to:
1. Identify which classes from the available list best match the user's intent
2. Be SPECIFIC - only include classes that directly relate to the request
3. For category requests like "electronics", include ONLY electronic devices, not furniture or fixtures
4. Include synonyms and related items (e.g., "katana sword" -> "knife" if knife is closest available)
5. Return ONLY the available class names that make sense, as a JSON array

Available YOLO classes:
{json.dumps(self.YOLO_CLASSES, indent=2)}

Rules:
- Only return classes that exist in the available list above
- Be PRECISE with category matching - electronics means CONSUMER ELECTRONICS only
- "Electronics" category includes ONLY: tv, laptop, cell phone, remote, keyboard, mouse, hair drier
- Plumbing fixtures (sink, toilet) are NEVER electronics - they are fixtures
- Only include items that genuinely match the user's intent
- Return result as a JSON array of strings, nothing else
- If no matches found, return empty array []

Examples:
- "Find all electronics" -> ["tv", "laptop", "cell phone", "remote", "keyboard", "mouse", "hair drier"]
- "Find all kitchen appliances" -> ["microwave", "oven", "toaster", "refrigerator"]
- "Find all sharp objects" -> ["knife", "scissors"]
- "Find all furniture" -> ["chair", "couch", "bed", "dining table"]
- "Find devices" -> ["tv", "laptop", "cell phone", "remote", "keyboard", "mouse"]"""

            user_prompt = f"User request: \"{natural_prompt}\"\n\nReturn matching classes as JSON array:"

            # Call OpenAI API
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "gpt-4o-mini",  # Fast and cost-effective model
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3,  # Lower temperature for more consistent results
                "max_tokens": 500
            }

            print(f"🤖 Sending NLP prompt to OpenAI: '{natural_prompt}'")
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=10)

            print(f"📊 OpenAI response status: {response.status_code}")

            if response.status_code != 200:
                print(f"❌ OpenAI API error: {response.text}")
                response.raise_for_status()

            # Parse response
            result = response.json()
            print(f"📦 OpenAI raw response: {json.dumps(result, indent=2)}")

            content = result['choices'][0]['message']['content'].strip()
            print(f"📝 Extracted content: {content}")

            # Extract JSON array from response
            # Handle cases where GPT might add markdown code blocks
            if content.startswith('```'):
                # Remove markdown code blocks
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            content = content.strip()

            # Parse JSON
            matched_classes = json.loads(content)

            # Validate all returned classes exist in YOLO_CLASSES
            valid_classes = [cls for cls in matched_classes if cls in self.YOLO_CLASSES]

            print(f"✅ NLP mapping: '{natural_prompt}' -> {valid_classes}")

            return valid_classes

        except requests.exceptions.RequestException as e:
            print(f"❌ OpenAI API request failed: {e}")
            return []
        except json.JSONDecodeError as e:
            print(f"❌ Failed to parse OpenAI response as JSON: {e}")
            print(f"Response content: {content}")
            return []
        except Exception as e:
            print(f"❌ NLP mapping error: {e}")
            import traceback
            traceback.print_exc()
            return []

    def map_prompt_with_explanations(self, natural_prompt: str) -> Dict[str, any]:
        """
        Map prompt and return results with explanations

        Returns:
            Dict with 'classes' (list), 'explanation' (str), and 'confidence' (float)
        """
        if not self.api_key:
            return {
                'classes': [],
                'explanation': 'No OpenAI API key configured',
                'confidence': 0.0
            }

        try:
            system_prompt = f"""You are an AI assistant that maps natural language object detection requests to specific object classes.

Given a natural language prompt and a list of available object classes, return a JSON object with:
1. "classes": Array of matching class names from the available list
2. "explanation": Brief explanation of why these classes were chosen
3. "confidence": Float 0-1 indicating how well the available classes match the request

Available YOLO classes:
{json.dumps(self.YOLO_CLASSES, indent=2)}

Example response format:
{{
  "classes": ["knife", "scissors"],
  "explanation": "These are sharp objects commonly used for cutting",
  "confidence": 0.9
}}"""

            user_prompt = f"User request: \"{natural_prompt}\""

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 500,
                "response_format": {"type": "json_object"}
            }

            response = requests.post(self.api_url, headers=headers, json=payload, timeout=10)
            response.raise_for_status()

            result = response.json()
            content = result['choices'][0]['message']['content'].strip()

            parsed = json.loads(content)

            # Validate classes
            parsed['classes'] = [cls for cls in parsed.get('classes', []) if cls in self.YOLO_CLASSES]

            return parsed

        except Exception as e:
            print(f"❌ NLP mapping with explanations error: {e}")
            return {
                'classes': [],
                'explanation': f'Error: {str(e)}',
                'confidence': 0.0
            }


# Singleton instance
_nlp_mapper = None

def get_nlp_mapper(api_key: Optional[str] = None) -> NLPClassMapper:
    """Get or create singleton NLP mapper instance"""
    global _nlp_mapper
    if _nlp_mapper is None:
        _nlp_mapper = NLPClassMapper(api_key)
    return _nlp_mapper
