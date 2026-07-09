# 角色 Prompt 参考

参考了 GitHub 上的角色卡思路：

- SillyTavern：LLM 前端，支持角色、视觉小说模式、图像生成和 TTS。
- character-card-spec-v2：角色卡字段包含 `name / description / personality / scenario / first_mes / system_prompt` 等。
- Character Card V1/V2 规范里明确把 `personality`、`scenario`、`first_mes`、`mes_example` 放进发给模型的上下文。
- Character Card V2 额外使用 `post_history_instructions`，适合放“不要跑偏、不要硬套场景、保持说话分寸”这类持续指令。
- 一些角色卡生成器也强调字段顺序和样例质量，但一期先不做完整导入/导出。

本项目一期采用最小字段：

```json
{
  "name": "",
  "role": "",
  "personality": "",
  "scenario": "",
  "first_message": "",
  "post_history_instructions": "",
  "mes_example": [],
  "avatar_url": "",
  "image_prompt": ""
}
```

没有照搬完整角色卡规范，先只保留对当前产品有用的字段。

本轮调 Prompt 的结论：

- `personality` 不要堆“性感、可爱、温柔”这类抽象标签，容易变成怪腔。
- `scenario` 写具体环境和当下动作，但场景只当背景，不让模型每句话都提风、灯、椅子、雨。
- `first_message` 必须像现实里能说出口的话，不写“楼上的灯还亮着，但你可以先离开它”这种漂亮但不真实的句子。
- `mes_example` 要放普通短句，避免诗化比喻，也避免和用户输入太撞，否则模型会逐字照抄。
- `post_history_instructions` 专门约束后续对话：只回用户最后一句，不复述设定，不写小说旁白。
- 系统 Prompt 明确要求“像现实聊天短句”，比“情绪陪伴者”更不容易有咨询师味。
