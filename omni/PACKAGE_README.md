# yibuapi 样例代码发布包

本包提供以下可直接运行的 Python 样例：

- `qwen35_omni_flash.py`：`qwen3.5-omni-flash` HTTP Chat Completions
- `qwen35_omni_plus.py`：`qwen3.5-omni-plus` HTTP Chat Completions
- `qwen35_omni_plus_realtime.py`：`qwen3.5-omni-plus-realtime` WebSocket
- `gemini31_flash_live.py`：`gemini-3.1-flash-live-preview` Gemini Live WebSocket
- `chat_completions_generic.py`：通用 OpenAI 兼容 Chat Completions
- `yibu_audit.py`：逐调用追加式 token 审计
- `summarize_usage.py`：JSON/CSV token 汇总归档

完整安装、调用、无代理设置和 token 统计说明见包内 `README.md`。

## 安全边界

- 包内不含 API Key，运行时只读取环境变量 `YIBU_API_KEY`。
- HTTP 显式设置 `trust_env=False`；WebSocket 显式设置 `proxy=None`。
- 不包含开发机虚拟环境、缓存、真实调用台账、Key 后四位、内部来源路径或历史预测数据。
- `.env.example` 中的凭据值为空。

## 验证状态

2026-09-18 已对五个正式入口完成真实在线最小调用，均曾成功返回内容及 usage。历史瞬时失败和具体调用台账未收入分享包。包内另含无需 Key 的单元测试。

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```
