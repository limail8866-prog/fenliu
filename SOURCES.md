# 规则来源与许可

本次从两个维护中的 GitHub 项目读取 **47 份固定版本文件**，包括递归 include 的文件。兼容规则按策略优先级去重后，共 **78,624 条、14 个分类**。构建使用已保存的 YAML，不会因为上游变化而悄悄改变发布结果。

| 项目 | 固定提交 | 许可 |
| --- | --- | --- |
| [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)，作者 blackmatrix7 | `83f37120c155f67c8eef43221dabe15cc3c95fec` | GPL-2.0，见 LICENSE |
| [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community)，V2Ray 社区 | `c6adacf29cc4fb05e04651fcf03e00989ef9f797` | MIT，见 licenses/v2fly-MIT.txt |

本项目以 GPL-2.0 发布，保留上述来源标注和 MIT 版权通知。`dist/` 同时携带 LICENSE、licenses/、本文、sources.yaml 和 upstream.yaml。

## 覆盖范围

| 分类 | 去重后条数 | 上游列表 |
| --- | ---: | --- |
| 广告拦截 | 38,066 | AdvertisingLite |
| AI | 123 | OpenAI、Claude、Gemini、Copilot；Twitter 中 Grok 独立站；v2fly OpenAI、Anthropic、Google DeepMind |
| 流媒体 | 1,687 | YouTube、Netflix、Spotify、Twitch、Disney、AmazonPrimeVideo、HBO、Hulu |
| Telegram | 38 | Telegram 与 v2fly Telegram |
| X | 31 | Twitter 与 v2fly Twitter；grok.com 分配给 AI |
| GitHub | 31 | GitHub |
| 游戏 | 256 | Steam、Epic、PlayStation、Xbox、Nintendo、Battle、Origin |
| Apple | 1,578 | Apple |
| Microsoft | 617 | Microsoft |
| 社交媒体 | 672 | Facebook、Instagram、Whatsapp、Discord、Reddit、TikTok；v2fly Discord、Reddit、Signal、Zoom |
| Google | 681 | Google |
| 支付 | 247 | PayPal |
| 通用代理 | 30,978 | Global 与 v2fly Wikimedia |
| 国内直连 | 3,619 | China 及四条手工 RFC 私网规则 |

导入兼容的完整分类列表，而非只抽取几个主站域名。上游本身存在共享平台、CDN、IP 网段和关键词的交叉，不能据此保证每个端点都被准确分类；用户可以调整策略或源规则。DNS 分流不能可靠移除与视频共用域名的 YouTube 广告。

## 转换、去重和例外

`upstream.yaml` 定义项目、固定提交、文件及分类；`sources.yaml` 记录每个实际文件的 SHA-256、成功导入的原文、跳过原因/数量和示例。每条受上游管理的规则在 comment 保留来源标记。

- blackmatrix 的 classical 规则转换为本项目六种支持类型；no-resolve 由生成器统一附加到 IP 规则。
- v2fly 的普通域名 / domain 转 DOMAIN-SUFFIX，full 转 DOMAIN，keyword 转 DOMAIN-KEYWORD，递归解析无属性过滤的 include。
- v2fly 的 @ads 条目不作为服务白名单导入；广告分类使用完整兼容的 AdvertisingLite。
- 4,285 条跨分类同类型同值规则由较高优先级分类持有，144 条同分类重复被去重。重复规则不会留在源规则里。
- 47 条未支持类型（如 PROCESS-NAME、IP-ASN、正则）和 11 条不符合严格域名/CIDR 规范的上游写法不导入，详情可在清单中审阅；手工校验仍会拒绝这些写法。
- Grok 独立站从 Twitter 列表转入 AI。Apple 的泛共享 akadns.net 和 Microsoft 的泛共享 akadns.net、edgesuite.net、b.akamaiedge.net 不归到单一服务组，保留更明确的服务端点，并交给通用代理或国内规则处理其他流量。
- 34 对合理的跨分类覆盖在 policy.yaml 显式说明原因并校验顺序；例如广告先于服务白名单、AI 的 Azure 端点先于 Microsoft、Discord 资源先于 Google。没有声明的覆盖仍导致校验失败，重复规则不允许通过覆盖声明豁免。

## 核验与更新

运行 `python tools/verify_sources.py`，通过 HTTPS 从固定提交下载来源文件，核验清单中的 SHA-256，并确认选取原文及转换结果同时存在于上游和本地源规则。保留 TLS 证书校验，不修改文件。

更新流程详见 README：编辑 upstream.yaml，运行 tools/sync_rules.py 默认预览，审阅变化和覆盖报告，必要时在 policy.yaml 声明新的合理覆盖，再加 --write 写入，最后运行 validate、build、pytest。手工规则会保留；来源标记的规则按上游替换。固定提交、摘要和导入结果必须一并通过 PR 审阅。

Shadowrocket 代理组格式参考 [LOWERTOP/Shadowrocket 的配置示例](https://github.com/LOWERTOP/Shadowrocket/blob/master/lazy_group.conf)，只参考语法。
