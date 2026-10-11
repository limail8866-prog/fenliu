# 初始规则来源与许可

初始规则精选自 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)，作者 blackmatrix7，固定提交为 `83f37120c155f67c8eef43221dabe15cc3c95fec`。上游以 GPL-2.0 发布；本项目以同一许可提供源码和生成的规则。完整许可见 [LICENSE](LICENSE)。

`sources.yaml` 记录每份上游文件的路径、固定提交、SHA-256 和实际选取的原始规则；每条选取规则也在 `rules/*.yaml` 的 comment 标明来源。构建时无需联网抓取上游，CI 不会因上游内容变化而悄悄改变输出。`dist/` 同时携带 LICENSE、本文和来源清单，以保留发布产物的归属信息。

选取范围：OpenAI / Claude / Gemini 的核心域名；YouTube / Netflix / Spotify 的主要服务与媒体域名；Telegram 核心域名及 IPv4、IPv6 网段；GitHub、Apple、Microsoft 的核心服务；国内常用服务白名单；AdvertisingLite 中的常见广告与跟踪服务。另补充了 RFC 私网直连规则。这是 **111 条精选规则**，不是完整黑名单/白名单镜像；尤其 DNS 分流不能可靠移除与视频共用域名的 YouTube 广告。

没有照搬上游中宽泛的共享 CDN/鉴权/统计域名、IP-ASN 等本项目未支持的类型。跨分类重叠会被校验器阻止，以免一份宽泛的白名单意外覆盖另一服务的代理规则；规则覆盖范围应按实际使用持续维护。

## 核验和更新

运行 `python tools/verify_sources.py`，从固定提交下载来源文件，以清单中的 SHA-256 核验内容，并确认选取规则同时存在于上游文件和本地源规则。下载通过 HTTPS 且保留证书校验，不修改本地文件。

更新时选择明确的上游提交，审阅对应 `.list` 差异，只把需要的规则写入各分类 YAML，并更新来源清单里的提交、文件摘要和 selected 列表。保留作者和许可标注。最后运行 `python validate.py && python build.py && python -m pytest`，以 PR 审阅规则变化。无需复制整份 AdvertisingLite 或 China 列表。

Shadowrocket 代理组格式参考 [LOWERTOP/Shadowrocket 的配置示例](https://github.com/LOWERTOP/Shadowrocket/blob/master/lazy_group.conf)，只参考语法，未复制其规则。
