"""Quick LLM connection diagnostic."""

import sys


def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:11434/v1"
    api_key = sys.argv[2] if len(sys.argv) > 2 else "ollama"
    model = sys.argv[3] if len(sys.argv) > 3 else "qwen2.5"

    print(f"Base URL : {base_url}")
    print(f"API Key  : {api_key[:8]}{'*' * max(0, len(api_key) - 8)}")
    print(f"Model    : {model}")
    print()

    # Step 1: raw HTTP check
    print("[1/3] 检查端点是否可达...")
    import urllib.request
    import urllib.error

    try:
        # Strip /v1 suffix to hit the root
        root_url = base_url.rstrip("/")
        if root_url.endswith("/v1"):
            root_url = root_url[:-3]
        req = urllib.request.Request(root_url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            print(f"  ✅ HTTP {resp.status} — 端点可达")
    except urllib.error.URLError as e:
        print(f"  ❌ 无法连接: {e.reason}")
        print(f"     请确认服务已启动，地址正确")
        return
    except Exception as e:
        print(f"  ⚠️  {e} (继续尝试...)")

    # Step 2: list models
    print("[2/3] 查询可用模型...")
    try:
        from openai import OpenAI

        client = OpenAI(base_url=base_url, api_key=api_key)
        models = client.models.list()
        model_ids = [m.id for m in models.data]
        if model_ids:
            print(f"  ✅ 找到 {len(model_ids)} 个模型:")
            for mid in model_ids[:10]:
                marker = " 👈" if mid == model else ""
                print(f"     - {mid}{marker}")
            if len(model_ids) > 10:
                print(f"     ... 还有 {len(model_ids) - 10} 个")
            if model not in model_ids:
                print(f"  ⚠️  目标模型 '{model}' 不在列表中!")
                print(f"     可用模型: {', '.join(model_ids[:5])}")
        else:
            print("  ⚠️  未找到模型（列表为空）")
    except Exception as e:
        print(f"  ⚠️  无法列出模型: {e}")
        print(f"     (部分 API 不支持 /models 端点，继续尝试...)")

    # Step 3: actual chat completion
    print(f"[3/3] 测试 chat completion (model={model})...")
    try:
        from wechat_summary.llm_client import LLMClient

        llm = LLMClient(base_url=base_url, api_key=api_key, model=model)
        response = llm.chat([{"role": "user", "content": "请用一句话回答：1+1等于几？"}])
        print(f"  ✅ 模型响应: {response[:200]}")
        print()
        print("🎉 LLM 连接正常，可以使用 --summarize 了！")
    except Exception as e:
        print(f"  ❌ Chat completion 失败: {e}")
        print()
        print("排查建议:")
        print(f"  1. 确认模型 '{model}' 已下载/加载")
        print(f"  2. 检查 API key 是否正确")
        print(f"  3. 尝试 curl: curl {base_url}/chat/completions \\")
        print(f'     -H "Authorization: Bearer {api_key[:8]}..." \\')
        print(f'     -d \'{{"model":"{model}","messages":[{{"role":"user","content":"hi"}}]}}\'')


if __name__ == "__main__":
    main()
