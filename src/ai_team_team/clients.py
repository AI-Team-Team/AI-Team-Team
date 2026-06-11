from typing import Optional, Any

class OpenAIClient:
    """Wraps the official OpenAI SDK client under the unified generate protocol."""
    def __init__(self, api_key: str, model: str = "gpt-4o", base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url

        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "The 'openai' library is required to use OpenAIClient. "
                "Please install it using: pip install openai"
            )
        self._raw_client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> str:
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        kwargs = {}
        if require_json:
            kwargs["response_format"] = {"type": "json_object"}

        response = self._raw_client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            **kwargs
        )
        return response.choices[0].message.content


class GoogleGenAIClient:
    """Wraps the official google-genai SDK client under the unified generate protocol."""
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key
        self.model = model

        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ImportError(
                "The 'google-genai' library is required to use GoogleGenAIClient. "
                "Please install it using: pip install google-genai"
            )
        self._genai_module = genai
        self._types_module = types
        self._raw_client = genai.Client(api_key=self.api_key)

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> str:
        model_name = self.model
        # Strip models/ prefix if present because the modern SDK handles it or prepends it
        if model_name.startswith("models/"):
            model_name = model_name[7:]

        config_kwargs = {
            "temperature": temperature
        }
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction
        if require_json:
            config_kwargs["response_mime_type"] = "application/json"

        config = self._types_module.GenerateContentConfig(**config_kwargs)

        response = self._raw_client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=config
        )
        return response.text


class AnthropicClient:
    """Wraps the official Anthropic SDK client under the unified generate protocol."""
    def __init__(self, api_key: str, model: str = "claude-3-5-sonnet-20240620"):
        self.api_key = api_key
        self.model = model

        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "The 'anthropic' library is required to use AnthropicClient. "
                "Please install it using: pip install anthropic"
            )
        self._raw_client = Anthropic(api_key=self.api_key)

    def generate(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.7,
        require_json: bool = False
    ) -> str:
        kwargs = {}
        if system_instruction:
            kwargs["system"] = system_instruction

        user_prompt = prompt
        if require_json and "json" not in user_prompt.lower():
            user_prompt += "\n\nReturn ONLY a valid JSON object."

        response = self._raw_client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
            **kwargs
        )
        return response.content[0].text
