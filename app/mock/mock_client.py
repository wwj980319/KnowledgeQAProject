from openai import OpenAI

'''DeepSeek 选择了一个非常务实的策略：让它的 API 格式与 OpenAI 高度对齐，
以降低开发者的迁移和接入成本。
这种兼容性覆盖了 OpenAI 最主要的 Chat Completions API'''

# openai SDK测试
client = OpenAI(
    api_key="sk-",
    base_url="http://localhost:8001/v1",
)

'''
因为 DeepSeek 的 API 兼容 OpenAI 的接口格式，
所以可以直接用 client.chat.completions.create(...) 来调用。
'''
resp = client.chat.completions.create(
    model="deepseek-flash",
    max_tokens=1024,
    messages=[
        # {"role": "system", "content": "你是一个知识库问答助手。只能基于用户提供的资料片段回答问题，并在句末用 [编号] 标注引用来源。若资料片段不足以回答，必须明确回答：资料中没有找到相关内容。不允许编造。"},
        {"role": "user", "content": "资料片段：\n1. 你好\n2. 你好吗\n3. 你好吗？\n\n问题：你好吗？"},
    ],
)

print(resp.choices[0].message.question + ", " + resp.choices[0].message.content)