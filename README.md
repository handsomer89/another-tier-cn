# Another Tier 中文镜像站

本项目是 [Another Tier](https://anothertier.com/) 的中文静态镜像，已获得原站作者许可。初始快照采集于 2026-09-24，榜单及相关角色数据最近更新于 2026-10-15。

项目保留原站的角色资料、评级、布局及来源署名，在展示层提供中文名称、界面和术语翻译。角色标识、路由和原始数据中的英文值保持不变，以兼容原站数据。

## 功能与数据

- 共 326 个静态页面，包括 322 个角色详情页、梦见星导榜、梦见无星导榜、配布榜，以及 `/teams?beta=true` 测试版队伍页。
- 支持使用中文名、英文名、已核实的 AC 别名及书籍名搜索；支持属性、武器、定位和个性筛选。
- 角色榜单及详情优先读取同源的 `data/characters/*.json`，本地快照缺失或无法加载时才请求原站 API。
- 图片优先使用原站 Cloudinary CDN，加载失败后切换到 `mirror-images/` 中的备份。
- 公共页面不加载原站统计 SDK、后台及登录路由；保留相关源文件，以兼容汉化脚本中的共享代码。
- 队伍页等其他功能仍沿用原站 API。

## 部署

站点统一使用 **`/another-tier-cn/`** 作为基础路径。客户端路由、静态资源、角色 JSON 和图片备份均使用这一前缀。

这是可以直接发布的静态站点，无需在托管平台安装 Node.js、Python 或运行汉化脚本。数据更新和图片下载在维护时完成，生成文件一并提交到仓库。

### GitHub Pages

在仓库的 **Settings → Pages** 中选择：

- 发布方式：Deploy from a branch。
- 分支：`main`。
- 目录：`/ (root)`。

访问地址：<https://handsomer89.github.io/another-tier-cn/>。

仓库根目录保留 `.nojekyll`，以直接发布静态文件。不要将 GitHub Pages 的发布目录改成 Cloudflare 使用的 `dist/`。

### Cloudflare Pages

使用以下配置：

- 生产分支：`main`。
- 框架预设：无。
- 根目录：仓库根目录。
- 构建输出目录：`dist`。
- 构建命令：

```sh
mkdir -p dist/another-tier-cn && git archive HEAD | tar -x -C dist/another-tier-cn && printf '<!doctype html><meta http-equiv="refresh" content="0;url=/another-tier-cn/">' > dist/index.html
```

该命令把已提交的站点放到 `dist/another-tier-cn/`，并在域名根路径生成跳转页。部署后的访问路径为 `https://你的域名/another-tier-cn/`；直接访问域名根路径也会跳转到这里。

`git archive HEAD` **只包含当前提交中的文件**。更新后的 HTML、JS、JSON 和图片备份必须先提交，才能进入部署产物。`dist/` 已加入 `.gitignore`，无需提交。

### 本地预览

在仓库的父目录运行：

```sh
python3 -m http.server 8000
```

然后打开 <http://localhost:8000/another-tier-cn/>。

## 更新榜单与角色资料

维护脚本需要 Python 3 和 Node.js。运行：

```sh
python3 scripts/refresh-rankings.py
```

刷新流程会：

1. 获取梦见星导、梦见无星导和配布三张榜单，核对展示卡片与内嵌评级数据。
2. 比较榜单与本地角色详情的共有字段，只抓取发生变化或新增的详情页。
3. 保留镜像的页面外壳及浏览器资源，更新内容后重新应用汉化。
4. 优化资源加载、生成本地角色 JSON、下载缺失的图片备份，并运行一致性检查。

刷新为手动触发，不会自动跟随原站更新。如果只有详情独有字段变化，而榜单中的共有字段未变，增量刷新不会主动重新抓取该详情。

也可以使用已缓存的原站 HTML：

```sh
python3 scripts/refresh-rankings.py --source-dir /path/to/upstream
```

缓存目录需要包含 `index.html`、`free.html`、`no-sa.html`，以及本次需要更新的 `c/<slug>/index.html`。

## 中文名称与术语

翻译映射保存在以下文件中：

| 文件 | 内容 |
| --- | --- |
| `data/cn-names.json` | 308 条角色名称映射 |
| `data/cn-ui.json` | 52 条界面文案 |
| `data/cn-terms.json` | 153 条筛选、分类及详情术语 |
| `data/cn-verified.json` | 295 条已核实国服译名：256 条书籍/材料、24 条副本、15 条个性 |
| `data/cn-aliases.json` | 已核实的 AC、AC AS 别名 |

更新翻译工作簿后运行：

```sh
python3 scripts/import-cn-names.py /path/to/Another_Tier_Character_Forms_CN_corrected.xlsx
python3 scripts/import-cn-terms.py /path/to/Another_Tier_待精译术语_筛选与分类已翻译.xlsx
python3 scripts/localize-cn.py
python3 scripts/optimize-mirror.py
python3 scripts/check-cn.py
```

导入器按工作簿中的源文和译文列读取，跳过空白译文，并保留站点特有的导航、搜索提示及匹配模式文案。

汉化同时覆盖静态页面和浏览器交互，角色页的标题、描述及内嵌展示元数据保持一致。定位和个性筛选的“且/或”只改变显示文字，原有筛选逻辑不变。

已核实的书籍、副本和个性翻译用于角色名已有中文映射的详情页。尚未核实的译名及仅有英文名的角色保留原文；仙华 AS 的转职书籍全名仍待核实。

- 待核实的 20 项及冲突候选：[待核实国服译名](reports/待核实国服译名.md)。
- AC 别名的国服来源：[AC 别名国服来源](reports/AC别名国服来源.md)。

运行时使用 JSON 映射及生成的 JS 文件，不依赖翻译工作簿或来源证据文件。

## 图片备份与回退

当前已备份 960 个图片版本，共约 **28.7 MiB**。相同角色的头像、小人图、立绘，以及不同尺寸的图标分别保存。

图片加载规则：

1. 正常请求原站 CDN；成功时不会额外请求本地备份。
2. 图片发生加载错误时，切换到镜像站对应的 WebP 文件。
3. 本地备份也失败时停止，不在 CDN 与镜像之间循环重试。

这一机制覆盖首次打开时已经失败的图片，以及站内跳转后新增的图片。仅加载缓慢、尚未报错的请求不会立即触发回退。

下载缺失备份：

```sh
python3 scripts/download-images.py
```

替换已有备份，例如原站更新了同一地址的立绘时：

```sh
python3 scripts/download-images.py --refresh
```

榜单刷新会自动下载缺失图片。下载失败后可以重新运行，已完成的文件会被复用。图片原有来源署名保持不变。

## 检查与维护

运行现有轻量检查：

```sh
python3 scripts/check-cn.py
```

检查内容包括翻译映射、榜单与详情 JSON 一致性、页面语言和标题、移动端缩放设置、图标文件，以及图片备份覆盖情况。

手动替换 HTML 快照后，应重新生成对应数据并补齐图片：

```sh
python3 scripts/generate-character-snapshots.py
python3 scripts/download-images.py
python3 scripts/check-cn.py
```

修改浏览器逻辑后，重点检查中文搜索、角色跳转、配布/无星导榜、直接打开详情页，以及屏蔽原站 API/CDN 后的数据与图片回退。无需引入单独的测试框架。
