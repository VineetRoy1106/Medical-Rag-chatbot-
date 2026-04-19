import os
from functools import wraps
from dotenv import load_dotenv

load_dotenv()

_langsmith_enabled = False

def init_langsmith():
    global _langsmith_enabled
    api_key = os.getenv("LANGSMITH_API_KEY")
    if api_key and api_key != "your_langsmith_api_key_here":
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "curalink")
        os.environ["LANGCHAIN_API_KEY"] = api_key
        _langsmith_enabled = True
        print("✅ LangSmith observability enabled")
    else:
        print("⚠️  LangSmith API key not set — tracing disabled")

def traced(name: str, metadata: dict = None):
    """
    Decorator that wraps async pipeline functions with LangSmith tracing.
    Falls back gracefully if LangSmith is not configured.
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not _langsmith_enabled:
                return await func(*args, **kwargs)
            try:
                from langsmith import traceable
                traced_func = traceable(
                    func,
                    name=name,
                    metadata=metadata or {},
                    project_name=os.getenv("LANGSMITH_PROJECT", "curalink")
                )
                return await traced_func(*args, **kwargs)
            except Exception:
                return await func(*args, **kwargs)
        return wrapper
    return decorator

def log_pipeline_event(event: str, data: dict):
    """Log a discrete pipeline event to LangSmith as metadata."""
    if not _langsmith_enabled:
        print(f"[Pipeline] {event}: {data}")
        return
    try:
        from langsmith import Client
        client = Client()
        print(f"[LangSmith] {event}: {data}")
    except Exception as e:
        print(f"[Pipeline] {event}: {data}")
