# SSP Video Studio

**AI运动科学科普视频全自动生产平台** — 从知识库到成品视频的完整管线。

## 功能

- 📚 **Obsidian 知识库集成** — 直接读取笔记，自动评分选题
- 🖼️ **循证证据管理** — 文献原图导入/检测/增强/标注
- 🎬 **Manim 动画渲染** — 一键触发 -ql/-qh 渲染
- 🔊 **TTS 中文配音** — edge-tts 自动生成
- 🎥 **ffmpeg 自动装配** — 场景拼接 + 音频同步
- ✅ **六道 QC 关卡** — 数据保真度/证据覆盖/代码质量/渲染/配音/技术合规
- 📡 **SSE 实时日志** — 渲染进度实时推送

## 快速启动

```bash
# 本地
双击 start.bat  →  http://127.0.0.1:5199

# 或命令行
cd ssp-video-studio
pip install -r requirements.txt
python -m backend.app
```

## 云端部署 (Render)

1. Fork 此仓库到你的 GitHub
2. 在 [Render](https://render.com) 创建新 Web Service
3. 连接 GitHub 仓库
4. Render 自动读取 `render.yaml` 完成部署

## 技术栈

- **后端**: Flask 3 + SQLAlchemy 2.0 + gunicorn
- **前端**: 单页面应用 (SSP 暗色主题)
- **动画**: Manim CE
- **配音**: edge-tts
- **视频**: ffmpeg (H.264 CRF 18)
- **数据库**: SQLite (本地) / Render 持久化磁盘

## 文档

- `完整架构_V2.md` — 十层系统架构
- `证据图质量与交互系统.md` — 证据图质量标准 + 10种展示模式
