"""Small native Claude/Gemini adapter. Responses are buffered, not simulated streams."""
import json
import uuid
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        raise HTTPError(request.full_url, code, "Model redirects are disabled", headers, fp)


def open_request(request, timeout):
    return build_opener(NoRedirect()).open(request, timeout=timeout)


class NativeLLM:
    streaming = False
    def __init__(self, config):
        self.config = config
        self.model_name = config["model_name"]

    @staticmethod
    def _tool(index, tool_id, name, args):
        return SimpleNamespace(index=index, id=tool_id, type="function",
                               function=SimpleNamespace(name=name, arguments=json.dumps(args, ensure_ascii=False)))

    def _request(self, dialogue, functions=None):
        cfg = self.config
        base = cfg["base_url"].rstrip("/")
        system = "\n".join(str(m.get("content") or "") for m in dialogue if m.get("role") == "system")
        headers = {"Content-Type": "application/json"}
        provider = cfg.get("provider", "").lower()
        if provider in ("claude", "anthropic"):
            messages = []
            for message in dialogue:
                role = message.get("role")
                if role == "system":
                    continue
                if role == "tool":
                    content = [{"type": "tool_result", "tool_use_id": message["tool_call_id"], "content": str(message.get("content") or "")}]
                    role = "user"
                else:
                    content = []
                    if message.get("content"):
                        content.append({"type": "text", "text": str(message["content"])})
                    for tool in message.get("tool_calls") or []:
                        func = tool["function"]
                        content.append({"type": "tool_use", "id": tool["id"], "name": func["name"], "input": json.loads(func.get("arguments") or "{}")})
                if content:
                    messages.append({"role": role, "content": content})
            body = {"model": self.model_name, "system": system, "messages": messages,
                    "max_tokens": int(cfg.get("max_tokens") or 1024)}
            if functions:
                body["tools"] = [{"name": f["function"]["name"], "description": f["function"].get("description", ""),
                                  "input_schema": f["function"].get("parameters", {"type": "object", "properties": {}})} for f in functions]
            headers.update({"x-api-key": cfg["api_key"], "anthropic-version": "2023-06-01"})
            url = base + ("/messages" if base.endswith("/v1") else "/v1/messages")
        else:
            contents = []
            names = {}
            for message in dialogue:
                role = message.get("role")
                if role == "system":
                    continue
                parts = []
                if role == "tool":
                    parts.append({"functionResponse": {"name": names.get(message["tool_call_id"], "tool"),
                                                       "response": {"result": str(message.get("content") or "")}}})
                elif message.get("content"):
                    parts.append({"text": str(message["content"])})
                for tool in message.get("tool_calls") or []:
                    func = tool["function"]
                    names[tool["id"]] = func["name"]
                    parts.append({"functionCall": {"name": func["name"], "args": json.loads(func.get("arguments") or "{}")}})
                if parts:
                    contents.append({"role": "model" if role == "assistant" else "user", "parts": parts})
            body = {"contents": contents, "systemInstruction": {"parts": [{"text": system}]},
                    "generationConfig": {"maxOutputTokens": int(cfg.get("max_tokens") or 1024)}}
            if functions:
                body["tools"] = [{"functionDeclarations": [{k: f["function"][k] for k in ("name", "description", "parameters") if k in f["function"]} for f in functions]}]
            headers["x-goog-api-key"] = cfg["api_key"]
            url = base + ("" if base.endswith(("/v1", "/v1beta")) else "/v1beta") + "/models/" + quote(self.model_name, safe="") + ":generateContent"
        request = Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with open_request(request, timeout=float(cfg.get("timeout", 20))) as response:
            data = json.load(response)
        if data.get("error"):
            raise RuntimeError("Model provider returned an error")
        texts, tools = [], []
        if provider in ("claude", "anthropic"):
            for part in data.get("content", []):
                if part.get("type") == "text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "tool_use":
                    tools.append(self._tool(len(tools), part["id"], part["name"], part.get("input", {})))
            usage = data.get("usage", {})
            incoming, outgoing = usage.get("input_tokens", 0), usage.get("output_tokens", 0)
        else:
            candidates = data.get("candidates") or []
            for part in (candidates[0].get("content", {}).get("parts", []) if candidates else []):
                if part.get("text"):
                    texts.append(part["text"])
                if part.get("functionCall"):
                    func = part["functionCall"]
                    tools.append(self._tool(len(tools), "gemini-" + uuid.uuid4().hex, func["name"], func.get("args", {})))
            usage = data.get("usageMetadata", {})
            incoming, outgoing = usage.get("promptTokenCount", 0), usage.get("candidatesTokenCount", 0)
        callback = cfg.get("_console_usage")
        if callback:
            callback({"input_tokens": incoming, "output_tokens": outgoing, "total_tokens": incoming + outgoing})
        return "".join(texts), tools

    def response(self, session_id, dialogue, **kwargs):
        yield self._request(dialogue)[0]

    def response_with_functions(self, session_id, dialogue, functions=None, **kwargs):
        yield self._request(dialogue, functions)
