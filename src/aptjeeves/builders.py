from __future__ import annotations

import os

from aptjeeves.config import Settings
from aptjeeves.extraction.fake_extractor import FakeExtractor
from aptjeeves.extraction.llm_extractor import LLMExtractor
from aptjeeves.retrieval.intent import KeywordIntentClassifier, OpenAIIntentClassifier
from aptjeeves.answering.formatter import AnswerFormatter


def build_embedding_model(settings: Settings) -> object:
    """Instantiate the embedding model specified in settings."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if settings.embedding_model and settings.embedding_model != "local" and api_key:
        from aptjeeves.indexing.openai_embeddings import OpenAIEmbeddingModel

        return OpenAIEmbeddingModel(api_key=api_key, model=settings.embedding_model)

    from aptjeeves.indexing.embeddings import LocalTokenEmbeddingModel

    return LocalTokenEmbeddingModel()


def build_answerer(settings: Settings) -> object:
    """Instantiate the answerer (LLM or template formatter) based on settings."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if settings.llm_model and settings.llm_provider == "openai" and api_key:
        from aptjeeves.answering.llm_answerer import LLMAnswerer

        return LLMAnswerer(api_key=api_key, model=settings.llm_model)

    return AnswerFormatter()


def build_extractor(settings: Settings) -> object:
    """Instantiate the extractor backend for extraction commands."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if settings.extraction_backend == "openai" and api_key:
        return LLMExtractor(api_key=api_key, model=settings.extraction_model)
    return FakeExtractor()


def build_intent_classifier(settings: Settings) -> object:
    """Instantiate the intent classifier backend for ask commands."""

    api_key = os.environ.get("OPENAI_API_KEY")
    if settings.intent_backend == "openai" and api_key:
        return OpenAIIntentClassifier(api_key=api_key, model=settings.intent_model)
    return KeywordIntentClassifier()