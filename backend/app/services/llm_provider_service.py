"""
LLM Provider Detection, Validation and Model Discovery Service.
Supports Google Gemini, OpenAI, Groq, OpenRouter, DeepSeek, Anthropic, and custom OpenAI-compatible endpoints.
"""

import time
import requests
from typing import Dict, Any, List, Optional
from openai import OpenAI

from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('oracle.llm_provider')


class LLMProviderService:
    """Service to auto-detect API keys, query available models, and test connections."""

    @classmethod
    def detect_provider(cls, api_key: str) -> Dict[str, Any]:
        """
        Detects LLM provider from the API key format, provides default base_url,
        and attempts to fetch available models from the provider API.
        """
        key = api_key.strip()
        provider = "custom"
        provider_name = "OpenAI Compatível (Custom)"
        suggested_base_url = "https://api.openai.com/v1"
        suggested_models: List[Dict[str, str]] = []

        # 1. Google Gemini
        if key.startswith("AIza") or key.startswith("AQ"):
            provider = "google"
            provider_name = "Google Gemini (AI Studio)"
            suggested_base_url = "https://generativelanguage.googleapis.com/v1beta/openai/"
            suggested_models = cls._fetch_gemini_models(key)
            if not suggested_models:
                suggested_models = [
                    {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash (Recomendado - Rápido & Inteligente)"},
                    {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro (Alta Capacidade / Raciocínio Jurídico)"},
                    {"id": "gemini-3.5-flash-lite", "name": "Gemini 3.5 Flash Lite (Econômico / Enxame Massivo)"},
                    {"id": "gemini-3.5-flash", "name": "Gemini 3.5 Flash"},
                    {"id": "gemini-1.5-flash", "name": "Gemini 1.5 Flash"},
                    {"id": "gemini-1.5-pro", "name": "Gemini 1.5 Pro"}
                ]

        # 2. Groq
        elif key.startswith("gsk_"):
            provider = "groq"
            provider_name = "Groq Cloud (Ultra Rápido LPU)"
            suggested_base_url = "https://api.groq.com/openai/v1"
            suggested_models = cls._fetch_openai_compatible_models(suggested_base_url, key)
            if not suggested_models:
                suggested_models = [
                    {"id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B Versatile"},
                    {"id": "llama-3.1-8b-instant", "name": "Llama 3.1 8B Instant"},
                    {"id": "mixtral-8x7b-32768", "name": "Mixtral 8x7B 32k"}
                ]

        # 3. OpenRouter
        elif key.startswith("sk-or-"):
            provider = "openrouter"
            provider_name = "OpenRouter"
            suggested_base_url = "https://openrouter.ai/api/v1"
            suggested_models = cls._fetch_openai_compatible_models(suggested_base_url, key)
            if not suggested_models:
                suggested_models = [
                    {"id": "google/gemini-2.5-flash", "name": "Gemini 2.5 Flash (via OpenRouter)"},
                    {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet"},
                    {"id": "deepseek/deepseek-chat", "name": "DeepSeek V3"}
                ]

        # 4. Anthropic
        elif key.startswith("sk-ant-"):
            provider = "anthropic"
            provider_name = "Anthropic Claude"
            suggested_base_url = "https://api.anthropic.com/v1"
            suggested_models = [
                {"id": "claude-3-5-sonnet-20241022", "name": "Claude 3.5 Sonnet (Recomendado)"},
                {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku (Rápido)"},
                {"id": "claude-3-opus-20240229", "name": "Claude 3 Opus"}
            ]

        # 5. DeepSeek
        elif key.startswith("deepseek-") or "deepseek" in key.lower():
            provider = "deepseek"
            provider_name = "DeepSeek"
            suggested_base_url = "https://api.deepseek.com"
            suggested_models = [
                {"id": "deepseek-chat", "name": "DeepSeek Chat (V3)"},
                {"id": "deepseek-reasoner", "name": "DeepSeek Reasoner (R1 Raciocínio Jurídico)"}
            ]

        # 6. OpenAI
        elif key.startswith("sk-"):
            provider = "openai"
            provider_name = "OpenAI Oficial"
            suggested_base_url = "https://api.openai.com/v1"
            suggested_models = cls._fetch_openai_compatible_models(suggested_base_url, key)
            if not suggested_models:
                suggested_models = [
                    {"id": "gpt-4o", "name": "GPT-4o (Recomendado)"},
                    {"id": "gpt-4o-mini", "name": "GPT-4o Mini (Econômico / Enxame)"},
                    {"id": "o1", "name": "o1 (Raciocínio Profundo)"},
                    {"id": "o3-mini", "name": "o3-mini"}
                ]

        # 7. Fallback / Custom
        else:
            suggested_models = [
                {"id": "gpt-4o-mini", "name": "gpt-4o-mini"},
                {"id": "gpt-4o", "name": "gpt-4o"}
            ]

        default_model = suggested_models[0]["id"] if suggested_models else "gpt-4o-mini"

        return {
            "provider": provider,
            "provider_name": provider_name,
            "base_url": suggested_base_url,
            "default_model": default_model,
            "models": suggested_models
        }

    @classmethod
    def _fetch_gemini_models(cls, api_key: str) -> List[Dict[str, str]]:
        """Queries Google Gemini API for models supporting generateContent."""
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
            res = requests.get(url, timeout=7)
            if res.status_code == 200:
                data = res.json()
                raw_models = data.get("models", [])
                result = []
                for m in raw_models:
                    name = m.get("name", "")
                    if name.startswith("models/"):
                        model_id = name.split("/", 1)[1]
                    else:
                        model_id = name

                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        display = m.get("displayName") or model_id
                        result.append({"id": model_id, "name": f"{display} ({model_id})"})
                
                # Sort putting flash/pro first
                result.sort(key=lambda x: (
                    0 if "flash" in x["id"] else 1 if "pro" in x["id"] else 2,
                    x["id"]
                ))
                return result
        except Exception as e:
            logger.warning(f"Could not fetch dynamic Gemini models: {e}")
        return []

    @classmethod
    def _fetch_openai_compatible_models(cls, base_url: str, api_key: str) -> List[Dict[str, str]]:
        """Queries /models endpoint for OpenAI-compatible providers."""
        try:
            url = f"{base_url.rstrip('/')}/models"
            headers = {"Authorization": f"Bearer {api_key}"}
            res = requests.get(url, headers=headers, timeout=7)
            if res.status_code == 200:
                data = res.json()
                items = data.get("data", [])
                result = []
                for item in items:
                    m_id = item.get("id")
                    if m_id:
                        result.append({"id": m_id, "name": m_id})
                result.sort(key=lambda x: x["id"])
                return result[:50]
        except Exception as e:
            logger.warning(f"Could not fetch models from {base_url}: {e}")
        return []

    @classmethod
    def test_connection(cls, api_key: str, base_url: str, model: str) -> Dict[str, Any]:
        """Tests an LLM connection by sending a lightweight completion."""
        try:
            client = OpenAI(
                api_key=api_key.strip(),
                base_url=base_url.strip(),
                timeout=15.0
            )
            start = time.time()
            response = client.chat.completions.create(
                model=model.strip(),
                messages=[
                    {"role": "user", "content": "Responda apenas 'OK'."}
                ],
                max_tokens=10,
                temperature=0.1
            )
            latency_ms = round((time.time() - start) * 1000, 2)
            content = ""
            if response.choices and len(response.choices) > 0:
                content = (response.choices[0].message.content or "").strip()

            return {
                "success": True,
                "latency_ms": latency_ms,
                "response": content or "OK",
                "message": f"Conexão bem-sucedida! Latência: {latency_ms}ms"
            }
        except Exception as e:
            logger.error(f"LLM connection test failed: {e}")
            return {
                "success": False,
                "error": str(e)
            }
