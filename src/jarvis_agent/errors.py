"""Error hierarchy used at CLI and agent boundaries."""


class JarvisError(Exception):
    """Base class for expected JARVIS failures."""

    code = "jarvis_error"


class ConfigurationError(JarvisError):
    code = "configuration_error"


class ModelError(JarvisError):
    code = "model_error"


class ModelAuthenticationError(ModelError):
    code = "authentication_error"


class ModelRateLimitError(ModelError):
    code = "rate_limit_error"


class ModelResponseError(ModelError):
    code = "model_response_error"


class ToolError(JarvisError):
    code = "tool_error"


class PolicyError(ToolError):
    code = "policy_error"


class AgentLimitError(JarvisError):
    code = "agent_limit_error"

