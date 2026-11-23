# 古建复原图的证据冲突与展签授权

本地数据与术语材料供业务人员整理分析资料使用，所有记录均为合成样例。

## 目录

`fixtures/` 保存合成输入，`docs/` 说明字段与业务规程，`evidencetool/` 是证据评估工具，`tests/` 检查输入结构与工具行为，`issued/` 保存已签发展签的快照。

## 工具用法

在仓库根目录运行（`--repo` 指向含 `fixtures/` 与 `issued/` 的目录，默认当前目录）：

- `python3 -m evidencetool summary`：证据、解释与整图解释总览。
- `python3 -m evidencetool families`：来源家族（同一原件的复制记录只计一次独立支持）与抄录关系存疑带来的依赖风险。
- `python3 -m evidencetool relations`：解释两两关系（同层备选、声明互斥、建造先后、日期不相交）。
- `python3 -m evidencetool sets`：仍成立的整图解释，逐层标注依据；标记“从未同时出现”的组合与图层缺口。
- `python3 -m evidencetool labels`：逐句评估展签（确定性陈述、多说法、授权与引文），给出可继续使用、必须更换、需修改等结论及所缺证据或授权。
- `python3 -m evidencetool impact`：应用 `updates.csv` 中的重新断代，对比前后结论，指出哪些展签必须更换、哪些可继续使用、替换稿还缺什么。
- `python3 -m evidencetool issue 标签 版本 --to 巡展方 --on 日期`：评估通过后签发并留存快照；有未通过问题的版本拒绝签发。
- `python3 -m evidencetool as-issued 标签 [版本]`：按原内容回查巡展方实际收到的标签。
- `python3 -m evidencetool verify`：校验已签发快照与登记内容一致，发现以新稿冒充原签发内容的情况。
- `python3 -m evidencetool snapshot`：为已登记签发但缺快照的版本补建快照（已有快照绝不覆盖）。

评估规则对应 `docs/业务规程.md`（馆方证据手册）：确定性陈述须在全部仍成立的整图解释里都站得住，且有不少于两家互相独立、可追到原始记录的来源家族支持；多说法可以并呈，但每种都必须属于某个仍成立的整图解释；仅供馆内研究的材料不得复制上展签，引用必须保留许可对象与展示范围。

## 环境和测试

Python 3.11 标准库，无需第三方依赖。运行 `python3 -m unittest discover -s tests` 检查输入结构与工具行为，运行 `python3 -m compileall -q .` 检查 Python 文件语法。
