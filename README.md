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
sources.yaml / SOURCES.md   固定上游提交、文件摘要、精选规则和许可
build.py / validate.py     生成与校验入口
tests/                     格式转换、策略引用、校验与订阅保密测试
dist/shadowrocket/         各分类 .list + shadowrocket.conf
dist/clash/                各分类 classical .yaml + config.yaml
```

初始包含 AI、流媒体、Telegram、GitHub、Apple、Microsoft、国内直连、广告拦截共八类。来自已有 GitHub 规则项目的 **111 条精选规则**，来源与 GPL-2.0 许可见 [SOURCES.md](SOURCES.md)。它们是可维护的起点，未保证覆盖所有服务；Apple 默认直连，Microsoft 和 GitHub 默认走节点选择，可在 policy.yaml 修改。

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

新增分类时同时在 `policy.yaml` 的 `categories` 添加策略组映射，在 `category_order` 添加位置。组类型支持 `select` 和 `url-test`；`proxies` 只引用组名或 `DIRECT` / `REJECT`，`use: [subscription]` 用于节点来源。自动测速组不包含 DIRECT，避免直连在测速中胜出。

两端使用相同的匹配顺序：

1. `ads_reject` → 拒绝
2. 自定义分类：AI → 流媒体 → Telegram → GitHub → Apple → Microsoft
3. `cn_direct` → 直连
4. `GEOIP,CN,DIRECT`
5. 小火箭 `FINAL,漏网之鱼` / Mihomo `MATCH,漏网之鱼`

`validate.py` 检查字段、YAML 重复键、规范化后的重复规则、跨分类域名/后缀/关键词覆盖、同版本 IP 网段重叠、映射及策略组循环引用；发现问题返回非零退出码。跨分类的同一规则也视为错误，即使映射同组。它只做静态检查，不下载 GEOIP 数据库或探测服务可用性；无法推断 GEOIP 与 CIDR 的关系，也无法证明所有关键词组合的交集。宽泛后缀包含精确广告域名也会报告冲突，需要明确调整分类边界。

## 自动发布与规则订阅

GitHub Actions 在 push（不含 gh-pages）和 main 的 PR 中执行 validate → build → pytest。全部通过后，**只有 main 分支**将 `dist/` 内容发布为 `gh-pages` 分支根目录；功能分支和 PR 只校验、不发布。也可手动运行 workflow。工作流不读取个人 SUB_URL，不需要配置订阅 Secret。

首次合并 PR 后 Actions 会创建 gh-pages。若仓库组织策略限制 GITHUB_TOKEN 写权限，需在仓库 Actions 设置允许工作流写入内容。raw 链接不依赖 GitHub Pages 网站开关，但仓库必须公开，客户端才能无鉴权订阅：

```text
https://raw.githubusercontent.com/limail8866-prog/fenliu/gh-pages/shadowrocket/shadowrocket.conf
https://raw.githubusercontent.com/limail8866-prog/fenliu/gh-pages/shadowrocket/ai.list
https://raw.githubusercontent.com/limail8866-prog/fenliu/gh-pages/clash/config.yaml
https://raw.githubusercontent.com/limail8866-prog/fenliu/gh-pages/clash/ai.yaml
```

Fork 后修改 `policy.yaml` 中的 `rule_base_url` 为自己的 `https://raw.githubusercontent.com/<用户名>/<仓库>/gh-pages`，重新构建。发布前 raw URL 会返回 404；应等 main 的发布任务成功再导入。

## 小火箭导入

1. 在首页添加自己的节点订阅，更新节点。订阅地址只填在客户端。
2. 在「配置」页添加上面的 `shadowrocket.conf` raw URL，下载并使用；全局路由选择「配置」。
3. 配置通过 RULE-SET 自动引用各分类 `.list`。节点选择和自动测速以 `policy-regex-filter` 筛选客户端已导入的节点；首次使用检查分组成员与所选节点。`[Proxy]` 留空。
4. 规则集更新可使用客户端的规则集更新功能；更新整份配置可能覆盖客户端的自定义修改，长期修改应维护在源 YAML 或 policy.yaml。

如果已有自己的配置，可只加入单个规则集：

```ini
RULE-SET,https://raw.githubusercontent.com/limail8866-prog/fenliu/gh-pages/shadowrocket/ai.list,AI
```

同时保证 `[Proxy Group]` 存在 AI 策略组，并将此规则放在 GEOIP / FINAL 前面。

## Mihomo / Clash Meta 导入及自己的订阅

`dist/clash/config.yaml` 包含 DNS fake-ip、proxy-groups、HTTP rule-providers 和规则顺序。`proxy-providers.subscription.url` 为 **`${SUB_URL}` 占位**；Mihomo 不会自动展开这个字符串，须在本地替换后才可加载。订阅需要提供 Mihomo/Clash 可读的 YAML（含 `proxies`），不能直接使用小火箭格式或普通 Base64 节点列表。

推荐生成仓库外的私人配置。下面命令从终端隐藏读取订阅，再通过环境变量传入，避免把地址写入命令历史：

```bash
read -rsp '输入自己的 Mihomo 订阅 URL: ' SUB_URL; echo
export SUB_URL
python build.py --subscription --output "$HOME/.config/fenliu"
unset SUB_URL
```

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
  ai:
    type: http
    behavior: classical
    format: yaml
    url: https://raw.githubusercontent.com/limail8866-prog/fenliu/gh-pages/clash/ai.yaml
    path: ./rules/ai.yaml
    interval: 86400
rules:
  - RULE-SET,ai,AI
  # 保留其他分类与最后的 GEOIP/MATCH；保证已有 AI 策略组。
```

DNS 默认启用 fake-ip，通过国内 DoH 解析；可按本地网络需求修改 policy 以外的生成器 DNS 设置。Mihomo 初次运行需下载订阅、规则和 GEOIP 数据，并按客户端提示授权对应网络访问。没有真实订阅时，本项目仅验证转换和配置结构，不能验证个人节点或客户端实际联网效果。

## 开发与许可

`python build.py --output /其他目录` 可生成独立产物；`--rules-dir`、`--policy` 支持测试用源目录。`python tools/verify_sources.py` 可联网核验固定上游来源；日常 validate / build / pytest 均可离线运行。

源码及分发的规则使用 GPL-2.0，见 [LICENSE](LICENSE) 和 [SOURCES.md](SOURCES.md)。本项目提供规则生成能力，不提供代理节点或订阅服务。
