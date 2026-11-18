# Aster MODs（初代）

Aster AI 的第一批扩展 MOD。**不依赖任何 API Key**，装进 `mods/` 就能用。

主仓：[AsterAI](https://gitee.com/Aster-home/aster-ai) · 本仓库只放 MOD，跟随主仓的 [MOD 规范](https://gitee.com/Aster-home/aster-ai/blob/main/docs/mod.md)。

## 两个 MOD

| MOD | 形态 | 做什么 | 触发 |
|---|---|---|---|
| `net_read` | 目录型（`manifest.json` + `main.py`） | 读网页正文 → 筛选 → 整合成资料块，交给主模型回答 | 消息里带链接；或 `/联网：URL 问题`、`/搜索：关键词` |
| `web_bridge` | 单文件（`handle_command`） | 新闻 / 天气 / 搜索 **直接给结果**，不经模型转述 | `看看今天的新闻`、`北京天气`、`帮我查一下…` |

分工：**带链接**的交给 `net_read` 深读；**要实时信息**的交给 `web_bridge` 直出。两者同时启用不冲突——兼容插件先被调用，返回 `None` 才轮到 `net_read`。

## 安装

```bash
# 把 mods/ 下的东西复制到 AsterAI 的 mods 目录
cp -r mods/net_read   <AsterAI>/mods/
cp    mods/web_bridge.py <AsterAI>/mods/
```

- `web_bridge.py`：**丢进去就生效**（主体会自动接管一次单文件插件）；
- `net_read/`：目录型，在「设置 → MOD 管理」里启用；
- 都可以在面板里停用/重载，状态写在 `aster_soul.json`。

## 兼容

- 需要 AsterAI **v1.0.3-beta 及以上**（MOD 系统从这版开始）；
- `net_read` 使用 `api: 2`；旧版本主体会提示"API 版本过高"并拒绝加载；
- `web_bridge` 走兼容接口，`handle_command(text)` 返回字符串即接管本轮回答，返回 `None` 就把话交回 Aster。

## 权限

| MOD | 声明 | 说明 |
|---|---|---|
| `net_read` | `net` | 只能访问 http/https，禁内网、本机、云元数据地址（SSRF 防护） |
| `web_bridge` | 无（旧接口） | 单文件插件不走能力隔离，代码会直接发请求 |

**注意**：MOD 是本机 Python 代码，权限表是能力隔离不是沙箱。只装你看过代码的 MOD。

## 数据来源与边界

- 新闻：IT之家 / Solidot / 少数派 **RSS**，按发布时间取头条，多源轮流；
- 天气：`wttr.in`（JSON），需要带城市名；
- 搜索：`cn.bing.com` 公开结果页 HTML；
- 不渲染 JS、不绕验证码、不重试轰炸；取不到就直说取不到。

## 目录结构

```
mods/
├── net_read/
│   ├── manifest.json    # id / api / 权限 / 钩子 / 指令 / 默认参数
│   ├── main.py          # 读取 → 筛选 → 整合 → 输出
│   └── README.md
└── web_bridge.py        # 兼容接口：handle_command
```

## 许可

MIT，与主仓一致。见 [LICENSE](LICENSE)。
