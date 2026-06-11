# Tentative Plans

This document records alternative plans and tentative designs for future reference.

## Plan B: Environment Variable / Key Vault Mapping Pattern

### Overview

Instead of exposing raw sensitive credentials (like `api_key`, `base_url`, or `model_name`) in model configuration files or passing them directly to the framework, the configuration only holds references to environment variables or key vault paths.

### Configuration Schema Example

```yaml
gemini:
  model_type: "llm"
  api_type: "gemini"
  model_name: "gemini-3.5-flash"
  api_key: "ENV:MY_GEMINI_SECRET_KEY"  # Resolves at runtime from os.environ
  base_url: "ENV:MY_GEMINI_ENDPOINT"   # Resolves at runtime from os.environ
  ai_note: "gemini-3.5-flash - A very impressive large model"
```

### Execution logic

1. The host application writes placeholders prefixed with `ENV:` or a custom format in the config.
2. The framework parses these credentials at runtime by querying:
   * System environment variables (`os.environ.get(env_var_name)`).
   * A custom credential resolver callback function registered by the host application on the manager.
