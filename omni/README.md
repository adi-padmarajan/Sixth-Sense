# yibuapi 直连调用与 Token 归档样例

这组样例不内置 Key、不读取仓库内 Key 文件、不使用代理。凭据只从进程环境变量 `YIBU_API_KEY` 读取。

## 安装

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
export YIBU_API_KEY='在当前 shell 中填写，不要写进代码'
```

## 模型入口

```bash
# Qwen3.5 Omni Flash：HTTP Chat Completions
python qwen35_omni_flash.py --prompt '你好，请用一句话介绍自己'

# Qwen3.5 Omni Plus：HTTP Chat Completions
python qwen35_omni_plus.py --prompt '你好，请用一句话介绍自己'

# Qwen3.5 Omni Plus Realtime：WebSocket
python qwen35_omni_plus_realtime.py --prompt '你好，请用一句话介绍自己'

# Gemini 3.1 Flash Live：Gemini Live WebSocket
python gemini31_flash_live.py --prompt '请简短回答：北京是哪个国家的首都？'

# 其他普通 OpenAI 兼容模型
python chat_completions_generic.py --model '精确模型 ID' --prompt '你好'
```

Qwen HTTP Omni 样例还支持本地图片或音频：

```bash
python qwen35_omni_flash.py --prompt '描述图片' --image /path/example.jpg
python qwen35_omni_plus.py --prompt '转写并总结音频' --audio /path/example.wav
```

Gemini Live 原生返回音频，脚本通过 `outputAudioTranscription` 输出文本。可用 `--audio-out reply.pcm` 保存原始音频字节。

## Token 审计与汇总

每次成功或失败调用都会自动向 `artifacts/yibu_api_calls.jsonl` 追加记录；不需要单独运行 audit。记录中不保存完整 Key、prompt 或模型正文。

也可以指定持久台账位置：

```bash
export YIBU_AUDIT_LOG=/path/yibu_api_calls.jsonl
```

任务结束后手动汇总：

```bash
python summarize_usage.py
```

默认生成：

```text
artifacts/summary/usage_summary.json
artifacts/summary/usage_by_model_key_purpose.csv
```

支持 OpenAI Chat Completions、OpenAI Realtime 和 Gemini Live 的 usage 字段。上游没有返回 usage 时保持 `null` 并增加 missing 计数，不能把未知消费当成 0。

## 无代理保证

- HTTP：`httpx.Client(..., trust_env=False)`
- WebSocket：`websockets.connect(..., proxy=None)`

因此不会读取 `HTTP_PROXY`、`HTTPS_PROXY` 或 `ALL_PROXY`。

## 离线测试

```bash
python -m unittest discover -s tests -v
python -m compileall -q .
```
