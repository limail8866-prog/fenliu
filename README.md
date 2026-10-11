# 分流规则生成器

用一份 YAML 源规则生成 **Shadowrocket（小火箭）** 与 **Mihomo / Clash Meta** 的规则集及配置模板。使用 Python 3.11。仓库不保存节点或个人订阅；公开模板中的订阅地址始终是 `${SUB_URL}`。

## 本地生成

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python validate.py
python build.py
python -m pytest
```

也可用 `uv venv --python 3.11 && uv pip install -r requirements.txt`。输出位于 `dist/`，不提交生成文件；同样的源文件重复构建产生相同内容。构建会先校验规则，校验失败不会开始写出产物。

```text
rules/                     每分类一个 YAML
policy.yaml                策略组、映射、分类顺序及公开规则 URL
upstream.yaml              上游项目、固定提交和导入分类
sources.yaml / SOURCES.md   文件摘要、导入原文、去重统计和许可
build.py / validate.py     生成与校验入口
tests/                     格式转换、策略引用、校验与订阅保密测试
dist/shadowrocket/         各分类 .list + shadowrocket.conf
dist/clash/                各分类 classical .yaml + config.yaml
```

目前从 **blackmatrix7/ios_rule_script** 和 **v2fly/domain-list-community** 的 47 份固定版本文件导入并去重，包含 **14 个分类、78,624 条规则**。来源、跳过统计与许可见 [SOURCES.md](SOURCES.md)。规则仍按分类匹配，但默认只生成一个可见策略组「节点选择」：需代理的分类及漏网流量走节点选择，国内直连分类直接走 `DIRECT`，广告规则直接走 `REJECT`。没有单独分类的网站优先匹配通用代理列表。

| 分类 | 覆盖范围 | 默认策略 |
| --- | --- | --- |
| 广告拦截 | AdvertisingLite 完整兼容规则，38,066 条 | `REJECT` |
| AI | OpenAI、ChatGPT、Sora、Claude、Gemini、Copilot、Grok | 节点选择 |
| 流媒体 | YouTube、Netflix、Spotify、Twitch、Disney+、Prime Video、HBO、Hulu | 节点选择 |
| Telegram | 域名、媒体 CDN、IPv4/IPv6 网段 | 节点选择 |
| X | Twitter/X 主站、t.co 短链、图片、视频、鉴权域名 | 节点选择 |
| GitHub | 主站、源码、资源、容器及存储端点 | 节点选择 |
| 游戏 | Steam、Epic、PlayStation、Xbox、Nintendo、Battle.net、Origin/EA | 节点选择 |
| Apple | Apple、iCloud、App Store 等 | `DIRECT` |
| Microsoft | Microsoft、Office、Outlook、OneDrive、Azure 等 | `DIRECT` |
| 社交媒体 | Facebook、Instagram、WhatsApp、Discord、Reddit、TikTok、Signal、Zoom | 节点选择 |
| Google | Google、Gmail、Drive 等 | 节点选择 |
| 支付 | PayPal、Venmo 等 | 节点选择 |
| 通用代理 | Global 与 Wikimedia，30,978 条 | 节点选择 |
| 国内直连 | China 白名单及私网，3,619 条 | `DIRECT` |

客户端只显示「节点选择」一个策略组。AI、流媒体、Telegram、X、GitHub 等规则仍分别匹配，命中后交给节点选择；Apple、Microsoft、国内服务直接走 `DIRECT`，广告直接走 `REJECT`，都不需要额外策略组。Grok 独立站 `grok.com` 归入 AI 规则，X 服务仍由 X 规则单独匹配。覆盖范围依赖已导入的上游规则，不能保证涵盖所有网站或服务的所有端点。

## 添加规则

向对应的 `rules/*.yaml` 列表追加条目：

```yaml
- type: DOMAIN-SUFFIX
  value: example.com
  comment: 示例服务，包含子域名
- type: DOMAIN
  value: api.example.net
  comment: 只匹配这个域名
- type: IP-CIDR6
  value: 2001:db8::/32
  comment: 文档示例网段，实际使用时替换
```

支持 `DOMAIN`、`DOMAIN-SUFFIX`、`DOMAIN-KEYWORD`、`IP-CIDR`、`IP-CIDR6`、`GEOIP`。不要把 URL、端口或 `*.` 通配符填入域名规则；CIDR 必须是对齐的网络地址且含前缀。IP 规则自动在两端追加 `no-resolve`。域名统一小写，并支持 IDNA 转换。`GEOIP` 的值要加引号，例如 `value: 'NO'`，避免 YAML 把它当成布尔值。

新增分类时同时在 `policy.yaml` 的 `categories` 添加目标（策略组名、`DIRECT` 或 `REJECT`），在 `category_order` 添加位置。当前默认模板只定义「节点选择」组，节点由 `use: [subscription]` 提供；分类规则可以直接选择内置的 `DIRECT` 和 `REJECT`。

两端使用相同的匹配顺序：

1. `ads_reject` → `REJECT`
2. 自定义分类：AI → 流媒体 → Telegram → X → GitHub → 游戏 → Apple → Microsoft → 社交媒体 → Google → 支付 → 通用代理
3. `cn_direct` → `DIRECT`
4. `GEOIP,CN,DIRECT`
5. 小火箭 `FINAL,节点选择` / Mihomo `MATCH,节点选择`

`validate.py` 检查字段、YAML 重复键、规范化后的重复规则、跨分类域名/后缀/关键词覆盖、同版本 IP 网段重叠、映射及策略组循环引用。重复规则始终报错；未声明的跨分类覆盖也报错。完整列表中的合理覆盖必须在 `policy.yaml` 的 `overrides` 写明较高/较低分类和原因，而且与 category_order 一致，例如广告子域名先于国内白名单、Discord 专用资源先于 Google 云平台。当前审阅了 34 对分类覆盖；它们按照原定顺序匹配，不改变拒绝和直连的优先级。

```yaml
overrides:
  - higher: ads_reject
    lower: cn_direct
    reason: 广告子域名先于国内服务的宽泛后缀
```

大规模校验使用域名后缀索引和 CIDR 区间，避免逐条比较全部域名。校验只做静态检查，不下载 GEOIP 数据库或探测服务可用性；无法推断 GEOIP 与 CIDR 的关系，也无法证明所有关键词组合的交集。

## 自动发布与规则订阅

GitHub Actions 在 push（不含 gh-pages）和 main 的 PR 中执行 validate → build → pytest，然后用固定版本且校验 SHA-256 的 Mihomo 编译域名规则集为 `.mrs`。全部通过后，**只有 main 分支**将 `dist/` 内容发布为 `gh-pages` 分支根目录；功能分支和 PR 只校验、不发布。也可手动运行 workflow。工作流不读取个人 SUB_URL，不需要配置订阅 Secret。

首次合并 PR 后 Actions 会创建 gh-pages。若仓库组织策略限制 GITHUB_TOKEN 写权限，需在仓库 Actions 设置允许工作流写入内容。raw 链接不依赖 GitHub Pages 网站开关，但仓库必须公开，客户端才能无鉴权订阅：

```text
https://cdn.jsdelivr.net/gh/limail8866-prog/fenliu@gh-pages/shadowrocket/shadowrocket.conf
https://cdn.jsdelivr.net/gh/limail8866-prog/fenliu@gh-pages/shadowrocket/ai.list
https://cdn.jsdelivr.net/gh/limail8866-prog/fenliu@gh-pages/clash/config.yaml
https://cdn.jsdelivr.net/gh/limail8866-prog/fenliu@gh-pages/clash/ai.yaml
```

规则默认通过 jsDelivr CDN 分发，地址在国内通常比 GitHub Raw 稳定。若 jsDelivr 不可用，可把 `policy.yaml` 中的 `rule_base_url` 改为 `https://raw.githubusercontent.com/limail8866-prog/fenliu/gh-pages` 后重新构建；Fork 时改成自己的 Raw 或 CDN 地址。发布前需先等待 main 的发布任务成功。

每周一自动检查两个上游仓库的新提交，运行 `tools/sync_rules.py` 导入并校验，然后创建或更新规则审阅 PR。更新不会直接发布；规则覆盖冲突或测试失败时，工作流停止并保留当前规则。

## 小火箭导入

1. 在首页添加自己的节点订阅，更新节点。订阅地址只填在客户端。
2. 在「配置」页添加上面的 `shadowrocket.conf` raw URL，下载并使用；全局路由选择「配置」。
3. 配置通过 RULE-SET 自动引用各分类 `.list`。客户端只显示「节点选择」，用 `policy-regex-filter` 自动纳入已导入节点。`[Proxy]` 留空。
4. 规则集更新可使用客户端的规则集更新功能；更新整份配置可能覆盖客户端的自定义修改，长期修改应维护在源 YAML 或 policy.yaml。

如果已有自己的配置，可只加入单个规则集：

```ini
RULE-SET,https://cdn.jsdelivr.net/gh/limail8866-prog/fenliu@gh-pages/shadowrocket/ai.list,AI
```

同时保证 `[Proxy Group]` 存在 AI 策略组，并将此规则放在 GEOIP / FINAL 前面。

## Mihomo / Clash Meta 导入及自己的订阅

`dist/clash/config.yaml` 包含 DNS fake-ip、国内/海外 `nameserver-policy`、唯一可见的「节点选择」组和规则顺序。DOMAIN / DOMAIN-SUFFIX 规则使用 `behavior: domain`，发布时编译成 `.mrs` 二进制；关键词和 IP 规则继续使用 classical。`proxy-providers.subscription.url` 为 **`${SUB_URL}` 占位**；Mihomo 不会自动展开这个字符串，须在本地替换后才可加载。订阅需要提供 Mihomo/Clash 可读的 YAML（含 `proxies`），不能直接使用小火箭格式或普通 Base64 节点列表。

推荐生成仓库外的私人配置。下面命令从终端隐藏读取订阅，再通过环境变量传入，避免把地址写入命令历史：

```bash
read -rsp '输入自己的 Mihomo 订阅 URL: ' SUB_URL; echo
export SUB_URL
python build.py --subscription --output "$HOME/.config/fenliu"
unset SUB_URL
```

本地已安装 Mihomo 时，可加 `--mrs` 编译二进制域名 provider；普通 `python build.py` 输出可读 YAML provider。

在 Mihomo 客户端以本地文件导入 `~/.config/fenliu/clash/config.yaml`；或使用内核：

```bash
mihomo -t -f "$HOME/.config/fenliu/clash/config.yaml"
mihomo -f "$HOME/.config/fenliu/clash/config.yaml"
```

生成器要求私人输出在仓库外；正常 `python build.py` 即使进程已有 SUB_URL，也只生成占位符。不要把私人配置复制回仓库或 gh-pages。公网 rule-provider 每 86400 秒更新，订阅 provider 同样每天更新。

也可复制公开模板到客户端私人配置区，手动把 `${SUB_URL}` 替换为自己的 HTTPS 订阅。不要直接把公开 config.yaml 当作已填订阅的配置链接；覆盖更新会恢复占位符。

若只订阅规则，在自己的配置添加：

```yaml
rule-providers:
  ai_domain:
    type: http
    behavior: domain
    format: mrs
    url: https://cdn.jsdelivr.net/gh/limail8866-prog/fenliu@gh-pages/clash/ai_domain.mrs
    path: ./rules/ai_domain.mrs
    interval: 86400
  ai:
    type: http
    behavior: classical
    format: yaml
    url: https://cdn.jsdelivr.net/gh/limail8866-prog/fenliu@gh-pages/clash/ai.yaml
    path: ./rules/ai.yaml
    interval: 86400
rules:
  - RULE-SET,ai_domain,节点选择
  - RULE-SET,ai,节点选择
  # 保留其他分类与最后的 GEOIP/MATCH；保证已有「节点选择」组。
```

DNS 默认启用 fake-ip，`geosite:cn` 使用国内 DoH，海外域名使用 Cloudflare / Google DoH；若本地网络无法访问海外 DoH，可按需要修改生成器 DNS 设置。Mihomo 初次运行需下载订阅、规则和 GEO 数据，并按客户端提示授权对应网络访问。没有真实订阅时，本项目仅验证转换和配置结构，不能验证个人节点或客户端实际联网效果。

## 开发与许可

`python build.py --output /其他目录` 可生成独立产物；`--rules-dir`、`--policy` 支持测试用源目录。日常 validate / build / pytest 均可离线运行，CI 不会在构建时下载新的上游规则。

更新完整列表时修改 `upstream.yaml` 的固定提交或来源文件，再运行：

```bash
# 默认仅预览；先审阅来源和覆盖报告。
python tools/sync_rules.py --cache-dir /tmp/fenliu-upstream-cache --report /tmp/fenliu-import-report.json
# 必要时在 policy.yaml 为合理覆盖补充明确说明；未声明的覆盖不能写入。
python tools/sync_rules.py --cache-dir /tmp/fenliu-upstream-cache --write
python validate.py
python build.py
python -m pytest
# 可选联网核验固定来源的摘要、原文及导入结果。
python tools/verify_sources.py
```

导入保留没有 `upstream:` / `blackmatrix7/` / `v2fly/` 来源标记的手工规则，按分类优先级去重，递归解析 v2fly 的 include。缓存以仓库、提交和完整路径为键；缓存齐全时可以加 `--offline`。同一固定提交的文件若与已保存摘要不符会失败。不要把手工新增规则的 comment 写成这些导入器来源标记，否则更新时会被当作受上游管理的规则替换。

本项目以 GPL-2.0 发布；v2fly 来源同时保留 MIT 版权许可，见 [LICENSE](LICENSE)、[licenses/v2fly-MIT.txt](licenses/v2fly-MIT.txt) 和 [SOURCES.md](SOURCES.md)。本项目提供规则生成能力，不提供代理节点或订阅服务。
