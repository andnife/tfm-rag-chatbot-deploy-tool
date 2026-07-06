#!/bin/sh
set -e
echo "Pulling default Ollama models..."
ollama pull "${OLLAMA_DEFAULT_LLM_MODEL:-llama3.1}" || echo "WARN: failed to pull LLM model"
ollama pull "${OLLAMA_DEFAULT_EMBEDDING_MODEL:-bge-m3}" || echo "WARN: failed to pull embedding model"
echo "Ollama seed complete."
