# test_env.py
 
print("环境验证开始")
print("=" * 40)

# 1. Python 版本
import sys
print(f"Python 版本: {sys.version}")

# 2. 关键包
from importlib.metadata import version as pkg_version
print(f"LangGraph 版本: {pkg_version('langgraph')}")


import langchain_core
print(f"LangChain Core 版本: {langchain_core.__version__}")

import pydantic
print(f"Pydantic 版本: {pydantic.__version__}")

# 3. .env 加载
from dotenv import load_dotenv
import os
load_dotenv(override=True)

dashscope_key = os.getenv("DASHSCOPE_API_KEY")
if dashscope_key:
    print(f"阿里云百炼 API Key 已配置: {dashscope_key[:8]}...{dashscope_key[-4:]}")
else:
    print("⚠️  未检测到 DASHSCOPE_API_KEY，请在 .env 文件中配置")

# 4. 模型调用测试
if dashscope_key:
    from langchain_openai import ChatOpenAI
    model = ChatOpenAI(
        model="qwen-plus",
        api_key=dashscope_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    response = model.invoke("回复'一切正常'四个字，不要其他内容")
    print(f"模型调用测试: {response.content}")
else:
    print("⚠️  跳过模型调用测试（缺少 API Key）")

print("=" * 40)
print("环境验证完成")
print("=" * 40)